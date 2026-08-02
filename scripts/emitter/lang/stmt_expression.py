"""An expression evaluated for its effect: `foo();`.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

ORDER IS LOAD-BEARING. This matches EVERY `ExpressionStatement`, so it must run
last of the handlers claiming that kind -- `stmt_conditional_access` tested
first in the chain and still must. It registers at `core.LANGUAGE + 1` against
that module's `core.LANGUAGE`, so the order is declared rather than inherited
from the order the modules happen to be imported in.

Returns an EMPTY list for a statement with no expression: that means "there was
nothing to emit", not "I could not translate it", so it is deliberately not
wrapped by `must_explain`. Returning empty also stops the chain, exactly as the
original `return []` did.
"""

from __future__ import annotations

from emitter import core


@core.stmt("ExpressionStatement", priority=core.LANGUAGE + 1)
def expression_stmt(em, oid: int, indent: int) -> list[str]:
    """One expression statement, terminated."""
    pad = "    " * indent
    kids = em.children(oid)

    if not kids:
        return []
    # An Increment here is in STATEMENT position, where prefix and
    # postfix are indistinguishable; route it to the statement rule
    # rather than the expression one, which reports a gap.
    # These kinds are STATEMENTS in every position we see them, but
    # they arrive wrapped in an ExpressionStatement, so without this
    # they fall through to emit_expr and are reported unhandled. The
    # list is the fix generalised: `Increment` alone was fixed once,
    # and `CompoundAssignment` then repeated the identical failure.
    if em.kind_of(kids[0][0]) in (
            "Increment", "Decrement", "CompoundAssignment"):
        return em.emit_stmt(kids[0][0], indent)
    prev_pos = getattr(em, "_stmt_position", False)
    em._stmt_position = True
    try:
        return [pad + em.emit_expr(kids[0][0]) + ";"]
    finally:
        em._stmt_position = prev_pos
