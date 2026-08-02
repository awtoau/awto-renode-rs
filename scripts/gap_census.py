#!/usr/bin/env python3
"""Count and CLASSIFY what the converter cannot yet emit.

Answers one question: when the converter meets code it has never been aimed at,
what stops it? Not "how much is left" -- what KIND of thing is left.

A gap type that appears once is a curiosity. One that appears four hundred
times across unrelated peripherals is the next piece of work, and the ranking
between them is not guessable from reading the code.

A GAP COUNT IS NOT A CORRECTNESS CLAIM
--------------------------------------
The corpus is the whole Renode tree (the cut was removed --
docs/decisions/remove-the-cut.md), so these counts cover ~448k lines rather
than a hand-picked ~22k. The total went UP as a direct result, and that is the
correct reading: the converter always could not emit those constructs; it was
simply never asked.

What this still cannot say is whether anything it DID emit is right. That is
trace replay, and it reaches only the peripherals with recorded traces. A
falling gap count means more was emitted, never that more was validated.

A database tagged `config = 'breadth'` is a scratch health-check run of the
same files (scripts/check_breadth.py); it is labelled below so its output is
never mistaken for the canonical corpus.

RELATIONSHIP TO THE RULE ENGINE (#35)
-------------------------------------
This is a partial step toward step 2 of the rule engine: it already does the
corpus-wide traversal -- query every type with a register-defining method, run
the emitter over ALL of them, classify what stopped it. What it does NOT do is
the bookkeeping: it writes nothing to `rule_match`, associates no result with a
rule, and validates nothing against the oracle.

It answers "what is blocked, and by what". The rule engine must answer "where
does rule R apply, and is R correct at each site". Turning this into that means
keeping the traversal and adding the recording. See docs/rule-engine-readiness.md.

Run:  python3 scripts/gap_census.py --db rulesdb/patterns.db
      python3 scripts/gap_census.py --db tmp/breadth.db --limit 400
      python3 scripts/gap_census.py --db rulesdb/patterns.db --blocking
Log:  ./tmp/logs/gap_census.log
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import io
import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Gap text -> a stable category. Ordered: first match wins, so put the specific
# patterns above the general ones.
CATEGORIES: list[tuple[str, str]] = [
    (r"nullability|conditional access", "null safety (?. and ??)"),
    (r"cannot emit stmt:Throw|Throw", "exceptions"),
    (r"cannot emit stmt:Switch|Switch", "switch / pattern matching"),
    (r"cannot emit stmt:Loop|loop:", "loops"),
    (r"cannot emit expr:", "unhandled expression kind"),
    (r"cannot emit stmt:", "unhandled statement kind"),
    (r"no Rust mapping for `System\.Collections", "collection types"),
    (r"no Rust mapping for `System\.", "BCL types"),
    (r"return type .* has no Rust mapping", "unmapped return type"),
    (r"parameter .* has no Rust mapping", "unmapped parameter type"),
    # Distinct from "unmapped": the object-graph rule HAS decided the mapping
    # (issue #57), and what is missing is the type it points at. Folding the
    # two together would report a solved decision as an open one.
    (r"the object-graph rule maps it to", "object graph: target not emitted"),
    (r"state field .* no Rust mapping", "unmapped state field type"),
    (r"base-class method", "untranslated base class"),
    (r"reaches state this peripheral does not have", "missing state (cascade)"),
    (r"needs peer method\(s\) not yet emitted", "missing peer method (cascade)"),
    (r"calls withheld method", "withheld dependency (cascade)"),
    (r"gap marker", "withheld: gap marker in body"),
    (r"computed field", "computed field dispatch"),
    (r"register-level callback", "register-level callback"),
    # Above "other" for a reason. These are the gaps that used to be SILENCE:
    # a callback kind the emitter never inspected, a field position that is not
    # a constant, a reset distinction the bank cannot express. Left uncategorised
    # they would arrive in "other", which is where a gap goes to stop being
    # counted -- and being uncounted is how they lasted this long.
    (r"is bound in the C# and no rule consumes it", "callback with no rule"),
    (r"is not a compile-time constant", "non-constant field placement"),
    (r"softResettable", "soft reset not modelled"),
    (r"trip count is not a compile-time constant", "unreplicable loop"),
]


def classify(gap: str) -> str:
    for pattern, name in CATEGORIES:
        if re.search(pattern, gap, re.IGNORECASE):
            return name
    return "other"


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--limit", type=int, default=0, help="cap types examined")
    ap.add_argument("--filter", default="", help="only types whose name matches")
    ap.add_argument("--blocking", action="store_true",
                    help="rank ROOT CAUSES by how many gaps each one blocks")
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("gap_census")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    for h in (logging.FileHandler(root / "tmp" / "logs" / "gap_census.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    db = root / args.db
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cfg = con.execute("SELECT config FROM corpus_run LIMIT 1").fetchone()
    breadth = bool(cfg and cfg[0] == "breadth")

    where = "AND t.name LIKE ?" if args.filter else ""
    params: tuple = (f"%{args.filter}%",) if args.filter else ()
    rows = con.execute(f"""
        SELECT t.name, MIN(mb.name) FROM type t
        JOIN member mb ON mb.type_id = t.id
        JOIN method m ON m.member_id = mb.id
        WHERE t.kind='class' AND m.has_body=1
          AND (mb.name LIKE '%Register%' OR mb.name LIKE '%DefineReg%') {where}
        GROUP BY t.name ORDER BY t.name""", params).fetchall()
    if args.limit:
        rows = rows[:args.limit]

    log.info("gap census over %s%s", args.db,
             "  [BREADTH -- scratch health-check database]"
             if breadth else "  [the corpus: the whole Renode tree]")
    log.info("%d type(s) with a register-defining method", len(rows))
    log.info("")

    from emit import Emitter
    quiet = logging.getLogger("quiet")
    quiet.addHandler(logging.NullHandler())

    cats: collections.Counter = collections.Counter()
    examples: dict[str, str] = {}
    per_type: list[tuple[str, int, int]] = []
    all_gaps: list[str] = []
    failures = 0
    emitted_lines = 0

    for name, method in rows:
        try:
            em = Emitter(sqlite3.connect(f"file:{db}?mode=ro", uri=True), quiet)
            with contextlib.redirect_stderr(io.StringIO()):
                out = em.emit_file(name, method, "x")
        except Exception as exc:                       # noqa: BLE001
            failures += 1
            cats[f"CONVERTER CRASH: {type(exc).__name__}"] += 1
            examples.setdefault(f"CONVERTER CRASH: {type(exc).__name__}",
                                f"{name}.{method}: {exc}")
            continue
        gaps = [l[8:].strip() for l in out.splitlines() if l.startswith("//!   - ")]
        emitted_lines += len(out.splitlines())
        per_type.append((name, len(out.splitlines()), len(gaps)))
        all_gaps.extend(gaps)
        for g in gaps:
            c = classify(g)
            cats[c] += 1
            examples.setdefault(c, f"{name}: {g}")

    if args.blocking:
        # A gap count is not a work estimate. Most gaps are CASCADES: one
        # unmapped type withholds a method, which withholds its callers, which
        # withholds their callbacks. Ranking the ROOTS says what to fix; ranking
        # the gaps says how loudly the roots are complaining.
        roots: collections.Counter = collections.Counter()
        for g in all_gaps:
            m = re.search(r"no Rust mapping for `([^`]+)`", g)
            if m:
                roots[f"type  {m.group(1).split('.')[-1]}"] += 1
                continue
            m = re.search(r"return type `([^`]+)`", g)
            if m:
                roots[f"type  {m.group(1).split('.')[-1]}"] += 1
                continue
            m = re.search(r"cannot emit (?:expr|stmt):(\w+)", g)
            if m:
                roots[f"construct  {m.group(1)}"] += 1
                continue
            m = re.search(r"base-class method `\w+` on `([^`]+)`", g)
            if m:
                roots[f"base class  {m.group(1)}"] += 1
                continue
            if "nullability" in g or "conditional access" in g:
                roots["construct  ConditionalAccess (?.)"] += 1
        log.info("")
        log.info("ROOT CAUSES, ranked by gaps blocked")
        log.info("(cascades excluded -- these are the things that CAUSE them)")
        log.info("%s", "-" * 72)
        log.info("%-46s %7s", "root cause", "blocks")
        for r, n in roots.most_common(25):
            log.info("%-46s %7d", r, n)
        log.info("%s", "-" * 72)
        log.info("%d distinct root causes account for %d direct gaps",
                 len(roots), sum(roots.values()))

    total = sum(cats.values())
    log.info("%-38s %7s  %s", "gap category", "count", "share")
    log.info("%s", "-" * 72)
    for cat, n in cats.most_common():
        log.info("%-38s %7d  %4.1f%%", cat, n, 100 * n / total if total else 0)
    log.info("%s", "-" * 72)
    log.info("%-38s %7d", "TOTAL", total)
    log.info("")
    log.info("%d type(s) emitted, %s lines total, %d converter crash(es)",
             len(per_type), f"{emitted_lines:,}", failures)
    log.info("")
    log.info("one example per category:")
    for cat, _ in cats.most_common():
        log.info("  %-36s %s", cat, examples.get(cat, "")[:96])

    if breadth:
        log.info("")
        log.info("BREADTH RUN -- a scratch health-check database, not the")
        log.info("canonical corpus. It reads the same files; it exists so a")
        log.info("smoke test cannot overwrite the corpus. A crash here is a bug")
        log.info("in our tooling, not a fact about the tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
