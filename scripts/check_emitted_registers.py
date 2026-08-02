#!/usr/bin/env python3
"""A type whose corpus calls register combinators must emit registers, or gap.

This is the check that was missing, and its absence hid the largest defect
found so far.

WHAT IT CATCHES
---------------
`compile_check.py` picks a type's register-defining method BY NAME -- the
alphabetically first member whose name contains "Register". That selector is
wrong in two directions at once, and both are silent:

  * A type whose register collection is an AUTO-PROPERTY has no getter method
    row, so it matches nothing and is dropped from the run entirely. Four
    peripherals of the target platform vanished this way -- STM32F4_RCC (240
    combinator calls), STM32F4_RTC (157), STM32_RNG (24), STM32_CRC (15).
  * A type with an unrelated member called `Register` -- an
    `IPeripheralContainer.Register` overload, say -- selects THAT, and then
    emits a module with an empty `define_registers`. STM32_Timer has 125
    combinator calls and emitted no register at all.

Neither produced an error, a gap, or a missing file. The modules simply were
not in the run, so every headline number -- module count, compile errors,
"N of M clean" -- was computed over the wrong denominator and read as complete.

WHY THIS SHAPE OF CHECK
-----------------------
It compares two things that come from different places and must agree:

    the CORPUS says this type calls N register combinators
    the CONVERTER emitted M register definitions for it

If N > 0 and M == 0, something is wrong and nobody was told. That is true
whatever the cause -- a bad selector, an unmatched DSL family, a rule that
declined -- which is what makes it worth having. A check that knows only how
the converter works cannot notice the converter not running.

The rule this enforces is the project's own: a path that emits nothing must
say why. Here the path is a whole peripheral.

Run:  python3 scripts/check_emitted_registers.py
Log:  ./tmp/logs/check_emitted_registers.log
"""

from __future__ import annotations

import contextlib
import io
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def main() -> int:
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_emitted_registers")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(
            root / "tmp" / "logs" / "check_emitted_registers.log", mode="w"),
            logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus at rulesdb/patterns.db -- it is gitignored, so a")
        log.error("fresh worktree does not have one. Copy it in or re-ingest.")
        return 1

    sys.path.insert(0, str(root / "scripts"))
    from emit import Emitter                                   # noqa: E402

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    # Every class the corpus shows calling register combinators, and how often.
    # Counted from the OPERATIONS, so it does not care what any method is
    # called -- which is the whole point, since the name is what misled the
    # existing selector.
    demand = {name: n for name, n in con.execute("""
        SELECT ty.name, COUNT(*) FROM operation o
        JOIN method m   ON m.member_id = o.method_id
        JOIN member mb  ON mb.id = m.member_id
        JOIN type ty    ON ty.id = mb.type_id
        WHERE ty.kind = 'class' AND o.kind = 'Invocation'
          AND (o.symbol LIKE '%.With%' OR o.symbol LIKE '%.Define(%'
               OR o.symbol LIKE '%.DefineValueField%'
               OR o.symbol LIKE '%.DefineFlagField%'
               OR o.symbol LIKE '%.DefineEnumField%')
        GROUP BY ty.name HAVING COUNT(*) > 0""")}

    quiet = logging.getLogger("quiet")
    quiet.addHandler(logging.NullHandler())

    # What the converter actually produces, via the SAME selector the emission
    # tooling uses. If the selector is broken this reports it, which is the
    # case that started this.
    selected = {name: method for name, method in con.execute("""
        SELECT t.name, MIN(mb.name) FROM type t
        JOIN member mb ON mb.type_id = t.id
        JOIN method m  ON m.member_id = mb.id
        WHERE t.kind='class' AND m.has_body=1
          AND (mb.name LIKE '%Register%' OR mb.name LIKE '%DefineReg%')
        GROUP BY t.name""")}

    unreachable: list[tuple[str, int]] = []
    empty: list[tuple[str, int, str]] = []
    ok = 0
    for name in sorted(demand):
        calls = demand[name]
        method = selected.get(name)
        if method is None:
            unreachable.append((name, calls))
            continue
        em = Emitter(sqlite3.connect(f"file:{db}?mode=ro", uri=True), quiet)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                out = em.emit_file(name, method, "m")
        except Exception as exc:                              # noqa: BLE001
            empty.append((name, calls, f"emit raised: {exc}"))
            continue
        if "bank.define(" not in out:
            empty.append((name, calls, f"selected `{method}`"))
            continue
        ok += 1

    log.info("%d type(s) call register combinators in the corpus", len(demand))
    log.info("%d emit at least one register definition", ok)
    log.info("")

    if unreachable:
        log.error("NO METHOD SELECTED -- these types are not emitted at all,")
        log.error("and nothing reports their absence:")
        for name, calls in sorted(unreachable, key=lambda kv: -kv[1]):
            log.error("    %-32s %5d combinator call(s) in the corpus",
                      name, calls)
        log.error("")
    if empty:
        log.error("EMITTED WITH NO REGISTERS -- the corpus says they have some:")
        for name, calls, why in sorted(empty, key=lambda kv: -kv[1]):
            log.error("    %-32s %5d combinator call(s), %s", name, calls, why)
        log.error("")

    if unreachable or empty:
        total = sum(c for _n, c in unreachable) + sum(c for _n, c, _w in empty)
        log.error("FAIL: %d type(s) with %d combinator call(s) between them "
                  "produce no register definition, and no gap says so.",
                  len(unreachable) + len(empty), total)
        log.error("A peripheral missing from the run is not a smaller run --")
        log.error("it is a wrong denominator for every number computed from it.")
        return 1

    log.info("OK: every type the corpus shows defining registers emits some")
    return 0


if __name__ == "__main__":
    sys.exit(main())
