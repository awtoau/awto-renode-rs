#!/usr/bin/env python3
"""Run the offset-switch rules over EVERY non-DSL memory-mapped type.

One site is not a rule. `census_handrolled_registers.py` says 59 of the 104
types that serve a bus without the register DSL dispatch a constant-case switch
on the offset; this is the other half of that claim -- it actually runs the
emitter on all 104 and reports how many registers each yields.

It is a REPORT, not a gate. A type that yields nothing is not a failure: the
shape may genuinely be absent, and declining is what a rule is supposed to do
when it does not match. What WOULD be a failure is the emitter raising, or a
type yielding registers with no gaps and no fields, and both are counted here.

Correctness is not claimed for any of them. Only 8 peripherals have traces, and
`can1` is the only one of the 104 among them -- so this measures REACH, which is
the thing a wider corpus can honestly measure, and nothing else.

Run:  python3 scripts/check_offset_switch.py
Log:  ./tmp/logs/check_offset_switch.log
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


ROOT = repo_root()
sys.path.insert(0, str(ROOT / "scripts" / "core"))
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))

import csharp_emitter as emit  # noqa: E402
from census_handrolled_registers import dsl_users, memory_mapped  # noqa: E402


def main() -> int:
    logdir = ROOT / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_offset_switch")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(logdir / "check_offset_switch.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    db = ROOT / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus at rulesdb/patterns.db -- it is gitignored.")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    em = emit.Emitter(con, log)

    names = sorted(memory_mapped(con) - dsl_users(con))
    emitted: list[tuple[str, int, int, int]] = []
    declined: list[str] = []
    silent: list[str] = []
    crashed: list[tuple[str, str]] = []
    for name in names:
        try:
            built = em._osr_build(name)
        except Exception as exc:                       # noqa: BLE001
            crashed.append((name, f"{type(exc).__name__}: {exc}"))
            continue
        regs = sum(1 for line in built["stmts"] if "bank.define(" in line)
        fields = sum(1 for line in built["stmts"] if ".with_" in line)
        if regs:
            emitted.append((name, regs, fields, len(built["gaps"])))
        elif built["gaps"]:
            declined.append(name)
        else:
            silent.append(name)

    log.info("%d memory-mapped type(s) use no register DSL.", len(names))
    log.info("")
    log.info("%d yield a register map:", len(emitted))
    for name, regs, fields, gaps in sorted(emitted, key=lambda r: -r[1]):
        log.info("    %-26s %3d register(s) %4d field(s) %3d gap(s)",
                 name, regs, fields, gaps)
    log.info("")
    log.info("%d yield nothing AND SAY WHY (a gap in the file header):",
             len(declined))
    log.info("    %s", ", ".join(declined))
    log.info("")
    log.info("%d yield nothing and report nothing -- these have no bus read "
             "method at all,", len(silent))
    log.info("so there is no path that could have emitted and did not:")
    log.info("    %s", ", ".join(silent))
    if crashed:
        log.error("")
        log.error("%d type(s) RAISED. A rule may decline; it may not fall over:",
                  len(crashed))
        for name, why in crashed:
            log.error("    %-26s %s", name, why)
        return 1
    log.info("")
    log.info("TOTAL %d register(s) and %d field(s) over %d type(s). Reach only "
             "-- of these,", sum(r for _n, r, _f, _g in emitted),
             sum(f for _n, _r, f, _g in emitted), len(emitted))
    log.info("only can1 has a trace, so nothing here claims the output is right.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
