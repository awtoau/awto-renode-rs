#!/usr/bin/env python3
"""Run the canonical build -> check -> report lifecycle.

This is the command to run before reporting progress or pushing a completed
change.  The individual stage scripts remain authoritative; this file only
defines their order and failure semantics.

Run:  python3 scripts/cycle.py
      python3 scripts/cycle.py --dry-run
Log:  ./tmp/logs/cycle.log (plus each stage's existing log)
Exit: the first failing stage's non-zero status, otherwise 0.

Reports deliberately run last.  A failed regeneration or gate must not leave
fresh-looking status artefacts describing an unchecked tree.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path


STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("build", ("scripts/regenerate.py",)),
    ("check", ("scripts/gates.py", "--full")),
    ("report: scorecard", ("scripts/scorecard.py",)),
    ("report: graph + HTML", ("scripts/progress_graph.py",)),
)


def repo_root() -> Path:
    return Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact ordered stages without running them",
    )
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("cycle")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (
        logging.FileHandler(logdir / "cycle.log", mode="w"),
        logging.StreamHandler(sys.stdout),
    ):
        handler.setFormatter(fmt)
        log.addHandler(handler)

    for number, (name, argv) in enumerate(STAGES, start=1):
        command = [sys.executable, *argv]
        display = " ".join(["python3", *argv])
        if args.dry_run:
            log.info("%d/%d %-20s %s", number, len(STAGES), name, display)
            continue

        log.info("%d/%d START %-14s %s", number, len(STAGES), name, display)
        started = time.monotonic()
        result = subprocess.run(command, cwd=root)
        elapsed = time.monotonic() - started
        if result.returncode != 0:
            log.error("%d/%d FAIL  %-14s exit %d after %.1fs; cycle stopped",
                      number, len(STAGES), name, result.returncode, elapsed)
            return result.returncode
        log.info("%d/%d PASS  %-14s %.1fs", number, len(STAGES), name, elapsed)

    if args.dry_run:
        log.info("dry run: no stage executed")
    else:
        log.info("cycle complete: generated output checked before reports refreshed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
