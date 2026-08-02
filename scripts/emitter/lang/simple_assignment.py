"""Assignment used as an expression.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 11


@core.expr("SimpleAssignment", priority=PRIORITY)
def simple_assignment(em, oid):
    """Always claims; the statement form and this one share an emitter."""
    # Assignment in expression position; C# yields the assigned value.
    return em.emit_assignment(oid).rstrip(";")
