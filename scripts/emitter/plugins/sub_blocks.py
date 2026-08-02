"""Child objects that define registers into their parent's bank.

CORPUS LAYER. This depends on the register DSL -- specifically on a child
calling `.Define(parent)` -- so it is not generic C#. The generic half it rests
on, an offset that is an expression rather than a constant, lives in the driver
and applies to any register map.

The shape
---------

    private readonly Stream[] streams;
    private const int NrOfStreams = 8;
    private const int StreamStep = 0x18;

    streams = Enumerable.Range(0, NrOfStreams)
                        .Select(id => new Stream(this, id)).ToArray();

and inside the child:

    var streamOffset = id * StreamStep;
    (Registers.StreamConfiguration + streamOffset).Define(parent)
        .WithFlag(0, out isEnabled, ...)

There is ONE register map, not a bank per child: the child defines into the
parent's collection at `base + id * step`. So the translation is a loop in the
parent's `define_registers`, not a dispatch that routes an offset to a child.

Why it mattered
---------------

Without it the parent's bank had nothing at those addresses, so every read
returned 0. On the `dma2` trace that was 6,164 divergences over 12,356
accesses -- and it reported no gap, because the register form only ever looked
for a constant offset and a non-constant one simply did not match anything.

What it is NOT
--------------

Not "any array of child objects". Five of the six array-of-corpus-class fields
in the cut hold children with no register block of their own; those are an
ordinary `Vec` and are not this rule's business. The discriminator is that the
child's own method defines registers AND the child holds a back-reference to
the parent -- both read from the corpus, neither guessed.
"""

from __future__ import annotations

from emitter.core import snake


def sub_blocks(em, type_name: str) -> tuple[list[dict], list[str]]:
    """Detected replicated child register blocks, and what could not be read."""
    spec = em.project.get("sub_blocks", {})
    if not spec:
        return [], []
    out: list[dict] = []
    gaps: list[str] = []
    for fname, dt in em.con.execute(
            "SELECT mb.name, mb.declared_type FROM member mb "
            "JOIN type t ON t.id = mb.type_id WHERE t.name = ? AND "
            "mb.kind = 'field' AND mb.is_static = 0 AND mb.has_storage = 1 "
            "AND mb.declared_type LIKE '%[]' ORDER BY mb.name", (type_name,)):
        child = (dt or "").strip()[:-2].split(".")[-1]
        if not child:
            continue
        # A back-reference to the parent is what makes the child a PART of this
        # peripheral rather than something it merely holds.
        if not em.con.execute(
                "SELECT 1 FROM member mb JOIN type t ON t.id = mb.type_id "
                "WHERE t.name = ? AND mb.kind = 'field' AND mb.declared_type "
                "LIKE ? LIMIT 1", (child, f"%.{type_name}")).fetchone():
            continue
        method = child_register_method(em, child)
        if method is None:
            continue          # a child with no register block: an ordinary Vec
        count, count_name = array_count(em, type_name, fname)
        if count is None:
            gaps.append(spec.get("gap_count",
                                 "sub-block `{field}`: the constructor does not "
                                 "give a constant instance count, so the register "
                                 "map cannot be replicated").format(field=fname))
            continue
        ident, ident_ty = identity_param(em, child, type_name)
        if ident is None:
            gaps.append(spec.get("gap_identity",
                                 "sub-block `{field}`: the child takes no "
                                 "instance index, so its registers cannot be "
                                 "placed").format(field=fname))
            continue
        out.append({"field": snake(fname), "child": child,
                    "module": snake(child), "method": method,
                    "count": count, "count_name": count_name,
                    "ident": ident, "ident_ty": ident_ty})
    return out, gaps


