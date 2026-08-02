"""A field or property read.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

The rendering itself stays on the emitter as `emit_reference()`, which several
other paths call directly. This module is the dispatch entry, and it is the
LAST of the reference rules -- the folded-constant rule and the enum-member
rule are both more specific and are consulted first.

This is one of the two load-bearing rules in the expression layer: a reference
emits its RECEIVER. Dropping it read the wrong object, and did so for 26% of
all references while the generated output stayed byte-identical and correct,
because the types converted at the time reached their state through `this`.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 13


@core.expr("PropertyReference", "FieldReference", priority=PRIORITY)
def reference(em, oid):
    """Declines when the corpus recorded no symbol for the member.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    row = em.con.execute(
        "SELECT kind, symbol FROM operation WHERE id=?", (oid,)).fetchone()
    kind, symbol = (row if row else (None, None))
    if not symbol:
        return None
    kids = [c[0] for c in em.children(oid)]
    return em.emit_reference(kind, symbol, kids)
