"""Two levels of one inheritance chain declaring the same field name.

LANGUAGE LAYER -- see `scripts/check_layering.py`.

Rust has no inheritance, so a base class's storage is merged into the
subclass's struct. If two levels of one chain declare the same name -- the same
C# spelling, or two spellings that collapse to one under `snake_case` -- the
merged struct declares the field twice. That is rustc E0124: the struct does
not compile at all, so nothing that mentions the type compiles either.

WHY EVERY COPY IS WITHHELD, NOT ONE OF THEM
-------------------------------------------
Keeping one copy picks a winner, and it is the wrong one about half the time:
the reader of the field is whichever level declared the code that touches it,
and that is not knowable from the declaration. A field that silently resolves
to the other level's storage is wrong code that compiles -- the failure class
this project keeps paying for. Withholding all copies makes every use site
report a gap instead, which is loud and countable.

WHY A GAP AND NOT A CRASH
-------------------------
A named gap is the stated discipline for something the converter cannot do.
An E0124 says the same thing later, in a language the gap census cannot count,
after the file has already been published as a translation.

WHY THIS IS NOT DEAD CODE
-------------------------
Today's cut has no collision, so this fires on nothing in it -- which is exactly
why it is here. The census found 11 types tree-wide whose merged struct declares
a field twice, two of them types this project ships; they are invisible only
because their bases sit outside the cut, and closing the cut makes them visible
all at once. `scripts/check_inheritance.py` builds a colliding two-level corpus
and asserts this fires, because a guard nobody has seen fire is worth nothing.
"""

from __future__ import annotations


def guard(fields: list[tuple[str, str, str]],
          spec: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """Drop every colliding name, naming each collision.

    Takes (rust name, rust type, declaring C# class) and returns the surviving
    (name, type) pairs plus one gap per collision. Empty gaps means there was no
    collision, which is the common case and a real answer -- not a path that
    declined to say why.
    """
    counts: dict[str, int] = {}
    for name, _ty, _owner in fields:
        counts[name] = counts.get(name, 0) + 1
    colliding = {n for n, c in counts.items() if c > 1}
    if not colliding:
        return [(n, t) for n, t, _o in fields], []

    form = spec.get(
        "gap",
        "state field `{name}`: declared at {levels} of one chain, which merge "
        "into one struct -- rustc E0124. Every copy is withheld; the layout "
        "question is open")
    gaps: list[str] = []
    for name in sorted(colliding):
        # Named by DECLARING CLASS and by the C# spelling each level used: two
        # names that differ only after snake_case are a different problem from
        # one name declared twice, and the message has to tell them apart.
        levels = ", ".join(
            f"`{o}`" for _n, _t, o in
            sorted((f for f in fields if f[0] == name), key=lambda f: f[2]))
        gaps.append(form.format(name=name, levels=levels))
    return ([(n, t) for n, t, _o in fields if n not in colliding],
            gaps)
