"""A reference to a local variable.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

The declared name is preferred over the symbol, because the symbol is not
always the name a human wrote and the declaration always is.
"""

from __future__ import annotations

import json

from emitter import core
from emitter.core import snake

PRIORITY = core.LANGUAGE + 24


@core.expr("LocalReference", priority=PRIORITY)
def local_reference(em, oid):
    """Declines when neither the declaration detail nor a symbol names it.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    row = em.con.execute(
        "SELECT symbol, detail FROM operation WHERE id=?", (oid,)).fetchone()
    symbol, detail = (row if row else (None, None))
    if detail:
        try:
            return snake(json.loads(detail).get("local", "local"))
        except json.JSONDecodeError:
            pass
    if symbol:
        return snake(symbol.split(".")[-1])
    return None
