#!/usr/bin/env python3
"""How many memory-mapped peripherals do NOT use the register DSL.

Read-only census, never a gate. It exists because `check_emitted_registers.py`
asks a question with a blind spot, and the size of that blind spot is a number
rather than an opinion.

That check compares
    the corpus says this type calls N register COMBINATORS
    the converter emitted M register definitions
and fails when N > 0 and M == 0. Sound as far as it goes -- but a type that
serves a memory-mapped bus WITHOUT the DSL scores N = 0, so it passes while
emitting nothing.

STMCAN is exactly that type. It has zero combinator calls anywhere in its
family, hand-rolls a register per nested class with `SetValue(uint)` /
`GetValue()`, and dispatches with `switch((RegisterOffset)offset)` inside
`ReadDoubleWord`. The name selector still picks a method for it -- the
alphabetically first member containing "Register", which is the predicate
`AddressIsWithinFilterRegistersArea` -- so a module IS emitted, with an empty
`define_registers`, and no gap says why. On the `can1` trace that scores 99
divergences over 115 reads: precisely the count of non-zero reads, because an
empty bank returns 0 for all of them.

So the useful question is not "does it call combinators", it is:

    does this type serve a memory-mapped bus at all,
    and if so does anything emit registers for it?

This prints that split. The subset worth acting on is the last one: types the
selector DOES pick a method for, which therefore emit a silent empty module.

Run:  python3 scripts/census_memory_mapped.py
Log:  ./tmp/logs/census_memory_mapped.log
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import subprocess
import sys
from pathlib import Path

# The bus entry points a memory-mapped peripheral implements. Named here rather
# than pattern-matched, because "has a method whose name starts with Read" also
# catches ReadFromFile.
BUS_METHODS = ("ReadDoubleWord", "ReadWord", "ReadByte")


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def dsl_users(con: sqlite3.Connection) -> set[str]:
    """Types the corpus shows calling a register combinator."""
    return {n for (n,) in con.execute("""
        SELECT DISTINCT ty.name FROM operation o
        JOIN method m  ON m.member_id = o.method_id
        JOIN member mb ON mb.id = m.member_id
        JOIN type ty   ON ty.id = mb.type_id
        WHERE o.kind = 'Invocation'
          AND (o.symbol LIKE '%.With%' OR o.symbol LIKE '%.Define(%'
               OR o.symbol LIKE '%.DefineValueField%'
               OR o.symbol LIKE '%.DefineFlagField%'
               OR o.symbol LIKE '%.DefineEnumField%')""")}


def memory_mapped(con: sqlite3.Connection) -> set[str]:
    """Types with a bus read entry point that has a body."""
    marks = ",".join("?" * len(BUS_METHODS))
    return {n for (n,) in con.execute(f"""
        SELECT DISTINCT t.name FROM type t
        JOIN member mb ON mb.type_id = t.id
        JOIN method m  ON m.member_id = mb.id
        WHERE t.kind = 'class' AND m.has_body = 1
          AND mb.name IN ({marks})""", BUS_METHODS)}


def selected(con: sqlite3.Connection) -> dict[str, str]:
    """type -> the register-defining member the emission tooling picks.

    Was a copy of the name-based query, deliberately, so that the disagreement
    it measured was the same disagreement `compile_check.py` had. That query is
    gone -- `scripts/register_owners.py` selects by what a body CONTAINS -- and
    the same reasoning now says to IMPORT it: a copy here would make this
    census describe a selector nothing uses.

    The census still earns its place. Selecting by content did not empty this
    set: five hand-rolled types have a stray dictionary `Add` somewhere, pass
    the form test, and emit a module with no registers in it.
    """
    from register_owners import owners
    return dict(owners(con))


def main() -> int:
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("census_memory_mapped")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(
            root / "tmp" / "logs" / "census_memory_mapped.log", mode="w"),
            logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus at rulesdb/patterns.db -- it is gitignored, so a")
        log.error("fresh worktree does not have one. Copy it in or re-ingest.")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    mm, dsl, sel = memory_mapped(con), dsl_users(con), selected(con)
    no_dsl = mm - dsl
    silent = sorted(no_dsl & set(sel))

    log.info("%d type(s) serve a memory-mapped bus (%s with a body)",
             len(mm), "/".join(BUS_METHODS))
    log.info("%d of those use the register DSL", len(mm & dsl))
    log.info("%d of those use NO register DSL -- invisible to "
             "check_emitted_registers", len(no_dsl))
    log.info("")
    log.info("Of the %d, the selector still picks a member for %d, so each "
             "emits", len(no_dsl), len(silent))
    log.info("a module with an empty `define_registers`:")
    for name in silent:
        log.info("    %-24s selector picks `%s`", name, sel[name])
    log.info("")
    log.info("The other %d are dropped from the run entirely.",
             len(no_dsl) - len(silent))
    log.info("`check_emitted_registers.py` now names both: it reads this same "
             "bus set, counts the hand-rolled types as a category, and FAILS on "
             "the ones that emit a module anyway.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
