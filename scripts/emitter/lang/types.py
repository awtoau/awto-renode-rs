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


def split_args(inner: str) -> list[str]:
    """Split generic arguments at the TOP level only.

    A nested `Func<long, T, T?>` inside another generic must not be split on
    its own commas.
    """
    out, depth, buf = [], 0, ""
    for ch in inner:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


class Types:
    """Mixin: C# type to Rust type."""

    def _warn_for_type(self, outer: str) -> None:
        """Queue a WARNING marker if this mapping is not an equivalence.

        Called only where the mapping SUCCEEDS. Queuing on a lookup that then
        returns None would attach the marker to whatever declaration drains
        next, which is a marker pointing at the wrong line -- worse than none,
        because it would be believed.
        """
        wid = self.language.get("stdlib", {}).get("warn_types", {}).get(outer)
        if wid:
            self.note_type_warning(wid)

    def resolve_declared_type(self, cs: str, args: tuple[str, ...] = ()) -> str | None:
        """A type the stdlib rules do not name -- one DECLARED by the input.

        An extension point rather than a table: what a declared type becomes
        depends on what the caller is emitting, and only the caller knows
        whether a Rust definition for it will exist. Callers install a resolver
        on `_type_resolver`; with none installed the answer is None, which is
        the same "no mapping, withhold" this module has always returned.
        """
        fn = getattr(self, "_type_resolver", None)
        return fn(cs, tuple(args)) if fn is not None else None

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
        # `T?` on a value type is Nullable<T> -- the C# type system already
        # says the value may be absent, so no inference is needed.
        if cs.endswith("?") and not cs.endswith("??"):
            inner = self.rust_type(cs[:-1])
            return (std.get("nullable_form", "Option<{inner}>").format(inner=inner)
                    if inner else None)
        # `T[,]` is rectangular in C#; Vec<Vec<T>> is jagged. See multidim_note.
        if cs.endswith("[*,*]"):
            inner = self.rust_type(cs[:-5])
            return (std.get("multidim_form", "Vec<Vec<{inner}>>").format(inner=inner)
                    if inner else None)
        if cs.endswith("[]"):
            inner = self.rust_type(cs[:-2])
            return (std.get("array_form", "Vec<{inner}>").format(inner=inner)
                    if inner else None)
        # A nested enum the translated type declares is a real Rust type.
        if cs.split(".")[-1] in self._enum_names:
            ename = cs.split(".")[-1]
            return getattr(self, "_enum_rust_names", {}).get(ename, ename)
        if "<" in cs:
            outer = cs.split("<")[0].split(".")[-1]
            inner = cs[cs.index("<") + 1:cs.rindex(">")]
            dele = std.get("delegates", {})
            parts = split_args(inner)
            if outer in ("Func", "Action") and outer in dele:
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
            # EVERY type argument, not just the first. A two-parameter generic
            # went through `rust_type("int, Foo")` and failed on a string that
            # is not a type at all -- reported as an unmapped type, which named
            # the wrong problem.
            mapped = [self.rust_type(x) for x in parts]
            if any(m is None for m in mapped):
                return None
            o = types.get(outer)
            if o:
                self._warn_for_type(outer)
                return std.get("generic_form", "{outer}<{inner}>").format(
                    outer=o, inner=", ".join(mapped))
            return self.resolve_declared_type(cs.split("<")[0], tuple(mapped))
        bare = cs.split(".")[-1]
        if bare in types:
            self._warn_for_type(bare)
            return types[bare]
        return self.resolve_declared_type(cs)

