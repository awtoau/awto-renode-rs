"""`$"a{b}c"` -- string interpolation, and the holes inside it.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Two operation kinds, one construct: the string builds the format text and the
hole nodes carry the expressions. They are one file because the hole's emitter
is only correct given what the string's emitter already did -- splitting them
would hide that.
"""

from __future__ import annotations

from emitter import core

PRIORITY_STRING = core.LANGUAGE + 6
PRIORITY_HOLE = core.LANGUAGE + 19


@core.expr("InterpolatedString", priority=PRIORITY_STRING)
def interpolated_string(em, oid):
    """Always claims: the format text and its arguments are built together."""
    rules = em.language.get("strings", {})
    fmt, holes = "", []
    for cid, ck, _s, cconst, _t in em.children(oid):
        if ck == "InterpolatedStringText":
            lit = em.const_text(cid)
            fmt += lit.replace("{", "{{").replace("}", "}}")
        else:
            fmt += rules.get("hole", "{}")
            holes.append(em.emit_expr(cid))
    return rules.get("interpolated", 'format!("{fmt}"{args})').format(
        fmt=fmt, args="".join(", " + h for h in holes))


@core.expr("Interpolation", priority=PRIORITY_HOLE)
def interpolation(em, oid):
    """Declines on a hole with no expression under it.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    kids = [c[0] for c in em.children(oid)]
    if not kids:
        return None
    # The hole node wraps the expression; the format placeholder was
    # already emitted by InterpolatedString.
    return em.emit_expr(kids[0])
