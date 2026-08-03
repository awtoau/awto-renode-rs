#!/usr/bin/env python3
"""Which captured traces could validate GENERATED code, and which do not.

The project has one real oracle -- trace replay -- and it currently exercises
two hand-written peripherals. Meanwhile 24 traces sit in `oracle/traces/`,
captured from C# Renode, holding ~123,000 recorded register accesses.

This asks how much of that is reachable: for each trace, which C# type is it a
trace OF, and can the converter emit that type?

The join is not by name. A trace is named for a platform INSTANCE -- `usart1`,
`gpioPortA` -- and the C# type comes from the `.repl`, so `docs/status/
platform.json` is the mapping. Matching trace names against type names directly
finds 4 of 24; going through the platform finds 19.

WHY THIS MATTERS MORE THAN THE COMPILE CHECK
--------------------------------------------
`compile_check.py` proves emitted code is well-formed. It cannot prove it is
right, and the difference is the whole problem: c2rust emits output >99.99% of
the time and only 72.64% of it runs. Four bugs in this project compiled
cleanly and were wrong.

Trace replay is the only thing here that tests behaviour. Every trace that
maps to an emittable type is an oracle we already paid for and are not using.

Run:  python3 scripts/oracle_coverage.py
Log:  ./tmp/logs/oracle_coverage.log
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def main() -> int:
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("oracle_coverage")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" / "oracle_coverage.log",
                                  mode="w"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    plat = json.loads((root / "docs" / "status" / "platform.json").read_text())
    peripherals = plat["peripherals"]

    con = sqlite3.connect(
        f"file:{root / 'rulesdb' / 'patterns.db'}?mode=ro", uri=True)
    # "Can the converter emit this type" is the same question the emission
    # tooling asks, so it is the same selector -- by what a body CONTAINS, not
    # by the member's name. Restricted to the platform's own types: the answer
    # for the other 580 is not wanted here, and asking for it costs a scan of
    # every candidate body in the corpus.
    from register_owners import owners
    emittable = {t for t, _m in owners(
        con, types={e["type"].split(".")[-1] for e in peripherals.values()})}

    reachable: list[tuple[str, str, int]] = []
    unreachable: list[tuple[str, str]] = []
    for f in sorted((root / "oracle" / "traces").glob("*.jsonl.gz")):
        name = re.sub(r"\.jsonl\.gz$", "", f.name)
        entry = peripherals.get(name)
        if not entry:
            unreachable.append((name, "not a peripheral in the .repl"))
            continue
        short = entry["type"].split(".")[-1]
        if short not in emittable:
            unreachable.append((name, f"{short}: converter cannot emit it"))
            continue
        with gzip.open(f, "rt") as fh:
            n = sum(1 for _ in fh)
        reachable.append((name, short, n))

    total_acc = sum(n for _, _, n in reachable)
    types = sorted({t for _, t, _ in reachable})

    log.info("%-14s %-22s %s", "trace", "C# type", "accesses")
    log.info("%s", "-" * 52)
    for name, ty, n in reachable:
        log.info("%-14s %-22s %8d", name, ty, n)
    log.info("%s", "-" * 52)
    log.info("%d trace(s), %d distinct type(s), %s recorded accesses",
             len(reachable), len(types), f"{total_acc:,}")
    log.info("")
    if unreachable:
        log.info("not reachable:")
        for name, why in unreachable:
            log.info("    %-14s %s", name, why)
    log.info("")
    log.info("Currently replayed against generated code: 0.")
    log.info("The two peripherals under test are HAND-WRITTEN; the generated")
    log.info("modules are compiled and never executed.")
    log.info("")
    log.info("This is the gap the compile check cannot close. Well-formed is")
    log.info("not correct -- c2rust emits >99.99%% and 72.64%% of it runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
