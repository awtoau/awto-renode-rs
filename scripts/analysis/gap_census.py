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
      python3 scripts/gap_census.py -j1        # serial, for the byte oracle
Log:  ./tmp/logs/gap_census.log
Out:  docs/status/gap_census.json (only on a canonical, unfiltered run --
      read by scripts/reports/scorecard.py; see the note there before deciding
      a slow report isn't worth wiring in)

Emission runs on every core (scripts/emit_pool.py). STDOUT IS BYTE-IDENTICAL
AT EVERY `-j`, and that is load-bearing rather than tidy: `check_refactor.py`
records this script's stdout as a golden artefact, so a report that depended on
scheduling would make every refactor look like a change. Wall-clock is reported
on stderr for the same reason.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import emit_pool

# Gap text -> a stable category. Ordered: first match wins, so put the specific
# patterns above the general ones.
CATEGORIES: list[tuple[str, str]] = [
    # FIRST, and each one separately, because these were SILENCE until the
    # constructor rule landed: 32 constructors were dropped with no output and
    # no gap. Folded into one line they would read as a single problem, and
    # they are five different ones -- only two of which are the converter's to
    # solve. A ctor gap also mentions parameters and statement kinds, so these
    # must out-rank the general patterns below or they would be filed as
    # unmapped parameters.
    (r"\.\.ctor .*: a base constructor", "constructor: base not inlined"),
    (r"\.\.ctor .*: statement \d+ withheld",
     "constructor: statement not an initialiser"),
    (r"\.\.ctor .*C# default value that the corpus does not record",
     "constructor: parameter default not ingested"),
    (r"\.\.ctor .*(no statement could be translated|body assigns nothing)",
     "constructor: nothing to initialise"),
    (r"\.\.ctor", "constructor: emitted, nothing constructs with it"),
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
    # BEFORE the two below, because it is the only one that describes a RUNTIME
    # PANIC rather than a withholding. It used to share the peer-method message,
    # so a collection nothing sizes -- which takes the peripheral down on its
    # first read -- was counted as a method cascade and looked like ordinary
    # unfinished work.
    (r"indexes a collection nothing sizes", "unsized collection (would panic)"),
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
    emit_pool.add_jobs_arg(ap)
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("gap_census")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    fileh = logging.FileHandler(root / "tmp" / "logs" / "gap_census.log", mode="w")
    for h in (fileh, logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    # Wall-clock goes to the log file and to STDERR, never to stdout.
    # `check_refactor.py` compares this script's stdout against a recorded
    # baseline, so a timing line on stdout would make every run differ from
    # every other run and turn the byte oracle into a clock.
    timing = logging.getLogger("gap_census.timing")
    timing.setLevel(logging.INFO)
    timing.propagate = False          # or it reaches `log`'s stdout handler
    for h in (fileh, logging.StreamHandler(sys.stderr)):
        h.setFormatter(fmt)
        timing.addHandler(h)

    db = root / args.db
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cfg = con.execute("SELECT config FROM corpus_run LIMIT 1").fetchone()
    breadth = bool(cfg and cfg[0] == "breadth")

    # Selected by what each body CONTAINS, not by the member's name -- see
    # scripts/register_owners.py. The census is a denominator, and the query
    # that used to be here dropped every type that builds its register map in
    # a constructor, so the census read as complete over a set that was not.
    from register_owners import owners
    rows = owners(con, name_filter=args.filter)
    if args.limit:
        rows = rows[:args.limit]

    log.info("gap census over %s%s", args.db,
             "  [BREADTH -- scratch health-check database]"
             if breadth else "  [the corpus: the whole Renode tree]")
    log.info("%d type(s) with a register-defining method", len(rows))
    log.info("")

    cats: collections.Counter = collections.Counter()
    examples: dict[str, str] = {}
    per_type: list[tuple[str, int, int]] = []
    all_gaps: list[str] = []
    failures = 0
    emitted_lines = 0

    # Emission is parallel; AGGREGATION IS NOT, and must not be. `emit_many`
    # returns results in task order, and this loop is byte-for-byte the serial
    # loop it replaced -- because `cats` is a Counter whose `most_common` breaks
    # ties on insertion order, and `examples` keeps the FIRST example per
    # category. Fold these in completion order and the totals still match while
    # the report changes: valid output, different bytes, no test to catch it.
    t0 = time.monotonic()
    results = emit_pool.emit_many(db, [(n, m, "x") for n, m in rows],
                                  args.jobs, lpt=not args.no_lpt)
    elapsed = time.monotonic() - t0
    cpu = sum(result.cpu_secs for result in results)
    timing.info("emitted %d type(s) in %.1fs at -j%d; %.1f effective CPU cores",
                len(results), elapsed, args.jobs, cpu / elapsed if elapsed else 0.0)
    emit_pool.report_tail(results, timing)

    for r in results:
        if r.err_type is not None:
            failures += 1
            cats[f"CONVERTER CRASH: {r.err_type}"] += 1
            examples.setdefault(f"CONVERTER CRASH: {r.err_type}",
                                f"{r.name}.{r.method}: {r.err_msg}")
            continue
        out = r.text
        gaps = [l[8:].strip() for l in out.splitlines() if l.startswith("//!   - ")]
        emitted_lines += len(out.splitlines())
        per_type.append((r.name, len(out.splitlines()), len(gaps)))
        all_gaps.extend(gaps)
        for g in gaps:
            c = classify(g)
            cats[c] += 1
            examples.setdefault(c, f"{r.name}: {g}")

    # Root causes are computed unconditionally (cheap: one regex pass over
    # gaps already collected) so the committed JSON artifact always carries
    # them; --blocking only controls whether they are also PRINTED.
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

    if args.blocking:
        # A gap count is not a work estimate. Most gaps are CASCADES: one
        # unmapped type withholds a method, which withholds its callers, which
        # withholds their callbacks. Ranking the ROOTS says what to fix; ranking
        # the gaps says how loudly the roots are complaining.
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

    # Committed so scorecard.py can report this WITHOUT re-running a ~6 min
    # full-corpus emission on every invocation. Written only for a canonical,
    # unfiltered run -- a --limit/--filter/breadth run is a debugging slice,
    # and overwriting the committed artifact with a slice would silently
    # shrink what the report shows.
    if not breadth and not args.limit and not args.filter:
        out = {
            "note": "python3 scripts/gap_census.py -- what the converter cannot yet "
                     "emit, classified. NOT a correctness claim -- see the module "
                     "docstring. Regenerate: python3 scripts/gap_census.py",
            "types_examined": len(rows),
            "types_emitted": len(per_type),
            "converter_crashes": failures,
            "emitted_lines": emitted_lines,
            "total_gaps": total,
            "categories": dict(cats.most_common()),
            "root_causes": dict(roots.most_common(25)),
            "examples": examples,
        }
        gap_path = root / "docs" / "status" / "gap_census.json"
        gap_path.write_text(json.dumps(out, indent=2, sort_keys=False) + "\n")
        log.info("wrote %s", gap_path.relative_to(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
