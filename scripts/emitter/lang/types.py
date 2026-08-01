"""C# type names to Rust type names.

LANGUAGE LAYER -- see `scripts/check_layering.py`.

Only the shape of the mapping lives here; every name comes from the `stdlib`
table in `rulesdb/rules/csharp_core.json`. Generic families are handled as
FAMILIES rather than enumerated: `Func<A,B,R>` and `Action<A,B>` differ only in
whether the final type argument is a return type, so one rule covers every
arity instead of a table that is always one shape out of date.

Returning None is meaningful. It means "no mapping", and callers must WITHHOLD
rather than guess -- an early version fell back to `()` for an unmapped return
type and emitted a function that silently dropped the value every caller read.
"""

from __future__ import annotations

from emitter.core import snake


class Types:
    """Mixin: C# type to Rust type."""

    def rust_type(self, cs: str) -> str | None:
        """A C# declared type as Rust, via the stdlib rules. None when unmapped
        -- reported as a gap rather than guessed."""
        std = self.language.get("stdlib", {})
        prim, types = std.get("primitives", {}), std.get("types", {})
        cs = cs.strip()
        if cs in prim:
            return prim[cs]
        # Non-generic `System.Action` -- no type arguments at all.
        if cs.split(".")[-1] == "Action":
            bare = std.get("delegates", {}).get("bare_action")
            if bare:
                return bare
        if cs.endswith("[]"):
            inner = self.rust_type(cs[:-2])
            return (std.get("array_form", "Vec<{inner}>").format(inner=inner)
                    if inner else None)
        # A nested enum the translated type declares is a real Rust type.
        if cs.split(".")[-1] in self._enum_names:
            return cs.split(".")[-1]
        if "<" in cs:
            outer = cs.split("<")[0].split(".")[-1]
            inner = cs[cs.index("<") + 1:cs.rindex(">")]
            dele = std.get("delegates", {})
            if outer in ("Func", "Action") and outer in dele:
                # Split the generic arguments at the TOP level only: a nested
                # `Func<long, T, T?>` inside another generic must not be split
                # on its own commas.
                parts, depth, buf = [], 0, ""
                for ch in inner:
                    if ch == "<":
                        depth += 1
                    elif ch == ">":
                        depth -= 1
                    if ch == "," and depth == 0:
                        parts.append(buf.strip()); buf = ""
                    else:
                        buf += ch
                if buf.strip():
                    parts.append(buf.strip())
                mapped = [self.rust_type(x) for x in parts]
                if any(m is None for m in mapped):
                    return None
                if outer == "Action":
                    return dele["Action"].format(params=", ".join(mapped))
                # Func's LAST type argument is the return type.
                return dele["Func"].format(params=", ".join(mapped[:-1]),
                                           ret=mapped[-1])
            if outer in dele:
                i = self.rust_type(inner)
                return dele[outer].format(inner=i) if i else None
            o, i = types.get(outer), self.rust_type(inner)
            if o and i:
                return std.get("generic_form", "{outer}<{inner}>").format(outer=o, inner=i)
            return None
        return types.get(cs.split(".")[-1])

