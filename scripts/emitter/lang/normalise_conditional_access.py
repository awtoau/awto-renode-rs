"""Normalisation: `x?.Foo();` in statement position becomes an if-guard.

LANGUAGE LAYER -- generic, names nothing specific to the corpus.

This is a REWRITE, not a mapping. The C# already declares that x may be
absent, so no inference is needed: in statement position the result is
discarded, which makes the short-circuit exactly an if-guard.

EXPRESSION position is deliberately NOT handled. `y = x?.Foo()` yields null
when x is absent, so it needs an optional-typed result and therefore the
deferred nullability decision. Those sites stay gaps rather than being
rewritten into something that merely looks equivalent.

Registered by NAME; its position in the sequence comes from the rules data.
"""

from __future__ import annotations

from emitter import core


@core.normalise("ConditionalAccessStatement")
def conditional_access_statement(em, method_id, rule):
    """Mark statement-position sites so emission takes the guarded form.

    Returns True if anything was newly marked, which is what lets the driver
    detect a fixpoint. Idempotent: re-running marks nothing new.
    """
    rows = em.con.execute(
        "SELECT o.id FROM operation o JOIN operation p ON p.id = o.parent_id "
        "WHERE o.kind = 'ConditionalAccess' AND p.kind = 'ExpressionStatement' "
        "AND o.method_id = ? ORDER BY o.id",
        (method_id,)).fetchall()
    marked = em.normalised.setdefault("ConditionalAccessStatement", set())
    before = len(marked)
    marked.update(r[0] for r in rows)
    return len(marked) != before
