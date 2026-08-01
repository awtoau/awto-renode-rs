#!/usr/bin/env python3
"""Emit Rust from the corpus. Issue #35 — the missing half of the rule engine.

Until now `rules.py` could propose a rule and find every occurrence, but not
turn one into code: `rule.emitter` was the string "TODO", and every translated
method was a hand-written patch. This closes that loop for the register DSL,
which is the population the whole thesis rests on.

## How a rule emits

A matched call is an `Invocation` whose children are `Argument` nodes. The
corpus already holds each callee's parameter list, so arguments bind to
parameter NAMES rather than positions — which is what disambiguates the twenty
`With*` overloads from each other.

An emitter is therefore a small function per combinator, reading named bindings:

    WithFlag(position: 7, mode: Read, name: "TXE", valueProviderCallback: <fn>)
      ->  .with_tagged_flag(7)          // provider present, no `out` field

## What this deliberately does not do

It emits the DECLARATIVE half only — register layout. Callback bodies are
arbitrary C# and become dispatch arms or `fn` items, which is a separate rule
family. Emitting a plausible-looking body would be worse than emitting nothing,
because the oracle would then be checking generated guesswork.

Run:  python3 scripts/emit.py --type STM32_UART --method DefineRegisters
Log:  ./tmp/logs/emit.log
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# FieldMode enum values as the C# defines them, for rendering.
FIELD_MODE = {
    1: "FieldMode::READ",
    2: "FieldMode::WRITE",
    4: "FieldMode::SET",
    8: "FieldMode::TOGGLE",
    16: "FieldMode::WRITE_ONE_TO_CLEAR",
    32: "FieldMode::WRITE_ZERO_TO_CLEAR",
}


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())




def load_rules(rules_dir: Path) -> list[dict]:
    """Load every rule file. The converter's knowledge lives HERE, as data.

    An emitter with combinator names hardcoded in its source is a converter with
    the corpus baked in -- the same failure as hand-writing the output, one level
    up. Rules are data so that supporting a new construct is an edit to
    rulesdb/rules/, reviewable on its own and applicable to any corpus."""
    rules: list[dict] = []
    if not rules_dir.exists():
        return rules
    for f in sorted(rules_dir.glob("*.json")):
        doc = json.loads(f.read_text())
        for r in doc.get("rules", []):
            r.setdefault("family", doc.get("family", ""))
            rules.append(r)
    return rules


def load_language(rules_dir: Path) -> dict:
    """Generic C#-to-Rust mappings. LANGUAGE layer, no project knowledge.

    Kept apart from project rules deliberately: a bug in an operator mapping is
    a transpiler bug that affects every corpus, and it must be fixable without
    reading anything about Renode."""
    f = rules_dir / "csharp_core.json"
    return json.loads(f.read_text()) if f.exists() else {}


def load_expressions(rules_dir: Path) -> list[dict]:
    """Project-specific expression idioms."""
    out: list[dict] = []
    if not rules_dir.exists():
        return out
    for f in sorted(rules_dir.glob("*.json")):
        out.extend(json.loads(f.read_text()).get("expressions", []))
    return out


def load_assignments(rules_dir: Path) -> list[dict]:
    """Project rules for assignment TARGETS.

    `field.Value = x` cannot use the generic `{target} = {value}` mapping: Rust
    has no assignable property and D2's field handles are indices, so it becomes
    a bank call. Assignment therefore needs a project rule even though
    assignment itself is a language construct."""
    out: list[dict] = []
    if not rules_dir.exists():
        return out
    for f in sorted(rules_dir.glob("*.json")):
        out.extend(json.loads(f.read_text()).get("assignments", []))
    return out


def load_register_forms(rules_dir: Path) -> list[dict]:
    """How to FIND a register, also data.

    Renode uses at least two idioms: the `Register.X.Define(this)` extension and
    a `Dictionary<long, DoubleWordRegister>` initialiser. Hardcoding the first
    made the converter silently emit zero registers for every peripheral using
    the second -- the same failure as hardcoding combinator names, one level
    down."""
    forms: list[dict] = []
    if not rules_dir.exists():
        return forms
    for f in sorted(rules_dir.glob("*.json")):
        forms.extend(json.loads(f.read_text()).get("register_forms", []))
    return forms


def to_const(name: str) -> str:
    """`Control1` -> `CONTROL1`, `BaudRate` -> `BAUD_RATE`."""
    return snake(name).upper()


def render_mode(const: str | None) -> str:
    """C# FieldMode is a [Flags] enum; render the combination."""
    if const is None:
        return "FieldMode::READ_WRITE"  # the C# default
    try:
        v = int(const)
    except ValueError:
        return "FieldMode::READ_WRITE"
    if v == 3:
        return "FieldMode::READ_WRITE"
    parts = [name for bit, name in sorted(FIELD_MODE.items()) if v & bit]
    return " | ".join(parts) if parts else "FieldMode::default()"


sys.path.insert(0, str(Path(__file__).resolve().parent))
from emitter.core import snake  # noqa: E402
from emitter.lang.statements import Statements  # noqa: E402
from emitter.plugins.renode_expressions import RenodeExpressions  # noqa: E402


