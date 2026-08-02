"""C# `if` / `else` as Rust `if` / `else`.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

DECLINES when the operation has fewer than two children -- a `Conditional` with
no branch to emit is malformed, and the built-in chain's fallback records it as
unhandled. Handling it here instead would replace a reported gap with plausible
output, which is the failure mode the work protocol names first.
"""

from __future__ import annotations

from emitter import core


@core.stmt("Conditional")
def conditional_stmt(em, oid: int, indent: int) -> list[str] | None:
    """`if (c) { .. } else { .. }`. Returns None on a malformed operation."""
    pad = "    " * indent
    kids = em.children(oid)
    if len(kids) < 2:
        return None

    cond = em.emit_expr(kids[0][0])
    then = em.emit_block(kids[1][0], indent + 1)
    out = [f"{pad}if {cond} {{"] + then
    if len(kids) >= 3:
        out.append(f"{pad}}} else {{")
        out.extend(em.emit_block(kids[2][0], indent + 1))
    out.append(pad + "}")
    return out
