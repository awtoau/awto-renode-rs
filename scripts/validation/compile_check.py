#!/usr/bin/env python3
"""Compile EVERYTHING the converter emits, and classify what rustc says.

The gap census answers "what does the converter know it cannot do". This
answers a different and harsher question: **of the code it was confident
enough to emit, how much actually compiles?**

Those are not the same, and until now we only had the first. Two peripherals
are wired into the workspace and compiled on every commit; the other twenty-odd
types the converter can emit have never been near a compiler. c2rust emits
output >99.99% of the time and only 72.64% of it runs -- "we emitted it" is
worth very little on its own.

Method is the one the literature keeps arriving at independently:

  * Laertes uses the Rust compiler as an oracle, and argues you must, because
    "the analysis must be tuned to be no more precise than the Rust compiler".
  * Bun grouped ~16,000 `cargo check` errors into a work queue.
  * Corrode's `corrode-cc` fell back to the real compiler on failure and
    hash-deduped each error message into a file, giving a free coverage metric.

An error CODE is a better work item than a gap, because rustc has already
classified the problem and pointed at the span.

Nothing is written to the repo: the scratch crate lives under tmp/.

Full rationale and the measured numbers: docs/decisions/two-tier-compile-gate.md

TWO TIERS
---------
    --working-set --ratchet   FAST. Compiles the declared clean set plus the
                              types the working diff names. Pre-commit.
    --ratchet                 FULL. All 569. Before a push, and on demand.

The fast tier says what it did NOT check, every run. A gate over a subset that
is quiet about its edges is exactly how the corpus cut hid four platform
peripherals for weeks while every number over it looked healthy.

THE GATE IS THE CLEAN SET, NOT THE ERROR TOTAL
----------------------------------------------
It used to be a ratchet on the total, and that had stopped being a gate. With
3,072 errors over 567 modules, 50 new errors is a 1.6% rise -- a broken rule
that takes out whole modules passes unnoticed. `compile_baseline.json` said so
itself under `why_this_ratchet_is_now_weaker`.

So the gate is per-module over the modules that compile CLEAN
(docs/status/compile_clean_set.json, declared data, may only grow). A module
leaving that set is unambiguous and attributable to one file. A module that
already fails can get worse and this will not notice -- stated plainly rather
than covered by a total that could not see it either.

Run:  python3 scripts/compile_check.py --working-set --ratchet   # fast tier
      python3 scripts/compile_check.py --ratchet                 # full tier
      python3 scripts/compile_check.py --record-clean-set        # grow the gate
      python3 scripts/compile_check.py --keep     # leave the crate for poking
      python3 scripts/compile_check.py -j1        # serial, for the byte oracle
Log:  ./tmp/logs/compile_check.log
Exit: 0, or 1 if a declared-clean module stopped compiling.

Emission runs on every core (scripts/emit_pool.py). THE EMITTED CRATE AND THIS
REPORT ARE BYTE-IDENTICAL AT EVERY `-j`. That matters more here than anywhere
else: this is the pre-commit compile gate, and a gate whose number moves with
the scheduler is a gate that fails at random and gets skipped. It was already
being skipped for taking ~15 min.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import emit_pool
from emitter.core import module_name as _module_name


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


CLEAN_SET = Path("docs") / "status" / "compile_clean_set.json"


def module_name(type_name: str) -> str:
    """The crate module a C# type is emitted as. One definition, used by all."""
    return _module_name(type_name)


