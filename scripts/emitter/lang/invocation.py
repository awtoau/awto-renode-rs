"""A method call.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

The last invocation rule to be consulted: the plugin layer runs first, and the
LINQ rule runs before this one, so reaching here means the call is an ordinary
one on an ordinary receiver.
"""

from __future__ import annotations

from emitter import core
from emitter.core import snake

PRIORITY = core.LANGUAGE + 5


@core.expr("Invocation", priority=PRIORITY)
def invocation(em, oid):
    """Declines when the corpus recorded no symbol for the call.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    if oid not in em._invocation_symbol_cache:
        row = em.con.execute(
            "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
        em._invocation_symbol_cache[oid] = row[0] if row else None
    symbol = em._invocation_symbol_cache[oid]
    if not symbol:
        return None
    all_kids = em.children(oid)
    args = [c for c in all_kids if c[1] == "Argument"]
    # Generic call. Project rules were tried above, so reaching here
    # means no idiom claimed it.
    inv = em.language.get("invocations", {})
    method = snake(symbol.split("(")[0].split(".")[-1])
    rendered_args = [em.emit_expr(a[0]) for a in args]
    # Preserve ref/out at call boundaries too.  Roslyn's invocation symbol is
    # the same key stored for an in-corpus member, so this is semantic lookup,
    # not name matching.  A ref parameter forwarded to another ref parameter
    # is already rendered as `*x` and therefore correctly becomes `&mut *x`.
    if symbol not in em._callee_cache:
        em._callee_cache[symbol] = em.con.execute(
            "SELECT mb.id, mb.is_static, t.name "
            "FROM member mb JOIN type t ON t.id=mb.type_id "
            "WHERE mb.run_id=? AND mb.key=? LIMIT 1",
            (em._run_id, symbol)).fetchone()
    callee = em._callee_cache[symbol]
    if callee:
        if callee[0] not in em._callee_params_cache:
            em._callee_params_cache[callee[0]] = tuple(em.con.execute(
                "SELECT ordinal, name, is_out, is_ref FROM parameter "
                "WHERE method_id=? ORDER BY ordinal", (callee[0],)))
        params = em._callee_params_cache[callee[0]]
        by_ordinal = {ordinal: bool(is_out or is_ref)
                      for ordinal, _name, is_out, is_ref in params}
        by_name = {name: bool(is_out or is_ref)
                   for _ordinal, name, is_out, is_ref in params}
        borrowed = []
        for i, (arg_row, rendered) in enumerate(zip(args, rendered_args)):
            # Roslyn records the parameter an argument bound to in the
            # Argument node's symbol.  That matters for named arguments, whose
            # source order need not be parameter order.  Fall back to ordinal
            # only for older corpus rows that lack the binding fact.
            bound = (arg_row[2] or "").split()[-1]
            is_by_ref = by_name.get(bound, by_ordinal.get(i, False))
            borrowed.append(f"&mut {rendered}" if is_by_ref else rendered)
        rendered_args = borrowed
    arg_txt = ", ".join(rendered_args)
    receiver = next((c[0] for c in all_kids if c[1] != "Argument"), None)
    key = em.stdlib_member(symbol)
    if key and receiver is not None:
        tmpl = em.language["stdlib"]["members"][key]
        # A guarded form is a STATEMENT (type ()); using it where a
        # value is wanted is E0317. Report rather than bolt on an
        # `else` returning a fabricated default -- that would compile.
        if tmpl.startswith("if let") and not getattr(
                em, "_stmt_position", False):
            em.unhandled["expr:DelegateInvokeInExpression"] = 1
            return "/* DelegateInvokeInExpression */"
        return tmpl.format(recv=em.emit_expr(receiver), args=arg_txt)

    # A receiver-less call is not necessarily a call on `this`. Static calls
    # have no receiver too, and treating one as `self.foo()` makes the later
    # free-function rewrite invent a peer method on the current type. The
    # member table carries Roslyn's resolved declaring type and staticness, so
    # use those facts. Static helpers declared on the type currently being
    # emitted still become its free functions; a helper on another type needs
    # that type's emitted module or a runtime rule, neither of which this
    # language fallback may guess.
    if (callee and callee[1]
            and callee[2] != getattr(em, "_current_type", None)):
        declaring = callee[2]
        source_name = symbol.split("(")[0].split(".")[-1]
        reason = f"StaticInvocation:{declaring}.{source_name}"
        em.unhandled[f"expr:{reason}"] = (
            em.unhandled.get(f"expr:{reason}", 0) + 1)
        em.gaps.append(
            f"static call `{declaring}.{source_name}` has no Rust mapping")
        return f"/* {reason} */"

    rkind = None
    if receiver is not None:
        if receiver not in em._operation_kind_cache:
            row = em.con.execute(
                "SELECT kind FROM operation WHERE id=?", (receiver,)).fetchone()
            em._operation_kind_cache[receiver] = row[0] if row else None
        rkind = em._operation_kind_cache[receiver]
    if receiver is None or rkind == "InstanceReference":
        return inv.get("self", "self.{method}({args})").format(
            method=method, args=arg_txt)
    return inv.get("instance", "{receiver}.{method}({args})").format(
        receiver=em.emit_expr(receiver), method=method, args=arg_txt)
