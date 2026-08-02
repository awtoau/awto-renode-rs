"""`x++` and `x--` in STATEMENT position.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

Position is the whole point of this module existing separately from the
expression handling of the same two kinds. In statement position the result is
discarded, so prefix and postfix are indistinguishable and one template serves
both. In EXPRESSION position they are not interchangeable, so that path reports
a gap instead of silently picking one.

DECLINES when there is no target or no template in the rules, leaving the
built-in chain's fallback to record it. Declining rather than emitting is what
keeps an unmapped operator a reported gap instead of a wrong line that compiles.
"""

from __future__ import annotations

from emitter import core


@core.stmt("Increment", "Decrement")
def increment_stmt(em, oid: int, indent: int) -> list[str] | None:
    """One increment or decrement statement, or None to decline."""
    pad = "    " * indent
    kind = em.kind_of(oid)
    kids = em.children(oid)
    if not kids:
        return None

    tmpl = em.language.get("increment", {}).get(kind)
    if tmpl:
        return [pad + tmpl.format(target=em.emit_expr(kids[0][0]))]
    return None
