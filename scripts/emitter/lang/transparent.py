"""Nodes that carry no code of their own.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

`(x)` is grouping the C# parser already resolved, and an argument node is the
tree's way of attaching a value to a parameter. Neither is written in Rust, so
both emit their single child and nothing else. One file, because there is one
behaviour.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 20


@core.expr("Parenthesized", "Argument", priority=PRIORITY)
def transparent(em, oid):
    """Always claims. A childless node emits a marker rather than nothing."""
    kids = [c[0] for c in em.children(oid)]
    # Transparent: neither is written in Rust.
    return em.emit_expr(kids[0]) if kids else "/* empty */"
