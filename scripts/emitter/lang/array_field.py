"""The declared length of an array field, read from its initialiser.

LANGUAGE LAYER. `private readonly T[] xs = new T[19];` is ordinary C#, and the
length is a fact about the declaration -- not about what any later code does
with it.

Why it needs saying at all
--------------------------

A caller that collects array ELEMENTS and sizes the array from the highest
index it saw is guessing, and it guesses low: an element the code never touches
does not exist as far as usage is concerned, so a 19-element array declared in
C# came out as 16 in Rust. The three missing elements were not visible in any
test, because nothing indexes them -- which is precisely why the size has to
come from the declaration and not from a maximum.

Not `const_under`
-----------------

`plugins/sub_blocks.const_under` walks a subtree and returns the FIRST folded
constant it meets, ignoring any operator above it -- on `new T[N * 2]` it
answers N. That is a defect, and it is load-bearing enough there that fixing it
belongs with that module rather than here. This reads the array creation's own
length expression and requires THAT to be the folded constant, so an operator
above the literal cannot be skipped past: an expression Roslyn did not fold is
reported, never approximated.
"""

from __future__ import annotations

from emitter.core import snake


class ArrayField:
    """Mixin: what an array field's declaration says about its length."""

    def declared_array_length(self, type_name: str,
                              base: str) -> tuple[int | None, str | None]:
        """(length, why it is unknown) for the array field emitted as `base`.

        `base` is the emitted (snake) name, because that is what the caller
        holds; the C# name is recovered by matching the same transformation.
        Never returns both values as None -- either the length is known, or the
        reason it is not is available to be reported."""
        for mid, name in self.con.execute(
                "SELECT mb.id, mb.name FROM member mb JOIN type t ON t.id = mb.type_id "
                "WHERE t.name = ? AND mb.kind = 'field' AND mb.declared_type LIKE '%[]' "
                "ORDER BY mb.name", (type_name,)):
            if snake(name) != base:
                continue
            row = self.con.execute(
                "SELECT id FROM operation WHERE method_id=? AND kind='ArrayCreation' "
                "ORDER BY depth, ordinal LIMIT 1", (mid,)).fetchone()
            if row is None:
                return None, (f"the C# field `{name}` is assigned elsewhere, so "
                              f"its declaration states no length")
            kids = self.children(row[0])
            if not kids:
                return None, f"the C# `new {name}[...]` states no length"
            _cid, _kind, _sym, const, _typ = kids[0]
            if const is None:
                return None, (f"the length in the C# declaration of `{name}` is "
                              f"an expression the compiler did not fold")
            return int(const), None
        return None, f"no C# array field is named `{base}`"
