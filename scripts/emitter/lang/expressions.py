"""Expressions: the dispatch entry, and the helpers a construct shares.

LANGUAGE LAYER. Nothing here may name anything specific to the codebase being
translated; `scripts/check_layering.py` fails the commit if it does. Corpus
idioms live in `scripts/emitter/plugins/` and are consulted FIRST, so an idiom
can override any mapping without this module knowing it exists.

Templates come from `rulesdb/rules/csharp_core.json`. Nothing here decides what
the Rust says.

**One construct, one file.** This module used to hold every expression kind as
a branch in one `if kind == ...` chain, which meant two agents adding two
constructs edited one file and every new kind widened a shared function. Each
kind is now its own module in this directory, found by the registry in
`core.py`; what is left here is the dispatch entry and the handful of helpers
more than one construct calls.

The two rules that are load-bearing kept their reasoning with them, in the
files they moved to:

  * A reference emits its RECEIVER (`reference.py`). Dropping it turned
    `queue.Count` into `self.count()` -- reading the wrong object -- and did so
    for 26% of all references while both generated files stayed byte-identical
    and correct, because the two types converted at the time reached their
    state through `this`.

  * An implicit NUMERIC conversion becomes an explicit cast (`conversion.py`).
    C# widens silently and Rust never does, so `16.0` emitted as `16` turned an
    f64 division into integer division that compiled and passed every test.
"""

from __future__ import annotations

import re

from emitter import core
from emitter.core import snake


