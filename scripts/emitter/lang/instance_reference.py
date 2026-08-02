"""`this` -- the instance the method is running on.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Its own file because the architecture says a construct is a file: the built-in
chain that used to hold this was one `if` among two dozen, and every new kind
edited it.
"""

from __future__ import annotations

from emitter import core

# Chain position 21 of the original built-in order. Priorities are assigned
# from that order so a handler moved out of the chain keeps the place it had
# relative to the others -- dispatch is per kind, so only handlers sharing a
# kind can actually collide, but stating the position makes that checkable.
PRIORITY = core.LANGUAGE + 21


@core.expr("InstanceReference", priority=PRIORITY)
def instance_reference(em, oid):
    """Always claims: `this` is `self`, unconditionally."""
    return "self"
