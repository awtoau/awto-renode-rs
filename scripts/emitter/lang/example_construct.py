"""Worked example: a construct added WITHOUT editing any shared file.

This module exists to prove the registry works, and to give an agent picking up
one of the emitter issues something to copy. Delete it if it ever stops being
the simplest possible demonstration.

`Parenthesized` has a real handler too, in `transparent.py`, so this module also
demonstrates the ORDER: handlers for a kind run in priority order and may
decline by returning None, in which case the next one still gets its turn. This
one sits at the default language priority and declines every time, so the real
handler behind it does all the work.
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
