"""`c ? a : b` -- the conditional operator.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 17


@core.expr("Conditional", priority=PRIORITY)
def conditional(em, oid):
    """Declines on a malformed node -- fewer than three operands.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    kids = [c[0] for c in em.children(oid)]
    if len(kids) < 3:
        return None
    # `c ? a : b`. Rust's if-else IS an expression, so this needs no
    # temporary -- the same rule the statement form uses.
    tmpl = em.language.get("statements", {}).get("Conditional", {}).get(
        "ternary", "if {cond} {{ {then} }} else {{ {else} }}")
    return tmpl.replace("{else}", "{alt}").format(
        cond=em.emit_expr(kids[0]), then=em.emit_expr(kids[1]),
        alt=em.emit_expr(kids[2]))
