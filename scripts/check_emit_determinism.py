#!/usr/bin/env python3
"""Prove the census output does not depend on how many workers emitted it.

`scripts/check_determinism.py` proves the INGEST is deterministic across -j1
and -jN. This is its counterpart on the other side of the pipeline: emission
was made parallel (scripts/emit_pool.py), so the same guarantee now has to hold
for the two census scripts.

CLAUDE.md: "Output must be byte-identical at -j1 and -j32. CI enforces this by
running both and diffing." Without it every diff against the C# reference is
scheduling noise and the differential oracle is worthless.

What makes this a real check rather than a plausible one
--------------------------------------------------------
Parallel emission would fail this in a way that is easy to miss, because the
wrong output is still VALID output. Collect 569 results in completion order and
the gap TOTAL is unchanged -- but `Counter.most_common` breaks its ties on
insertion order, and "one example per category" keeps whichever example arrived
first. The report differs; nothing in it looks wrong. That is the same failure
class as the invented `.with_reserved(9, 23)`: behaviourally inert and
invisible to anything that only checks totals.

So this compares BYTES, not counts, and it runs three things:

  1. -j1 vs -jN            -- does the pool change the answer at all
  2. -jN three times       -- is the pool itself stable run to run
  3. -jN with --no-lpt     -- does the ORDER WORK IS ISSUED leak into output

(3) is the one that would catch a regression nobody would think to look for:
the scheduler hands out the expensive types first, so if any aggregation ever
started depending on arrival order, the longest-first ordering is what would
make it differ.

Run:  python3 scripts/check_emit_determinism.py
      python3 scripts/check_emit_determinism.py --jobs 31 --repeat 3
      python3 scripts/check_emit_determinism.py --limit 60   # quick version
Log:  ./tmp/logs/check_emit_determinism.log
Exit: 0 identical, 1 divergent.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import logging
import os
import subprocess
import sys
import time
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def run(root: Path, script: str, extra: list[str],
        log: logging.Logger) -> tuple[str, float]:
    """Run a census and return (stdout, seconds).

    Only STDOUT is compared. The timing lines the census scripts emit go to
    stderr precisely so they cannot enter this comparison -- a clock in a
    golden artefact makes every run differ from every other one.
    """
    argv = [sys.executable, str(root / "scripts" / script), *extra]
    label = f"{script} {' '.join(extra)}".strip()
    t0 = time.monotonic()
    log.info("START %-40s", label)
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=root,
    )
    while True:
        try:
            out, err = proc.communicate(timeout=30)
            break
        except subprocess.TimeoutExpired:
            log.info("RUN   %-40s %6.1fs elapsed", label,
                     time.monotonic() - t0)
    dt = time.monotonic() - t0
    log.info("DONE  %-40s %6.1fs rc=%d", label, dt, proc.returncode)
    if proc.returncode != 0:
        # A CRASH IS NOT AN ARTEFACT. Two runs that both died compare equal and
        # prove nothing -- this repo has already recorded nine identical stack
        # traces as a green baseline once.
        log.error("%s %s exited %d", script, " ".join(extra), proc.returncode)
        for line in (err or "(no stderr)").strip().splitlines()[-10:]:
            log.error("    %s", line)
        raise SystemExit(1)
    if not out.strip():
        log.error("%s %s produced no stdout -- nothing to compare",
                  script, " ".join(extra))
        raise SystemExit(1)
    return out, dt


def compare(log: logging.Logger, label: str, a: str, b: str) -> bool:
    """True if identical. Prints a real diff, not just a hash mismatch."""
    ha = hashlib.sha256(a.encode()).hexdigest()[:16]
    hb = hashlib.sha256(b.encode()).hexdigest()[:16]
    if a == b:
        log.info("%-46s MATCH    %s", label, ha)
        return True
    log.error("%-46s DIVERGE  %s vs %s", label, ha, hb)
    diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                     lineterm=""))
    for line in diff[:40]:
        log.error("    %s", line)
    if len(diff) > 40:
        log.error("    ... %d more diff line(s)", len(diff) - 40)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 8)
    ap.add_argument("--repeat", type=int, default=3,
                    help="how many times to re-run at -jN")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap types (gap_census only); for a fast smoke run")
    ap.add_argument("--only", default="",
                    help="gap_census | compile_check")
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_emit_determinism")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" /
                                  "check_emit_determinism.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)

    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        # Gitignored and 308 MB, so a fresh worktree has none -- and every emit
        # would then fail identically at both -j1 and -jN, which is a green
        # result that means nothing.
        log.error("no corpus at rulesdb/patterns.db -- it is gitignored, so a")
        log.error("fresh worktree does not have one. Copy it in or re-ingest;")
        log.error("without it both runs fail identically and this check passes")
        log.error("while proving nothing.")
        return 1

    scripts = ["gap_census.py", "compile_check.py"]
    if args.only:
        scripts = [s for s in scripts if s.startswith(args.only)]
        if not scripts:
            log.error("--only %s matches no census script", args.only)
            return 1

    cap = ["--limit", str(args.limit)] if args.limit else []
    bad = 0
    for script in scripts:
        log.info("")
        log.info("%s", script)
        log.info("%s", "-" * 72)
        extra = cap if script == "gap_census.py" else []

        serial, t_serial = run(root, script, [*extra, "-j1"], log)
        log.info("%-46s %6.1fs", "-j1 (serial, no pool)", t_serial)

        runs: list[str] = []
        for i in range(max(1, args.repeat)):
            out, dt = run(root, script, [*extra, "-j", str(args.jobs)], log)
            log.info("%-46s %6.1fs", f"-j{args.jobs} run {i + 1}", dt)
            runs.append(out)

        nolpt, dt = run(root, script,
                        [*extra, "-j", str(args.jobs), "--no-lpt"], log)
        log.info("%-46s %6.1fs", f"-j{args.jobs} --no-lpt", dt)

        log.info("")
        if not compare(log, f"{script}  -j1 vs -j{args.jobs}", serial, runs[0]):
            bad += 1
        for i, out in enumerate(runs[1:], start=2):
            if not compare(log, f"{script}  -j{args.jobs} run 1 vs run {i}",
                           runs[0], out):
                bad += 1
        if not compare(log, f"{script}  -j{args.jobs} lpt vs --no-lpt",
                       runs[0], nolpt):
            bad += 1
        log.info("speedup at -j%d: %.1fx", args.jobs,
                 t_serial / dt if dt else 0)

    log.info("")
    if bad:
        log.error("FAIL: %d comparison(s) diverged. Emission output depends on "
                  "the worker count or the scheduler, so every diff against "
                  "the C# reference is now noise. Collect results in TASK "
                  "order and aggregate in that order -- see "
                  "scripts/emit_pool.py.", bad)
        return 1
    log.info("OK: census output is byte-identical at -j1 and -j%d, stable "
             "across %d repeat run(s), and unaffected by the scheduling order.",
             args.jobs, max(1, args.repeat))
    return 0


if __name__ == "__main__":
    sys.exit(main())
