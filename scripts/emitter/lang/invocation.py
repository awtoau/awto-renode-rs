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
    rkind = None
    if receiver is not None:
        rkind = em.con.execute(
            "SELECT kind FROM operation WHERE id=?", (receiver,)).fetchone()[0]
    if receiver is None or rkind == "InstanceReference":
        return inv.get("self", "self.{method}({args})").format(
            method=method, args=arg_txt)
    return inv.get("instance", "{receiver}.{method}({args})").format(
        receiver=em.emit_expr(receiver), method=method, args=arg_txt)
