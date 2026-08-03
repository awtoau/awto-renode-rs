"""A C# indexer read (`x[i]`) reached through `this[...]`.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Consulted before `reference.py`: an indexer is still a `PropertyReference`
by kind, and `reference.py`'s dotted-name walk would otherwise take it, since
it has a receiver and a name like anything else -- just a name that happens
to be `this[int]`.

DECLINES for anything that is not an `int`-keyed indexer symbol, or lacks the
receiver/argument shape a genuine indexer read has. Falls through to
`reference.py`, which already handled every other property.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 11


@core.expr("PropertyReference", priority=PRIORITY)
def indexer_reference(em, oid):
    """`list[i]`.

    Roslyn names any indexer property `Type.this[KeyType]`, never the name a
    C# reader would recognise, because it is one construct with the KEY TYPE
    varying -- `List<T>.this[int]`, `Dictionary<TKey,TValue>.this[TKey]`, and
    a dozen more in this corpus. Only the `int`-keyed ones are handled here:
    those are a SEQUENCE, and Rust's `[i as usize]` is exactly the C# indexer,
    the same conversion `ArrayElementReference` already applies. A `TKey`
    indexer is a map lookup instead, needs `.get(&key)`, and is left alone --
    declining rather than guessing at a shape this rule was not written for.
    """
    row = em.con.execute(
        "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
    symbol = row[0] if row else None
    if not symbol or not symbol.endswith(".this[int]"):
        return None
    kids = em.children(oid)
    if len(kids) < 2:
        return None
    receiver_id = kids[0][0]
    arg_kids = em.children(kids[1][0])
    if not arg_kids:
        return None
    index_id = arg_kids[0][0]
    tmpl = em.language.get("references", {}).get(
        "Indexer", {}).get("emit", "{receiver}[{index} as usize]")
    return tmpl.format(receiver=em.emit_expr(receiver_id),
                        index=em.emit_expr(index_id))
