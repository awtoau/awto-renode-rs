"""A binary operator.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Which operators exist and what each becomes is DATA -- `operators.binary` in the
generic rules. This module only decides that the node is one, and how the two
operands nest.

Three of them do not become operators. C# integer `+`, `-` and `*` wrap (or
throw, in a `checked` context) where Rust's operator panics-or-wraps by build
profile, and C# `<<`/`>>` mask the shift count where Rust's operator panics. All
three differences are invisible at the call site, so under
`docs/decisions/runtime-is-the-fourth-layer.md` they emit a CALL into
`csharp-rt`. `operators.runtime` in the data says which call; this module only
decides that the node qualifies.
"""

from __future__ import annotations

import json

from emitter import core

PRIORITY = core.LANGUAGE + 2


def runtime_template(em, symbol: str | None, rtype: str | None,
                     detail: str | None) -> str | None:
    """The `csharp-rt` call for this node, or None to use the operator.

    Shared with the compound-assignment rule, because `x += y` has exactly the
    overflow semantics `x + y` has and a second copy of this decision would
    drift from it silently.

    Three guards, each of which would produce code that does not compile if it
    were dropped:

      * the resolved type must be INTEGRAL. `Add` also arrives on `string`,
        `double` and two user types with operator overloads.
      * the operator must not be LIFTED -- a lifted operator's operands are
        `Nullable<T>`, which has no mapping yet at all.
      * the `checked` flag picks the table. It is a fact the ingest records and
        that nothing read until now.
    """
    ops = em.language.get("operators", {})
    rt = ops.get("runtime", {})
    if not rt or not symbol:
        return None
    if rtype not in ops.get("integral_types", []):
        return None
    facts = {}
    if detail:
        try:
            facts = json.loads(detail)
        except ValueError:
            facts = {}
    if facts.get("lifted"):
        return None
    shift = rt.get("shift", {}).get(symbol)
    if shift:
        return shift
    table = "checked" if facts.get("checked") else "unchecked"
    return rt.get(table, {}).get(symbol)


@core.expr("Binary", priority=PRIORITY)
def binary(em, oid):
    """Declines when the operator has no mapping, and counts it by SYMBOL.

    The per-symbol count is the useful one: `expr:Binary` says an operator was
    missed, `Binary:<symbol>` says which. Both are recorded, exactly as they
    were when this was a branch in the built-in chain -- the caller adds the
    kind-level count once this declines.
    """
    row = em.con.execute(
        "SELECT symbol, type, detail FROM operation WHERE id=?", (oid,)).fetchone()
    symbol, rtype, detail = row if row else (None, None, None)
    kids = [c[0] for c in em.children(oid)]
    if symbol in ("Equals", "NotEquals") and len(kids) == 2:
        # `x == null` as a bare `==` needs `T: PartialEq`, which a boxed
        # closure field (e.g. a hook) does not have -- and would not even be
        # the right check if it did, since every nullable in this corpus is
        # `Option<T>`. `is_none`/`is_some` works for any `T`.
        sides = [em.con.execute(
            "SELECT kind, const_value FROM operation WHERE id=?", (k,)).fetchone()
            for k in kids]
        null_at = next((i for i, s in enumerate(sides)
                        if s and s[0] == "Literal" and s[1] == "null"), None)
        if null_at is not None:
            other = kids[1 - null_at]
            method = "is_none" if symbol == "Equals" else "is_some"
            return f"{em.emit_expr(other)}.{method}()"
    if len(kids) >= 2:
        rt = runtime_template(em, symbol, rtype, detail)
        if rt:
            # A call is already atomic, so it is NOT wrapped in the extra
            # parentheses the operator forms need.
            return rt.format(lhs=em.emit_expr(kids[0]),
                             rhs=em.emit_expr(kids[1]))
    table = em.language.get("operators", {}).get("binary", {})
    tmpl = table.get(symbol or "")
    if tmpl and len(kids) >= 2:
        return "(" + tmpl.format(lhs=em.emit_expr(kids[0]),
                                 rhs=em.emit_expr(kids[1])) + ")"
    em.unhandled[f"Binary:{symbol}"] = em.unhandled.get(f"Binary:{symbol}", 0) + 1
    return None
