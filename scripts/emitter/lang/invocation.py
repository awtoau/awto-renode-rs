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
    row = em.con.execute(
        "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
    symbol = row[0] if row else None
    if not symbol:
        return None
    all_kids = em.children(oid)
    args = [c[0] for c in all_kids if c[1] == "Argument"]
    # Generic call. Project rules were tried above, so reaching here
    # means no idiom claimed it.
    inv = em.language.get("invocations", {})
    method = snake(symbol.split("(")[0].split(".")[-1])
    arg_txt = ", ".join(em.emit_expr(a) for a in args)
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
    static_callee = em.con.execute(
        "SELECT mb.is_static, t.name "
        "FROM member mb JOIN type t ON t.id=mb.type_id "
        "WHERE mb.key=? LIMIT 1", (symbol,)).fetchone()
    if (static_callee and static_callee[0]
            and static_callee[1] != getattr(em, "_current_type", None)):
        declaring = static_callee[1]
        source_name = symbol.split("(")[0].split(".")[-1]
        reason = f"StaticInvocation:{declaring}.{source_name}"
        em.unhandled[f"expr:{reason}"] = (
            em.unhandled.get(f"expr:{reason}", 0) + 1)
        em.gaps.append(
            f"static call `{declaring}.{source_name}` has no Rust mapping")
        return f"/* {reason} */"

    rkind = None
    if receiver is not None:
        rkind = em.con.execute(
            "SELECT kind FROM operation WHERE id=?", (receiver,)).fetchone()[0]
    if receiver is None or rkind == "InstanceReference":
        return inv.get("self", "self.{method}({args})").format(
            method=method, args=arg_txt)
    return inv.get("instance", "{receiver}.{method}({args})").format(
        receiver=em.emit_expr(receiver), method=method, args=arg_txt)
