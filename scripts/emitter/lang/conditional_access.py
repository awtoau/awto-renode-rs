"""`a?.b` -- the null-conditional operator, and the receiver it binds.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Two operation kinds, one construct. The access itself is a GAP: Rust has no
null-conditional operator, and the faithful shape depends on whether the
receiver is an `Option` -- which needs nullability analysis this transpiler
does not have. A statement-position `?.` is rewritten to a guard by a
normalisation pass before it ever reaches here; the instance handler below is
what makes the bound receiver visible inside that guard.
"""

from __future__ import annotations

from emitter import core

PRIORITY_INSTANCE = core.LANGUAGE + 9
PRIORITY_ACCESS = core.LANGUAGE + 10


@core.expr("ConditionalAccessInstance", priority=PRIORITY_INSTANCE)
def conditional_access_instance(em, oid):
    """Declines outside a guard, where there is no binding to stand for.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    # Inside a normalised `?.` guard this is the bound receiver.
    b = getattr(em, "_ca_binding", None)
    if b:
        return b
    return None


@core.expr("ConditionalAccess", priority=PRIORITY_ACCESS)
def conditional_access(em, oid):
    """Always claims, and always records a gap -- it never emits real code."""
    gap = em.language.get("statements", {}).get("ConditionalAccess", {})
    em.gaps.append("conditional access `?.` needs nullability analysis")
    # The normalisation pass rewrites the common `x?.Foo();` shape to a
    # guard before it ever reaches here (see module docstring), but not
    # every statement-position `?.` matches that shape -- and reached from
    # `stmt_expression.py`'s plain form, the marker is a bare statement
    # (`/* GAP: ?. */;`), which is valid Rust. Only an expression-position
    # one is not, so only that one counts as unhandled.
    if not getattr(em, "_stmt_position", False):
        em.unhandled["expr:ConditionalAccess"] = em.unhandled.get("expr:ConditionalAccess", 0) + 1
    return gap.get("emit", "/* GAP: ?. */")
