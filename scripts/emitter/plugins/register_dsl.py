"""Renode's register DSL: how a register is FOUND, and how a bank is emitted.

CORPUS LAYER. Everything here knows what a register, a bank, an offset enum and
a fluent combinator chain are, so none of it is generic C#. It lived in
`scripts/emit.py` beside the driver, which meant the boundary between "knows
about Renode" and "orchestrates" was a convention rather than a file --
`scripts/check_layering.py` can only enforce the boundary where the boundary is
a directory.

What is here is the register DSL and nothing else:

  * FINDING a register -- the forms in `rulesdb/rules/` are data, but running
    them, reading an offset out of an enum member and splitting a computed
    offset into `<const> + <expr>` is the mechanism they drive.
  * EMITTING a bank -- the layout function, its preamble, the offset module,
    and a replicated child block as a submodule.
  * The two helpers that only the DSL uses: the `out` parameter that binds a
    field handle, and the combinator name behind a fully-qualified symbol.

What is deliberately NOT here: `emit_file`, `emit_peripheral_method`,
`state_fields`, `rewrite_this` and `base_chain` stay in the driver. A driver
reads both layers by definition -- `emit_file` asks this module for a bank and
the language layer for a method body, and pretending it belonged to one of them
would put the seam in the wrong place.

Mixin, not free functions, because every method reaches `self.con`,
`self.project`, `self.forms` and `self.gaps`. `Emitter` inherits it.
"""

from __future__ import annotations

import re

from emitter.core import snake


def to_const(name: str) -> str:
    """`Control1` -> `CONTROL1`, `BaudRate` -> `BAUD_RATE`."""
    return snake(name).upper()


