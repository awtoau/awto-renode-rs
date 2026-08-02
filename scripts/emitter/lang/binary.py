"""A binary operator.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Which operators exist and what each becomes is DATA -- `operators.binary` in the
generic rules. This module only decides that the node is one, and how the two
operands nest.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 2


@core.expr("Binary", priority=PRIORITY)
def binary(em, oid):
    """Declines when the operator has no mapping, and counts it by SYMBOL.

    The per-symbol count is the useful one: `expr:Binary` says an operator was
    missed, `Binary:<symbol>` says which. Both are recorded, exactly as they
    were when this was a branch in the built-in chain -- the caller adds the
    kind-level count once this declines.
    """
    row = em.con.execute(
        "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
    symbol = row[0] if row else None
    kids = [c[0] for c in em.children(oid)]
    table = em.language.get("operators", {}).get("binary", {})
    tmpl = table.get(symbol or "")
    if tmpl and len(kids) >= 2:
        return "(" + tmpl.format(lhs=em.emit_expr(kids[0]),
                                 rhs=em.emit_expr(kids[1])) + ")"
    em.unhandled[f"Binary:{symbol}"] = em.unhandled.get(f"Binary:{symbol}", 0) + 1
    return None
