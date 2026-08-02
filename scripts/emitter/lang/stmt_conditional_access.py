"""`x?.Foo();` in STATEMENT position, rewritten to an if-guard.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

ORDER IS LOAD-BEARING. This and `stmt_expression` both claim
`ExpressionStatement`, and in the chain this test came FIRST -- the plain form
matches every expression statement, so registering them at equal priority would
let import order decide which won. It registers at `core.LANGUAGE` and the plain
form at `core.LANGUAGE + 1`, which reproduces the chain order as data rather
than as an accident of the module names.

DECLINES for any expression statement that is not a normalised conditional
access, which is the overwhelming majority; the plain form then handles it.
"""

from __future__ import annotations

from emitter import core


@core.stmt("ExpressionStatement", priority=core.LANGUAGE)
def conditional_access_stmt(em, oid: int, indent: int) -> list[str] | None:
    """The guarded rewrite, or None to fall through to the plain form."""
    pad = "    " * indent
    kids = em.children(oid)
    if not (kids and kids[0][0]
            in em.normalised.get("ConditionalAccessStatement", ())):
        return None

    # NORMALISATION, not a mapping. `x?.Foo();` in statement position
    # discards its result, so the short-circuit IS an if-guard -- an
    # exact rewrite needing no decision about whether x is nullable,
    # because the C# already said it might be. Expression position is
    # NOT this: `y = x?.Foo()` yields null and needs D4.
    # Passes are an ORDERED LIST keyed by `name`, not a dict -- order
    # is data. Looking it up as a dict key silently yielded {} and the
    # branch fell through to the gap, with no error anywhere.
    spec = next((x for x in em.language.get("normalisations", {})
                 .get("passes", [])
                 if x.get("name") == "ConditionalAccessStatement"), {})
    ca = list(em.children(kids[0][0]))
    if len(ca) >= 2 and spec.get("emit"):
        recv = em.emit_expr(ca[0][0])
        prev = getattr(em, "_ca_binding", None)
        em._ca_binding = "__v"
        # The guarded part is an EXPRESSION (the call), not a
        # statement; routing it through emit_stmt records a bogus
        # unhandled `stmt:Invocation` and withholds the method.
        body = [("    " * (indent + 1))
                + em.emit_expr(ca[1][0]) + ";"]
        em._ca_binding = prev
        head = spec["emit"].split("\n")[0].format(
            receiver=recv, body="")
        return [pad + head.replace("Some(x)", "Some(__v)"),
                *body, pad + "}"]
    return None
