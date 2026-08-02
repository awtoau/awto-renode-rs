"""One declared C# local: `let` with or without an initialiser.

LANGUAGE LAYER. Split out of the `emit_stmt` chain unchanged; the templates
still come from `rulesdb/rules/csharp_core.json` under
`statements.VariableDeclarator`.

The declared name lives in the operation's `detail` JSON, not in its symbol,
and a corpus row whose detail does not parse falls back to `value` rather than
raising -- the same behaviour the chain had.

Never declines.
"""

from __future__ import annotations

import json

from emitter import core
from emitter.core import snake


@core.stmt("VariableDeclarator")
def variable_declarator_stmt(em, oid: int, indent: int) -> list[str]:
    """`let mut x = init;`, or the bare form when there is no initialiser."""
    pad = "    " * indent
    detail = (em.con.execute(
        "SELECT detail FROM operation WHERE id=?", (oid,)).fetchone()
        or [None])[0]
    kids = em.children(oid)
    stmts = em.language.get("statements", {})

    name = "value"
    if detail:
        try:
            name = snake(json.loads(detail).get("local", "value"))
        except json.JSONDecodeError:
            pass
    init = None
    for cid, ckind, _s, _c, _t in kids:
        if ckind == "VariableInitializer":
            inner = em.children(cid)
            if inner:
                init = em.emit_expr(inner[0][0])
    tmpl = stmts.get("VariableDeclarator", {})
    if init is not None:
        return [pad + tmpl.get("with_init", "let mut {name} = {init};")
                .format(name=name, init=init)]
    return [pad + tmpl.get("bare", "let mut {name};").format(name=name)]
