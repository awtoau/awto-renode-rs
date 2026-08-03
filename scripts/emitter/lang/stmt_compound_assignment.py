"""`x += y` and friends.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

DECLINES when the operator has no binary mapping, after recording it as
unhandled. Declining is deliberate: the built-in chain's fallback then emits the
gap comment, so an unmapped compound operator is visible in the output instead
of producing a line that compiles with the wrong operator.
"""

from __future__ import annotations

import re

from emitter import core
from emitter.lang.binary import runtime_template

# `Option<Box<dyn FnMut(T)>>` -- a callback slot (`stdlib.delegates` in
# csharp_core.json). C# `+=` on one is a multicast combine, which needs state
# (which subscriber(s) are already there) -- `docs/decisions/
# runtime-is-the-fourth-layer.md` tell #1 -- so it is a runtime call, not an
# operator.
_HOOK_TYPE = re.compile(r"^Option<Box<dyn FnMut\([^()]*\)( \+ 'static)?>>$")


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

    # The target is emitted twice below (once read into the call, once
    # written), the same hazard `runtime_target_kinds_why` documents for the
    # checked-arithmetic redirect -- a property getter call must not reach
    # here, only a place expression may.
    if (_symbol == "Add"
            and em.kind_of(kids[0][0]) in spec.get("runtime_target_kinds", [])
            and _HOOK_TYPE.match(em.rust_type(_rtype or "") or "")):
        target = em.emit_expr(kids[0][0])
        value = em.emit_expr(kids[1][0])
        # `target` is a place behind `&mut State`; reading it by value to pass
        # to the combinator would try to MOVE the field out from behind the
        # reference (E0507). `.take()` moves it out and leaves `None` in its
        # place for the instant before the result is written back.
        return [pad + f"{target} = csharp_rt::combine_hook({target}.take(), {value});"]

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
        if em.kind_of(kids[0][0]) == "PropertyReference":
            # A C# property with a custom getter/setter has no Rust lvalue --
            # emitting the plain template puts a call expression on the left
            # of `{op}=`, which does not parse (E0067). `emit_assignment`
            # already resolves a plain `=` on one of these through the
            # project's own rule for it; the compound form needs the SAME
            # resolution, just with a computed value instead of the literal
            # one -- read the current value (the project's read rule, same
            # as any other expression), combine it with the operator, and
            # write the result back through the project's write rule for
            # this exact target, rather than assuming an operator token
            # applies to a call.
            trow = em.con.execute(
                "SELECT symbol, type FROM operation WHERE id=?",
                (kids[0][0],)).fetchone()
            tsym, ttype = trow if trow else (None, None)
            for rule in em.assignments:
                if rule["target_kind"] != "PropertyReference":
                    continue
                if rule.get("target_symbol_contains") and (
                        not tsym or rule["target_symbol_contains"] not in tsym):
                    continue
                if rule.get("target_type_is") and ttype != rule["target_type_is"]:
                    continue
                current = em.emit_expr(kids[0][0])
                value = em.emit_expr(kids[1][0])
                new_value = f"({current} {op} {value})"
                return [pad + rule["emit"].format(
                    field=em.receiver_field(kids[0][0]) or "UNKNOWN",
                    value=new_value)]
        return [pad + spec.get("template", "{target} {op}= {value};")
                .format(target=em.emit_expr(kids[0][0]), op=op,
                        value=em.emit_expr(kids[1][0]))]
    em.unhandled[f"CompoundAssignment:{_symbol}"] = 1
    return None
