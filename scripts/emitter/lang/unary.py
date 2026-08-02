"""A unary operator.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Which operators exist and what each becomes is DATA -- `operators.unary` in the
generic rules.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 3


@core.expr("Unary", priority=PRIORITY)
def unary(em, oid):
    """Declines when the operator has no mapping.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    row = em.con.execute(
        "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
    symbol = row[0] if row else None
    kids = [c[0] for c in em.children(oid)]
    table = em.language.get("operators", {}).get("unary", {})
    tmpl = table.get(symbol or "")
    if tmpl and kids:
        return tmpl.format(operand=em.emit_expr(kids[0]))
    return None
