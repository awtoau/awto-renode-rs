"""A reference to one of the enclosing method's parameters.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.
"""

from __future__ import annotations

from emitter import core
from emitter.core import snake

PRIORITY = core.LANGUAGE + 23


@core.expr("ParameterReference", priority=PRIORITY)
def parameter_reference(em, oid):
    """Declines when the corpus recorded no symbol for the parameter.

    Declining is not silence: the unclaimed kind is counted by the caller, which
    is where it was counted before this moved out of the built-in chain.
    """
    row = em.con.execute(
        "SELECT symbol, type FROM operation WHERE id=?", (oid,)).fetchone()
    symbol, rtype = (row if row else (None, None))
    if not symbol:
        return None
    # A WithEnumFields callback slot is declared u64 in Rust but typed
    # as the enum in C#; convert where it is used. Only for lambda
    # slots -- see enums.typed_callback_param.
    nm = snake(symbol.split()[-1])
    ety = (rtype or "").split(".")[-1]
    if nm in em._enum_slots and ety in em._enum_names:
        return em.project.get("enums", {}).get(
            "typed_callback_param", {}).get(
            "emit", "{type}::from_u64({name})").format(type=ety, name=nm)
    # A WithFlag callback slot is likewise declared u64 in Rust (the
    # signature is width-uniform across flag and value fields) but typed
    # bool in C#; convert the same way -- see bool_callback_param.
    if nm in em._enum_slots and ety == "bool":
        return em.project.get("bool_callback_param", {}).get(
            "emit", "({name} != 0)").format(name=nm)
    # The symbol is "byte value" -- type then name. Splitting on "."
    # returned the whole thing and emitted `enqueue(byte value)`.
    if nm in getattr(em, "_by_ref_params", set()):
        # The signature carries `ref`/`out` as `&mut T`; ordinary reads and
        # assignment targets operate on the referred-to C# value.
        return f"*{nm}"
    return nm