class RegisterDsl:
    """Mixin: finding registers, and emitting the bank they describe."""

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
        node, kind, sym = inner[0][0], inner[0][1], inner[0][2]
        if kind == "ArrayElementReference":
            # `out regularSequence[0]` -- the target is an ARRAY ELEMENT, not a
            # plain field. Unrecognised, this returned None, the combinator
            # rule fell through to the tag form, and the register STOPPED
            # STORING: every read came back 0 while the trace expected the
            # written value. Silent, and only a trace could see it.
            kids = self.children(node)
            if len(kids) >= 2:
                arr = kids[0][2]
                idx = self.emit_expr(kids[1][0])
                if arr:
                    base = snake(arr.split(".")[-1].split("(")[0])
                    return f"{base}[{idx}]"
        # Symbol is a fully-qualified field reference; the leaf is the name.
        return snake(sym.split(".")[-1].split("(")[0]) if sym else None

    def combinator(self, symbol: str) -> str | None:
        """Bare combinator name, e.g. `WithFlag`, from a full symbol."""
        if "PeripheralRegisterExtensions." not in symbol:
            return None
        after = symbol.split("PeripheralRegisterExtensions.", 1)[1]
        return after.split("<")[0].split("(")[0]

    def enum_offset(self, oid: int) -> tuple[str | None, int | None, str | None]:
        """Register offset from a `Define` call's first argument.

        `Register.Status.Define(...)` passes the enum member, and Roslyn records
        an enum member reference as a CONSTANT -- so the numeric offset and its
        name are both recoverable without evaluating anything.

        The offset need not BE a constant. `(Registers.StreamConfiguration +
        streamOffset).Define(parent)` is the same register map replicated per
        child instance, and reading only the constant form dropped all six of
        those registers silently -- the peripheral defined nothing at those
        addresses and every read came back 0. So the third element is the
        RUNTIME term, already emitted as Rust, or None for the constant case.
        The constant is still returned because it is what names the offset and
        orders the map."""
        args = [c for c in self.children(oid) if c[1] == "Argument"]
        if not args:
            return None, None, None
        # Argument -> Conversion -> FieldReference(const = the enum value)
        node = args[0][0]
        for _ in range(3):
            kids = self.children(node)
            if not kids:
                break
            cid, kind, sym, const, _typ = kids[0]
            if kind == "FieldReference" and const is not None:
                return (sym.split(".")[-1] if sym else None), int(const), None
            if kind == "Binary":
                base, term = self.split_offset(cid)
                if base is not None:
                    return base[0], base[1], term
                break
            node = cid
        return None, None, None

    def split_offset(self, oid: int) -> tuple[tuple[str | None, int] | None, str | None]:
        """`<enum const> + <expression>` -> ((name, const), rust for the rest).

        Only addition: an offset is a base plus a displacement, and any other
        operator is a shape this has not seen and must not guess at."""
        # The operator lives in `symbol`, not `type` -- `type` is the C# type of
        # the expression. Reading `type` here found nothing and the six stream
        # registers stayed missing with no gap reported.
        row = self.con.execute(
            "SELECT symbol FROM operation WHERE id=?", (oid,)).fetchone()
        if not row or row[0] != "Add":
            return None, None
        kids = self.children(oid)
        if len(kids) != 2:
            return None, None
        for i in (0, 1):
            cid, kind, sym, const, _typ = kids[i]
            if kind == "FieldReference" and const is not None:
                other = self.emit_expr(kids[1 - i][0])
                if other is None:
                    return None, None
                name = sym.split(".")[-1] if sym else None
                return (name, int(const)), other
        return None, None

    def find_registers(self, method_id: int) -> list[tuple[str | None, int, str, int, str | None]]:
        """(name, offset, reset, chain span start, runtime term) per register."""
        found: list[tuple[str | None, int, str, int, str | None]] = []
        for oid, symbol, span in self.con.execute(
                "SELECT id, symbol, span_start FROM operation WHERE method_id=? "
                "AND kind='Invocation' AND symbol IS NOT NULL ORDER BY span_start",
                (method_id,)):
            for form in self.forms:
                if form["symbol_contains"] not in symbol:
                    continue
                b = self.bind(oid, symbol)
                term: str | None = None
                if form["offset_from"] == "$first_argument_enum":
                    name, offset, term = self.enum_offset(oid)
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
                found.append((name, offset, reset, chain_span, term))
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

        found = self.find_registers(method_id)
        pre, pre_gaps = self.register_preamble(
            method_id, [r[4] for r in found if r[4]], {r[3] for r in found})
        stmts.extend(pre)
        gaps.extend(pre_gaps)

        for name, offset, reset, chain_span, term in sorted(
                found, key=lambda r: r[1]):
            body: list[str] = []
            self.gaps = []
            self._current_reg = name or f"reg_{offset:x}"
            skipped: list[str] = []
            for _end, oid, symbol in sorted(chains.get(chain_span, [])):
                if self.combinator(symbol) is None:
                    # NOT NECESSARILY IRRELEVANT. This skipped anything the
                    # combinator table did not name, silently, and the table
                    # names one extension class -- so `reg.DefineValueField(..)`
                    # (an INSTANCE method) and `.WithWriteCallback(..)` (a
                    # different extension class) both vanished here. One
                    # peripheral's entire register map was empty as a result and
                    # its file reported four gaps, none of them about registers.
                    #
                    # Only calls that look like part of THIS chain are worth
                    # reporting: the span carries the whole fluent expression, so
                    # unrelated nested calls appear too.
                    # The register FORM's own call is not a missing rule -- it is
                    # what located this register in the first place.
                    if any(f["symbol_contains"] in symbol for f in self.forms):
                        continue
                    leaf = symbol.split("(")[0].split(".")[-1]
                    if leaf.startswith(("With", "Define")) and leaf not in skipped:
                        skipped.append(leaf)
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
            if skipped:
                gaps.append(
                    f"{name or hex(offset)}: {len(skipped)} call(s) no rule "
                    f"matches: {', '.join(sorted(skipped))}"
                    + ("" if body else " -- the register has NO fields and is "
                       "not in the bank"))
            if not body:
                # A register the forms LOCATED and that emitted nothing. Dropping
                # it silently is indistinguishable from a rule declining, and it
                # is how a peripheral ends up with an empty `define_registers`
                # that looks finished.
                if not skipped:
                    gaps.append(
                        f"{name or hex(offset)}: located at 0x{offset:X} but no "
                        f"field emitted -- the register is NOT in the bank")
                continue
            const_name = to_const(name or f"REG_{offset:X}")
            where = f"reg::{const_name}"
            if term is not None:
                where = f"{where} + ({term}) as u64"
            stmts.append(f"    bank.define({where}, {reset})")
            stmts.extend(f"        {l}" for l in body)
            stmts.append("        .done();")
            stmts.append("")
        return stmts, fields, gaps

    def register_preamble(self, method_id: int, terms: list[str],
                          chain_spans: set[int]) -> tuple[list[str], list[str]]:
        """Locals a register offset expression depends on, and what was dropped.

        A register offset may name a local: `var streamOffset = id * StreamStep;`
        then `(Registers.StreamConfiguration + streamOffset).Define(parent)`.
        Emitting the offset term without its declaration names an undeclared
        variable, so the declaration comes with it -- but ONLY when a term
        actually references it. A layout method's other locals are the register
        map itself, which the Bank already is (see the `elided` rule), and
        emitting those would invent a second collection.

        The second return value is the reason this method exists at all.
        `emit_registers` walked the register forms and nothing else, so a
        statement that defines registers by any other route was DROPPED WITHOUT
        COMMENT -- STM32DMA's `for` loop extends four register builders held in
        locals, and all of it, including a stored `transferCompleteIrqStatus`
        flag, simply was not in the bank. Silent, and the same failure class the
        `must_explain` decorator was written for. A top-level statement whose
        subtree calls a combinator that was not emitted is reported."""
        root = self.con.execute(
            "SELECT id FROM operation WHERE method_id=? AND parent_id IS NULL",
            (method_id,)).fetchone()
        if not root:
            return [], []
        tops: list[tuple] = []
        for cid, kind, _s, _c, _t in self.children(root[0]):
            tops.extend(self.children(cid) if kind == "Block" else [
                (cid, kind, _s, _c, _t)])
        wanted = {w for t in terms for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", t)}
        out: list[str] = []
        gaps: list[str] = []
        for cid, kind, _s, _c, _t in tops:
            if kind == "VariableDeclarationGroup":
                names = {snake(n) for n in self.declared_in(cid)}
                if not (names & wanted):
                    continue
                lines = self.emit_stmt(cid, 1)
                if lines:
                    out.extend(lines)
                else:
                    gaps.append(f"layout: offset depends on local(s) "
                                f"{', '.join(sorted(names & wanted))}, which did "
                                f"not emit -- the offset is wrong")
                continue
            if self.emits_registers(cid, chain_spans):
                gaps.append(f"layout: top-level `{kind}` calls register "
                            f"combinators that were not emitted -- those fields "
                            f"are missing from the bank")
        if out:
            out.append("")
        return out, gaps

    def emit_sub_block(self, parent: str,
                       sub: dict) -> tuple[list[str], list[tuple[str, int]], list[str]]:
        """A replicated child register block as a submodule of the parent.

        A submodule and not a sibling file: the child defines into the PARENT's
        bank, so its `define_registers` is typed on the parent's `State` and the
        two cannot be separated. That is the C# relationship, not a packaging
        choice -- `Define(parent)` names it explicitly."""
        spec = self.project.get("sub_blocks", {})
        prev = (self._current_type, self._state_names)
        self._current_type = sub["child"]
        stmts, fields, gaps = self.emit_registers(sub["child"], sub["method"])
        offsets = self.register_offsets(sub["child"], sub["method"])
        state, state_gaps = self.state_fields(sub["child"])
        # The back-reference is dropped: the parent arrives as `bank`, so
        # keeping it would be a cycle Rust cannot express and that the C# only
        # needs because a nested class has no other route back.
        # Matched on the QUALIFIED name: the gap text carries the C# type as
        # Roslyn spells it, so a bare `STM32DMA` never matched and the dropped
        # back-reference was reported as an unmappable type.
        state = [(n, t) for n, t in state if t != parent]
        state_gaps = [g for g in state_gaps
                      if not g.rstrip("`").endswith(f".{parent}")]
        self._current_type, self._state_names = prev
        gaps = [f"{sub['module']}: {g}" for g in gaps + state_gaps]

        L = [f"/// C# nested `{sub['child']}`, {sub['count']} instances. Each one",
             "/// defines its registers into the PARENT's bank at a computed",
             "/// offset, so there is one flat register map and no dispatch.",
             spec.get("module", "pub mod {module} {{").format(**sub),
             "    use super::{Bank, FieldMode, FlagId, ValueId, reg};",
             "",
             spec.get("child_fields", "    pub struct Fields {{").format(**sub)]
        for f in fields:
            L.append(f"        pub {f}: {self.field_type(f)},")
        L.append("    }")
        L.append("")
        L.append(spec.get("child_state", "").format(**sub))
        L.append("    #[derive(Default)]")
        L.append("    pub struct State {")
        for n, t in state:
            L.append(f"        pub {n}: {t},")
        L.append("    }")
        L.append("")
        L.append(spec.get("child_fn", "    pub fn define_registers("
                          "bank: &mut Bank<super::State>, f: &mut Fields, "
                          "st: &State) {{").format(**sub))
        for line in self.rewrite_this(stmts):
            L.append(f"    {line}".rstrip())
        L.append("    }")
        L.append("}")
        return L, offsets, gaps

    def emits_registers(self, oid: int, emitted_spans: set[int]) -> bool:
        """Does this statement define register fields the layout did not emit?

        Tells a dropped statement that MATTERS -- one binding register fields --
        from the layout method's own plumbing, such as returning the map it
        built. `emitted_spans` are the chain roots already emitted; every call in
        a fluent chain shares its root's span start, so a combinator outside that
        set belongs to a chain nothing emitted."""
        rows = self.con.execute(
            "SELECT symbol, span_start FROM operation WHERE kind='Invocation' "
            "AND symbol IS NOT NULL AND span_start >= (SELECT span_start FROM "
            "operation WHERE id=?) AND span_start < (SELECT span_start + span_len "
            "FROM operation WHERE id=?) AND method_id=(SELECT method_id FROM "
            "operation WHERE id=?)", (oid, oid, oid))
        return any(self.combinator(s) is not None and start not in emitted_spans
                   for s, start in rows)

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
        seen = {name: off for name, off, _r, _s, _t in self.find_registers(row[0])
                if name}
        return sorted(seen.items(), key=lambda kv: kv[1])
