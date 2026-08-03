"""An enum member read through the type that declares it.

LANGUAGE LAYER. Generic C#; names nothing specific to any corpus.

ORDER IS LOAD-BEARING. This must be consulted before the general reference
rule, or a member reads as an access to state that does not exist -- see the
comment in the body, which records exactly what that produced. `PRIORITY` is
one less than `reference.PRIORITY`, which is the same order the two had when
both were branches in one chain.
"""

from __future__ import annotations

from emitter import core

PRIORITY = core.LANGUAGE + 12


@core.expr("FieldReference", priority=PRIORITY)
def enum_member(em, oid):
    """Declines unless the type before the dot is a known enum.

    Declining hands the node to the general reference rule, which is the
    ordinary outcome for an actual field -- not a failure, and so not counted.
    """
    row = em.con.execute(
        "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
    symbol = row[0] if row else None
    if not (symbol and em._enum_names):
        return None
    # `OversamplingMode.By16` is an enum MEMBER, not state. Without this
    # it fell through to the field rule and emitted `st.by16`.
    parts = symbol.split("(")[0].split(".")
    if len(parts) >= 2 and parts[-2] in em._enum_names:
            rust_name = getattr(em, "_enum_rust_names", {}).get(parts[-2], parts[-2])
            return em.project.get("enums", {}).get(
                "reference", "{type}::{member}").format(
                type=rust_name, member=parts[-1])