def load_clean_set(root: Path, log: logging.Logger) -> set[str] | None:
    """The declared set of modules that MUST compile clean. None if unusable.

    This replaced a ratchet on the ERROR TOTAL, which had stopped being a gate:
    against a total in the thousands, a broken rule that takes out whole
    modules is a rise of a percent or two and passes unnoticed.
    `docs/status/compile_baseline.json` said so itself, under
    `why_this_ratchet_is_now_weaker`.

    The clean set is the part of the population that carries signal. A module
    LEAVING it is unambiguous, attributable to one file, and is the thing a
    total can never tell you. A module that already fails can get worse and
    this will not notice -- that is stated here rather than papered over,
    because pretending the total covered it is how the weak ratchet survived.

    No count is quoted here on purpose: the current one lives in the declared
    file, and a number repeated in a docstring is a second source of truth that
    goes stale without anything failing.
    """
    p = root / CLEAN_SET
    # A MISSING DECLARATION IS A BROKEN GATE, not an empty one -- the same
    # failure the old baseline had when it defaulted to a billion.
    if not p.exists():
        log.error("no clean set at %s. The per-module ratchet has nothing to",
                  CLEAN_SET.as_posix())
        log.error("compare against and is therefore not a gate. Record one with")
        log.error("    python3 scripts/compile_check.py --record-clean-set")
        return None
    doc = json.loads(p.read_text())
    mods = doc.get("modules")
    if not isinstance(mods, list) or not mods:
        log.error("%s has no `modules` list -- nothing to ratchet on.",
                  CLEAN_SET.as_posix())
        return None
    floor = int(doc.get("min_modules", 0))
    # The set may only GROW. Deleting entries is how a gate is quietly
    # narrowed, and it looks exactly like a gate that has nothing to say, so
    # shrinking has to take two edits and show up in review as a lowered floor.
    if len(mods) < floor:
        log.error("%s declares min_modules=%d but lists %d. The clean set may "
                  "only grow; lower the floor deliberately if it must shrink.",
                  CLEAN_SET.as_posix(), floor, len(mods))
        return None
    return set(mods)


def touched_types(root: Path, candidates: set[str]) -> set[str]:
    """Corpus types named anywhere in the working tree's diff against HEAD.

    Crude on purpose. It is not trying to compute the true blast radius of a
    rule change -- nothing can, which is exactly why the fast tier reports what
    it did NOT check instead of claiming coverage. It catches the common case:
    a plugin, a rule or a test that names a type is a type worth compiling.
    """
    diff = subprocess.run(["git", "diff", "HEAD", "--unified=0"],
                          cwd=root, capture_output=True, text=True)
    text = diff.stdout + subprocess.run(
        ["git", "diff", "--cached", "--unified=0"],
        cwd=root, capture_output=True, text=True).stdout
    words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    return {t for t in candidates if t in words}


