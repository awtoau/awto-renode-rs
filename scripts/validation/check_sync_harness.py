#!/usr/bin/env python3
"""Prove the interleaving oracle can FAIL, then prove it passes.

A concurrency check that has never failed is worth nothing. This project has
already shipped one checker that reported success while verifying nothing, and
a harness whose only evidence is its own green tick is the same shape.

So the harness is run twice:

  1. as it stands -- every test must PASS;
  2. with `--features prove-the-harness-can-fail`, which deletes the lock from
     the locked arm of every experiment -- the tests that depend on mutual
     exclusion must FAIL, by name.

Point 2 is the one that matters. If deleting a lock leaves the suite green, the
suite is not observing locks, whatever it claims in its assertions.

The mutation is a cargo feature rather than a text edit, so nothing is ever
patched in place and there is no half-mutated tree to recover if this is
interrupted.

Run:  python3 scripts/check_sync_harness.py
Log:  ./tmp/logs/check_sync_harness.log
Exit: 0 when the harness passes clean AND fails under the mutation, 1 otherwise.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

# Tests whose result depends on mutual exclusion actually holding. Deleting the
# lock must break every one of them. The others -- the vacuity guard, the
# disjoint-data control, the deadlock finder -- are unaffected by design, and
# expecting them to fail would be expecting the wrong thing.
MUST_FAIL = [
    "tests::a_deleted_lock_is_caught",
    "tests::locking_leaves_only_serial_outcomes",
    "deleting_the_lock_loses_a_real_write",
    "deleting_the_lock_tears_an_invariant_across_two_registers",
]

RESULT = re.compile(r"^test (\S+) \.\.\. (ok|FAILED)", re.MULTILINE)


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def run_tests(root: Path, features: list[str]) -> tuple[dict[str, str], str]:
    cmd = ["cargo", "test", "-p", "renode-sync", "--no-fail-fast"]
    for f in features:
        cmd += ["--features", f]
    p = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    out = p.stdout + p.stderr
    return {name: status for name, status in RESULT.findall(out)}, out


def main() -> int:
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_sync_harness")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    for h in (logging.FileHandler(root / "tmp" / "logs" / "check_sync_harness.log",
                                  mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    failures = 0

    clean, raw = run_tests(root, [])
    if not clean:
        log.error("no test results parsed -- the harness did not build:\n%s", raw[-4000:])
        return 1
    bad = sorted(n for n, s in clean.items() if s != "ok")
    log.info("clean run: %d test(s), %d failing", len(clean), len(bad))
    for n in bad:
        log.error("  FAILED %s", n)
        failures += 1

    mutated, raw = run_tests(root, ["prove-the-harness-can-fail"])
    if not mutated:
        log.error("no test results parsed under the mutation:\n%s", raw[-4000:])
        return 1
    log.info("mutated run (lock deleted): %d test(s), %d failing",
             len(mutated), sum(1 for s in mutated.values() if s == "FAILED"))
    for name in MUST_FAIL:
        status = mutated.get(name)
        if status is None:
            log.error("  MISSING %s -- renamed or removed, so the proof is gone", name)
            failures += 1
        elif status == "ok":
            log.error("  SURVIVED %s -- passes with the lock deleted, so it is "
                      "not observing the lock", name)
            failures += 1
        else:
            log.info("  caught   %s", name)

    log.info("")
    if failures:
        log.error("FAIL: %d problem(s)", failures)
        return 1
    log.info("PASS: the harness passes clean and fails when a lock is deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
