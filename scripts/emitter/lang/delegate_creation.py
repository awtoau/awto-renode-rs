"""A delegate built from an inline function -- C#'s lambda, Rust's closure.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

Only the anonymous-function form is claimed. A delegate made from a NAMED
method is a different construct with a different Rust shape, and emitting a
closure for it would be plausible output rather than correct output.
"""

from __future__ import annotations

import json

from emitter import core

PRIORITY = core.LANGUAGE + 8


@core.expr("DelegateCreation", priority=PRIORITY)
def delegate_creation(em, oid):
    """Declines unless the delegate wraps an anonymous function.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    kids = [c[0] for c in em.children(oid)]
    if not kids:
        return None
    inner = kids[0]
    if em.kind_of(inner) != "AnonymousFunction":
        return None
    det = (em.con.execute(
        "SELECT detail FROM operation WHERE id=?", (inner,)
    ).fetchone() or [None])[0]
    names = []
    if det:
        try:
            names = json.loads(det).get("params", "").split()
        except json.JSONDecodeError:
            names = []
    body = []
    for cid, ck, _s, _c, _t in em.children(inner):
        body.extend(em.emit_block(cid, 0) if ck == "Block"
                    else em.emit_stmt(cid, 0))
    txt = " ".join(l.strip() for l in body).rstrip(";")
    return em.language.get("delegates_expr", {}).get(
        "closure", "|{params}| {body}").format(
        params=", ".join(n if n != "_" else "_" for n in names),
        body=txt)
