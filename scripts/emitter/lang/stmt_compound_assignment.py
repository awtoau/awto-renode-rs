"""`x += y` and friends.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

DECLINES when the operator has no binary mapping, after recording it as
unhandled. Declining is deliberate: the built-in chain's fallback then emits the
gap comment, so an unmapped compound operator is visible in the output instead
of producing a line that compiles with the wrong operator.
"""

from __future__ import annotations

from emitter import core


@core.stmt("CompoundAssignment")
def compound_assignment_stmt(em, oid: int, indent: int) -> list[str] | None:
    """One compound assignment, or None when the operator is unmapped."""
    pad = "    " * indent
    row = em.con.execute(
        "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
    _symbol = row[0] if row else None
    kids = em.children(oid)
    if len(kids) < 2:
        return None

    # `x += y`. The operator is the same OperatorKind the binary table
    # carries, so `+=` is DERIVED from `+` rather than tabulated twice;
    # two tables drift and a compound assignment quietly using the
    # wrong operator is invisible in review.
    spec = em.language.get("compound_assignment", {})
    binop = em.language.get("operators", {}).get("binary", {}).get(
        _symbol or "")
    if binop:
        op = binop.replace("{lhs}", "").replace("{rhs}", "").strip()
        return [pad + spec.get("template", "{target} {op}= {value};")
                .format(target=em.emit_expr(kids[0][0]), op=op,
                        value=em.emit_expr(kids[1][0]))]
    em.unhandled[f"CompoundAssignment:{_symbol}"] = 1
    return None
