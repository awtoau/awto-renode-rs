"""Worked example: a construct added WITHOUT editing any shared file.

This module exists to prove the registry works, and to give an agent picking up
one of the emitter issues something to copy. Delete it if it ever stops being
the simplest possible demonstration.

`Parenthesized` is handled in the built-in chain too, so registering here also
demonstrates the ORDER: registered handlers run first and may decline by
returning None, in which case the built-in chain still gets its turn.
"""

from __future__ import annotations

from emitter import core


@core.expr("Parenthesized")
def parenthesized(em, oid):
    """`(x)` -- transparent, as it is in the built-in chain.

    Returns None to decline, which is the interesting half: a handler that only
    recognises some cases costs nothing when it does not.
    """
    return None
