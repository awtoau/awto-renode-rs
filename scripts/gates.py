#!/usr/bin/env python3
"""Run every non-negotiable gate with a bounded CPU budget.

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

Independent gates run concurrently. The compile emitter receives the CPUs left
after reserving one for every other gate, so parallel orchestration does not
oversubscribe the host. In the full tier, compile and gap censuses split the
same budget and use separate scratch paths.

Run:  python3 scripts/dev.py gate
      python3 scripts/dev.py ci
      python3 scripts/dev.py gates --only check-layering
Log:  ./tmp/logs/gates.log
Exit: 1 if any gate failed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


GATES: list[tuple[str, list[str]]] = [
    ("check_paths", []), ("check_derived", []), ("check_layering", []),
    ("check_generated", []), ("check_ingest", []),
    ("check_rule_negatives", []), ("check_sync_harness", []),
    ("check_peer_calls", []), ("check_semantic_differences", []),
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


@dataclass(frozen=True)
class Result:
    label: str
    returncode: int
    seconds: float
    output: str


def run_gate(root: Path, gate: tuple[str, list[str]]) -> Result:
    name, extra = gate
    script = root / "scripts" / f"{name}.py"
    label = " ".join([name, *extra])
    if not script.exists():
        return Result(label, 127, 0.0, "script missing")
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(script), *extra], cwd=root,
        capture_output=True, text=True,
    )
    return Result(label, result.returncode, time.monotonic() - started,
                  result.stdout + result.stderr)


def run_parallel(root: Path, gates: list[tuple[str, list[str]]],
                 log: logging.Logger, cpu_budget: int) -> list[Result]:
    if not gates:
        return []
    workers = min(len(gates), cpu_budget)
    log.info("parallel wave: %d gate(s), %d process slot(s), CPU budget %d",
             len(gates), workers, cpu_budget)
    for name, extra in gates:
        log.info("    START %s", " ".join([name, *extra]))
    found: dict[str, Result] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_gate, root, gate): " ".join([gate[0], *gate[1]])
                   for gate in gates}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            found[result.label] = result
            log.info("    DONE  %-36s %-14s %6.1fs", result.label,
                     "ok" if result.returncode == 0 else f"FAILED ({result.returncode})",
                     result.seconds)
    # Stable summary and failure excerpts even though completion order is not.
    return [found[" ".join([name, *extra])] for name, extra in gates]


def allocated_fast(gates: list[tuple[str, list[str]]], jobs: int
                   ) -> list[tuple[str, list[str]]]:
    others = sum(1 for name, _extra in gates if name != "compile_check")
    compile_jobs = max(1, jobs - min(others, jobs - 1))
    return [(name, [*extra, "--jobs", str(compile_jobs)]
             if name == "compile_check" else extra)
            for name, extra in gates]


def allocated_full(jobs: int) -> list[tuple[str, list[str]]]:
    compile_jobs = max(1, (jobs + 1) // 2)
    gap_jobs = max(1, jobs - compile_jobs)
    return [
        ("compile_check", ["--ratchet", "--jobs", str(compile_jobs)]),
        ("gap_census", ["--jobs", str(gap_jobs)]),
    ]


def report(results: list[Result], log: logging.Logger) -> int:
    bad = 0
    log.info("")
    log.info("stable summary:")
    for result in results:
        log.info("%-40s %-14s %6.1fs", result.label,
                 "ok" if result.returncode == 0 else f"FAILED ({result.returncode})",
                 result.seconds)
        if result.returncode:
            bad += 1
            for line in result.output.splitlines()[-25:]:
                log.error("    %s", line)
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--full", action="store_true",
                    help="also run the whole-corpus tier (slow, gates a push)")
    detected = os.cpu_count() or 1
    ap.add_argument("--jobs", type=int, default=detected,
                    help="total CPU budget (default: available online CPUs)")
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error("--jobs must be positive")

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
        gates = [(g.replace("-", "_"), []) for g in args.only]
        results = run_parallel(root, gates, log, args.jobs)
    else:
        fast = allocated_fast(GATES, args.jobs)
        results = run_parallel(root, fast, log, args.jobs)
        if args.full:
            results += run_parallel(root, allocated_full(args.jobs), log, args.jobs)

    bad = report(results, log)
    if not args.full and not args.only:
        log.info("")
        log.info("NOT RUN: the whole-corpus tier -- all 569 emitted modules "
                 "and the full gap census.")
        log.info("Nothing above says anything about the modules outside the "
                 "declared clean set.")
        log.info("    python3 scripts/gates.py --full")
    log.info("%d of %d gate(s) failed", bad, len(results))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
