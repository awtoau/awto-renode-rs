"""LINQ: extension methods that are STATIC calls wearing instance syntax.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Ordered BEFORE the generic invocation rule, and that order is the whole point
-- see the comment inside. `PRIORITY` is one less than
`invocation.PRIORITY` so the two keep the places they had when both were
branches in one chain.
"""

from __future__ import annotations

import re

from emitter import core

PRIORITY = core.LANGUAGE + 4


@core.expr("Invocation", priority=PRIORITY)
def linq_invocation(em, oid):
    """Declines any call the LINQ marker does not appear in.

    Declining hands the node to the generic invocation rule, which is the
    ordinary outcome for most calls -- not a failure, and so not counted.
    """
    row = em.con.execute(
        "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
    symbol = row[0] if row else None
    linq = em.language.get("linq", {})
    if not (symbol and linq.get("symbol_contains", "\0") in symbol):
        return None
    args = [c[0] for c in em.children(oid) if c[1] == "Argument"]
    # STATIC extension method: argument 0 is the receiver, and there is
    # no receiver child at all. The generic rule below finds none and
    # emits the self-call form, which turned `xs.Select(f)` into
    # `self.select(f)` -- a LINQ call read as a state field.
    meth = symbol.split("(")[0].split(".")[-1].split("<")[0]
    vals = [em.emit_expr(a) for a in args]
    if vals:
        recv, rest = vals[0], vals[1:]
        tmpl = (linq.get("no_predicate", {}).get(meth) if not rest
                else None) or linq.get("members", {}).get(meth)
        if tmpl:
            # A chained LINQ call already yields an iterator; adding a
            # second `.iter()` does not compile.
            # Anywhere in the receiver, not just near its end: once a
            # chain is an iterator it stays one, and a predicate can be
            # arbitrarily long -- a fixed window missed `.filter(` by
            # one character.
            if any(p in recv for p in linq.get("iterator_producers", [])):
                tmpl = tmpl.replace("{recv}.iter()", "{recv}")
            # A closure body of one `return X;` is the expression X.
            rest = [re.sub(r"^\|([^|]*)\|\s*return\s+(.*?);?$",
                           r"|\1| \2", r) for r in rest]
            return tmpl.format(recv=recv, args=", ".join(rest))
    em.unhandled[f"linq:{meth}"] = 1
    return f"/* Linq{meth} */"
