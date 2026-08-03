#!/usr/bin/env python3
"""What does a case body DO, across the offset-switch peripherals.

`census_handrolled_registers.py` establishes that 59 of the 104 non-DSL
memory-mapped types dispatch an offset through a constant-case switch. That
locates the registers. It says nothing about what each register IS, and the
answer to that decides how many of the 59 a layout rule can serve.

So this classifies every READ case body -- the statement a `case` runs in a bus
read method -- into the shapes a register map can be built from:

  accessor     `retval = X.GetValue()`   -- a hand-rolled register class
  storage      `retval = someField`      -- a plain field, full width
  indexed      `retval = arr[i]`         -- an array of words
  computed     anything else             -- needs behaviour, not layout

A shape is only worth a rule if it recurs. The counts here are what decide it,
and they are counted over the whole corpus rather than over the one peripheral
that prompted the question.

Run:  python3 scripts/census_case_bodies.py
Log:  ./tmp/logs/census_case_bodies.log
"""

from __future__ import annotations

import collections
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from census_handrolled_registers import (BUS_READ, Corpus, dsl_users,   # noqa: E402
                                         memory_mapped, repo_root,
                                         switch_shape)


def classify(cp: Corpus, con: sqlite3.Connection, case_id: int) -> str:
    """The shape of one case body, by the operation tree alone."""
    stmts = [k for k in cp.children(case_id)
             if k[1] not in ("CaseClause", "Branch")]
    if not stmts:
        return "empty"
    if len(stmts) > 1:
        return "computed"
    kind = stmts[0][1]
    if kind != "ExpressionStatement":
        return "computed"
    inner = cp.children(stmts[0][0])
    if not inner or inner[0][1] != "SimpleAssignment":
        return "computed"
    rhs = cp.children(inner[0][0])
    if len(rhs) < 2:
        return "computed"
    r = rhs[1]
    if r[1] == "Invocation" and r[2] and r[2].split("(")[0].endswith(".GetValue"):
        return "accessor"
    if r[1] == "FieldReference":
        return "storage"
    if r[1] == "ArrayElementReference":
        return "indexed"
    if r[1] == "Conversion":
        under = cp.children(r[0])
        if under and under[0][1] == "FieldReference":
            return "storage"
        if under and under[0][1] == "ArrayElementReference":
            return "indexed"
    return "computed"


def main() -> int:
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("census_case_bodies")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(
            root / "tmp" / "logs" / "census_case_bodies.log", mode="w"),
            logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    db = root / "rulesdb" / "patterns.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cp = Corpus(con)
    per_method: dict[int, list[tuple]] = {}

    def subtree_of_method(method_id: int):
        if method_id not in per_method:
            per_method[method_id] = list(con.execute(
                "SELECT id, kind, symbol, const_value, detail FROM operation "
                "WHERE method_id = ? ORDER BY id", (method_id,)))
        return per_method[method_id]

    cp.subtree_of_method = subtree_of_method   # type: ignore[attr-defined]

    no_dsl = sorted(memory_mapped(con) - dsl_users(con))
    shapes = collections.Counter()
    per_type: dict[str, collections.Counter] = {}
    for name in no_dsl:
        reads = list(con.execute(
            "SELECT m.member_id FROM member mb JOIN method m ON m.member_id = mb.id "
            "JOIN type t ON t.id = mb.type_id WHERE t.name = ? AND m.has_body = 1 "
            f"AND mb.name IN ({','.join('?' * len(BUS_READ))})",
            (name, *BUS_READ)))
        got = collections.Counter()
        for (mid,) in reads:
            if switch_shape(cp, mid) is None:
                continue
            for oid, kind, _s, _c, _d in subtree_of_method(mid):
                if kind != "Switch":
                    continue
                for case in cp.children(oid):
                    if case[1] != "SwitchCase":
                        continue
                    labels = [cl for cl in cp.children(case[0])
                              if cl[1] == "CaseClause" and cp.children(cl[0])]
                    if not labels:
                        continue          # default:
                    got[classify(cp, con, case[0])] += len(labels)
        if got:
            per_type[name] = got
            shapes.update(got)

    total = sum(shapes.values())
    log.info("%d type(s) with a constant-case offset switch in a bus READ",
             len(per_type))
    log.info("%d case label(s) in total. What each case body does:", total)
    for shape, n in shapes.most_common():
        log.info("   %5d  %5.1f%%  %s", n, 100.0 * n / total, shape)
    log.info("")
    log.info("Per type, cases by shape (accessor/storage/indexed/computed/empty):")
    for name in sorted(per_type):
        c = per_type[name]
        log.info("   %-30s a=%-4d s=%-4d i=%-4d c=%-4d e=%-4d", name,
                 c["accessor"], c["storage"], c["indexed"], c["computed"],
                 c["empty"])
    log.info("")
    layoutable = [n for n, c in per_type.items()
                  if c["accessor"] or c["storage"] or c["indexed"]]
    log.info("%d of %d have at least one case a LAYOUT rule can serve; the rest "
             "are all `computed`.", len(layoutable), len(per_type))
    return 0


if __name__ == "__main__":
    sys.exit(main())
