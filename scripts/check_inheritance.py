#!/usr/bin/env python3
"""The two guards the inheritance-layout decision turns on. Pre-commit.

Both were taken from `docs/decisions/inheritance-layout.md`, and both guard a
failure that COMPILES. Neither can be checked by reading the output, which is
why they are executed.

1. STRICT DISPATCH RESOLUTION
   A trait method must forward to the PLAIN emitted name or leave the trait.
   The obvious resolver falls back to the `{base}_{name}` copy -- and run that
   way it gave three of four implementors a `reset` that ran the BASE's body,
   because each overrides it in C# and each override was withheld for an
   unrelated reason. Wrong virtual dispatch, in code that compiles and passes
   its trace.

   So this asserts BOTH halves, and the second matters as much as the first:

     a. under the strict resolver no forward names a qualified copy;
     b. under the permissive resolver at least one does.

   (b) is what stops this becoming a check that verifies nothing. If the
   permissive resolver ever stops demonstrating the bug -- because the corpus
   moved, or because every override started emitting -- then (a) passing means
   nothing, and the check says so instead of reporting success.

2. THE FIELD-COLLISION GUARD
   Two levels of one chain declaring the same field name merge into a struct
   that declares it twice: rustc E0124, and the type does not compile at all.
   The guard turns that into a named gap.

   Today's cut has ZERO collisions, so this guard fires on nothing in it -- and
   an unfired guard is worth nothing; this project has shipped three checks that
   reported success while verifying nothing. So the check builds a two-level
   corpus that DOES collide, in memory, and asserts the guard fires on it. It
   also asserts the guard does NOT fire on a corpus that does not collide,
   because a guard that always fires is equally worthless.

   If `tmp/breadth.db` is present it additionally REPORTS how many tree-wide
   types the guard fires on. Reported, never asserted: breadth is a discovery
   corpus and is not always there.

Run:  python3 scripts/check_inheritance.py
Log:  ./tmp/logs/check_inheritance.log
Exit: 0 clean, 1 if either guard is broken or has stopped being able to fire.
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import emit as _emit                                        # noqa: E402
from emitter.lang.dispatch_trait import dispatch_target     # noqa: E402


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def quiet_log(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    log.addHandler(logging.NullHandler())
    log.propagate = False
    return log


# ---------------------------------------------------------------------------
# 1. strict dispatch resolution
# ---------------------------------------------------------------------------

def check_strict_dispatch(root: Path, log: logging.Logger) -> int:
    """Run the real analysis both ways over the real corpus and compare."""
    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus at rulesdb/patterns.db -- it is gitignored, so a")
        log.error("fresh worktree does not have one. Without it this check")
        log.error("would pass by having nothing to look at.")
        return 1
    con = sqlite3.connect(db)
    em = _emit.Emitter(con, quiet_log("check_inheritance.emit"))
    targets = _emit.dispatch_targets(em)
    pattern = em.project.get("dispatch", {}).get("signature")
    if not pattern:
        log.error("no `dispatch.signature` rule -- nothing can be resolved")
        con.close()
        return 1

    strict = em.dispatch_analysis(targets, pattern, strict=True)
    loose = em.dispatch_analysis(targets, pattern, strict=False)
    con.close()

    bad = 0

    # (a) nothing strict emits may forward to a qualified base copy.
    for r in strict:
        for m in r["methods"]:
            for impl, target in sorted(m["forwards"].items()):
                if target != m["name"]:
                    log.error("STRICT RESOLVER FORWARDED TO A BASE COPY: "
                              "%s::%s on %s -> %s", r["base"], m["name"],
                              impl, target)
                    bad += 1
    if not bad:
        n = sum(len(m["forwards"]) for r in strict for m in r["methods"])
        log.info("ok  strict: %d forward(s), every one to the plain name", n)

    # (b) the permissive resolver must still be able to demonstrate the bug,
    #     or (a) proves nothing.
    demos: list[str] = []
    for r in loose:
        for m in r["methods"]:
            for impl, target in sorted(m["forwards"].items()):
                if target != m["name"]:
                    demos.append(f"{r['base']}::{m['name']} on {impl} would "
                                 f"forward to `{target}` -- the base's body")
    if not demos:
        log.error("")
        log.error("THE PERMISSIVE RESOLVER NO LONGER DEMONSTRATES THE BUG.")
        log.error("Check (a) above therefore proves nothing: it would pass on a")
        log.error("resolver with no fallback at all and on the broken one alike.")
        log.error("Either the corpus moved or every override now emits. Find out")
        log.error("which before trusting this check again.")
        bad += 1
    else:
        log.info("ok  permissive: %d forward(s) would run the base's body, so "
                 "the strict check above has teeth", len(demos))
        for d in demos:
            log.info("      %s", d)

    # And say plainly what strict costs, since the decision priced it.
    for r in strict:
        for w in r["withheld"]:
            log.info("    withheld: %s", w)
    return bad


# ---------------------------------------------------------------------------
# 2. the field-collision guard
# ---------------------------------------------------------------------------

def synthetic_corpus(root: Path, collide: bool) -> sqlite3.Connection:
    """A two-level chain, in memory, that does or does not collide.

    Deliberately not a fixture file: a corpus small enough to read is worth more
    than one nobody checks, and the schema comes from `rulesdb/schema.sql` so it
    cannot drift away from the real one.
    """
    con = sqlite3.connect(":memory:")
    con.executescript((root / "rulesdb" / "schema.sql").read_text())
    con.execute("INSERT INTO corpus_run (id, started_at, renode_commit, "
                "tool_version, config) VALUES (1, '2026-01-01T00:00:00+10:00', "
                "'-', '-', 'unit')")
    con.execute("INSERT INTO file (id, run_id, path, sha256, loc) "
                "VALUES (1, 1, 'unit.cs', '-', 0)")
    for tid, name, base in ((1, "Base", None), (2, "Derived", 1)):
        con.execute(
            "INSERT INTO type (id, run_id, file_id, key, namespace, name, "
            "kind, base_type_id, accessibility) "
            "VALUES (?, 1, 1, ?, 'N', ?, 'class', ?, 'public')",
            (tid, f"N.{name}", name, base))
    # `unshared` is the negative control INSIDE the positive case: it must
    # survive while the colliding names are withheld, or the guard is just
    # emptying the struct.
    members = [(1, "unshared", "int"),
               (1, "sharedName", "int"),
               (2, "sharedName" if collide else "derivedOwn", "int"),
               # A collision that exists ONLY after snake_case. C# permits the
               # two spellings on two levels and Rust does not, and a guard
               # comparing C# names would miss it.
               (1, "initialLimit", "int"),
               (2, "InitialLimit" if collide else "otherLimit", "int")]
    for i, (tid, name, dtype) in enumerate(members, start=1):
        con.execute(
            "INSERT INTO member (id, run_id, type_id, key, kind, name, "
            "declared_type, accessibility, has_storage) "
            "VALUES (?, 1, ?, ?, 'field', ?, ?, 'private', 1)",
            (i, tid, f"N.{'Base' if tid == 1 else 'Derived'}.{name}", name,
             dtype))
    con.commit()
    return con


def check_collision_guard(root: Path, log: logging.Logger) -> int:
    bad = 0
    for collide in (True, False):
        con = synthetic_corpus(root, collide)
        em = _emit.Emitter(con, quiet_log("check_inheritance.emit"))
        em._sub_fields = {}
        fields, gaps = em.state_fields("Derived")
        con.close()
        names = [n for n, _ in fields]
        dup = sorted({n for n in names if names.count(n) > 1})
        collisions = [g for g in gaps if "E0124" in g]
        what = "colliding" if collide else "clean"

        if dup:
            log.error("%s corpus: `struct State` would declare %s twice -- the "
                      "guard did not fire", what, ", ".join(dup))
            bad += 1
        if collide:
            if len(collisions) != 2:
                log.error("colliding corpus: expected 2 collision gap(s), got "
                          "%d: %s", len(collisions), collisions)
                bad += 1
            for g in collisions:
                log.info("    gap: %s", g)
            if "shared_name" in names or "initial_limit" in names:
                log.error("colliding corpus: a colliding name survived into "
                          "the struct -- one copy was picked, which is the "
                          "silently-wrong-storage case")
                bad += 1
            if "unshared" not in names:
                log.error("colliding corpus: the non-colliding field was "
                          "dropped too -- the guard is emptying the struct, "
                          "not withholding a collision")
                bad += 1
        else:
            if collisions:
                log.error("clean corpus: the guard fired on a corpus with no "
                          "collision: %s", collisions)
                bad += 1
            for expect in ("unshared", "shared_name", "derived_own",
                           "initial_limit", "other_limit"):
                if expect not in names:
                    log.error("clean corpus: `%s` is missing -- the guard is "
                              "dropping fields it should not", expect)
                    bad += 1
        if not bad:
            log.info("ok  %s corpus: %d field(s), %d collision gap(s)",
                     what, len(fields), len(collisions))
    return bad


def report_breadth(root: Path, log: logging.Logger) -> None:
    """How many tree-wide types the guard fires on. REPORTED, never asserted.

    Breadth is a discovery corpus and is not always present; asserting on it
    would make this check pass or fail on whether someone ran an ingest.
    """
    db = root / "tmp" / "breadth.db"
    if not db.exists():
        log.info("no tmp/breadth.db -- skipping the tree-wide count "
                 "(discovery only; nothing is asserted on it)")
        return
    con = sqlite3.connect(db)
    em = _emit.Emitter(con, quiet_log("check_inheritance.emit"))
    names = [n for (n,) in con.execute(
        "SELECT DISTINCT t.name FROM type t JOIN type b "
        "ON t.base_type_id = b.id WHERE t.kind='class' ORDER BY t.name")]
    fired: list[str] = []
    for name in names:
        em._sub_fields = {}
        try:
            _fields, gaps = em.state_fields(name)
        except Exception:                                   # noqa: BLE001
            continue
        if any("E0124" in g for g in gaps):
            fired.append(name)
    con.close()
    log.info("tree-wide: the guard fires on %d of %d subclass(es); %s",
             len(fired), len(names), ", ".join(fired) or "(none)")


def main() -> int:
    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_inheritance")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_inheritance.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    bad = check_strict_dispatch(root, log)
    bad += check_collision_guard(root, log)
    # OPT-IN, because it costs ~2 MINUTES against a 309 MB breadth database and
    # this script runs in the pre-commit hook. It timed a commit out the day it
    # landed. It is a REPORT, never an assertion, so skipping it weakens no
    # guard -- and a hook slow enough to be bypassed is a hook that does not
    # run, which is the failure this repo has already had three times.
    if "--tree" in sys.argv:
        report_breadth(root, log)
    else:
        log.info("tree-wide count skipped -- pass --tree for it (~2 min)")

    if bad:
        log.error("FAIL: %d inheritance guard problem(s)", bad)
        return 1
    log.info("OK: dispatch resolves strictly, and the collision guard fires")
    return 0


if __name__ == "__main__":
    sys.exit(main())
