"""Expressions: generic C# to Rust.

LANGUAGE LAYER. Nothing here may name anything specific to the codebase being
translated; `scripts/check_layering.py` fails the commit if it does. Corpus
idioms live in `scripts/emitter/plugins/` and are consulted FIRST, so an idiom
can override any mapping below without this module knowing it exists.

Templates come from `rulesdb/rules/csharp_core.json`. This module decides which
rule applies and how expressions nest; it never decides what the Rust says.

Two things here are load-bearing:

  * A reference emits its RECEIVER. Dropping it turned `queue.Count` into
    `self.count()` -- reading the wrong object -- and did so for 26% of all
    references while both generated files stayed byte-identical and correct,
    because the two types converted at the time reached their state
    through `this`.

  * An implicit NUMERIC conversion becomes an explicit cast. C# widens
    silently and Rust never does, so `16.0` emitted as `16` turned an f64
    division into integer division that compiled and passed every test.
"""

from __future__ import annotations

import json

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

        # Registered handlers, then the built-in chain. A new expression kind
        # is a new file; see core.py.
        for fn in core.expr_handlers(kind):
            got = fn(self, oid)
            if got is not None:
                return got

        # Language layer: generic C# to Rust, valid for any corpus.
        if kind == "Literal":
            return self.literal(const, rtype)
        if kind == "Binary":
            table = self.language.get("operators", {}).get("binary", {})
            tmpl = table.get(symbol or "")
            if tmpl and len(kids) >= 2:
                return "(" + tmpl.format(lhs=self.emit_expr(kids[0]),
                                         rhs=self.emit_expr(kids[1])) + ")"
            self.unhandled[f"Binary:{symbol}"] = self.unhandled.get(f"Binary:{symbol}", 0) + 1
        if kind == "Unary":
            table = self.language.get("operators", {}).get("unary", {})
            tmpl = table.get(symbol or "")
            if tmpl and kids:
                return tmpl.format(operand=self.emit_expr(kids[0]))
        if kind == "Invocation" and symbol:
            # Generic call. Project rules were tried above, so reaching here
            # means no idiom claimed it.
            inv = self.language.get("invocations", {})
            method = snake(symbol.split("(")[0].split(".")[-1])
            arg_txt = ", ".join(self.emit_expr(a) for a in args)
            receiver = next((c[0] for c in all_kids if c[1] != "Argument"), None)
            key = self.stdlib_member(symbol)
            if key and receiver is not None:
                return self.language["stdlib"]["members"][key].format(
                    recv=self.emit_expr(receiver), args=arg_txt)
            rkind = None
            if receiver is not None:
                rkind = self.con.execute(
                    "SELECT kind FROM operation WHERE id=?", (receiver,)).fetchone()[0]
            if receiver is None or rkind == "InstanceReference":
                return inv.get("self", "self.{method}({args})").format(
                    method=method, args=arg_txt)
            return inv.get("instance", "{receiver}.{method}({args})").format(
                receiver=self.emit_expr(receiver), method=method, args=arg_txt)

        if kind == "InterpolatedString":
            rules = self.language.get("strings", {})
            fmt, holes = "", []
            for cid, ck, _s, cconst, _t in self.children(oid):
                if ck == "InterpolatedStringText":
                    lit = self.const_text(cid)
                    fmt += lit.replace("{", "{{").replace("}", "}}")
                else:
                    fmt += rules.get("hole", "{}")
                    holes.append(self.emit_expr(cid))
            return rules.get("interpolated", 'format!("{fmt}"{args})').format(
                fmt=fmt, args="".join(", " + h for h in holes))

        if kind == "NameOf":
            # Roslyn folds nameof to a constant, so the corpus already has it.
            return self.language.get("strings", {}).get(
                "nameof", '"{name}"').format(name=(const or "").strip('"'))

        if kind == "DelegateCreation" and kids:
            inner = kids[0]
            if self.kind_of(inner) == "AnonymousFunction":
                det = (self.con.execute(
                    "SELECT detail FROM operation WHERE id=?", (inner,)
                ).fetchone() or [None])[0]
                names = []
                if det:
                    try:
                        names = json.loads(det).get("params", "").split()
                    except json.JSONDecodeError:
                        names = []
                body = []
                for cid, ck, _s, _c, _t in self.children(inner):
                    body.extend(self.emit_block(cid, 0) if ck == "Block"
                                else self.emit_stmt(cid, 0))
                txt = " ".join(l.strip() for l in body).rstrip(";")
                return self.language.get("delegates_expr", {}).get(
                    "closure", "|{params}| {body}").format(
                    params=", ".join(n if n != "_" else "_" for n in names),
                    body=txt)

        if kind == "ConditionalAccessInstance":
            # Inside a normalised `?.` guard this is the bound receiver.
            b = getattr(self, "_ca_binding", None)
            if b:
                return b

        if kind == "ConditionalAccess":
            gap = self.language.get("statements", {}).get("ConditionalAccess", {})
            self.gaps.append("conditional access `?.` needs nullability analysis")
            return gap.get("emit", "/* GAP: ?. */")

        if kind == "SimpleAssignment":
            # Assignment in expression position; C# yields the assigned value.
            return self.emit_assignment(oid).rstrip(";")

        if kind == "FieldReference" and symbol and self._enum_names:
            # `OversamplingMode.By16` is an enum MEMBER, not state. Without this
            # it fell through to the field rule and emitted `st.by16`.
            parts = symbol.split("(")[0].split(".")
            if len(parts) >= 2 and parts[-2] in self._enum_names:
                return self.project.get("enums", {}).get(
                    "reference", "{type}::{member}").format(
                    type=parts[-2], member=parts[-1])

        if kind in ("PropertyReference", "FieldReference") and symbol:
            return self.emit_reference(kind, symbol, kids)

        if kind == "ArrayElementReference" and len(kids) >= 2:
            tmpl = self.language.get("references", {}).get(
                "ArrayElementReference", {}).get("emit", "{array}[{index} as usize]")
            return tmpl.format(array=self.emit_expr(kids[0]),
                               index=self.emit_expr(kids[1]))

        if kind == "Conversion" and kids:
            inner = self.emit_expr(kids[0])
            # Only NUMERIC conversions need spelling in Rust; see language rule.
            try:
                num = json.loads(detail or "{}").get("numeric", False)
            except json.JSONDecodeError:
                num = False
            # An explicit cast to a generated enum needs from_u64: Rust has no
            # numeric-to-enum cast. See enums.from_u64.
            if (rtype or "").split(".")[-1] in self._enum_names:
                return f"{(rtype or '').split('.')[-1]}::from_u64({inner})"
            tgt = self.rust_type(rtype or "") if num else None
            if num and tgt:
                return self.language.get("conversions", {}).get(
                    "numeric", "{expr} as {target}").format(expr=inner, target=tgt)
            return inner

        if kind == "Conditional" and len(kids) >= 3:
            # `c ? a : b`. Rust's if-else IS an expression, so this needs no
            # temporary -- the same rule the statement form uses.
            tmpl = self.language.get("statements", {}).get("Conditional", {}).get(
                "ternary", "if {cond} {{ {then} }} else {{ {else} }}")
            return tmpl.replace("{else}", "{alt}").format(
                cond=self.emit_expr(kids[0]), then=self.emit_expr(kids[1]),
                alt=self.emit_expr(kids[2]))

        if kind in ("Increment", "Decrement"):
            self.gaps.append(
                f"{kind.lower()} in expression position: prefix/postfix "
                f"difference is observable there (see language rule `increment`)")
            return f"/* GAP: {kind} in expression position */"

        if kind == "Interpolation" and kids:
            # The hole node wraps the expression; the format placeholder was
            # already emitted by InterpolatedString.
            return self.emit_expr(kids[0])

        if kind in ("Parenthesized", "Argument"):
            # Transparent: neither is written in Rust.
            return self.emit_expr(kids[0]) if kids else "/* empty */"
        if kind == "InstanceReference":
            return "self"
        if kind == "ObjectCreation" and symbol:
            ty = symbol.split("(")[0].split(".")[-1]
            return f"{ty}::new({', '.join(self.emit_expr(a) for a in args)})"
        if kind == "ParameterReference" and symbol:
            # A WithEnumFields callback slot is declared u64 in Rust but typed
            # as the enum in C#; convert where it is used. Only for lambda
            # slots -- see enums.typed_callback_param.
            nm = snake(symbol.split()[-1])
            ety = (rtype or "").split(".")[-1]
            if nm in self._enum_slots and ety in self._enum_names:
                return self.project.get("enums", {}).get(
                    "typed_callback_param", {}).get(
                    "emit", "{type}::from_u64({name})").format(type=ety, name=nm)
            # The symbol is "byte value" -- type then name. Splitting on "."
            # returned the whole thing and emitted `enqueue(byte value)`.
            return snake(symbol.split()[-1])
        if kind == "LocalReference":
            if detail:
                try:
                    return snake(json.loads(detail).get("local", "local"))
                except json.JSONDecodeError:
                    pass
            if symbol:
                return snake(symbol.split(".")[-1])

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

    def literal(self, const: str | None, rtype: str | None = None) -> str:
        """A literal, rendered for Rust.

        The TYPE matters: a string literal emitted bare produced
        `self.log(..., Received a character, ...)` -- unquoted prose spliced into
        an argument list, which is both wrong and syntactically invalid."""
        if const is None:
            return "0"
        if const in ("True", "False"):
            return const.lower()
        if rtype == "string":
            escaped = const.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
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

