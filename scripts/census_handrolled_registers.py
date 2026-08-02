#!/usr/bin/env python3
"""What SHAPE are the 104 memory-mapped types that do not use the register DSL.

`census_memory_mapped.py` counts them. Counting is not enough to justify a
rule: 104 types that share nothing are 104 special cases, and CLAUDE.md calls a
"rule" matching one site a hand-written file wearing a rule's name. So this
asks the next question, which is the one that decides whether a rule family
exists at all:

    of the types that serve a memory-mapped bus WITHOUT the DSL, how many
    dispatch an offset to a per-register accessor, and how many of those
    accessors pack their fields against declared bit-mask constants?

Three facts are read per type, all from the corpus, none guessed:

  DISPATCH   a bus method contains a `switch` whose case clauses are all
             compile-time constants -- so offset -> case is a static table.
             Reported separately for a switch on a CAST offset (the
             `switch((RegisterOffset)offset)` idiom) and on the raw parameter.

  ACCESSOR   a case body reads `X.GetValue()` or writes `X.SetValue(v)` on a
             field, and that field's declared type declares the matching
             method. This is a hand-rolled register: one class per register,
             its own get/set pair.

  MASKS      that accessor class declares `const` integer fields, and its
             GetValue/SetValue reference them. These are the bit positions --
             the same information `WithFlag(3, ...)` carries in the DSL, spelt
             as `const uint FULL = (1u << 3)`.

A type scoring all three is translatable by the same rule as any other type
scoring all three, which is what "rule family" means here.

Run:  python3 scripts/census_handrolled_registers.py
Log:  ./tmp/logs/census_handrolled_registers.log
"""

from __future__ import annotations

import collections
import json
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

BUS_READ = ("ReadDoubleWord", "ReadWord", "ReadByte")
BUS_WRITE = ("WriteDoubleWord", "WriteWord", "WriteByte")
BUS_METHODS = BUS_READ + BUS_WRITE


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def dsl_users(con: sqlite3.Connection) -> set[str]:
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
    marks = ",".join("?" * len(BUS_READ))
    return {n for (n,) in con.execute(f"""
        SELECT DISTINCT t.name FROM type t
        JOIN member mb ON mb.type_id = t.id
        JOIN method m  ON m.member_id = mb.id
        WHERE t.kind = 'class' AND m.has_body = 1
          AND mb.name IN ({marks})""", BUS_READ)}


class Corpus:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self._kids: dict[int, list[tuple]] = {}

    def children(self, oid: int) -> list[tuple]:
        if oid not in self._kids:
            self._kids[oid] = list(self.con.execute(
                "SELECT id, kind, symbol, const_value, detail FROM operation "
                "WHERE parent_id = ? ORDER BY ordinal, id", (oid,)))
        return self._kids[oid]

    def subtree(self, oid: int):
        stack = [oid]
        while stack:
            for row in self.children(stack.pop()):
                yield row
                stack.append(row[0])

    def bus_methods(self, type_name: str) -> list[tuple[str, int]]:
        return list(self.con.execute(
            "SELECT mb.name, m.member_id FROM member mb "
            "JOIN method m ON m.member_id = mb.id "
            "JOIN type t ON t.id = mb.type_id "
            "WHERE t.name = ? AND m.has_body = 1 AND mb.name IN "
            f"({','.join('?' * len(BUS_METHODS))}) ORDER BY mb.name",
            (type_name, *BUS_METHODS)))

    def has_method(self, type_name: str, method: str) -> bool:
        return self.con.execute(
            "SELECT 1 FROM member mb JOIN type t ON t.id = mb.type_id "
            "WHERE t.name = ? AND mb.name = ? AND mb.kind = 'method' LIMIT 1",
            (type_name, method)).fetchone() is not None

    def const_fields(self, type_name: str) -> list[tuple[str, str]]:
        return list(self.con.execute(
            "SELECT mb.name, mb.const_value FROM member mb "
            "JOIN type t ON t.id = mb.type_id "
            "WHERE t.name = ? AND mb.kind = 'field' AND mb.const_value IS NOT NULL "
            "AND mb.declared_type IN ('uint','int','ulong','long','ushort','byte') "
            "ORDER BY mb.name", (type_name,)))


def switch_shape(cp: Corpus, method_id: int) -> str | None:
    """'cast', 'raw' or None -- what the method switches on, if anything.

    A switch whose case clauses are not all compile-time constants is not an
    offset table, so it does not count: the case value has to BE the offset.
    """
    best = None
    for oid, kind, _sym, _const, _det in cp.subtree_of_method(method_id):
        if kind != "Switch":
            continue
        kids = cp.children(oid)
        if not kids:
            continue
        cases = [k for k in kids if k[1] == "SwitchCase"]
        if not cases:
            continue
        consts = 0
        total = 0
        for c in cases:
            for cl in cp.children(c[0]):
                if cl[1] != "CaseClause":
                    continue
                label = cp.children(cl[0])
                if not label:
                    # `default:` -- a CaseClause with no value operand. It is
                    # not an offset, so it neither counts toward the table nor
                    # disqualifies it. Treating it as a non-constant clause is
                    # what hid STMCAN from the first run of this census.
                    continue
                total += 1
                if any(g[3] is not None for g in label):
                    consts += 1
        if not total or consts < total:
            continue
        subject = kids[0]
        shape = "cast" if subject[1] == "Conversion" else "raw"
        if best != "cast":
            best = shape
    return best


