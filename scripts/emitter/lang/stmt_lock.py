"""C# `lock (x) { .. }` as a Rust mutex guard.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged; the marker and
the guard line still come from the `locking` rule.

DECLINES when the operation has fewer than two children, so a malformed `Lock`
reaches the built-in chain's fallback and is reported rather than guessed at.
"""

from __future__ import annotations

from emitter import core


@core.stmt("Lock")
def lock_stmt(em, oid: int, indent: int) -> list[str] | None:
    """A guarded block. Returns None when there is no body to guard."""
    pad = "    " * indent
    kids = em.children(oid)
    if len(kids) < 2:
        return None

    # Structure preserved, timing explicitly NOT guaranteed -- see the
    # `locking` rule. Each site is marked so it can be measured.
    #
    # The marker is no longer a literal in this rule: it is a WARNING-severity
    # deviation like any other, rendered from `severity.warnings`. Same tag and
    # same text, so nothing that already looks for it changes -- but it is now
    # the mechanism three other deviations use rather than the only marker in
    # the emitter.
    spec = em.language.get("locking", {})
    body = em.emit_block(kids[1][0], indent + 1) \
        if kids[1][1] == "Block" else em.emit_stmt(kids[1][0], indent + 1)
    return [*em.warn_line(spec.get("warning", ""), indent),
            pad + "{",
            pad + "    " + spec.get(
                "guard", "let _sync = {target}.lock().unwrap();").format(
                target=em.emit_expr(kids[0][0])),
            *body,
            pad + "}"]
