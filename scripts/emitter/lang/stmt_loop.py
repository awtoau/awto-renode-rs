"""C# loops: For, ForEach, While and Do.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged.

This is one of the two things the statement layer got wrong before and must not
get wrong again:

  * A loop's KIND comes from the corpus (Roslyn's LoopKind), not from guessing
    at the child shape. For, ForEach, While and Do all arrive as kind `Loop`
    and have different children; inferring instead of reading it produced a
    `for(;;)` emitted as a `foreach`.

WRAPPED IN `must_explain`, deliberately: an unrecognised LoopKind returns an
empty body, and an empty body is a `while` that never advances. A `/* GAP */`
left in a loop increment compiled into an infinite loop once already, so
silence here is the expensive kind. The decorator moved with the code; it
raises unless the empty return recorded the unhandled kind first.
"""

from __future__ import annotations

import json

from emitter import core
from emitter.core import must_explain, snake


@core.stmt("Loop")
@must_explain
def emit_loop(em, oid: int, indent: int) -> list[str]:
    """A C# loop. The kind comes from the corpus (LoopKind), not from the
    child shape, so a For and a ForEach are never confused."""
    pad = "    " * indent
    rules = em.language.get("loops", {})
    det = (em.con.execute("SELECT detail FROM operation WHERE id=?", (oid,))
           .fetchone() or [None])[0]
    info = {}
    if det:
        try:
            info = json.loads(det)
        except json.JSONDecodeError:
            info = {}
    lk = info.get("loop")
    kids = list(em.children(oid))
    body_id = next((c[0] for c in kids if c[1] == "Block"), None)
    body = em.emit_block(body_id, indent + 1) if body_id is not None else []

    if lk == "ForEach" and len(kids) >= 2:
        coll = em.emit_expr(kids[0][0])
        var = snake(info.get("var") or "item")
        return [pad + f"for {var} in {coll} {{", *body, pad + "}"]

    if lk == "While":
        cond = em.emit_expr(kids[0][0]) if kids else "true"
        return [pad + f"while {cond} {{", *body, pad + "}"]

    if lk == "For":
        init = [c for c in kids if c[1] == "VariableDeclarationGroup"]
        cond = [c for c in kids if c[1] == "Binary"]
        incr = [c for c in kids if c[1] == "ExpressionStatement"]
        out = []
        for c in init:
            out.extend(em.emit_stmt(c[0], indent))
        cond_txt = em.emit_expr(cond[0][0]) if cond else "true"
        out.append(pad + f"while {cond_txt} {{")
        out.extend(body)
        for c in incr:
            out.extend(em.emit_stmt(c[0], indent + 1))
        out.append(pad + "}")
        return out

    em.unhandled[f"loop:{lk}"] = em.unhandled.get(f"loop:{lk}", 0) + 1
    return []