class Expressions:
    """Mixin: expression emission."""

    def emit_expr(self, oid: int) -> str:
        """Recursively emit one expression.

        Generic structure (operators, literals) comes from the LANGUAGE rules;
        anything mentioning a corpus construct comes from the PROJECT
        rules. The split is enforced by where each table is loaded from, so a
        a corpus idiom cannot leak into the language layer.

        This function no longer knows any construct by name. It finds the
        handlers for the kind, tries them in order, and counts the kind if none
        of them claims it -- so a construct is added by adding a FILE, and
        nothing that already works is touched.
        """
        row = self.con.execute(
            "SELECT kind, symbol, const_value, detail, type FROM operation WHERE id=?",
            (oid,)).fetchone()
        if row is None:
            return "/* missing */"
        kind, symbol, const, detail, rtype = row
        all_kids = self.children(oid)
        kids = [c[0] for c in all_kids]
        # Arguments only. An Invocation's first child is the RECEIVER, so
        # indexing all children made `arg0` the object being called on rather
        # than the value passed to it.
        args = [c[0] for c in all_kids if c[1] == "Argument"]

        # Corpus idioms first: they are more specific than the language rules,
        # and live in scripts/emitter/plugins/ so the language layer can be
        # checked for purity. See check_layering.py.
        claimed = self.plugin_expr(oid, kind, symbol, const, rtype, detail,
                                   kids, args, all_kids)
        if claimed is not None:
            return claimed

        # Every language construct, in priority order. A handler returns None to
        # decline, and the next one gets its turn; the priorities are assigned
        # from the order the constructs had when they were one chain, because
        # some pairs are order-sensitive and the more specific must go first.
        for fn in core.expr_handlers(kind):
            got = fn(self, oid)
            if got is not None:
                return got

        # Nothing claimed it. Counting the kind is what makes an unsupported
        # construct MEASURABLE rather than a plausible-looking comment nobody
        # notices, so this is the one path allowed to produce filler.
        self.unhandled[f"expr:{kind}"] = self.unhandled.get(f"expr:{kind}", 0) + 1
        return f"/* {kind} */"

    def const_text(self, oid: int) -> str:
        """The literal text of an interpolated string's fixed piece."""
        row = self.con.execute(
            "SELECT const_value FROM operation WHERE parent_id=? AND kind='Literal'",
            (oid,)).fetchone()
        if row and row[0] is not None:
            return str(row[0]).strip('"')
        row = self.con.execute(
            "SELECT const_value FROM operation WHERE id=?", (oid,)).fetchone()
        return str(row[0]).strip('"') if row and row[0] is not None else ""

    def kind_of(self, oid: int) -> str:
        row = self.con.execute("SELECT kind FROM operation WHERE id=?", (oid,)).fetchone()
        return row[0] if row else ""

    def stdlib_member(self, symbol: str) -> str | None:
        """The BCL member name as `Type.Member`, if this is one we map."""
        std = self.language.get("stdlib", {}).get("members", {})
        parts = symbol.split("(")[0].split(".")
        if len(parts) < 2:
            return None
        ty = parts[-2].split("<")[0]
        key = f"{ty}.{parts[-1]}"
        return key if key in std else None

    def emit_reference(self, kind: str, symbol: str, kids: list) -> str:
        """A field or property reference, WITH its receiver.

        The receiver was previously dropped and every reference emitted as
        `self.<name>`, which reads the wrong object whenever the C# names one
        -- `receiveFifo.Count` became `self.count()`."""
        forms = self.language.get("references", {}).get(kind, {})
        key = self.stdlib_member(symbol)
        if key and kids:
            return self.language["stdlib"]["members"][key].format(
                recv=self.emit_expr(kids[0]), args="")
        name = snake(symbol.split(".")[-1].split("(")[0])
        if not kids:
            # No receiver child: a static reference, or `this` left implicit.
            return forms.get("self", "self.{name}").format(name=name)
        rid = kids[0]
        rkind = self.kind_of(rid)
        if rkind == "InstanceReference":
            return forms.get("self", "self.{name}").format(name=name)
        return forms.get("instance", "{receiver}.{name}").format(
            receiver=self.emit_expr(rid), name=name)

    def csharp_format(self, text: str) -> str:
        """C# composite format to Rust. `{0:X}` -> `{:X}`, `{1:X8}` -> `{:08X}`.

        Passing the C# form through is a compile ERROR, not a wrong string:
        rustc reports `invalid format string: expected }, found 8`."""
        spec = self.language.get("format_strings", {})
        table = spec.get("specs", {})

        def one(m):
            fmt = m.group(2) or ""
            if not fmt:
                return "{}"
            kind, digits = fmt[0], fmt[1:]
            mapped = table.get(kind, kind)
            if digits.isdigit() and mapped:
                return "{:" + spec.get("padded_hex", "0{width}{spec}").format(
                    width=digits, spec=mapped) + "}"
            return "{:" + mapped + "}" if mapped else "{}"

        return re.sub(r"\{(\d+)(?::([^}]*))?\}", one, text)

    def literal(self, const: str | None, rtype: str | None = None) -> str:
        """A literal, rendered for Rust.

        The TYPE matters: a string literal emitted bare produced
        `self.log(..., Received a character, ...)` -- unquoted prose spliced into
        an argument list, which is both wrong and syntactically invalid."""
        if const is None:
            return "0"
        if const == "null":
            # The `null` literal's own `type` column is never populated (it is
            # not a typed constant), so this cannot be gated on rtype the way
            # string/char/float are -- but every nullable field in this corpus
            # is represented as `Option<T>`, so `None` is unconditionally the
            # right rendering, standing bare in a comparison or an assignment.
            return "None"
        if const in ("True", "False"):
            return const.lower()
        if rtype == "string":
            escaped = const.replace("\\", "\\\\").replace('"', '\\"')
            # C# composite formatting is not Rust format syntax, and passing it
            # through is a compile ERROR rather than a wrong string.
            return f'"{self.csharp_format(escaped)}"'
        if rtype == "char":
            return f"'{const}'"
        if rtype in ("double", "float") and "." not in const and "e" not in const.lower():
            # `16.0` arrives from Roslyn as the constant 16; emitting it bare
            # turns an f64 division into integer division and silently changes
            # the result. See language rule `literals`.
            return const + self.language.get("literals", {}).get("float_suffix", ".0")
        return const

    def receiver_field(self, oid: int) -> str | None:
        """Field name behind `someField.Value` -- the reference under the
        property access."""
        for cid, kind, sym, _c, _t in self.children(oid):
            if kind in ("FieldReference", "PropertyReference") and sym:
                return snake(sym.split(".")[-1].split("(")[0])
            inner = self.receiver_field(cid)
            if inner:
                return inner
        return None

