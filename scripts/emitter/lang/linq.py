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


def _closure_arity(arg: str) -> int | None:
    """How many parameters an emitted closure takes, or None if not one.

    Reads the emitted Rust rather than the C# delegate, because the emitted
    closure is what has to fit the Rust method: if the two ever disagree, the
    one that decides whether the output compiles is this one.
    """
    if not arg.startswith("|"):
        return None
    end = arg.find("|", 1)
    if end < 0:
        return None
    params = arg[1:end].strip()
    return len([p for p in params.split(",") if p.strip()])


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
        # Keyed by NAME AND ARITY, receiver included. Keying on the name
        # alone gave every overload the first overload's template: the
        # indexed `Select(source, (item, index) => ..)` took the one-argument
        # selector's `.map(f)`, and `Min(source, keySelector)` took `.min()`
        # and dropped the selector -- a wrong answer that compiles, which is
        # this project's recurring defect. An unlisted overload now falls
        # through to the reported gap below.
        key = f"{meth}/{len(vals)}"
        tmpl = linq.get("members", {}).get(key)
        # ... and by the CLOSURE's parameter count where the data declares
        # one, because argument count does not separate LINQ's indexed
        # overloads: `Select(source, x => ..)` and `Select(source, (x, i) =>
        # ..)` are both two-argument calls. `.map()` takes a one-parameter
        # closure and `.map(|x, i| ..)` does not compile.
        want = linq.get("lambda_arity", {}).get(key)
        if tmpl and want is not None:
            got = _closure_arity(rest[0] if rest else "")
            if got is not None and got != want:
                em.unhandled[f"linq:{key} lambda/{got}"] = 1
                return f"/* Linq{meth} */"
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
            out = tmpl.format(recv=recv, args=", ".join(rest))
            # A mapping that is not an equivalence marks its own site. The
            # identifier comes from the data, so a member absent from `warn`
            # is claiming faithfulness rather than merely not having been
            # thought about -- which is the difference the tier exists for.
            wid = linq.get("warn", {}).get(meth)
            if wid:
                return f"{em.warn_inline(wid)} {out}"
            return out
    # Counted WITH the arity: `linq:Select/3` says an overload is missing,
    # which is different work from `linq:Union/2` saying an operator is.
    # Reporting both as `linq:Select` would hide the overload behind an
    # operator that already looks supported.
    em.unhandled[f"linq:{meth}/{len(vals)}"] = 1
    return f"/* Linq{meth} */"
