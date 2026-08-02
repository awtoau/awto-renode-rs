"""A literal constant.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

The rendering itself stays on the emitter as `literal()`, because the statement
layer and the type layer both call it directly. This module is only the
dispatch entry -- what used to be one `if` in the built-in chain.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 1


@core.expr("Literal", priority=PRIORITY)
def literal(em, oid):
    """Always claims. The declared TYPE decides the rendering, not the text."""
    row = em.con.execute(
        "SELECT const_value, type FROM operation WHERE id=?", (oid,)).fetchone()
    const, rtype = (row if row else (None, None))
    return em.literal(const, rtype)