def emit_all(root: Path, db: Path, log: logging.Logger,
             timing: logging.Logger, jobs: int,
             lpt: bool = True, keep_types: set[str] | None = None
             ) -> tuple[list[tuple[str, int]], set[str]]:
    """Emit types with a register-defining method into a scratch crate.

    `keep_types` limits WHICH types are emitted (the fast tier); None means all
    569. It never changes HOW one is emitted, so a module's bytes are the same
    in either tier -- generated modules carry no cross-module references, so
    compiling a subset gives each included module the same verdict.

    Parallel across types, and byte-identical to the serial version: modules
    are named from the type, written to their own path, and `mods` is built in
    task order, so nothing here depends on which worker finished first.
    """
    # The register-defining member of each type, chosen by what its body
    # CONTAINS. The query that used to be here chose by NAME, so it dropped
    # every type that builds its map in a constructor and picked an unrelated
    # `Register` overload where one existed -- see scripts/register_owners.py.
    from register_owners import owners
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = owners(con)

    crate = root / "tmp" / "compile_check"
    shutil.rmtree(crate, ignore_errors=True)
    (crate / "src").mkdir(parents=True)

    # A sub-block has no standalone form. Its `define_registers` is typed on
    # the PARENT's State, because that is whose bank it defines into, so
    # emitting it as its own module produces a `self` with nothing to bind to.
    # It is compiled -- inside its parent's module, which is the only place it
    # exists. Counting it twice would report errors for a file the converter
    # does not actually produce.
    #
    # Probed over EVERY type even when only a subset is being compiled: a
    # working-set module can be the child of a type outside the set, and
    # probing only the subset would emit it standalone -- a module the
    # converter does not actually produce, with errors nobody can act on.
    tp = time.monotonic()
    nested = emit_pool.probe_nested(db, [n for n, _m in rows], jobs)
    timing.info("sub-block probe over %d type(s): %.1fs at -j%d", len(rows),
                time.monotonic() - tp, jobs)
    if nested:
        log.info("%d type(s) emitted only inside a parent: %s",
                 len(nested), ", ".join(sorted(nested)))

    wanted = [(n, m) for n, m in rows
              if n not in nested and (keep_types is None or n in keep_types)]
    t0 = time.monotonic()
    results = emit_pool.emit_many(db, [(n, m, "m") for n, m in wanted],
                                  jobs, lpt=lpt)
    elapsed = time.monotonic() - t0
    cpu = sum(result.cpu_secs for result in results)
    timing.info("emitted %d type(s) in %.1fs at -j%d; %.1f effective CPU cores",
                len(results), elapsed, jobs, cpu / elapsed if elapsed else 0.0)
    emit_pool.report_tail(results, timing)

    mods: list[tuple[str, int]] = []
    for r in results:
        if r.err_type is not None:
            log.warning("emit crashed on %s: %s", r.name, r.err_msg)
            continue
        mod = module_name(r.name)
        (crate / "src" / f"{mod}.rs").write_text(r.text)
        mods.append((mod, len(r.text.splitlines())))

    # Free-function utility modules (BitHelper, Misc, ...) a peripheral's
    # cross-module calls resolve into (emitter/plugins/utility_calls.py).
    # Always emitted, in both tiers: a working-set peripheral can still call
    # into one, and skipping it here would leave that reference dangling in
    # the fast tier's own crate.
    from register_owners import utility_owners
    from emit import Emitter
    tu = time.monotonic()
    quiet = logging.getLogger("compile_check.quiet")
    if not quiet.handlers:
        quiet.addHandler(logging.NullHandler())
    for t in utility_owners(con):
        em = Emitter(con, quiet)
        text = em.emit_utility_file(t)
        mod = module_name(t)
        (crate / "src" / f"{mod}.rs").write_text(text)
        mods.append((mod, len(text.splitlines())))
    timing.info("emitted utility module(s) in %.1fs",
               time.monotonic() - tu)

    (crate / "src" / "lib.rs").write_text(
        "//! Scratch crate: every module the converter can emit, compiled\n"
        "//! together so rustc can say what is actually wrong. Generated by\n"
        "//! scripts/compile_check.py; not part of the workspace.\n"
        "#![allow(dead_code, unused_variables, unused_mut, unused_imports)]\n\n"
        + "\n".join(f"pub mod {m};" for m, _ in sorted(mods)) + "\n")

    (crate / "Cargo.toml").write_text(
        "[package]\nname = \"compile-check\"\nedition = \"2021\"\n"
        "version = \"0.0.0\"\npublish = false\n\n"
        "[dependencies]\n"
        f"renode-regs = {{ path = \"{'../../src/renode-regs'}\" }}\n"
        f"csharp-rt = {{ path = \"{'../../src/csharp-rt'}\" }}\n"
        "log = \"0.4\"\n\n[workspace]\n")
    # The second value is every module the FULL tier would have compiled. The
    # fast tier subtracts what it emitted from this to say what it did not
    # check -- and it must say so every run. A gate over a subset that stays
    # quiet about the subset is how the corpus cut hid four platform
    # peripherals for weeks while every headline number looked healthy.
    return mods, {module_name(n) for n, _m in rows if n not in nested}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--keep", action="store_true", help="leave the scratch crate")
    ap.add_argument("--ratchet", action="store_true",
                    help="fail if a module in the declared clean set stopped "
                         "compiling")
    ap.add_argument("--working-set", action="store_true",
                    help="FAST TIER: emit and compile only the declared clean "
                         "set plus what the diff touches, and say what was "
                         "not checked")
    ap.add_argument("--record-clean-set", action="store_true",
                    help="rewrite docs/status/compile_clean_set.json from a "
                         "FULL run (refused on a working-set run)")
    emit_pool.add_jobs_arg(ap)
    args = ap.parse_args()

    if args.record_clean_set and args.working_set:
        print("--record-clean-set needs a FULL run: a working-set run has not "
              "compiled the modules it would be declaring clean.",
              file=sys.stderr)
        return 1

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("compile_check")
    log.setLevel(logging.INFO)
    fileh = logging.FileHandler(root / "tmp" / "logs" / "compile_check.log",
                                mode="w")
    for h in (fileh, logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    # Timing goes to the log file and STDERR, never stdout: `check_refactor.py`
    # keeps this script's stdout as a golden artefact, and a clock in a golden
    # file makes every run differ from every other one.
    timing = logging.getLogger("compile_check.timing")
    timing.setLevel(logging.INFO)
    timing.propagate = False
    for h in (fileh, logging.StreamHandler(sys.stderr)):
        h.setFormatter(logging.Formatter("%(message)s"))
        timing.addHandler(h)

    # Only read when it is actually going to be used: `load_clean_set` reports
    # a missing declaration as an error, and a plain measurement run has not
    # asked to be gated.
    declared: set[str] | None = None
    if args.ratchet or args.working_set:
        declared = load_clean_set(root, log)
        if declared is None:
            return 1

    keep: set[str] | None = None
    if args.working_set:
        con = sqlite3.connect(f"file:{root / args.db}?mode=ro", uri=True)
        all_types = {r[0] for r in con.execute(
            "SELECT DISTINCT name FROM type WHERE kind='class'")}
        con.close()
        # A module name is lossy (`STM32_UART` -> `stm32_uart`), so the working
        # set is built in TYPE space and the declared clean set is mapped into
        # it, not the other way round.
        declared_types = {t for t in all_types if module_name(t) in declared}
        touched = touched_types(root, all_types)
        keep = declared_types | touched
        log.info("WORKING SET: %d declared-clean type(s), %d named in the "
                 "working diff, %d total",
                 len(declared_types), len(touched), len(keep))

    mods, universe = emit_all(root, root / args.db, log, timing, args.jobs,
                              lpt=not args.no_lpt, keep_types=keep)
    total_lines = sum(n for _, n in mods)
    log.info("emitted %d module(s), %s lines", len(mods), f"{total_lines:,}")

    crate = root / "tmp" / "compile_check"
    tc = time.monotonic()
    proc = subprocess.run(
        ["cargo", "check", "--message-format=json", "--quiet"],
        cwd=crate, capture_output=True, text=True)
    timing.info("cargo check: %.1fs", time.monotonic() - tc)

    # CARGO FAILING TO RUN IS NOT ZERO ERRORS. The error total below is parsed
    # from `compiler-message` lines, so if cargo dies BEFORE compiling -- broken
    # manifest, unresolvable path dependency, lock conflict, no registry -- it
    # emits no JSON at all, `total` is 0, this logs "ALL MODULES COMPILE" and
    # the ratchet exits 0.
    #
    # This is the only compile gate in the pre-commit hook, and it produced
    # exactly that false green during a review on 2026-08-02. A check that
    # reports success when it did not run is worse than no check: it is the
    # third one found this week, after the refactor oracle that recorded a
    # crash as a baseline and the concurrency suite that had never failed.
    #
    # Distinguished from "cargo ran and found errors" by whether any JSON
    # arrived, because a normal failing build still emits messages and exits 101.
    if not proc.stdout.strip():
        log.error("cargo produced NO output. It did not compile anything --")
        log.error("this is not a clean build, it is a build that never ran.")
        log.error("exit code %d", proc.returncode)
        for line in (proc.stderr or "(no stderr)").strip().splitlines()[:15]:
            log.error("    %s", line)
        return 1

    codes: collections.Counter = collections.Counter()
    per_mod: collections.Counter = collections.Counter()
    examples: dict[str, str] = {}
    total = 0
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("reason") != "compiler-message":
            continue
        d = msg.get("message", {})
        if d.get("level") != "error":
            continue
        total += 1
        code = (d.get("code") or {}).get("code") or "no-code"
        codes[code] += 1
        examples.setdefault(code, (d.get("message") or "")[:88])
        for span in d.get("spans", []):
            f = span.get("file_name", "")
            if f.endswith(".rs"):
                per_mod[Path(f).stem] += 1
                break

    log.info("")
    if total == 0:
        log.info("ALL %d MODULES COMPILE. %s lines.", len(mods), f"{total_lines:,}")
        log.info("That is a stronger statement than the gap count -- it says the")
        log.info("code the converter was confident enough to emit is at least")
        log.info("well-formed. It says nothing about whether it is CORRECT.")
    else:
        log.info("%-14s %7s  %s", "rustc code", "count", "example")
        log.info("%s", "-" * 78)
        for code, n in codes.most_common(20):
            log.info("%-14s %7d  %s", code, n, examples.get(code, "")[:56])
        log.info("%s", "-" * 78)
        log.info("%d error(s) across %d module(s)", total, len(per_mod))
        log.info("")
        log.info("worst modules:")
        for m, n in per_mod.most_common(8):
            log.info("    %-34s %4d", m, n)

    emitted = {m for m, _n in mods}
    clean_now = emitted - set(per_mod)
    log.info("")
    log.info("%d of %d modules compile clean", len(clean_now), len(mods))

    # WHAT THIS RUN DID NOT CHECK. Printed every run, in both tiers, because
    # a subset that stays quiet about its own edges is the failure mode: the
    # corpus cut excluded four platform peripherals for weeks and every
    # headline number over it looked healthy.
    unseen = universe - emitted
    if unseen:
        log.info("")
        log.info("NOT CHECKED: %d of %d module(s) were not compiled by this "
                 "run.", len(unseen), len(universe))
        if keep is None:
            # A full run, so these are the ones emission CRASHED on. They are
            # named above; this says out loud that nothing below covers them,
            # because "emit crashed on X" scrolls past and a clean-looking
            # error table underneath reads like full coverage.
            log.info("Emission crashed on them (listed above). Nothing here "
                     "says anything about them.")
        else:
            log.info("They are outside the working set. Nothing here says "
                     "anything about them. Run the full tier:")
            log.info("    python3 scripts/gates.py --full")
    log.info("")
    log.info("An error CODE is a better work item than a gap: rustc has already")
    log.info("classified the problem and pointed at the span. A gap is what the")
    log.info("converter KNOWS it cannot do; these are what it got wrong anyway.")

    if args.record_clean_set:
        doc = {
            "note": "Modules that compile with ZERO rustc errors. THE GATE. "
                    "A module leaving this set is a regression attributable to "
                    "one file; that is what an error TOTAL can never tell you, "
                    "and why the total stopped being the ratchet.",
            "not_covered": "A module NOT listed here already fails to compile. "
                           "It can get worse and nothing will notice. That is "
                           "accepted deliberately -- a ratchet over a mostly-"
                           "broken population carries no signal (50 new errors "
                           "was a 1.6% rise against 3,072 and passed).",
            "may_only_grow": "min_modules is a floor. Shrinking the set takes "
                             "two edits so it cannot happen quietly.",
            "record_with": "python3 scripts/compile_check.py --record-clean-set",
            "min_modules": len(clean_now),
            "modules": sorted(clean_now),
        }
        (root / CLEAN_SET).write_text(json.dumps(doc, indent=2) + "\n")
        log.info("")
        log.info("recorded %d clean module(s) to %s",
                 len(clean_now), CLEAN_SET.as_posix())

    if not args.keep:
        shutil.rmtree(crate, ignore_errors=True)

    if args.ratchet:
        assert declared is not None            # checked before emitting
        # A declared-clean module that was never compiled is a gate that did
        # not run -- indistinguishable from a gate that passed. It can only
        # happen if emission crashed on it or it left the corpus, and both are
        # things to hear about rather than skip.
        missing = declared - emitted
        if missing:
            log.error("")
            log.error("RATCHET CANNOT RUN: %d declared-clean module(s) were "
                      "not compiled at all:", len(missing))
            for m in sorted(missing)[:15]:
                log.error("    %s", m)
            log.error("Either emission crashed on them or they left the "
                      "corpus. Not compiling a module is not the same as it "
                      "passing.")
            return 1
        regressed = sorted(declared & set(per_mod))
        if regressed:
            log.error("")
            log.error("RATCHET: %d module(s) left the clean set.", len(regressed))
            for m in regressed:
                log.error("    %-34s %4d error(s)", m, per_mod[m])
            log.error("Each of these compiled with zero errors and no longer "
                      "does. A rule that quietly stops being applied looks "
                      "exactly like a rule that correctly declines -- this is "
                      "the check that tells the two apart.")
            return 1
        gained = sorted(clean_now - declared)
        if gained:
            log.info("")
            log.info("RATCHET: %d module(s) now compile clean and are not "
                     "declared. Grow the gate:", len(gained))
            for m in gained[:15]:
                log.info("    %s", m)
            log.info("    python3 scripts/compile_check.py --record-clean-set")
        log.info("")
        log.info("RATCHET OK: all %d declared-clean module(s) still compile "
                 "clean.", len(declared))
        # Trend only, never a gate -- see load_clean_set. Reported only on a
        # full run, because a subset's total is not comparable to anything.
        if not unseen:
            log.info("error total across all %d module(s): %d (trend, not a "
                     "gate)", len(mods), total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
