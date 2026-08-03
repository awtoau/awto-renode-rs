#!/usr/bin/env python3
"""Run every non-negotiable gate in one go and report exit codes.

The gate list in CLAUDE.md and in `scripts/githooks/pre-commit` is prose; a
person running them by hand runs the ones they remember. This is the same list
as a program, so "all gates" is a command rather than a habit.

TWO TIERS
---------
    python3 scripts/gates.py            fast -- what every commit must pass
    python3 scripts/gates.py --full     fast, plus the whole-corpus tier

The fast tier compiles the DECLARED CLEAN SET plus whatever the diff touches.
The full tier compiles all 569 emitted modules and runs the gap census over the
whole corpus. Both are one command, which is the point: the full tier existing
only as a thing you remember to type is the same as it not existing.

Why the split: the full compile census took ~15 min, `--ratchet` was in the
pre-commit hook, and the hook was therefore being SKIPPED -- so the last
several commits ran no compile gate at all. A gate slow enough to be bypassed
is a gate that does not run. Emission is now parallel (scripts/emit_pool.py)
AND the everyday tier is scoped, because either alone was not enough.

Run:  python3 scripts/gates.py
      python3 scripts/gates.py --full
      python3 scripts/gates.py --only check_layering
Log:  ./tmp/logs/gates.log
Exit: 1 if any gate failed.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


GATES: list[tuple[str, list[str]]] = [
    ("check_paths", []), ("check_derived", []), ("check_layering", []),
    ("check_generated", []), ("check_ingest", []),
    ("check_rule_negatives", []), ("check_sync_harness", []),
    # Source defects are data with their own evidence; this refuses one that
    # has lost its authority, its default or its measured switch-impact.
    # `--prove` is separate and deliberate: it is the mutation proof that the
    # check itself works, and it belongs beside the check rather than inside
    # it so the everyday tier stays fast.
    ("check_bug_rules", []), ("check_bug_rules", ["--prove"]),
    ("check_inheritance", []), ("check_postconditions", []),
    ("prove_postconditions", []),
    # The everyday compile gate: the declared clean set plus what the diff
    # names. It prints what it did not check.
    ("compile_check", ["--working-set", "--ratchet"]),
]

#: Whole-corpus, explicitly invoked. Slow because it is measuring 569 modules
#: and ~448k lines, not because anything is inefficient.
FULL: list[tuple[str, list[str]]] = [
    ("compile_check", ["--ratchet"]),
    ("gap_census", []),
]

# NOT in either tier, and deliberately: `check_emit_determinism.py` runs each
# census five times to prove the parallel output is byte-identical to the
# serial output. That is a CI job, like `check_determinism.py` for the ingest.
# Putting a 20-minute proof in the tier that gates a push is how the push tier
# becomes the next thing people skip.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--full", action="store_true",
                    help="also run the whole-corpus tier (slow, gates a push)")
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("gates")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    for h in (logging.FileHandler(root / "tmp" / "logs" / "gates.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    if args.only:
        gates = [(g, []) for g in args.only]
    else:
        gates = GATES + (FULL if args.full else [])

    bad = 0
    for g, extra in gates:
        script = root / "scripts" / f"{g}.py"
        label = " ".join([g, *extra])
        if not script.exists():
            log.error("%-40s MISSING", label)
            bad += 1
            continue
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, str(script), *extra], cwd=root,
                           capture_output=True, text=True)
        log.info("%-40s %-14s %6.1fs", label,
                 "ok" if r.returncode == 0 else f"FAILED ({r.returncode})",
                 time.monotonic() - t0)
        if r.returncode != 0:
            bad += 1
            for line in (r.stdout + r.stderr).splitlines()[-25:]:
                log.error("    %s", line)
    if not args.full and not args.only:
        log.info("")
        log.info("NOT RUN: the whole-corpus tier -- all 569 emitted modules "
                 "and the full gap census.")
        log.info("Nothing above says anything about the modules outside the "
                 "declared clean set.")
        log.info("    python3 scripts/gates.py --full")
    log.info("%d of %d gate(s) failed", bad, len(gates))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
