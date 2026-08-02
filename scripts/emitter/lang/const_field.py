"""C# `const` fields: a folded value, not storage.

Generic C#. This module knows nothing about any corpus -- it asks the corpus
database one question, "is the type declaring this member a class or an enum",
and answers it the same way for any C# input.

A `const` field has no storage. The C# compiler folds its value into every use
site, and Roslyn hands us the folded constant on the reference itself. Reading
it as a field access emitted a struct member that cannot exist, and the calling
method was then withheld for reaching state the type does not have -- naming a
field that was never a field.

An enum member is ALSO a folded constant and must not take this path: the enum
rule maps it to a named Rust constant, which is better than a bare number and,
where the runtime already provides the constant, is the only correct output.
The two are told apart by the declaring type's kind, never by name.
"""

from __future__ import annotations

from emitter import core


@core.expr("FieldReference")
def constant_field(em, oid):
    """Declines unless the reference is to a `const` field of a class."""
    row = em.con.execute(
        "SELECT symbol, const_value FROM operation WHERE id=?", (oid,)).fetchone()
    if not row:
        return None
    symbol, const = row
    if not symbol or const is None:
        return None
    spec = em.language.get("references", {}).get("ConstantField", {})
    if not spec.get("emit"):
        return None
    if declaring_type_kind(em, symbol) != "class":
        return None
    return spec["emit"].format(value=const)


def declaring_type_kind(em, symbol: str) -> str | None:
    """`class` or `enum` for the type a member is declared on.

    Resolution is by name, which is ambiguous: one corpus can hold several
    distinct types sharing a short name. A name that is an enum ANYWHERE
    resolves as an enum, because that direction is the safe one -- it leaves the
    existing enum mapping in place rather than inlining a value some runtime may
    have a named constant for.
    """
    parts = symbol.split("(")[0].split(".")
    if len(parts) < 2:
        return None
    cache = getattr(em, "_decl_kind_cache", None)
    if cache is None:
        cache = em._decl_kind_cache = {}
    name = parts[-2]
    if name not in cache:
        kinds = {k for (k,) in em.con.execute(
            "SELECT DISTINCT kind FROM type WHERE name=?", (name,))}
        cache[name] = "enum" if "enum" in kinds else ("class" if kinds else None)
    return cache[name]
