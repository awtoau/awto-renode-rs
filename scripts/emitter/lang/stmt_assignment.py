"""C# simple assignment in statement position.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

The work is all in `emit_assignment`, which stays where it is because the
expression layer calls it too (`x = y` used for its value). This module is only
the statement wrapper: the terminating form and the indent.

Never declines.
"""

from __future__ import annotations

from emitter import core


@core.stmt("SimpleAssignment")
def simple_assignment_stmt(em, oid: int, indent: int) -> list[str]:
    """`x = y;` -- one assignment on one line."""
    pad = "    " * indent
    return [pad + em.emit_assignment(oid)]
