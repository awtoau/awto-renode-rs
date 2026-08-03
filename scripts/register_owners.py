#!/usr/bin/env python3
"""Which member of a type actually defines its registers. Selected by CONTENT.

THE DEFECT THIS REPLACES
------------------------
Five scripts each carried their own copy of this query::

    SELECT t.name, MIN(mb.name) FROM type t
    JOIN member mb ON mb.type_id = t.id
    JOIN method m ON m.member_id = mb.id
    WHERE t.kind='class' AND m.has_body=1
      AND (mb.name LIKE '%Register%' OR mb.name LIKE '%DefineReg%')
    GROUP BY t.name

It picks the alphabetically first member whose NAME contains "Register", which
is wrong in two directions at once, and silent in both:

  * **Missed.** A type that builds its register map in its CONSTRUCTOR has no
    such member, so it matched nothing and was dropped from every run. Four
    peripherals of the target platform vanished this way -- STM32F4_RCC,
    STM32F4_RTC, STM32_RNG, STM32_CRC. Their registers were never emitted and
    nothing said so, because a type absent from the list produces no file that
    could be noticed missing.
  * **Mis-picked.** A type with an unrelated member called `Register` -- an
    `IPeripheralContainer.Register` overload, an
    `AddressIsWithinFilterRegistersArea` predicate -- selects THAT, and emits a
    module whose `define_registers` is empty. STM32_Timer has 125 combinator
    calls and emitted no register at all.

Neither produced an error. Every headline number -- module count, compile
errors, gap census, "N of M clean" -- was therefore computed over the wrong set
of types, and read as complete.

WHAT REPLACES IT
----------------
The corpus records what each body DOES, so ask that instead. Two facts about
each body, both read from the emitter's own definitions rather than from a
second copy of them:

  1. **Register forms** -- what LOCATES a register (`.Define(`, and a
     dictionary `Add`). A member with none of them has nothing the emitter
     could turn into a register, so it is not a candidate at all.
  2. **Combinators** -- `WithFlag`, `DefineValueField` and the rest, recognised
     by `RegisterDsl.combinator`, which knows the four declaring types the DSL
     is spread across. This is what makes a located register a register rather
     than a dictionary entry.

The winner is the candidate with the most COMBINATOR calls, then the most
forms, then the member name ascending -- so the selection is identical at `-j1`
and `-j32`.

Combinators rank ahead of forms because the dictionary form matches ANY
`Dictionary<TKey, TValue>.Add`. STM32_SYSCFG's constructor adds sixteen GPIOs
to a dictionary in a loop, which `find_registers` will happily report as
sixteen located registers at four-byte spacing; its `CreateRegisters` locates
four and is the real one. Ranking on located registers picked the constructor
and emitted a module with no registers in it. Ranking on combinators picks
`CreateRegisters`, because a bag of `new GPIO()` has none.

A type whose every candidate has zero combinators is still selected, on the
form count alone. Dropping it would move a peripheral from "emitted a module
with no registers", which `check_emitted_registers.py` reports and names, to
"absent", which is the silence this whole module exists to remove.

Member KIND is not filtered. A constructor has a body, and so does an explicit
interface implementation of a property getter -- `.ctor` and
`IProvidesRegisterCollection<..>.get_RegistersCollection` are both real answers
in this corpus, and both were unreachable while the selector filtered on how
the member was spelled.

THE SAME QUESTION, ONE LEVEL DOWN
---------------------------------
`sub_blocks.child_register_method` already asks this for a NESTED child, and
already asks it by trying rather than by name -- it runs `find_registers` over
each candidate and keeps the first that yields anything. It restricts to
`mb.kind = 'method'`, which is precisely what hides a constructor, so the same
defect exists there one level down.

The two are not merged here because that file belongs to another issue. They
should be, and when they are, note that this module's ranking is deliberately
NOT "first candidate that locates registers": that rule picks STM32_SYSCFG's
constructor over its `CreateRegisters`, for the reason given above.

WHAT IT DOES NOT FIX
--------------------
The emitter takes a member NAME (`emit_file(type, method, module)`) and looks
it up with `WHERE t.name=? AND mb.name=?`, so an overloaded name, or two
distinct types sharing a short name, still resolve to whichever row sqlite
returns first. 21 of 728 candidates are ambiguous that way. That is a
pre-existing ambiguity in the emitter's lookup, not one introduced here, and
fixing it means changing the emitter's interface.

Nor does it invent a register method for a type that has none: STMCAN switches
on the address and uses no DSL at all, so no member of it contains a register
form and it is correctly absent. 105 of the 393 types that serve a memory-mapped
bus are like that. `check_emitted_registers.py` is the check that compares this
selection against two independent readings of the corpus -- combinator calls,
and bus entry points -- and reports what is still missing. Five hand-rolled
types still pass this selector on a stray dictionary `Add` and emit an empty
module; that check names them.

Not a check; nothing here exits non-zero. Run it to see the selection::

    python3 scripts/register_owners.py                 # every type
    python3 scripts/register_owners.py --filter STM32
Log:  ./tmp/logs/register_owners.log
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Iterable

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def form_symbols(rules_dir: Path | None = None) -> list[str]:
    """The `symbol_contains` of every register form, from the rules data."""
    from emit import load_register_forms
    rd = rules_dir or repo_root() / "rulesdb" / "rules"
    return sorted({f["symbol_contains"] for f in load_register_forms(rd)
                   if f.get("symbol_contains")})


def candidates(con: sqlite3.Connection, rules_dir: Path | None = None,
               name_filter: str | None = None,
               types: Iterable[str] | None = None
               ) -> list[tuple[str, str, int, int]]:
    """(type, member, member id, register-form invocations) per candidate body.

    `instr`, not `LIKE`: `find_registers` tests `symbol_contains in symbol`,
    and `LIKE` would give `%` and `_` inside a form's symbol a wildcard meaning
    the emitter does not give them.
    """
    syms = form_symbols(rules_dir)
    if not syms:
        return []
    pred = " OR ".join(["instr(o.symbol, ?) > 0"] * len(syms))
    params: list = list(syms)
    where = ""
    if name_filter:
        where += " AND ty.name LIKE ?"
        params.append(f"%{name_filter}%")
    names = sorted(types) if types is not None else None
    if names is not None:
        if not names:
            return []
        where += f" AND ty.name IN ({','.join('?' * len(names))})"
        params.extend(names)
    return con.execute(f"""
        SELECT ty.name, mb.name, mb.id, COUNT(*)
        FROM operation o
        JOIN member mb ON mb.id = o.method_id
        JOIN method m  ON m.member_id = mb.id
        JOIN type ty   ON ty.id = mb.type_id
        WHERE ty.kind = 'class' AND m.has_body = 1
          AND o.kind = 'Invocation' AND o.symbol IS NOT NULL
          AND ({pred}) {where}
        GROUP BY ty.name, mb.name, mb.id""", params).fetchall()


def combinator_counts(con: sqlite3.Connection, member_ids: Iterable[int],
                      rules_dir: Path | None = None) -> dict[int, int]:
    """member id -> how many register COMBINATORS its body calls.

    `RegisterDsl.combinator` decides, so the four declaring types the DSL is
    spread across, and the leaf prefixes that separate a combinator from
    `UnderlyingValue`, are read from the rules rather than approximated with a
    `LIKE '%.With%'` here. Distinct symbols are classified once: the corpus has
    a few hundred of them and hundreds of thousands of calls.
    """
    # Sorted, not set-ordered: the chunking below is what reaches sqlite, and a
    # query that varies run to run is exactly the kind of thing that makes an
    # output differ at -j1 and -j32 for no visible reason.
    ids = sorted(member_ids)
    if not ids:
        return {}
    from emit import Emitter
    quiet = logging.getLogger("register_owners.quiet")
    quiet.handlers.clear()
    quiet.addHandler(logging.NullHandler())
    em = Emitter(con, quiet, rules_dir)

    out: dict[int, int] = {i: 0 for i in ids}
    known: dict[str, bool] = {}
    for chunk in (ids[i:i + 500] for i in range(0, len(ids), 500)):
        for mid, symbol, n in con.execute(
                f"""SELECT o.method_id, o.symbol, COUNT(*) FROM operation o
                    WHERE o.kind = 'Invocation' AND o.symbol IS NOT NULL
                      AND o.method_id IN ({','.join('?' * len(chunk))})
                    GROUP BY o.method_id, o.symbol""", chunk):
            is_comb = known.get(symbol)
            if is_comb is None:
                is_comb = em.combinator(symbol) is not None
                known[symbol] = is_comb
            if is_comb:
                out[mid] += n
    return out


def owner_counts(con: sqlite3.Connection, rules_dir: Path | None = None,
                 name_filter: str | None = None,
                 types: Iterable[str] | None = None
                 ) -> dict[str, tuple[str, int, int]]:
    """type name -> (member name, combinator calls, register-form calls)."""
    rows = candidates(con, rules_dir, name_filter, types)
    if not rows:
        return {}
    combs = combinator_counts(con, {r[2] for r in rows}, rules_dir)

    ranked: dict[str, list[tuple[int, int, str]]] = {}
    for tname, mname, mid, forms in rows:
        ranked.setdefault(tname, []).append((combs.get(mid, 0), forms, mname))

    return {t: (m, c, f) for t, cands in ranked.items()
            for c, f, m in [sorted(cands, key=lambda c: (-c[0], -c[1], c[2]))[0]]}


def owners(con: sqlite3.Connection, rules_dir: Path | None = None,
           name_filter: str | None = None,
           types: Iterable[str] | None = None) -> list[tuple[str, str]]:
    """(type, register-defining member) for every type that has one, sorted.

    The drop-in replacement for the name-based query, and the only selector any
    script should use.
    """
    return sorted((t, v[0]) for t, v in
                  owner_counts(con, rules_dir, name_filter, types).items())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--filter", default=None, help="substring of the type name")
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("register_owners")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    for h in (logging.FileHandler(root / "tmp" / "logs" / "register_owners.log",
                                  mode="w"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    con = sqlite3.connect(f"file:{root / args.db}?mode=ro", uri=True)
    counts = owner_counts(con, name_filter=args.filter)
    log.info("register forms: %s", ", ".join(form_symbols()))
    log.info("%d type(s) have a member whose body defines registers", len(counts))
    log.info("%d of them call at least one combinator",
             sum(1 for _m, c, _f in counts.values() if c))
    log.info("")
    log.info("%-40s %-46s %11s %7s", "type", "member", "combinators", "forms")
    for t, (m, c, f) in sorted(counts.items()):
        log.info("%-40s %-46s %11d %7d", t, m, c, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
