"""`x++` / `x--` where a VALUE is wanted.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

The statement form is handled elsewhere and is straightforward. This one is
not, which is why it reports rather than emits.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 18


@core.expr("Increment", "Decrement", priority=PRIORITY)
def increment_decrement(em, oid):
    """Always claims, and always records a gap -- it never emits real code."""
    kind = em.con.execute(
        "SELECT kind FROM operation WHERE id=?", (oid,)).fetchone()[0]
    em.gaps.append(
        f"{kind.lower()} in expression position: prefix/postfix "
        f"difference is observable there (see language rule `increment`)")
    # This marker can land in a condition/index/scrutinee, where a comment is
    # not a valid expression -- count it so the enclosing method is withheld
    # rather than emitting invalid syntax.
    em.unhandled[f"expr:{kind}"] = em.unhandled.get(f"expr:{kind}", 0) + 1
    return f"/* GAP: {kind} in expression position */"