class Emitter(RenodeExpressions, Statements):
    PROJECT_KEYS = ("state_struct", "peripheral_methods", "callback_naming",
                    "logging", "enums", "register_collection", "inheritance")

    def __init__(self, con: sqlite3.Connection, log: logging.Logger,
                 rules_dir: Path | None = None):
        self.con = con
        self.log = log
        self.unhandled: dict[str, int] = {}
        self.gaps: list[str] = []
        self.rules = load_rules(rules_dir or repo_root() / "rulesdb" / "rules")
        self._flag_fields: set[str] = set()
        self._callbacks: list[str] = []
        self._emitted_fns: set[str] = set()
        self._state_names: set[str] = set()
        self._current_type: str | None = None
        self._enum_names: set[str] = set()
        self._enum_slots: set[str] = set()
        self._current_reg: str | None = None
        rd = rules_dir or repo_root() / "rulesdb" / "rules"
        self.forms = load_register_forms(rd)
        self.assignments = load_assignments(rd)
        self.language = load_language(rd)
        self.callback_signatures = {}
        for f in sorted(rd.glob("*.json")):
            self.callback_signatures.update(
                {k: v for k, v in json.loads(f.read_text())
                 .get("callback_signatures", {}).items() if isinstance(v, dict)})
        self.expressions = load_expressions(rd)
        # Project rules, read by state_struct and peripheral_methods. Previously
        # read but never assigned: emit.py worked only where a caller happened
        # to set it by hand.
        self.project: dict = {}
        for f in sorted(rd.glob("*.json")):
            doc = json.loads(f.read_text())
            if doc.get("family") or doc.get("layer") != "language":
                for k in self.PROJECT_KEYS:
                    if k in doc:
                        self.project[k] = doc[k]

    def params(self, symbol: str) -> list[str]:
        """Parameter names of the callee, in order."""
        rows = self.con.execute("""
            SELECT p.name FROM parameter p
            JOIN member mb ON mb.id = p.method_id
            WHERE mb.key = ? ORDER BY p.ordinal""", (symbol,)).fetchall()
        return [r[0] for r in rows]

    def children(self, oid: int):
        return self.con.execute(
            "SELECT id, kind, symbol, const_value, type FROM operation "
            "WHERE parent_id=? ORDER BY ordinal", (oid,)).fetchall()

    def out_field(self, oid: int, symbol: str) -> str | None:
        """Name of the `out` parameter's target, e.g. `readFifoNotEmpty`.

        This is D2's central pattern: `out IFlagRegisterField f` hands the
        peripheral a handle into register storage. The corpus records which
        parameters are `out`, so the binding is exact rather than positional
        guesswork."""
        outs = self.con.execute("""
            SELECT p.ordinal FROM parameter p
            JOIN member mb ON mb.id = p.method_id
            WHERE mb.key = ? AND p.is_out = 1""", (symbol,)).fetchall()
        if not outs:
            return None
        ordinal = outs[0][0]
        args = [c for c in self.children(oid) if c[1] == "Argument"]
        if ordinal >= len(args):
            return None
        inner = self.children(args[ordinal][0])
        if not inner:
            return None
        sym = inner[0][2]
        # Symbol is a fully-qualified field reference; the leaf is the name.
        return snake(sym.split(".")[-1].split("(")[0]) if sym else None

    def bind(self, oid: int, symbol: str) -> dict[str, tuple]:
        """Map parameter name -> the argument's (kind, symbol, const) triple.

        Uses the argument's RECORDED BOUND PARAMETER, not its position. C# named
        arguments may skip earlier optionals -- `Define(this, name: "USART_DR")`
        omits resetValue -- and positional binding then reads the name as the
        reset value. Roslyn resolved this at compile time; the ingest records it.
        """
        out: dict[str, tuple] = {}
        fallback = self.params(symbol)
        for i, (arg_id, kind, arg_sym, _c, _t) in enumerate(self.children(oid)):
            if kind != "Argument":
                continue
            inner = self.children(arg_id)
            if not inner:
                continue
            _iid, ikind, isym, iconst, _ityp = inner[0]
            # `arg_sym` is the parameter, e.g. "uint resetValue"; take its name.
            if arg_sym:
                pname = arg_sym.split()[-1]
            elif i < len(fallback):
                pname = fallback[i]
            else:
                continue
            out[pname] = (ikind, isym, iconst)
        return out

    def combinator(self, symbol: str) -> str | None:
        """Bare combinator name, e.g. `WithFlag`, from a full symbol."""
        if "PeripheralRegisterExtensions." not in symbol:
            return None
        after = symbol.split("PeripheralRegisterExtensions.", 1)[1]
        return after.split("<")[0].split("(")[0]

    def emit_call(self, oid: int, symbol: str) -> str | None:
        """Apply the first matching RULE. This method knows nothing about any
        individual combinator -- adding support for a new one is a data change
        to rulesdb/rules/, never a code change here."""
        name = self.combinator(symbol)
        if name is None:
            return None
        b = self.bind(oid, symbol)

        def const(param: str):
            v = b.get(param)
            return v[2] if v else None

        def present(param: str) -> bool:
            v = b.get(param)
            return v is not None and v[0] != "DefaultValue"

        env = {
            "pos": const("position"),
            "width": const("width"),
            "count": const("count"),
            "mode": render_mode(const("mode")),
            "field": self.out_field(oid, symbol),
        }
        flags = {
            "field": env["field"] is not None,
            "provider": present("valueProviderCallback"),
            "writer": present("writeCallback"),
        }
        # A computed field's callbacks become free fns emitted beside the
        # layout. Named from register + bit position so the name is content-
        # derived and never depends on emission order.
        naming = self.project.get("callback_naming", {}).get(
            "template", "{reg}_{pos}_{kind}")
        for param, kind, key in (("valueProviderCallback", "provider", "provider_fn"),
                                 ("writeCallback", "writer", "writer_fn")):
            env[key] = "None"
            if not flags[kind]:
                continue
            lam = self.find_lambda(oid, param)
            if lam is None:
                continue
            fname = naming.format(reg=snake(self._current_reg or "reg"),
                                  pos=env["pos"], kind=kind)
            body = self.emit_lambda(lam, fname, param)
            if not body:
                continue
            # Does the body call a peer method we cannot emit yet? If so the
            # file would not compile, and a stub would look finished. Withhold
            # the callback and name the gap instead.
            text = "\n".join(body)
            missing = sorted({
                m for m in re.findall(r"\b([a-z_][a-z0-9_]*)\(bank, st", text)
                if m not in self._emitted_fns})
            missing += sorted({
                f"st.{m}" for m in re.findall(r"\bst\.([a-z_][a-z0-9_]*)", text)
                if m != "f" and m not in self._state_names})
            if missing:
                self.gaps.append(
                    "callback for bit {} needs peer method(s) not yet emitted: {}"
                    .format(env["pos"], ", ".join(missing)))
                continue
            self._callbacks.append("\n".join(body))
            env[key] = f"Some({fname})"

        for rule in self.rules:
            if name not in rule["matches"].split("|"):
                continue
            cond = rule.get("when")
            if cond and not any(flags.get(tok.strip(), False) for tok in cond.split(" or ")):
                continue
            if rule.get("gap"):
                self.gaps.append(f"{name}: {rule['gap']}")
            template = rule.get("emit")
            if template is None:
                return None
            try:
                return template.format(**env)
            except KeyError as missing:
                self.unhandled[f"{rule['name']}:missing {missing}"] = 1
                return None

        self.unhandled[name] = self.unhandled.get(name, 0) + 1
        return None

    def emit_expr(self, oid: int) -> str:
        """Recursively emit one expression.

        Generic structure (operators, literals) comes from the LANGUAGE rules;
        anything mentioning a register or a peripheral comes from the PROJECT
        rules. The split is enforced by where each table is loaded from, so a
        Renode idiom cannot leak into the language layer.
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

    def emit_lambda(self, oid: int, name: str, param: str) -> list[str]:
        """A C# lambda as a Rust free function.

        The closure captured `this`; the free fn takes what it captured as
        parameters instead, which is the same move the DSL makes for callbacks
        generally. The body is ordinary statements, so nothing here duplicates
        the statement rules."""
        sigs = self.callback_signatures.get(param)
        if not sigs:
            self.unhandled[f"lambda:{param}"] = 1
            return []
        lam = self.language.get("lambdas", {})
        # A computed flag returns bool; the value callback returns u64. Rust
        # will not widen implicitly, so the conversion is emitted.
        # Bind the C# lambda's OWN parameter names onto the trailing slots.
        # `(idx, val) => ...` must emit a body that references idx and val, so
        # the source's names win and unbound slots keep an underscore.
        det = (self.con.execute("SELECT detail FROM operation WHERE id=?", (oid,))
               .fetchone() or [None])[0]
        cs_params = []
        if det:
            try:
                raw = json.loads(det).get("params", "")
                cs_params = [x for x in raw.split() if x and x != "_"]
                n_declared = len(raw.split()) if raw else 0
            except json.JSONDecodeError:
                n_declared = 0
        else:
            n_declared = 0
        slots = [list(s) for s in sigs.get("slots", [])]
        if n_declared:
            tail = slots[-n_declared:] if n_declared <= len(slots) else slots
            raw_names = (json.loads(det).get("params", "").split()
                         if det else [])
            for slot, nm in zip(tail, raw_names[-len(tail):]):
                slot[0] = nm if nm != "_" else "_" + slot[0]
        prev_slots = self._enum_slots
        self._enum_slots = {n for n, _ in slots if not n.startswith("_")}
        used = self.lambda_uses(oid)
        for slot in slots:
            if not slot[0].startswith("_") and slot[0] not in used:
                slot[0] = "_" + slot[0]
        params = sigs["fixed"].format(state="State") + "".join(
            f", {n if n.startswith('_') else n}: {ty}" for n, ty in slots)
        prev = getattr(self, "_coerce_ret", None)
        self._coerce_ret = None
        if sigs["ret"] == "u64":
            rt = self.lambda_return_type(oid)
            if rt and "bool" in rt.lower():
                self._coerce_ret = "bool_to_u64"
            elif rt and rt.split(".")[-1] in self._enum_names:
                self._coerce_ret = "enum_to_u64"
        body: list[str] = []
        for cid, kind, _s, _c, _t in self.children(oid):
            if kind == "Block":
                body.extend(self.emit_block(cid, 1))
            else:
                body.extend(self.emit_stmt(cid, 1))
        self._coerce_ret = prev
        if not body:
            return []
        # Rewrite the captured `this`. In the C# the closure reaches the
        # peripheral through `this`; as a free fn it receives `bank` and `st`
        # instead, so references must be redirected to the parameters.
        self._enum_slots = prev_slots
        body = self.rewrite_this(body)
        text = lam.get("free_fn", "fn {name}({params}) -> {ret} {{\n{body}\n}}").format(
            name=name, params=params, ret=sigs["ret"], body="\n".join(body))
        return text.splitlines()

    def rewrite_this(self, body: list[str]) -> list[str]:
        """Redirect a captured `this` onto the (bank, st) parameters.

        Shared by lambdas and peripheral methods: both are free fns that
        received what the C# reached through `this`."""
        call = self.project.get("peripheral_methods", {}).get(
            "call", "{name}(bank, st{args})")
        rewritten: list[str] = []
        for line in body:
            line = line.replace("self.bank.", "bank.").replace("self.f.", "st.f.")
            # A peer-method call: the peripheral's own methods are free fns
            # over (bank, st) too, so the receiver becomes those parameters.
            # Scan for balanced parentheses: a nested call in the arguments
            # (`self.foo(bar(x))`) defeated a flat [^()]* match, and the call
            # was then left as `self.` and mangled into `st.` by the next rule.
            out_chars, i = [], 0
            while i < len(line):
                m = re.match(r"self\.([a-z_][a-z0-9_]*)\(", line[i:])
                if not m:
                    out_chars.append(line[i])
                    i += 1
                    continue
                j = i + m.end()
                depth, start = 1, j
                while j < len(line) and depth:
                    depth += (line[j] == "(") - (line[j] == ")")
                    j += 1
                inner = line[start:j - 1].strip()
                out_chars.append(call.format(
                    name=m.group(1), args=(", " + inner) if inner else ""))
                i = j
            line = "".join(out_chars)
            line = line.replace("self.", "st.")
            rewritten.append(line)
        return rewritten

    def lambda_uses(self, oid: int) -> set[str]:
        """Parameter names actually referenced in this lambda's body, so unused
        slots can carry an underscore instead of a rustc warning."""
        out: set[str] = set()
        stack = [oid]
        while stack:
            cur = stack.pop()
            for cid, kind, sym in self.con.execute(
                    "SELECT id, kind, symbol FROM operation WHERE parent_id=?", (cur,)):
                if kind == "ParameterReference" and sym:
                    out.add(sym.split()[-1])
                stack.append(cid)
        return out

    def lambda_return_type(self, oid: int) -> str | None:
        """The C# type this lambda yields, from the corpus's recorded operation
        types rather than inferred from emitted text."""
        for sql in (
            "SELECT o.type FROM operation o WHERE o.kind='Return' "
            "AND o.parent_id IN (SELECT id FROM operation WHERE parent_id=?)",
            "SELECT c.type FROM operation r JOIN operation c ON c.parent_id=r.id "
            "WHERE r.kind='Return' AND r.parent_id IN "
            "(SELECT id FROM operation WHERE parent_id=?)",
        ):
            for (ty,) in self.con.execute(sql, (oid,)).fetchall():
                if ty:
                    return ty
        return None

    def returns_bool(self, oid: int) -> bool:
        """Does this lambda's body yield a bool? Read from the corpus's recorded
        operation types rather than inferred from the emitted text."""
        rows = self.con.execute(
            "SELECT o.type FROM operation o WHERE o.kind='Return' "
            "AND o.parent_id IN (SELECT id FROM operation WHERE parent_id=?)",
            (oid,)).fetchall()
        for (ty,) in rows:
            if ty and "bool" in ty.lower():
                return True
        # The Return node may carry no type; consult its value child.
        rows = self.con.execute(
            "SELECT c.type FROM operation r JOIN operation c ON c.parent_id=r.id "
            "WHERE r.kind='Return' AND r.parent_id IN "
            "(SELECT id FROM operation WHERE parent_id=?)", (oid,)).fetchall()
        return any(ty and "bool" in ty.lower() for (ty,) in rows)

    def find_lambda(self, oid: int, param: str) -> int | None:
        """The AnonymousFunction passed as a given named parameter."""
        for aid, kind, sym, _c, _t in self.children(oid):
            if kind != "Argument" or not sym or sym.split()[-1] != param:
                continue
            node = aid
            for _ in range(3):
                kids = self.children(node)
                if not kids:
                    return None
                cid, ckind, _s2, _c2, _t2 = kids[0]
                if ckind == "AnonymousFunction":
                    return cid
                node = cid
        return None

    def emit_assignment(self, oid: int) -> str:
        """`x = y`, with project rules for register-field targets."""
        kids = self.children(oid)
        if len(kids) < 2:
            return "/* malformed assignment */"
        target_id, value_id = kids[0][0], kids[1][0]
        trow = self.con.execute(
            "SELECT kind, symbol, type FROM operation WHERE id=?", (target_id,)).fetchone()
        tkind, tsym, ttype = trow if trow else (None, None, None)
        value = self.emit_expr(value_id)

        for rule in self.assignments:
            if rule["target_kind"] != tkind:
                continue
            if rule.get("target_symbol_contains") and (
                    not tsym or rule["target_symbol_contains"] not in tsym):
                continue
            if rule.get("target_type_is") and ttype != rule["target_type_is"]:
                continue
            return rule["emit"].format(
                field=self.receiver_field(target_id) or "UNKNOWN", value=value)

        tmpl = self.language.get("statements", {}).get(
            "SimpleAssignment", {}).get("default", "{target} = {value};")
        return tmpl.format(target=self.emit_expr(target_id), value=value)

    def emit_body(self, type_name: str, method_name: str) -> list[str]:
        """Emit a method body, statement by statement."""
        row = self.con.execute("""
            SELECT m.member_id FROM method m
            JOIN member mb ON mb.id = m.member_id
            JOIN type t ON t.id = mb.type_id
            WHERE t.name = ? AND mb.name = ?""", (type_name, method_name)).fetchone()
        if not row:
            return []
        block = self.con.execute(
            "SELECT id FROM operation WHERE method_id=? AND kind='Block' "
            "ORDER BY id LIMIT 1", (row[0],)).fetchone()
        if not block:
            return []
        out: list[str] = []
        for sid, _kind, _s, _c, _t in self.children(block[0]):
            out.extend(self.emit_stmt(sid))
        return out

    def enum_offset(self, oid: int) -> tuple[str | None, int | None]:
        """Register offset from a `Define` call's first argument.

        `Register.Status.Define(...)` passes the enum member, and Roslyn records
        an enum member reference as a CONSTANT -- so the numeric offset and its
        name are both recoverable without evaluating anything."""
        args = [c for c in self.children(oid) if c[1] == "Argument"]
        if not args:
            return None, None
        # Argument -> Conversion -> FieldReference(const = the enum value)
        node = args[0][0]
        for _ in range(3):
            kids = self.children(node)
            if not kids:
                break
            cid, kind, sym, const, _typ = kids[0]
            if kind == "FieldReference" and const is not None:
                return (sym.split(".")[-1] if sym else None), int(const)
            node = cid
        return None, None

    def find_registers(self, method_id: int) -> list[tuple[str | None, int, str, int]]:
        """(name, offset, reset, chain span start) per register, via the forms."""
        found: list[tuple[str | None, int, str, int]] = []
        for oid, symbol, span in self.con.execute(
                "SELECT id, symbol, span_start FROM operation WHERE method_id=? "
                "AND kind='Invocation' AND symbol IS NOT NULL ORDER BY span_start",
                (method_id,)):
            for form in self.forms:
                if form["symbol_contains"] not in symbol:
                    continue
                b = self.bind(oid, symbol)
                if form["offset_from"] == "$first_argument_enum":
                    name, offset = self.enum_offset(oid)
                else:
                    name, offset = self.arg_enum(oid, form["offset_from"])
                if offset is None:
                    break
                reset = "0"
                if form.get("reset_from"):
                    v = b.get(form["reset_from"])
                    if v and v[2] is not None:
                        reset = v[2]
                if form["chain_from"] == "$self":
                    chain_span = span
                else:
                    chain_span = self.arg_span(oid, form["chain_from"])
                    if chain_span is None:
                        break
                found.append((name, offset, reset, chain_span))
                break
        return found

    def arg_enum(self, oid: int, param: str) -> tuple[str | None, int | None]:
        """Enum member passed as a NAMED parameter, e.g. the dictionary key."""
        for aid, kind, sym, _c, _t in self.children(oid):
            if kind != "Argument" or not sym or sym.split()[-1] != param:
                continue
            node = aid
            for _ in range(4):
                kids = self.children(node)
                if not kids:
                    break
                cid, ckind, csym, cconst, _ct = kids[0]
                if ckind == "FieldReference" and cconst is not None:
                    return (csym.split(".")[-1] if csym else None), int(cconst)
                node = cid
        return None, None

    def arg_span(self, oid: int, param: str) -> int | None:
        """Span start of a named argument's expression -- the chain root."""
        for aid, kind, sym, _c, _t in self.children(oid):
            if kind != "Argument" or not sym or sym.split()[-1] != param:
                continue
            kids = self.con.execute(
                "SELECT span_start FROM operation WHERE parent_id=? ORDER BY ordinal LIMIT 1",
                (aid,)).fetchone()
            return kids[0] if kids else None
        return None

    def emit_registers(self, type_name: str, method_name: str) -> tuple[list[str], list[str], list[str]]:
        """Emit a whole register-layout function.

        Registers are located by the FORMS in rulesdb/rules/; combinator calls
        are associated with one by SPAN START, since every call in a fluent chain
        shares the start of the chain's root expression."""
        row = self.con.execute("""
            SELECT m.member_id FROM method m
            JOIN member mb ON mb.id = m.member_id
            JOIN type t ON t.id = mb.type_id
            WHERE t.name = ? AND mb.name = ?""", (type_name, method_name)).fetchone()
        if not row:
            return [], [], [f"{type_name}.{method_name} not in the corpus"]
        method_id, = row

        self._state_names = {n for n, _ in self.state_fields(type_name)[0]}
        self._current_type = type_name
        chains: dict[int, list[tuple[int, int, str]]] = {}
        for oid, symbol, start, end in self.con.execute(
                "SELECT id, symbol, span_start, span_start + span_len FROM operation "
                "WHERE method_id=? AND kind='Invocation' AND symbol IS NOT NULL",
                (method_id,)):
            chains.setdefault(start, []).append((end, oid, symbol))

        stmts: list[str] = []
        fields: list[str] = []
        gaps: list[str] = []

        for name, offset, reset, chain_span in sorted(
                self.find_registers(method_id), key=lambda r: r[1]):
            body: list[str] = []
            self.gaps = []
            self._current_reg = name or f"reg_{offset:x}"
            for _end, oid, symbol in sorted(chains.get(chain_span, [])):
                if self.combinator(symbol) is None:
                    continue
                line = self.emit_call(oid, symbol)
                gaps.extend(f"{name}: {g}" for g in self.gaps)
                self.gaps = []
                if line is None:
                    continue
                f = self.out_field(oid, symbol)
                if f and f not in fields:
                    fields.append(f)
                    if self.combinator(symbol) == "WithFlag":
                        self._flag_fields.add(f)
                body.append(line)
            if not body:
                continue
            const_name = to_const(name or f"REG_{offset:X}")
            stmts.append(f"    bank.define(reg::{const_name}, {reset})")
            stmts.extend(f"        {l}" for l in body)
            stmts.append("        .done();")
            stmts.append("")
        return stmts, fields, gaps

    def emit_file(self, type_name: str, method_name: str, module: str) -> str:
        """A complete, compilable Rust module: offsets, field handles, layout.

        Only the DECLARATIVE half. Behaviour stays in a hand-written sibling that
        `use`s this, so the boundary between generated and hand-written is a file
        boundary rather than a convention -- which is what lets check_generated.py
        enforce it byte-for-byte.
        """
        self._enum_names = self.enum_names(type_name)
        state, state_gaps = self.state_fields(type_name)
        self._callbacks = []
        # Peripheral methods first: a callback may call one, and the converter
        # only emits a callback whose dependencies exist.
        methods: list[str] = []
        self._emitted_fns = set()
        self._state_names = {n for n, _ in state}
        self._current_type = type_name
        self._enum_names = self.enum_names(type_name)
        self.gaps = []
        method_gaps: list[str] = []
        names = [r[0] for r in self.con.execute(
            "SELECT mb.name FROM member mb JOIN method m ON m.member_id=mb.id "
            "JOIN type t ON t.id=mb.type_id WHERE t.name=? AND mb.kind='method' "
            "AND m.has_body=1 AND mb.name<>? ORDER BY mb.name",
            (type_name, method_name))]
        emitted: dict[str, str] = {}
        # Base-class methods, flattened. A name the derived type also defines is
        # qualified by its declaring type, so `base.Reset()` has something
        # unambiguous to call. See inheritance.qualified_call.
        derived = set(names)
        inh = self.project.get("inheritance", {})
        for base in self.base_chain(type_name):
            for (bn,) in self.con.execute(
                    "SELECT mb.name FROM member mb JOIN method m ON m.member_id=mb.id "
                    "JOIN type t ON t.id=mb.type_id WHERE t.name=? AND mb.kind='method' "
                    "AND m.has_body=1 ORDER BY mb.name", (base,)):
                self.gaps = []
                lines = self.emit_peripheral_method(base, bn)
                method_gaps.extend(self.gaps)
                if not lines:
                    continue
                key = self.fn_name(bn)
                if bn in derived:
                    key = inh.get("qualified_call", "{base}_{name}").format(
                        base=snake(base), name=self.fn_name(bn))
                    lines[0] = lines[0].replace(
                        f"fn {self.fn_name(bn)}(", f"fn {key}(", 1)
                emitted[key] = "\n".join(lines)
        # Visible to the derived methods as they emit, so a base call can
        # resolve; the fixpoint below still prunes anything left dangling.
        self._emitted_fns = set(emitted)
        self._current_type = type_name
        for nm in names:
            self.gaps = []
            lines = self.emit_peripheral_method(type_name, nm)
            method_gaps.extend(self.gaps)
            if lines:
                emitted[self.fn_name(nm)] = "\n".join(lines)
        # A method may call another that was withheld. Drop until stable, so
        # the file never references a function it does not contain.
        while True:
            drop = {n for n, src in emitted.items()
                    for c in re.findall(r"\b([a-z_][a-z0-9_]*)\(bank, st", src)
                    if c not in emitted and c != n}
            if not drop:
                break
            for n in sorted(drop):
                pass
            casualties = {n for n, src in emitted.items()
                          if any(c not in emitted and c != n for c in
                                 re.findall(r"\b([a-z_][a-z0-9_]*)\(bank, st", src))}
            for n in sorted(casualties):
                missing = sorted({c for c in re.findall(
                    r"\b([a-z_][a-z0-9_]*)\(bank, st", emitted[n])
                    if c not in emitted and c != n})
                method_gaps.append(
                    f"{n}: withheld, calls withheld method(s): {', '.join(missing)}")
                del emitted[n]
        methods = [emitted[k] for k in sorted(emitted)]
        self._emitted_fns = set(emitted)
        self.gaps = []
        stmts, fields, gaps = self.emit_registers(type_name, method_name)
        gaps.extend(method_gaps)
        gaps.extend(state_gaps)
        offsets = self.register_offsets(type_name, method_name)


        L: list[str] = []
        a = L.append
        a(f"//! Register layout for `{type_name}`, GENERATED from the corpus.")
        a("//!")
        a("//! Do not edit: `scripts/check_generated.py` fails the commit if this")
        a("//! file differs from converter output. To change it, change the rules")
        a(f"//! in `rulesdb/rules/` or the C# it is derived from.")
        a("//!")
        a(f"//! Source: {type_name}.{method_name}")
        if gaps:
            a("//!")
            a("//! GAPS the converter reports rather than guessing:")
            for g in sorted(set(gaps)):
                a(f"//!   - {g}")
        a("")
        a("use renode_regs::{Bank, FieldMode, FlagId, ValueId};")
        if any("VecDeque" in ty for _, ty in state):
            a("use std::collections::VecDeque;")
        a("")
        a("/// Register offsets, from the C# `enum Register`.")
        a("pub mod reg {")
        for name, off in offsets:
            a(f"    pub const {to_const(name)}: u64 = 0x{off:02X};")
        a("}")
        a("")
        a("/// Field handles bound by `out` parameters in the C#.")
        a("#[derive(Default)]")
        a("pub struct Fields {")
        for f in fields:
            a(f"    pub {f}: {self.field_type(f)},")
        a("}")
        a("")
        # The offset enum is already `mod reg`; identified by content.
        off_names = {n for n, _ in offsets}
        enums = [(n, m) for n, m in self.nested_enums(type_name)
                 if not (off_names and {x for x, _ in m} >= off_names)]
        for ename, members in enums:
            spec = self.project.get("enums", {})
            a(f"/// C# `enum {ename}`, discriminants as declared.")
            a(spec.get("decl", "pub enum {name} {{").format(name=ename))
            for i, (mname, val) in enumerate(members):
                a(spec.get("member", "    {default}{name} = {value},").format(
                    default=spec.get("default_marker", "#[default] ") if i == 0 else "",
                    name=mname, value=val))
            a("}")
            a("")
            conv = spec.get("from_u64", {})
            if conv.get("impl"):
                arms = "\n".join(conv.get("arm", "            {value} => Self::{member},")
                                  .format(value=v, member=m) for m, v in members)
                a(conv["impl"].format(name=ename, arms=arms))
                a("")
        a("/// The peripheral's own state: every C# instance member that actually")
        a("/// stores something. Computed properties are excluded -- they hold")
        a("/// nothing, so a field here would invent storage the C# lacks.")
        a("#[derive(Default)]")
        a("pub struct State {")
        a("    /// Register field handles, bound by the C# `out` parameters.")
        a("    pub f: Fields,")
        for n, ty in state:
            a(f"    pub {n}: {ty},")
        a("}")
        a("")
        if methods:
            a("// The peripheral's own methods. C# reaches its state through")
            a("// `this`; these receive it as (bank, st) instead, so a callback")
            a("// can call them -- a closure cannot borrow what it lives inside.")
            for m in methods:
                a(m)
                a("")
        if self._callbacks:
            a("// Callbacks for computed fields. C# writes these as lambdas capturing")
            a("// `this`; a closure cannot live inside the object it borrows, so each")
            a("// becomes a free fn over (bank, state). See rulesdb/rules/.")
            for cb in self._callbacks:
                a(cb)
                a("")
        a("/// C# `DefineRegisters()`, field for field.")
        a("pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {")
        for line in stmts:
            a(line.rstrip())
        a("}")
        return "\n".join(L).rstrip() + "\n"

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
        # A nested enum this peripheral declares is a real Rust type.
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

    def base_chain(self, type_name: str) -> list[str]:
        """Base types of this peripheral, nearest first, that are IN the corpus.

        A base outside the cut cannot be flattened; callers report that rather
        than silently translating a peripheral with half its state missing."""
        out: list[str] = []
        row = self.con.execute(
            "SELECT id, base_type_id, base_extern FROM type WHERE name=?",
            (type_name,)).fetchone()
        seen = set()
        while row and row[1] and row[1] not in seen:
            seen.add(row[1])
            nxt = self.con.execute(
                "SELECT name, id, base_type_id, base_extern FROM type WHERE id=?",
                (row[1],)).fetchone()
            if not nxt:
                break
            out.append(nxt[0])
            row = (nxt[1], nxt[2], nxt[3])
        return out

    def external_base(self, type_name: str) -> str | None:
        row = self.con.execute(
            "SELECT base_extern FROM type WHERE name=?", (type_name,)).fetchone()
        return row[0] if row and row[0] else None

    def nested_enums(self, type_name: str) -> list[tuple[str, list[tuple[str, str]]]]:
        """Enums declared inside the peripheral, with their C# discriminants."""
        out = []
        # Keyed on the type's ID, never its name: the corpus holds many types
        # called `Registers` and two called `Mode`, and matching by name merged
        # all of them into one enum with duplicate discriminants.
        for tid, ename in self.con.execute(
                "SELECT t.id, t.name FROM type t WHERE t.kind='enum' "
                "AND t.key LIKE ? ORDER BY t.name", (f"%.{type_name}.%",)):
            members = self.con.execute(
                "SELECT mb.name, mb.const_value FROM member mb "
                "WHERE mb.type_id=? AND mb.const_value IS NOT NULL "
                "ORDER BY CAST(mb.const_value AS INTEGER), mb.name", (tid,)).fetchall()
            if members:
                out.append((ename, members))
        return out

    def enum_names(self, type_name: str) -> set[str]:
        return {n for n, _ in self.nested_enums(type_name)}

    def state_fields(self, type_name: str) -> tuple[list[tuple[str, str]], list[str]]:
        """The peripheral's State, from its non-handle instance fields."""
        spec = self.project.get("state_struct", {})
        handles = spec.get("handle_types", [])
        _ = spec.get("requires_storage")  # documented in the rule; applied in SQL
        out: list[tuple[str, str]] = []
        gaps: list[str] = []
        kinds = spec.get("also_state", {}).get("kinds", ["field"])
        qmarks = ",".join("?" for _ in kinds)
        for n, dt in self.con.execute(
                f"SELECT mb.name, mb.declared_type FROM member mb "
                f"JOIN type t ON t.id=mb.type_id WHERE t.name IN "
                f"({','.join('?' for _ in [type_name] + self.base_chain(type_name))}) "
                f"AND mb.kind IN ({qmarks}) "
                f"AND mb.is_static=0 AND mb.has_storage=1 "
                f"ORDER BY mb.name",
                (*([type_name] + self.base_chain(type_name)), *kinds)):
            if any(h in (dt or "") for h in handles):
                continue          # a register handle: already in `Fields`
            if (dt or "").strip() in spec.get("elided", {}).get("types", []):
                continue          # the Bank already is this -- see elided.note
            rt = spec.get("type_map", {}).get((dt or "").strip()) \
                or self.rust_type(dt or "")
            if rt is None:
                gaps.append(f"state field `{n}`: no Rust mapping for `{dt}`")
                continue
            out.append((snake(n), rt))
        return out, gaps

    def field_type(self, name: str) -> str:
        """Flag or value handle, decided by how the field is used."""
        return "FlagId" if name in self._flag_fields else "ValueId"

    def register_offsets(self, type_name: str, method_name: str) -> list[tuple[str, int]]:
        """Offsets via the same discovery path as the layout.

        This previously had its OWN `.Define(` search, so when register discovery
        became rule-driven the layout found six registers and the offset module
        found none -- generating code that referenced constants it had not
        emitted. One discovery path, used by both."""
        row = self.con.execute("""
            SELECT m.member_id FROM method m
            JOIN member mb ON mb.id = m.member_id
            JOIN type t ON t.id = mb.type_id
            WHERE t.name = ? AND mb.name = ?""", (type_name, method_name)).fetchone()
        if not row:
            return []
        seen = {name: off for name, off, _r, _s in self.find_registers(row[0]) if name}
        return sorted(seen.items(), key=lambda kv: kv[1])

    def fn_name(self, method_name: str) -> str:
        """Emitted function name. Property accessors lose their get_/set_ prefix
        so they match the PropertyReference call sites."""
        for pre in (self.project.get("peripheral_methods", {})
                    .get("accessor_names", {}).get("strip_prefixes", [])):
            if method_name.startswith(pre):
                method_name = method_name[len(pre):]
                break
        return snake(method_name)

    def emit_peripheral_method(self, type_name: str, method_name: str) -> list[str]:
        """A whole C# method as a free fn over (bank, st).

        Distinct from emit_method, which walks a fluent register chain; this
        emits an ordinary body, so a callback can call it."""
        row = self.con.execute("""
            SELECT m.member_id, m.return_type FROM method m
            JOIN member mb ON mb.id = m.member_id
            JOIN type t ON t.id = mb.type_id
            WHERE t.name = ? AND mb.name = ? AND m.has_body = 1""",
            (type_name, method_name)).fetchone()
        if not row:
            return []
        method_id, ret_cs = row
        before = len(self.unhandled)
        seen_unhandled = set(self.unhandled)
        self._current_type = type_name
        spec = self.project.get("peripheral_methods", {})
        if (ret_cs or "void") == "void":
            ret = spec.get("void_ret", "()")
        else:
            ret = ((self.project.get("state_struct", {}).get("type_map", {})
                    .get((ret_cs or "").strip())) or self.rust_type(ret_cs or ""))
            if ret is None:
                # Falling back to () here fabricated a signature: `parity_bit`
                # returns a C# enum and emitted `-> ()`, silently dropping the
                # value every caller reads.
                self.gaps.append(
                    f"{method_name}: withheld, return type `{ret_cs}` has no "
                    f"Rust mapping")
                return []

        extra = ""
        for pname, ptype in self.con.execute(
                "SELECT name, type FROM parameter WHERE method_id=? ORDER BY ordinal",
                (method_id,)):
            rt = (self.project.get("state_struct", {}).get("type_map", {})
                  .get((ptype or "").strip()) or self.rust_type(ptype or ""))
            if rt is None:
                self.gaps.append(
                    f"{method_name}: parameter `{pname}` has no Rust mapping "
                    f"for `{ptype}`")
                return []
            extra += f", {snake(pname)}: {rt}"

        root = self.con.execute(
            "SELECT id FROM operation WHERE method_id=? AND parent_id IS NULL",
            (method_id,)).fetchone()
        if not root:
            return []
        body: list[str] = []
        for cid, kind, _s, _c, _t in self.children(root[0]):
            body.extend(self.emit_block(cid, 1) if kind == "Block"
                        else self.emit_stmt(cid, 1))
        if not body:
            return []
        # Any construct the converter could not emit leaves a marker; those do
        # not parse in expression position and a stub would look finished.
        if len(self.unhandled) > before:
            new = sorted(set(self.unhandled) - seen_unhandled)
            self.gaps.append(
                f"{method_name}: withheld, cannot emit {', '.join(new)}")
            return []
        marker = [l.strip() for l in body if "/* GAP" in l]
        if marker:
            self.gaps.append(
                f"{method_name}: withheld, body still contains a gap marker "
                f"({marker[0][:60]})")
            return []
        body = self.rewrite_this(body)
        unknown = sorted({m for m in re.findall(
            r"\bst\.([a-z_][a-z0-9_]*)", "\n".join(body))
            if m != "f" and m not in self._state_names})
        if unknown:
            self.gaps.append(
                f"{method_name}: withheld, reaches state this peripheral does "
                f"not have: {', '.join('st.' + u for u in unknown)}")
            return []
        decl = spec.get("decl",
                        "fn {name}(bank: &Bank<State>, st: &mut State{extra}) -> {ret}")
        return [decl.format(name=self.fn_name(method_name), extra=extra, ret=ret) + " {",
                *body, "}"]

    def emit_method(self, type_name: str, method_name: str) -> list[str]:
        row = self.con.execute("""
            SELECT m.member_id FROM method m
            JOIN member mb ON mb.id = m.member_id
            JOIN type t ON t.id = mb.type_id
            WHERE t.name = ? AND mb.name = ?""", (type_name, method_name)).fetchone()
        if not row:
            self.log.error("%s.%s not in the corpus", type_name, method_name)
            return []
        method_id, = row

        # Order by where each call ENDS, not where it starts. In a fluent chain
        # `a.X().Y().Z()` every call's span STARTS at `a` -- the receiver is part
        # of the expression -- so span_start is identical across the chain and
        # sorting by it leaves the emission reversed. The end position is what
        # distinguishes them, and it recovers source order exactly.
        out: list[str] = []
        for oid, symbol, _end in self.con.execute(
                "SELECT id, symbol, span_start + span_len AS e FROM operation "
                "WHERE method_id=? AND kind='Invocation' AND symbol IS NOT NULL "
                "ORDER BY e, id", (method_id,)):
            line = self.emit_call(oid, symbol)
            if line:
                out.append(line)
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--file", metavar="MODULE",
                    help="emit a complete Rust module to stdout")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("emit")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    fh = logging.FileHandler(logdir / "emit.log", mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt)
    log.addHandler(fh); log.addHandler(sh)

    con = sqlite3.connect(root / args.db)
    em = Emitter(con, log)
    if args.file:
        text = em.emit_file(args.type, args.method, args.file)
        con.close()
        sys.stdout.write(text)
        return 0
    lines = em.emit_method(args.type, args.method)
    con.close()

    log.info("// generated from %s.%s", args.type, args.method)
    for l in lines:
        log.info("    %s", l)
    log.info("")
    log.info("%d combinator call(s) emitted", len(lines))
    if em.unhandled:
        log.info("unhandled combinators: %s",
                 ", ".join(f"{k}x{v}" for k, v in sorted(em.unhandled.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