def accessor_types(cp: Corpus, method_id: int) -> set[str]:
    """Declared types of fields the method calls GetValue()/SetValue() on."""
    out: set[str] = set()
    for _oid, kind, sym, _const, _det in cp.subtree_of_method(method_id):
        if kind != "Invocation" or not sym:
            continue
        head = sym.split("(")[0]
        leaf = head.split(".")[-1]
        if leaf not in ("GetValue", "SetValue", "SetResetValue"):
            continue
        owner = ".".join(head.split(".")[:-1]).split(".")[-1]
        if owner:
            out.add(owner)
    return out


def main() -> int:
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("census_handrolled_registers")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(
            root / "tmp" / "logs" / "census_handrolled_registers.log", mode="w"),
            logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus at rulesdb/patterns.db -- it is gitignored.")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cp = Corpus(con)

    # Method-scoped subtree, cached: walking by parent_id per node is O(n) queries.
    per_method: dict[int, list[tuple]] = {}

    def subtree_of_method(method_id: int):
        if method_id not in per_method:
            per_method[method_id] = list(con.execute(
                "SELECT id, kind, symbol, const_value, detail FROM operation "
                "WHERE method_id = ? ORDER BY id", (method_id,)))
        return per_method[method_id]

    cp.subtree_of_method = subtree_of_method   # type: ignore[attr-defined]

    mm, dsl = memory_mapped(con), dsl_users(con)
    no_dsl = sorted(mm - dsl)

    rows = []
    for name in no_dsl:
        methods = cp.bus_methods(name)
        shapes = {m: switch_shape(cp, mid) for m, mid in methods}
        accessors: set[str] = set()
        for _m, mid in methods:
            accessors |= accessor_types(cp, mid)
        # An accessor type counts only if the CORPUS shows it declaring the
        # pair. A `GetValue` on a BCL type is not a hand-rolled register.
        real = {a for a in accessors
                if cp.has_method(a, "GetValue") and (cp.has_method(a, "SetValue")
                                                     or cp.has_method(a, "SetResetValue"))}
        masks = {a: len(cp.const_fields(a)) for a in sorted(real)}
        rows.append({
            "type": name,
            "dispatch": ("cast" if "cast" in shapes.values()
                         else "raw" if "raw" in shapes.values() else None),
            "bus_methods": len(methods),
            "accessors": sorted(real),
            "mask_consts": sum(masks.values()),
        })

    n = len(rows)
    by_dispatch = collections.Counter(r["dispatch"] for r in rows)
    with_acc = [r for r in rows if r["accessors"]]
    full = [r for r in rows if r["dispatch"] and r["accessors"] and r["mask_consts"]]

    log.info("%d memory-mapped types use NO register DSL. Their shapes:", n)
    log.info("")
    log.info("  DISPATCH -- a bus method switches on a constant case table")
    log.info("    %3d  switch on a CAST offset  (switch((SomeEnum)offset))",
             by_dispatch.get("cast", 0))
    log.info("    %3d  switch on the raw offset", by_dispatch.get("raw", 0))
    log.info("    %3d  no constant-case switch at all -- if/else, array index,",
             by_dispatch.get(None, 0))
    log.info("         or a shape this census does not name")
    log.info("")
    log.info("  ACCESSOR -- a case body calls GetValue()/SetValue() on a field")
    log.info("             whose declared type declares that pair")
    log.info("    %3d  yes", len(with_acc))
    log.info("    %3d  no", n - len(with_acc))
    log.info("")
    log.info("  BOTH, plus bit-mask constants on the accessor class:")
    log.info("    %3d  type(s)", len(full))
    for r in full:
        log.info("      %-22s %-5s %2d accessor class(es), %3d mask const(s)",
                 r["type"], r["dispatch"], len(r["accessors"]), r["mask_consts"])
    log.info("")
    log.info("DISPATCH-ONLY -- a constant-case offset switch, no accessor pair.")
    log.info("These share the OFFSET half of the shape and not the field half:")
    only = [r for r in rows if r["dispatch"] and not r["accessors"]]
    log.info("    %3d type(s)", len(only))
    for r in only:
        log.info("      %-22s %s", r["type"], r["dispatch"])
    log.info("")
    log.info("NEITHER -- no constant-case switch and no accessor pair:")
    none = [r for r in rows if not r["dispatch"] and not r["accessors"]]
    log.info("    %3d type(s): %s", len(none),
             ", ".join(r["type"] for r in none))

    out = root / "tmp" / "handrolled_census.json"
    out.write_text(json.dumps(rows, indent=2, sort_keys=True))
    log.info("")
    log.info("per-type detail: tmp/handrolled_census.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
