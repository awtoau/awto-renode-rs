"""`new T(...)` -- construction.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 22


@core.expr("ObjectCreation", priority=PRIORITY)
def object_creation(em, oid):
    """Declines when the corpus recorded no constructor symbol.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    row = em.con.execute(
        "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
    symbol = row[0] if row else None
    if not symbol:
        return None
    args = [c[0] for c in em.children(oid) if c[1] == "Argument"]
    ty = symbol.split("(")[0].split(".")[-1]
    # `new List<T>()` named its own C# type literally -- `List::new(...)`,
    # which does not exist in Rust. The BCL correspondence table already maps
    # `List` -> `Vec` for a field's TYPE; a constructor never consulted it.
    ty = em.language.get("stdlib", {}).get("types", {}).get(ty, ty)
    return f"{ty}::new({', '.join(em.emit_expr(a) for a in args)})"
