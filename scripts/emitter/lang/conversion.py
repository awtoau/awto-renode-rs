"""A conversion node -- C#'s silent widening made explicit, or dropped.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

This is one of the two load-bearing rules in the expression layer. C# widens
silently and Rust never does, so `16.0` emitted as `16` turned an f64 division
into integer division that compiled and passed every test.
"""

from __future__ import annotations

import json

from emitter import core

PRIORITY = core.LANGUAGE + 16


@core.expr("Conversion", priority=PRIORITY)
def conversion(em, oid):
    """Declines on a conversion with nothing under it.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    row = em.con.execute(
        "SELECT detail, type FROM operation WHERE id=?", (oid,)).fetchone()
    detail, rtype = (row if row else (None, None))
    kids = [c[0] for c in em.children(oid)]
    if not kids:
        return None
    inner = em.emit_expr(kids[0])
    # Only NUMERIC conversions need spelling in Rust; see language rule.
    try:
        num = json.loads(detail or "{}").get("numeric", False)
    except json.JSONDecodeError:
        num = False
    # An explicit cast to a generated enum needs from_u64: Rust has no
    # numeric-to-enum cast. See enums.from_u64.
    ename = (rtype or "").split(".")[-1]
    if ename in em._enum_names:
        rust_name = getattr(em, "_enum_rust_names", {}).get(ename, ename)
        return f"{rust_name}::from_u64({inner})"
    tgt = em.rust_type(rtype or "") if num else None
    if num and tgt:
        return em.language.get("conversions", {}).get(
            "numeric", "{expr} as {target}").format(expr=inner, target=tgt)
    return inner
