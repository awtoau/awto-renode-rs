"""Indexing an array, in one dimension or two.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Both shapes live in one file because they are one construct told apart by
ARITY, and the two-index form must be consulted first -- a rectangular access
also satisfies the one-index test, so the looser rule would swallow it. The
priorities below keep the order the two had when both were branches in one
chain.
"""

from __future__ import annotations

from emitter import core

PRIORITY_2D = core.LANGUAGE + 14
PRIORITY_1D = core.LANGUAGE + 15


@core.expr("ArrayElementReference", priority=PRIORITY_2D)
def array_element_reference_2d(em, oid):
    """Declines anything without two index operands.

    Declining hands the node to the one-index rule below, which is the ordinary
    outcome -- not a failure, and so not counted.
    """
    kids = [c[0] for c in em.children(oid)]
    if len(kids) < 3:
        return None
    # Two index children means a rectangular access -- told apart by
    # arity rather than by consulting the declared type.
    tmpl = em.language.get("references", {}).get(
        "ArrayElementReference2D", {}).get(
        "emit", "{array}.get({row} as usize, {col} as usize)")
    return tmpl.format(array=em.emit_expr(kids[0]),
                       row=em.emit_expr(kids[1]),
                       col=em.emit_expr(kids[2]))


@core.expr("ArrayElementReference", priority=PRIORITY_1D)
def array_element_reference(em, oid):
    """Declines a malformed node with no index operand.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    kids = [c[0] for c in em.children(oid)]
    if len(kids) < 2:
        return None
    tmpl = em.language.get("references", {}).get(
        "ArrayElementReference", {}).get("emit", "{array}[{index} as usize]")
    return tmpl.format(array=em.emit_expr(kids[0]),
                       index=em.emit_expr(kids[1]))