def identity_param(em, child: str, parent: str) -> tuple[str | None, str | None]:
    """The constructor parameter that tells one instance from another.

    `Stream(STM32DMA parent, int id)` -- everything but the back-reference. The
    name is NOT assumed to be `id`: it is the parameter, so the emitted loop
    binds whatever the C# called it, and the type is the C# type mapped, so the
    struct literal does not need a cast that may not be valid.
    """
    ctor = em.con.execute(
        "SELECT mb.id FROM member mb JOIN type t ON t.id = mb.type_id "
        "WHERE t.name = ? AND mb.kind = 'ctor'", (child,)).fetchone()
    if not ctor:
        return None, None
    rest = [(n, ty) for n, ty in em.con.execute(
        "SELECT name, type FROM parameter WHERE method_id=? ORDER BY ordinal",
        (ctor[0],)) if (ty or "").split(".")[-1] != parent]
    if len(rest) != 1:
        return None, None
    name, ty = rest[0]
    return snake(name), em.rust_type(ty or "")


def child_register_method(em, child: str) -> str | None:
    """The child's method that defines registers, found by TRYING, not by name.

    Matching on a name would make the rule fit one corpus. Running the register
    forms over each method with a body and keeping the one that yields registers
    works wherever the forms do.
    """
    for (name,) in em.con.execute(
            "SELECT mb.name FROM member mb JOIN method m ON m.member_id = mb.id "
            "JOIN type t ON t.id = mb.type_id WHERE t.name = ? AND "
            "mb.kind = 'method' AND m.has_body = 1 ORDER BY mb.name", (child,)):
        row = em.con.execute(
            "SELECT m.member_id FROM method m JOIN member mb ON mb.id = m.member_id "
            "JOIN type t ON t.id = mb.type_id WHERE t.name = ? AND mb.name = ?",
            (child, name)).fetchone()
        if not row:
            continue
        prev_type, prev_gaps = em._current_type, em.gaps
        em._current_type, em.gaps = child, []
        try:
            found = em.find_registers(row[0])
        finally:
            em._current_type, em.gaps = prev_type, prev_gaps
        if found:
            return name
    return None


def array_count(em, type_name: str, field: str) -> tuple[int | None, str | None]:
    """How many instances the constructor makes, and the C# name for that count.

    Two forms, both reduced to a folded constant Roslyn already resolved:
    `new C[N]`, and a `Range(0, N)` feeding a projection. Anything else returns
    None and is reported rather than assumed.
    """
    ctor = em.con.execute(
        "SELECT m.member_id FROM method m JOIN member mb ON mb.id = m.member_id "
        "JOIN type t ON t.id = mb.type_id WHERE t.name = ? AND mb.kind = 'ctor'",
        (type_name,)).fetchone()
    if not ctor:
        return None, None
    assign = None
    for oid, in em.con.execute(
            "SELECT id FROM operation WHERE method_id=? AND kind='SimpleAssignment'",
            (ctor[0],)):
        kids = em.children(oid)
        if kids and kids[0][1] == "FieldReference" and kids[0][2] \
                and kids[0][2].split(".")[-1] == field:
            assign = oid
            break
    if assign is None:
        return None, None
    stack, best = [assign], (None, None)
    while stack:
        for cid, kind, sym, const, _t in em.children(stack.pop()):
            if kind == "Invocation" and sym and ".Range(" in sym:
                for aid, akind, asym, _c, _t2 in em.children(cid):
                    if akind == "Argument" and asym and asym.split()[-1] == "count":
                        best = const_under(em, aid)
            elif kind == "ArrayCreation":
                got = const_under(em, cid)
                if got[0] is not None:
                    best = got
            stack.append(cid)
    return best


def const_under(em, oid: int) -> tuple[int | None, str | None]:
    """First folded constant in a subtree, with the C# name if it had one."""
    stack = [oid]
    while stack:
        for cid, kind, sym, const, _t in em.children(stack.pop()):
            if const is not None and kind in ("Literal", "FieldReference"):
                try:
                    return int(const), (sym.split(".")[-1]
                                        if kind == "FieldReference" and sym else None)
                except ValueError:
                    return None, None
            stack.append(cid)
    return None, None
