#!/usr/bin/env python3
"""A type whose corpus calls register combinators must emit registers, or gap.

This is the check that was missing, and its absence hid the largest defect
found so far.

WHAT IT CAUGHT
--------------
`compile_check.py` used to pick a type's register-defining method BY NAME --
the alphabetically first member whose name contains "Register". That selector
was wrong in two directions at once, and both were silent:

  * A type whose register map is built in its CONSTRUCTOR has no such member,
    so it matched nothing and was dropped from the run entirely. Four
    peripherals of the target platform vanished this way -- STM32F4_RCC (240
    combinator calls), STM32F4_RTC (157), STM32_RNG (24), STM32_CRC (15).
  * A type with an unrelated member called `Register` -- an
    `IPeripheralContainer.Register` overload, say -- selected THAT, and then
    emitted a module with an empty `define_registers`. STM32_Timer has 125
    combinator calls and emitted no register at all.

Neither produced an error, a gap, or a missing file. The modules simply were
not in the run, so every headline number -- module count, compile errors,
"N of M clean" -- was computed over the wrong denominator and read as complete.

That selector is gone: `scripts/register_owners.py` chooses the member whose
BODY contains register-form invocations, and every consumer imports it. This
check is what proves the replacement is doing its job, and it stays because the
next selector defect will look exactly like the last one -- a number that got
smaller with nobody told.

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

THE BLIND SPOT IN THAT SHAPE, AND WHAT COVERS IT
------------------------------------------------
`N` is a count of combinator calls, so a type that uses NO register DSL scores
N = 0 and passes -- while serving a memory-mapped bus and modelling every
register by hand in a `switch` on the offset. 393 corpus types answer
`ReadDoubleWord`/`ReadWord`/`ReadByte` with a body (the set
`scripts/census_memory_mapped.py` names, imported from there); 284 use the DSL
and **104 do not**. STMCAN is one: a 58-case switch and not a single `With*`
call anywhere in it.

Those 104 are a category, not a regression, and no plugin is coming for them --
the specific hand-rolled idiom appears twice in 448k lines, and a rule matching
two sites is a hand-written file wearing a rule's name. So they are counted and
named, and they do not fail this check.

What DOES fail is the sharp end of it: a type in that set for which the
selector picks a member anyway, so the converter emits a module whose
`define_registers` is empty. A module that looks like a peripheral and models
nothing is worse than no module, because the module list is what every other
number is computed over. Five types are in that state, down from seven.

Run:  python3 scripts/check_emitted_registers.py
Log:  ./tmp/logs/check_emitted_registers.log
"""

from __future__ import annotations

import logging
import os
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
    import emit_pool                                           # noqa: E402

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

    # What the converter actually produces, via the SAME selector the emission
    # tooling uses -- `scripts/register_owners.py`, imported rather than
    # re-implemented, so this check can never pass while measuring a different
    # set of types than compile_check.py emits. If the selector is broken this
    # reports it, which is the case that started this.
    from register_owners import owners                          # noqa: E402
    selected = dict(owners(con))

    # Types that serve a memory-mapped bus. `demand` cannot see the ones that
    # model their registers by hand, because it counts DSL calls and they make
    # none -- so this is the second question, asked of the same corpus by a
    # different route. The bus entry points are named in
    # `scripts/census_memory_mapped.py` and imported, not re-listed: which
    # methods count as a bus surface is exactly the sort of fact that drifts
    # when two files each hold their own copy.
    from census_memory_mapped import memory_mapped                # noqa: E402
    bus = memory_mapped(con)
    hand_rolled = sorted(bus - set(demand))

    # One pool for both questions. Serial this was ~40 minutes over 580 types,
    # which is the length at which a check stops being run -- the same reason
    # the compile gate was being skipped. `emit_pool` returns results in TASK
    # order, so nothing here depends on which worker finished first.
    tasks = [(n, selected[n], "m") for n in sorted(demand) if n in selected]
    tasks += [(n, selected[n], "m") for n in hand_rolled if n in selected]
    results = {r.name: r for r in emit_pool.emit_many(
        db, tasks, jobs=max(1, (os.cpu_count() or 2) - 1))}

    unreachable: list[tuple[str, int]] = []
    empty: list[tuple[str, int, str]] = []
    ok = 0
    for name in sorted(demand):
        calls = demand[name]
        method = selected.get(name)
        if method is None:
            unreachable.append((name, calls))
            continue
        r = results[name]
        if r.text is None:
            empty.append((name, calls, f"emit raised: {r.err_type}: {r.err_msg}"))
        elif "bank.define(" not in r.text:
            empty.append((name, calls, f"selected `{method}`"))
        else:
            ok += 1

    # The hand-rolled set. Emitting a module for one of these is the defect;
    # not emitting one is the correct outcome, and is reported as a size.
    phantom: list[str] = []
    for name in hand_rolled:
        method = selected.get(name)
        if method is None:
            continue
        r = results[name]
        if r.text is None:
            phantom.append(f"{name} (selected `{method}`, emit raised)")
        elif "bank.define(" not in r.text:
            phantom.append(f"{name} (selected `{method}`)")

    log.info("%d type(s) call register combinators in the corpus", len(demand))
    log.info("%d emit at least one register definition", ok)
    log.info("")
    log.info("%d type(s) serve a memory-mapped bus; %d of them use the register "
             "DSL and %d model their registers by hand.",
             len(bus), len(bus & set(demand)), len(hand_rolled))
    log.info("The hand-rolled %d are a CATEGORY, not a regression: the specific "
             "idiom appears twice in the corpus, and a rule matching two sites "
             "is a hand-written file wearing a rule's name. They are counted "
             "here so the number is visible, and they do not fail this check.",
             len(hand_rolled))
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

    if phantom:
        log.error("PHANTOM MODULE -- serves a bus, defines no register by any "
                  "mechanism, and the selector picked a member anyway, so a "
                  "module is emitted whose `define_registers` is empty:")
        for line in phantom:
            log.error("    %s", line)
        log.error("A module that looks like a peripheral and models nothing is "
                  "worse than no module: the module list is the denominator of "
                  "every other number.")
        log.error("")

    if unreachable or empty or phantom:
        total = sum(c for _n, c in unreachable) + sum(c for _n, c, _w in empty)
        log.error("FAIL: %d type(s) with %d combinator call(s) between them "
                  "produce no register definition, and no gap says so.",
                  len(unreachable) + len(empty), total)
        log.error("Plus %d phantom module(s) from the hand-rolled set.",
                  len(phantom))
        log.error("A peripheral missing from the run is not a smaller run --")
        log.error("it is a wrong denominator for every number computed from it.")
        return 1

    log.info("OK: every type the corpus shows defining registers emits some, "
             "and no hand-rolled type emits an empty module")
    return 0


if __name__ == "__main__":
    sys.exit(main())
