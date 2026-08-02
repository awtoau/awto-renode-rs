"""`nameof(x)` -- a compile-time string.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 7


@core.expr("NameOf", priority=PRIORITY)
def name_of(em, oid):
    """Always claims: the folded constant is on the operation itself."""
    row = em.con.execute(
        "SELECT const_value FROM operation WHERE id=?", (oid,)).fetchone()
    const = row[0] if row else None
    # Roslyn folds nameof to a constant, so the corpus already has it.
    return em.language.get("strings", {}).get(
        "nameof", '"{name}"').format(name=(const or "").strip('"'))
