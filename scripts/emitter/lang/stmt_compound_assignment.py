"""`x += y` and friends.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

DECLINES when the operator has no binary mapping, after recording it as
unhandled. Declining is deliberate: the built-in chain's fallback then emits the
gap comment, so an unmapped compound operator is visible in the output instead
of producing a line that compiles with the wrong operator.
"""

from __future__ import annotations

from emitter import core
from emitter.lang.binary import runtime_template


@core.stmt("CompoundAssignment")
def compound_assignment_stmt(em, oid: int, indent: int) -> list[str] | None:
    """One compound assignment, or None when the operator is unmapped."""
    pad = "    " * indent
    row = em.con.execute(
        "SELECT symbol, type, detail FROM operation WHERE id=?", (oid,)).fetchone()
    _symbol, _rtype, _detail = row if row else (None, None, None)
    kids = em.children(oid)
    if len(kids) < 2:
        return None

    spec = em.language.get("compound_assignment", {})

    # `x += y` has exactly the overflow semantics `x + y` has, so it takes the
    # same runtime redirect -- decided by the BINARY rule's function rather
    # than by a second copy of the same three guards.
    rt = runtime_template(em, _symbol, _rtype, _detail)
    if rt and em.kind_of(kids[0][0]) in spec.get("runtime_target_kinds", []):
        # The target is emitted twice, so this is confined to place
        # expressions. A property target is a getter CALL and C# evaluates it
        # once; see `runtime_target_kinds_why`.
        target = em.emit_expr(kids[0][0])
        expr = rt.format(lhs=target, rhs=em.emit_expr(kids[1][0]))
        return [pad + spec.get("runtime_template", "{target} = {expr};")
                .format(target=target, expr=expr)]

    # `x += y`. The operator is the same OperatorKind the binary table
    # carries, so `+=` is DERIVED from `+` rather than tabulated twice;
    # two tables drift and a compound assignment quietly using the
    # wrong operator is invisible in review.
    binop = em.language.get("operators", {}).get("binary", {}).get(
        _symbol or "")
    if binop:
        op = binop.replace("{lhs}", "").replace("{rhs}", "").strip()
        return [pad + spec.get("template", "{target} {op}= {value};")
                .format(target=em.emit_expr(kids[0][0]), op=op,
                        value=em.emit_expr(kids[1][0]))]
    em.unhandled[f"CompoundAssignment:{_symbol}"] = 1
    return None
