"""C# `return` as Rust `return`.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged; the templates
still come from `rulesdb/rules/csharp_core.json` under `statements.Return`.

Never declines: a `Return` operation always produces a line, with or without a
value, so an empty result here would be a bug rather than a rule that does not
apply.
"""

from __future__ import annotations

from emitter import core


@core.stmt("Return")
def return_stmt(em, oid: int, indent: int) -> list[str]:
    """`return;` and `return x;`, with the declared return coercion applied."""
    pad = "    " * indent
    kids = em.children(oid)
    stmts = em.language.get("statements", {})

    tmpl = stmts.get("Return", {})
    if kids:
        child_id = kids[0][0]
        val = em.emit_expr(child_id)
        coerce = getattr(em, "_coerce_ret", None)
        if coerce:
            val = em.language.get("coercions", {}).get(
                coerce, "{expr}").format(expr=val)
        elif getattr(em, "_ret_is_owned_string", False):
            # A bare string literal renders as `&'static str`; the method's
            # declared return type is the owned `String` every other string
            # producer in this corpus maps C# `string` to (see `rust_type`).
            row = em.con.execute(
                "SELECT kind, type FROM operation WHERE id=?", (child_id,)).fetchone()
            if row and row[0] == "Literal" and row[1] == "string":
                val = f"{val}.to_string()"
        return [pad + tmpl.get("with_value", "return {value};")
                .format(value=val)]
    return [pad + tmpl.get("bare", "return;")]
