#!/usr/bin/env python3
"""Run every non-negotiable gate in one go and report exit codes.

The gate list in CLAUDE.md and in `scripts/githooks/pre-commit` is prose; a
person running them by hand runs the ones they remember. This is the same list
as a program, so "all gates" is a command rather than a habit.

Run:  python3 scripts/gates.py
      python3 scripts/gates.py --only check_layering
Log:  ./tmp/logs/gates.log
Exit: 1 if any gate failed.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


GATES = [
    "check_paths", "check_derived", "check_layering", "check_generated",
    "check_ingest", "check_rule_negatives", "check_sync_harness",
    "check_inheritance", "check_postconditions", "prove_postconditions",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[])
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

    gates = args.only or GATES
    bad = 0
    for g in gates:
        script = root / "scripts" / f"{g}.py"
        if not script.exists():
            log.error("%-26s MISSING", g)
            bad += 1
            continue
        r = subprocess.run([sys.executable, str(script)], cwd=root,
                           capture_output=True, text=True)
        log.info("%-26s %s", g, "ok" if r.returncode == 0 else
                 f"FAILED ({r.returncode})")
        if r.returncode != 0:
            bad += 1
            for line in (r.stdout + r.stderr).splitlines()[-25:]:
                log.error("    %s", line)
    log.info("%d of %d gate(s) failed", bad, len(gates))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
