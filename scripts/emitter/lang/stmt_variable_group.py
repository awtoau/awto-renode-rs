"""A C# local declaration, which may declare several names at once.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

`int a = 1, b = 2;` arrives as a group wrapping one declarator per name, so
this is pure structure: emit each child and concatenate. The declarator itself
is a separate construct, in its own module.

Emits nothing for a group with no children -- which is what "declared nothing"
means, not a path that could not translate. It therefore stays unwrapped by
`must_explain`, deliberately.
"""

from __future__ import annotations

from emitter import core


@core.stmt("VariableDeclarationGroup", "VariableDeclaration")
def variable_group_stmt(em, oid: int, indent: int) -> list[str]:
    """Flatten a declaration group into its declarators."""
    out: list[str] = []
    for cid, _k, _s, _c, _t in em.children(oid):
        out.extend(em.emit_stmt(cid, indent))
    return out
