"""Resolve a static call into an emitted utility module (BitHelper, Misc, ...).

PLUGIN LAYER. `register_owners.utility_owners` decides which types earn a
module of their own, and that decision is Renode-corpus content, not a
generic C# fact -- so it belongs here, tried before the generic language
fallback in `emitter/lang/invocation.py` ever runs. That fallback still
withholds the call when `Emitter.utility_module_functions` reports the target
is not a recognised module, or is one but did not itself emit the specific
function -- both cases fall through unchanged to the same withhold as before
this file existed.
"""

from __future__ import annotations

from emitter import core
from emitter.core import snake, module_name

PRIORITY = core.PLUGIN + 50


@core.expr("Invocation", priority=PRIORITY)
def utility_call(em, oid):
    """Declines whenever the generic language-layer withhold is still right.

    That is: no recorded symbol, no corpus-resolved callee, an instance call,
    a call on the type currently being emitted (its own free-function rewrite
    already handles that), the declaring type is not a recognised utility
    module, or it is one that did not itself emit this particular method.
    """
    if oid not in em._invocation_symbol_cache:
        row = em.con.execute(
            "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
        em._invocation_symbol_cache[oid] = row[0] if row else None
    symbol = em._invocation_symbol_cache[oid]
    if not symbol:
        return None
    if symbol not in em._callee_cache:
        em._callee_cache[symbol] = em.con.execute(
            "SELECT mb.id, mb.is_static, t.name "
            "FROM member mb JOIN type t ON t.id=mb.type_id "
            "WHERE mb.run_id=? AND mb.key=? LIMIT 1",
            (em._run_id, symbol)).fetchone()
    callee = em._callee_cache[symbol]
    if not callee or not callee[1]:
        return None
    declaring = callee[2]
    if declaring == getattr(em, "_current_type", None):
        return None
    fn_names = em.utility_module_functions(declaring)
    if fn_names is None:
        return None
    fname = snake(symbol.split("(")[0].split(".")[-1])
    if fname not in fn_names:
        return None
    args = [c for c in em.children(oid) if c[1] == "Argument"]
    arg_txt = ", ".join(em.emit_expr(a[0]) for a in args)
    return f"{module_name(declaring)}::{fname}({arg_txt})"
