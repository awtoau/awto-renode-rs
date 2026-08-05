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

import json
import re

from emitter.core import snake, snake_case


def to_const(name: str) -> str:
    """`Control1` -> `CONTROL1`, `BaudRate` -> `BAUD_RATE`.

    Uses the un-escaped casing: Rust keywords are all-lowercase, so an
    upper-cased name can never collide with one.
    """
    return snake_case(name).upper()


def field_mode_bits(con) -> dict[int, str]:
    """The C# `FieldMode` [Flags] enum, READ FROM THE CORPUS.

    This used to be a six-entry dict written out by hand, next to a C# enum
    that declares twelve members. The other six rendered as
    `FieldMode::default()` -- a field answering neither reads nor writes --
    with nothing saying so, which is how `SYS_TICK_CONTROL` bit 16 shipped as
    an inert field where the C# says `ReadToClear`.

    Retyping an enum the corpus already records in full is the second source of
    truth the project rules forbid, and this is what it cost: the copy was not
    wrong, it was INCOMPLETE, and an incomplete lookup table has no way to say
    so. Derived, a member added upstream renders on the next ingest.

    The Rust name is the C# name in SCREAMING_SNAKE -- a naming convention, not
    a per-member mapping, so there is no table to fall behind either.
    `scripts/check_field_mode.py` pins the convention against `renode_regs`.
    """
    out: dict[int, str] = {}
    for name, val in con.execute(
            "SELECT mb.name, mb.const_value FROM member mb "
            "JOIN type t ON t.id = mb.type_id "
            "WHERE t.name = 'FieldMode' AND mb.kind = 'field' "
            "  AND mb.const_value IS NOT NULL"):
        try:
            out[int(val)] = f"FieldMode::{to_const(name)}"
        except (TypeError, ValueError):
            continue
    return out


class RegisterDsl:
    """Mixin: finding registers, and emitting the bank they describe."""

    def render_mode(self, const: str | None) -> str | None:
        """C# `FieldMode` is a [Flags] enum; render the combination.

        Returns None when the mode cannot be expressed, so the caller can
        WITHHOLD the field and report a gap. It used to return
        `FieldMode::default()` in that case -- a field that answers neither
        reads nor writes, emitted as though it were a translation. That is the
        inert-but-plausible output the whole checking layer exists to catch:
        it compiles, it runs, and it is silently not the C# field.
        """
        if const is None:
            # The C# default parameter on every combinator: Read | Write.
            return "FieldMode::READ_WRITE"
        try:
            v = int(const)
        except (TypeError, ValueError):
            # Not a compile-time constant. The C# default is not a safe
            # substitute for a mode nobody has read, so say so.
            return None
        if not hasattr(self, "_field_mode"):
            self._field_mode = field_mode_bits(self.con)
        bits = self._field_mode
        if v == 0 or v & ~sum(bits):
            # A bit the C# enum does not declare, or no bits at all. Either
            # way there is nothing faithful to emit.
            return None
        alias = self.project.get("field_mode", {}).get("compound", {})
        if str(v) in alias:
            return alias[str(v)]
        return " | ".join(name for bit, name in sorted(bits.items()) if v & bit)

    def out_field(self, oid: int, symbol: str) -> str | None:
        """Name of the `out` parameter's target, e.g. `readFifoNotEmpty`.

        This is D2's central pattern: `out IFlagRegisterField f` hands the
        peripheral a handle into register storage. Found by the ARGUMENT's OWN
        recorded parameter -- its symbol is `out IFlagRegisterField flagField`,
        literally prefixed `out ` -- never by the `out` parameter's DECLARED
        ordinal indexed into the argument list. `IInvocationOperation.Arguments`
        is recorded in WRITTEN order, not declared-parameter order, and a call
        using named arguments out of declaration order --
        `WithFlag(0, name: .., mode: .., flagField: out x)`, LPC_CTimer's
        MR0INT -- has its `out` argument at a different tree position than its
        declared ordinal. Indexing by ordinal silently returned the `mode`
        argument instead: not a `FieldReference`, so the field looked entirely
        unbound and the site fell to the anonymous rule with no gap reported.
        `bind()` above already reads arguments this same self-describing way,
        by name, for exactly this reason."""
        args = [c for c in self.children(oid) if c[1] == "Argument"]
        arg = next((a for a in args if a[2] and a[2].startswith("out ")), None)
        if arg is None:
            return None
        inner = self.children(arg[0])
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
                idx = self.index_expr(kids[1][0])
                if arr:
                    base = snake(arr.split(".")[-1].split("(")[0])
                    return f"{base}[{idx}]"
        # Symbol is a fully-qualified field reference; the leaf is the name.
        return snake(sym.split(".")[-1].split("(")[0]) if sym else None

    def index_expr(self, oid: int) -> str:
        """An array index into a field-handle array.

        Folded to a literal when a loop environment is in force -- the handles
        live in a fixed-size array whose size the emitter derives from the
        highest index it sees, and `exti_mappings[pin_number]` names a variable
        that does not exist in the generated function."""
        v = self.const_eval(oid, self._loop_env) if self._loop_env else None
        return str(v) if v is not None else self.emit_expr(oid)

    def assigned_field(self, oid: int) -> str | None:
        """Handle bound by ASSIGNING the combinator's result, not by `out`.

        The extension combinators hand a field back through `out`; the INSTANCE
        combinators return it, so `extiMappings[pin] = reg.DefineValueField(..)`
        binds exactly what `WithValueField(.., out f, ..)` binds. Reading only
        `out` saw no handle at all for the instance form -- which then looked
        like a tag field, and the register stopped storing.

        Only a direct assignment of THIS call's result counts. A call nested in
        a larger expression is not a binding, so the walk up stops at anything
        that is not a transparent wrapper."""
        node = oid
        transparent = {"Conversion", "Parenthesized"}
        for _ in range(4):
            row = self.con.execute(
                "SELECT parent_id FROM operation WHERE id=?", (node,)).fetchone()
            if not row or row[0] is None:
                return None
            pid = row[0]
            pkind, = self.con.execute(
                "SELECT kind FROM operation WHERE id=?", (pid,)).fetchone()
            if pkind in transparent:
                node = pid
                continue
            if pkind not in ("SimpleAssignment", "Assignment"):
                return None
            kids = self.children(pid)
            if len(kids) != 2 or kids[1][0] != node:
                return None          # this call is the TARGET, not the value
            tid, tkind, tsym, _c, _t = kids[0]
            if tkind == "ArrayElementReference":
                arr = self.children(tid)
                if len(arr) >= 2 and arr[0][2]:
                    base = snake(arr[0][2].split(".")[-1].split("(")[0])
                    return f"{base}[{self.index_expr(arr[1][0])}]"
                return None
            return snake(tsym.split(".")[-1].split("(")[0]) if tsym else None
        return None

    def combinator(self, symbol: str) -> str | None:
        """Bare combinator name, e.g. `WithFlag`, from a full symbol.

        The DECLARING TYPES are data (`combinator_providers`), because the DSL
        does not live in one class. Hardcoding `PeripheralRegisterExtensions`
        here named one of four:

          * `DoubleWordRegisterExtensions` carries the REGISTER-level callbacks
            (`WithWriteCallback`), 18 call sites, every one skipped in silence;
          * `PeripheralRegister` carries the same combinators as INSTANCE
            methods (`reg.DefineValueField(..)`), which is how a register held
            in a local is extended;
          * `PeripheralRegister<T>` carries `DefineWriteCallback` and friends,
            what the register-level extensions forward to.

        Returning None for those made them indistinguishable from a call that
        is not part of the DSL at all, and one peripheral's whole register map
        was empty as a result.

        `leaf_starts_with` is not decoration. `PeripheralRegister` also declares
        `UnderlyingValue`, `RecalculateFieldMask` and fifty other members; the
        prefix says which of a provider's members are combinators, so widening
        the provider list does not turn every method call on a register into an
        unhandled combinator."""
        best: tuple[int, str] | None = None
        for prov in self.project.get("combinator_providers", {}).get("providers", []):
            marker = prov["symbol_contains"]
            if marker not in symbol:
                continue
            leaf = symbol.split(marker, 1)[1].split("<")[0].split("(")[0]
            starts = prov.get("leaf_starts_with")
            if starts and not leaf.startswith(tuple(starts)):
                continue
            # Longest marker wins: `...Registers.PeripheralRegister.` is a
            # prefix of nothing else here, but `PeripheralRegisterExtensions`
            # and `PeripheralRegister` differ by one character and an ordering
            # accident must not decide which one matched.
            if best is None or len(marker) > best[0]:
                best = (len(marker), leaf)
        return best[1] if best else None

    def callback_aliases(self) -> dict[str, str]:
        """C# callback parameter name -> the `{<alias>_fn}` slot rules bind."""
        return self.project.get("callback_params", {}).get("aliases", {})

    def bound_callbacks(self, b: dict) -> list[str]:
        """Callback parameters this CALL SITE actually binds.

        Read from the binding rather than from a list in code. `emit_call`
        inspected exactly `valueProviderCallback` and `writeCallback`, so
        `changeCallback` (18 peripheral sites), `readCallback` (3) and
        `shadowReloadCallback` were dropped with no gap -- while a
        `writeCallback` on the neighbouring bit reported one. Same corpus, same
        DelegateCreation, opposite treatment, and nothing in the data said so.

        The suffix is the DSL's own convention and the corpus spells it, so
        detection needs no table; the table (`callback_params.aliases`) only
        says which template slot each one fills."""
        suffix = self.project.get("callback_params", {}).get("suffix", "Callback")
        return sorted(p for p, v in b.items()
                      if p.endswith(suffix) and v[0] != "DefaultValue")

    def select_rule(self, name: str, flags: dict[str, bool]) -> dict | None:
        """First rule matching this combinator whose condition holds.

        `when` is a disjunction of conjunctions -- `a and b`, `a or b`. The
        original grammar was `or` only, which cannot say "bound by `out` AND
        carrying a change callback", and that shape is 18 sites."""
        for rule in self.rules:
            if name not in rule["matches"].split("|"):
                continue
            cond = rule.get("when")
            if cond and not any(
                    all(flags.get(tok.strip(), False) for tok in conj.split(" and "))
                    for conj in cond.split(" or ")):
                continue
            return rule
        return None

    def emit_call(self, oid: int, symbol: str) -> str | None:
        """Apply the first matching RULE. This method knows nothing about any
        individual combinator -- adding support for a new one is a data change
        to rulesdb/rules/, never a code change here.

        ORDER MATTERS, and it changed. Callbacks used to be emitted BEFORE the
        rule was chosen, so a callback whose rule then declined was emitted into
        the file and called by nothing: five dead `fn`s in one peripheral,
        visible only as `never used` warnings among 123 that nothing gates on.
        The rule is chosen first, and only the callbacks its template consumes
        are emitted -- so a bound callback with nowhere to go is a GAP, which is
        what it always was."""
        name = self.combinator(symbol)
        if name is None:
            return None
        b = self.bind(oid, symbol)

        def const(param: str):
            v = b.get(param)
            if v is not None and v[2] is not None:
                return v[2]
            # Inside a replicated loop the argument is arithmetic over the loop
            # variable rather than a literal, so Roslyn records no constant.
            # It IS one per iteration, and folding it here is what makes the
            # iterations distinguishable.
            node = self.arg_node(oid, param) if self._loop_env else None
            folded = self.const_eval(node, self._loop_env) if node else None
            return None if folded is None else str(folded)

        env = {
            "pos": const("position"),
            "width": const("width"),
            "count": const("count"),
            "mode": self.render_mode(const("mode")),
            # `out f` first, then `x = reg.DefineField(..)`: the two forms of
            # the same binding, and a combinator uses one or the other.
            "field": self.out_field(oid, symbol) or self.assigned_field(oid),
        }
        aliases = self.callback_aliases()
        bound = self.bound_callbacks(b)
        flags = {"field": env["field"] is not None}
        for param in bound:
            flags[aliases.get(param, param)] = True

        rule = self.select_rule(name, flags)
        if rule is None:
            self.unhandled[name] = self.unhandled.get(name, 0) + 1
            return None
        if rule.get("gap"):
            self.gaps.append(f"{name}: {rule['gap']}")
        template = rule.get("emit")

        # A layout constant that is not a constant. `position` may be an
        # expression over a loop variable, and formatting None into the
        # template emitted `.with_value(None, 4, ..)` -- which does not compile,
        # but only after the file had been published as a translation.
        for slot, param in (("pos", "position"), ("width", "width"),
                            ("count", "count")):
            if template and f"{{{slot}}}" in template and env[slot] is None:
                self.gaps.append(
                    f"{name}: `{param}` is not a compile-time constant, so the "
                    f"field's placement is unknown -- withheld")
                return None

        # A `FieldMode` that cannot be expressed. Same reasoning as the layout
        # constants above and one step further: a wrong POSITION does not
        # compile, whereas `FieldMode::default()` compiles into a field that
        # silently answers nothing. The mode is the field's whole behaviour, so
        # a field whose mode is unknown is a gap, never a default.
        if template and "{mode}" in template and env["mode"] is None:
            self.gaps.append(
                f"{name}"
                f"{'' if env['pos'] is None else ' bit ' + str(env['pos'])}: "
                f"`mode` is `{const('mode')}`, which no member of the C# "
                f"FieldMode enum accounts for -- withheld")
            return None

        # `softResettable: false` marks a field a soft reset must not clear.
        # The bank has one reset, so the distinction has nowhere to go; saying
        # so is the difference between a known limit and a silent one.
        srr = self.project.get("callback_params", {}).get("soft_resettable", {})
        if srr.get("param") and template:
            v = b.get(srr["param"])
            if v and v[0] != "DefaultValue" and str(v[2]) in ("0", "False", "false"):
                self.gaps.append(f"{name}: {srr.get('gap', 'softResettable is not modelled')}")

        env.update(self.emit_callbacks(oid, name, env, rule, bound, template))
        if template is None:
            return None
        try:
            text = template.format(**env)
        except KeyError as missing:
            self.unhandled[f"{rule['name']}:missing {missing}"] = 1
            return None
        # THE EMIT-SHAPE POSTCONDITION. Everything above this line is a
        # judgement about the INPUT -- which combinator, which arm, which
        # bindings. This is the only check on what came OUT, and it is the one
        # that can refuse a link the source did not ask for. It raises: a rule
        # whose output does not match its own declared shape is a defect in the
        # rule or in this method, never a fact about the corpus, so recording it
        # as a gap would file it under the wrong heading and keep going.
        return self.assert_postcondition(rule, text)

    def emit_callbacks(self, oid: int, name: str, env: dict, rule: dict,
                       bound: list[str], template: str | None) -> dict[str, str]:
        """Each bound callback as a free fn, or a gap saying why not.

        Returns the `{<alias>_fn}` slots. Every slot the template names starts
        at `None`, so a withheld callback leaves a register whose LAYOUT is
        still right and whose behaviour is visibly absent -- see the
        `unemitted_dependency` rule."""
        aliases = self.callback_aliases()
        naming = self.project.get("callback_naming", {})
        slots: dict[str, str] = {
            f"{a}_fn": "None" for a in aliases.values()}
        seen_unh = dict(self.unhandled)
        for param in bound:
            alias = aliases.get(param)
            key = f"{alias}_fn" if alias else None
            if not template or key is None or f"{{{key}}}" not in template:
                # Bound in the C#, consumed by nothing. This is the asymmetry
                # the callback-kind gap exists to remove: a writeCallback on
                # bit 30 reported, a changeCallback on bit 0 did not, and the
                # only difference was which two names the emitter read.
                self.gaps.append(
                    f"{name}{'' if env['pos'] is None else ' bit ' + str(env['pos'])}: "
                    f"`{param}` is bound in the C# and no rule consumes it -- "
                    f"that behaviour is missing")
                continue
            lam = self.find_lambda(oid, param)
            if lam is None:
                self.gaps.append(
                    f"{name}: `{param}` is bound to something that is not a "
                    f"lambda, which the converter cannot lift into a free fn")
                continue
            tmpl = (naming.get("register_template", "{reg}_{kind}")
                    if env["pos"] is None
                    else naming.get("template", "{reg}_{pos}_{kind}"))
            fname = tmpl.format(reg=snake(self._current_reg or "reg"),
                                pos=env["pos"], kind=alias)
            # The callback's SHAPE may differ from the field-level one: a
            # register-level write callback takes (old, new) and no field
            # index, so the rule names which signature applies.
            sig = rule.get("callback_signatures", {}).get(param, param)
            # OCCURRENCES, not distinct keys. `unhandled` is a counter, and
            # comparing its LENGTH means only the FIRST site of a given kind is
            # ever caught -- every later one leaves the count of keys unchanged
            # and passes. See the same fix in emit_peripheral_method.
            before_unh = sum(self.unhandled.values())
            body = self.emit_lambda(lam, fname, sig)
            if not body:
                continue
            # Callbacks had no unhandled check at all, so an unemittable
            # construct inside one reached the file as a `/* Kind */` marker.
            # Methods have withheld on this since the beginning; lambdas were
            # simply missed.
            if sum(self.unhandled.values()) > before_unh:
                self.gaps.append(
                    f"callback for bit {env['pos']}: withheld, cannot emit "
                    f"{', '.join(sorted(k for k, v in self.unhandled.items() if v > seen_unh.get(k, 0)))}")
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
            # A callback that INDEXES a state collection nothing sizes. The
            # C# constructor allocates `mode = new Mode[NumberOfPins]`; the
            # constructor is not translated, so the generated `Vec` is empty
            # and `st.mode[idx]` panics on the first read. Compiles, passes
            # review, and takes the whole peripheral down at run time -- the
            # same class as the `/* GAP */` left in a loop increment.
            missing += sorted({
                f"st.{m}[..]" for m in re.findall(
                    r"\bst\.([a-z_][a-z0-9_]*)\s*\[", text)
                if m != "f" and self.state_is_unsized(m)})
            if missing:
                # THREE DIFFERENT FAILURES, and they used to share one message
                # that named only the first. A state field reported as a
                # "peer method not yet emitted" is not a smaller version of a
                # missing method -- it is a different fix, in a different file,
                # and `gap_census.py` filed all three under one category, so
                # the runtime-panic case was counted as a method cascade.
                #
                # Split by what the reference actually is. The categories in
                # gap_census.py match on these prefixes.
                fns = [m for m in missing if not m.startswith("st.")]
                unsized = [m for m in missing if m.endswith("[..]")]
                fields = [m for m in missing
                          if m.startswith("st.") and not m.endswith("[..]")]
                if fns:
                    self.gaps.append(
                        "callback for bit {} needs peer method(s) not yet "
                        "emitted: {}".format(env["pos"], ", ".join(fns)))
                if fields:
                    self.gaps.append(
                        "callback for bit {} reaches state this peripheral "
                        "does not have: {}".format(env["pos"], ", ".join(fields)))
                if unsized:
                    self.gaps.append(
                        "callback for bit {} indexes a collection nothing "
                        "sizes, so it would PANIC on the first read: {}"
                        .format(env["pos"], ", ".join(unsized)))
                continue
            self._callbacks.append("\n".join(body))
            slots[key] = f"Some({fname})"
        return slots

    def state_is_unsized(self, field: str) -> bool:
        """Is this State field a collection that no emitted code ever sizes?

        `#[derive(Default)]` gives a `Vec` length zero. The C# constructor is
        what gives it a length, and constructors are not translated, so any
        indexed read of one is an out-of-bounds panic waiting for the first
        access. Sized ones exist -- the sub-block loop calls `resize_with` --
        so this asks rather than assumes."""
        ty = dict(getattr(self, "_state_types", {})).get(field)
        if not ty or not ty.startswith("Vec<"):
            return False
        return field not in getattr(self, "_sized_state", set())

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

    # ---- constant-bounds loop replication -------------------------------
    #
    # A register map written as a LOOP, which the layout walker could only see
    # one iteration of. The `for` is deterministic and its bounds are literals,
    # so the iterations are known at conversion time and the registers they
    # define are constants -- there is nothing to defer to run time. See the
    # `loop_replication` rule for why this unrolls rather than emitting a Rust
    # loop.

    def const_eval(self, oid: int, env: dict[str, int | list[int]]) -> int | None:
        """Fold an expression to an integer under a loop environment.

        Deliberately small: literals, constants, the arithmetic C# uses to
        place a field, and the locals the loop binds. Anything else returns
        None, and None means the caller reports a gap rather than guessing --
        which is the whole point of doing this instead of emitting `{pos}` as
        the string `None`."""
        row = self.con.execute(
            "SELECT kind, symbol, const_value FROM operation WHERE id=?",
            (oid,)).fetchone()
        if not row:
            return None
        kind, sym, const = row
        if const is not None and kind in ("Literal", "FieldReference", "Conversion"):
            try:
                return int(const)
            except (TypeError, ValueError):
                return None
        if kind in ("Conversion", "Parenthesized", "VariableInitializer",
                    "Argument"):
            kids = self.children(oid)
            return self.const_eval(kids[0][0], env) if kids else None
        if kind == "LocalReference":
            v = env.get((sym or "").split()[-1])
            # An ARRAY-valued local is in the same environment but is not a
            # number; returning the list would make `arr + 5` a list.
            return v if isinstance(v, int) else None
        spec = self.project.get("loop_replication", {}).get("const_arrays", {})
        if spec and kind == spec.get("element_reference"):
            # `streamRegOffset[streamIdx]` -- a table of positions indexed by
            # the loop variable, which is how one C# loop places fields that
            # are NOT evenly spaced. Without this the index folds and the table
            # does not, so the position is not a constant and the field is
            # withheld: six fields per register, four registers.
            kids = self.children(oid)
            if len(kids) != 2:
                return None
            arr = self.const_array(kids[0][0], env)
            idx = self.const_eval(kids[1][0], env)
            if arr is None or idx is None or not 0 <= idx < len(arr):
                return None
            return arr[idx]
        if kind == "Binary":
            kids = self.children(oid)
            if len(kids) != 2:
                return None
            a = self.const_eval(kids[0][0], env)
            b = self.const_eval(kids[1][0], env)
            if a is None or b is None:
                return None
            op = self.project.get("loop_replication", {}).get(
                "operators", {}).get(sym or "")
            if op == "add":
                return a + b
            if op == "sub":
                return a - b
            if op == "mul":
                return a * b
            if op == "div" and b:
                return a // b
            return None
        return None

    def const_array(self, oid: int,
                    env: dict[str, int | list[int]]) -> list[int] | None:
        """An expression that names a constant array of integers, or None.

        Two shapes and no more: the array LITERAL itself, and a local bound to
        one. `new int[] {0, 6, 16, 22}` is data written as code -- the C#
        author's alternative to four `const int`s -- so folding it is folding a
        constant, not evaluating the program.

        Any element that is not a compile-time integer makes the whole array
        unknown. A partly-folded array would place some fields and silently
        misplace the rest, which is worse than placing none.

        Returns None with the `const_arrays` rule absent from the data, which
        is what makes the rule a rule: delete the section and the loops that
        depend on a table report themselves as gaps again."""
        spec = self.project.get("loop_replication", {}).get("const_arrays", {})
        if not spec:
            return None
        row = self.con.execute(
            "SELECT kind, symbol FROM operation WHERE id=?", (oid,)).fetchone()
        if not row:
            return None
        kind, sym = row
        if kind in ("Conversion", "Parenthesized", "VariableInitializer",
                    "Argument"):
            kids = self.children(oid)
            return self.const_array(kids[0][0], env) if kids else None
        if kind == "LocalReference":
            v = env.get((sym or "").split()[-1])
            return v if isinstance(v, list) else None
        if kind != spec.get("creation"):
            return None
        # ArrayCreation's children are the dimension size(s) and then the
        # initialiser; only an explicitly initialised array has known elements.
        for cid, ckind, _s, _c, _t in self.children(oid):
            if ckind != spec.get("initialiser"):
                continue
            out: list[int] = []
            for eid, _k, _s2, _c2, _t2 in self.children(cid):
                v = self.const_eval(eid, env)
                if v is None:
                    return None
                out.append(v)
            return out
        return None

    def loop_bounds(self, oid: int) -> tuple[str, range] | None:
        cache = getattr(self, "_loop_bounds_cache", None)
        if cache is None:
            cache = self._loop_bounds_cache = {}
        if oid not in cache:
            cache[oid] = self._loop_bounds_uncached(oid)
        return cache[oid]

    def _loop_bounds_uncached(self, oid: int) -> tuple[str, range] | None:
        """`for(var i = C0; i < C1; ++i)` -> the variable and its values.

        Only the counted form, and only with CONSTANT bounds. A loop whose trip
        count is not known here is not replicated, and the register it defines
        is reported rather than emitted once and quietly wrong."""
        kids = self.children(oid)
        if len(kids) < 3:
            return None
        init, cond = kids[0], kids[1]
        if init[1] != "VariableDeclarationGroup" or cond[1] != "Binary":
            return None
        names = self.declared_in(init[0])
        if len(names) != 1:
            return None
        var = names[0]
        # The initialiser: `var i = 0`.
        start = None
        stack = [init[0]]
        while stack and start is None:
            for cid, ckind, _s, _c, _t in self.children(stack.pop()):
                if ckind == "VariableInitializer":
                    start = self.const_eval(cid, {})
                    break
                stack.append(cid)
        if start is None:
            return None
        ops = self.project.get("loop_replication", {}).get("conditions", {})
        rel = ops.get(cond[2] or "")
        if rel is None:
            return None
        ckids = self.children(cond[0])
        if len(ckids) != 2:
            return None
        limit = self.const_eval(ckids[1][0], {})
        if limit is None:
            return None
        # `i++` and `++i` step by one; anything else is not this shape.
        inc = kids[3] if len(kids) > 3 else None
        if inc is not None:
            found = self.con.execute(
                "SELECT count(*) FROM operation WHERE kind='Increment' AND "
                "span_start >= (SELECT span_start FROM operation WHERE id=?) "
                "AND span_start < (SELECT span_start + span_len FROM operation "
                "WHERE id=?)", (inc[0], inc[0])).fetchone()[0]
            if not found:
                return None
        stop = limit + 1 if rel == "le" else limit
        return var, range(start, stop)

    def loop_envs(self, oid: int) -> list[dict[str, int]] | None:
        """Every iteration of every counted loop enclosing this operation.

        Returns `[{}]` when nothing encloses it -- one environment binding
        nothing, so the ordinary non-loop path is the degenerate case of this
        one rather than a parallel code path.

        None means an enclosing loop exists whose trip count is not constant.
        That is the honest answer: the site IS replicated and we cannot say how
        many times, so nothing may be emitted for it."""
        cache = getattr(self, "_loop_envs_cache", None)
        if cache is None:
            cache = self._loop_envs_cache = {}
        if oid not in cache:
            cache[oid] = self._loop_envs_uncached(oid)
        return cache[oid]

    def _loop_envs_uncached(self, oid: int) -> list[dict[str, int]] | None:
        loops: list[tuple[str, range]] = []
        node = oid
        while True:
            row = self.con.execute(
                "SELECT parent_id FROM operation WHERE id=?", (node,)).fetchone()
            if not row or row[0] is None:
                break
            node = row[0]
            kind, = self.con.execute(
                "SELECT kind FROM operation WHERE id=?", (node,)).fetchone()
            if kind != "Loop":
                continue
            b = self.loop_bounds(node)
            if b is None:
                return None
            loops.append(b)
        envs: list[dict[str, int]] = [{}]
        for var, rng in reversed(loops):          # outermost first
            envs = [dict(e, **{var: i}) for e in envs for i in rng]
        return envs

    def local_consts(self, oid: int,
                     env: dict[str, int | list[int]]) -> dict[str, int | list[int]]:
        """Locals declared between the enclosing loops and this operation.

        `var pinNumber = regNumber * 4 + fieldNumber;` is part of the index
        arithmetic, not a separate concern: without it the field's array slot
        cannot be resolved and the whole replication is useless.

        A local bound to a constant ARRAY is in here too, under its own name.
        The alternative -- a second environment threaded through every caller --
        buys nothing: `const_eval` and `const_array` each ignore the shape they
        cannot use, so one map is enough and there is one place a name can
        come from."""
        out: dict[str, int | list[int]] = dict(env)
        method_id, = self.con.execute(
            "SELECT method_id FROM operation WHERE id=?", (oid,)).fetchone()
        span = self.con.execute(
            "SELECT span_start FROM operation WHERE id=?", (oid,)).fetchone()[0]
        for did, in self.con.execute(
                "SELECT id FROM operation WHERE method_id=? AND "
                "kind='VariableDeclarationGroup' AND span_start < ? "
                "ORDER BY span_start", (method_id, span)):
            names = self.declared_in(did)
            # A loop's OWN initialiser is a declaration too, and folding it
            # rebound the loop variable to its starting value -- every
            # iteration then evaluated as iteration zero, so four registers
            # came out at one address with four fields all at bit 0. The
            # environment wins over any declaration of the same name.
            if len(names) != 1 or names[0] in env:
                continue
            stack, init = [did], None
            while stack and init is None:
                for cid, ckind, _s, _c, _t in self.children(stack.pop()):
                    if ckind == "VariableInitializer":
                        init = cid
                        break
                    stack.append(cid)
            if init is None:
                continue
            v: int | list[int] | None = self.const_eval(init, out)
            if v is None:
                v = self.const_array(init, out)
            if v is not None:
                out[names[0]] = v
        return out

    def find_registers(self, method_id: int) -> list[tuple]:
        """(name, offset, reset, chain keys, runtime term, env) per register.

        One entry per LOOP ITERATION, not per source site. A register map built
        by a counted loop is four registers in the C# and was one here, because
        the walker read the site and never the loop around it.

        A register may answer to SEVERAL chain keys, which is why this is a
        tuple and not a scalar. A key is a span start for a fluent chain and a
        local's NAME when the register is reached through one -- and a chain
        DECLARED INTO a local has both, because the C# extends it through
        either. Keeping only the span dropped every combinator in the later
        statements; keeping only the local would drop the chain's own."""
        found: list[tuple] = []
        self._form_gaps: list[str] = []
        blocals = self.builder_locals(method_id)
        for oid, symbol, span in self.con.execute(
                "SELECT id, symbol, span_start FROM operation WHERE method_id=? "
                "AND kind='Invocation' AND symbol IS NOT NULL ORDER BY span_start",
                (method_id,)):
            for form in self.forms:
                if form["symbol_contains"] not in symbol:
                    continue
                b = self.bind(oid, symbol)
                if form["chain_from"] == "$self":
                    keys: list[int | str] = [span]
                else:
                    k = self.chain_key(oid, form["chain_from"])
                    if k is None:
                        break
                    keys = [k]
                for k in list(keys):
                    lk = self.local_key(blocals[k]) if (
                        isinstance(k, int) and k in blocals) else None
                    if lk is not None:
                        keys.append(lk)
                chain_key = tuple(keys)
                envs = self.loop_envs(oid)
                if envs is None:
                    self._form_gaps.append(
                        "layout: a register is defined inside a loop whose trip "
                        "count is not a compile-time constant, so its registers "
                        "cannot be placed -- none of them are in the bank")
                    break
                reset = self.register_reset(oid, form, b)
                if reset is None:
                    self._form_gaps.append(
                        "layout: a register reset value is not a compile-time "
                        "constant at the form's declared source, so the "
                        "register is withheld")
                    break
                for env in envs:
                    name, offset, term = self.register_offset(oid, form, env)
                    if offset is None:
                        break
                    found.append((name, offset, reset, chain_key, term, env))
                break
        return found

    def register_reset(self, oid: int, form: dict, b: dict) -> str | None:
        """Read the reset only from the source the matched form declares."""
        source = form.get("reset_from")
        if isinstance(source, str):
            value = b.get(source)
            return str(value[2]) if value and value[2] is not None else None
        if isinstance(source, dict):
            return self.chain_root_constant_argument(oid, form, source)

        # A missing declaration must not turn a known non-zero construction
        # into plausible output. Zero remains safe for forms whose root proves
        # that it is the C# default.
        probe = self.chain_root_constant_argument(oid, form, {
            "chain_root_kind": "ObjectCreation", "constant_argument": 1,
            "follow_local_initializer": True})
        return "0" if probe in (None, "0") else None

    def chain_root_constant_argument(self, oid: int, form: dict,
                                     source: dict) -> str | None:
        """Read a constant argument from the declared operation at chain root."""
        node = oid if form["chain_from"] == "$self" else self.arg_node(
            oid, form["chain_from"])
        if node is None:
            return None
        node_kind, node_symbol, node_start = self.con.execute(
            "SELECT kind, symbol, span_start FROM operation WHERE id=?",
            (node,)).fetchone()
        if node_kind == "LocalReference" and node_symbol and \
                source.get("follow_local_initializer"):
            method_id, = self.con.execute(
                "SELECT method_id FROM operation WHERE id=?", (node,)).fetchone()
            local = node_symbol.split()[-1]
            for did, in self.con.execute(
                    "SELECT id FROM operation WHERE method_id=? AND "
                    "kind='VariableDeclarator' AND span_start < ? "
                    "ORDER BY span_start DESC", (method_id, node_start)):
                detail, = self.con.execute(
                    "SELECT detail FROM operation WHERE id=?", (did,)).fetchone()
                try:
                    declared = json.loads(detail or "{}").get("local")
                except json.JSONDecodeError:
                    declared = None
                if local != declared:
                    continue
                stack = [did]
                while stack:
                    current = stack.pop()
                    kind, = self.con.execute(
                        "SELECT kind FROM operation WHERE id=?",
                        (current,)).fetchone()
                    if kind == source.get("chain_root_kind"):
                        node = current
                        break
                    stack.extend(c[0] for c in self.children(current))
                break
        root_span, = self.con.execute(
            "SELECT span_start FROM operation WHERE id=?", (node,)).fetchone()
        wanted = source.get("chain_root_kind")
        stack = [node]
        creation = None
        while stack:
            current = stack.pop()
            kind, span = self.con.execute(
                "SELECT kind, span_start FROM operation WHERE id=?",
                (current,)).fetchone()
            if kind == wanted and span == root_span:
                creation = current
                break
            stack.extend(c[0] for c in self.children(current))
        if creation is None:
            return None
        args = [c for c in self.children(creation) if c[1] == "Argument"]
        index = source.get("constant_argument")
        if not isinstance(index, int) or index >= len(args):
            return None
        value = args[index][3]
        if value is None:
            kids = self.children(args[index][0])
            value = kids[0][3] if kids else None
        return str(value) if value is not None else None

    def register_offset(self, oid: int, form: dict,
                        env: dict[str, int]) -> tuple[str | None, int | None, str | None]:
        """This iteration's offset, and its name in the C# offset enum."""
        if env:
            # Inside a loop the offset is arithmetic over the loop variable, so
            # it FOLDS -- `(long)Registers.Exti1 + 4 * regNumber` is 0x8, 0xC,
            # 0x10, 0x14 and each is a member of the same enum. Only taken when
            # a loop binds something: outside one the existing path also yields
            # the RUNTIME term that a computed offset needs, and const-folding
            # cannot express that.
            arg = self.offset_arg(oid, form)
            base, _b, _t = self._raw_offset(oid, form)
            value = self.const_eval(arg, self.local_consts(oid, env)) if arg else None
            if value is not None:
                named = self.offset_name(base, value)
                if named is not None:
                    return named, value, None
                # No enum member names THIS iteration's discriminant: the
                # loop computes an array slot at runtime
                # (`Registers.ListRegister_0 + i`) and only slot 0 has its
                # own name. Falling back to `base` unconditionally gave every
                # iteration the SAME name -- one Rust constant and one set of
                # provider/writer functions for what the C# declares as N
                # distinct registers, so iterations 1..N-1 silently collided
                # into iteration 0's address and iteration 0's function names
                # collided with themselves N times (E0428). The environment
                # IS what distinguishes one iteration from the next, so it
                # disambiguates the name too.
                suffix = "_".join(str(v) for _, v in sorted(env.items()))
                return (f"{base}_{suffix}" if base else None), value, None
        return self._raw_offset(oid, form)

    def _raw_offset(self, oid: int, form: dict) -> tuple[str | None, int | None, str | None]:
        if form["offset_from"] == "$first_argument_enum":
            return self.enum_offset(oid)
        name, offset = self.arg_enum(oid, form["offset_from"])
        return name, offset, None

    def offset_arg(self, oid: int, form: dict) -> int | None:
        """The node holding the offset expression, whichever form named it."""
        if form["offset_from"] == "$first_argument_enum":
            args = [c for c in self.children(oid) if c[1] == "Argument"]
            return args[0][0] if args else None
        for aid, kind, sym, _c, _t in self.children(oid):
            if kind == "Argument" and sym and sym.split()[-1] == form["offset_from"]:
                return aid
        return None

    def offset_name(self, base: str | None, value: int) -> str | None:
        """The offset enum member with this discriminant.

        Looked up in the enum that declares `base`, never across all of them:
        a peripheral may declare several enums and two of them may share a
        value, and picking by value alone would name the register after
        whichever enum sorted first."""
        if not base:
            return None
        for _ename, members in self.nested_enums(self._current_type or ""):
            names = {m for m, _v in members}
            if base not in names:
                continue
            for mname, mval in members:
                try:
                    if int(mval) == value:
                        return mname
                except (TypeError, ValueError):
                    continue
        return None

    def chain_key(self, oid: int, param: str) -> int | str | None:
        """How a form says which combinator calls belong to its register.

        Two shapes, and only one was read. `Define(this).WithFlag(..)` is a
        fluent chain, and every call in it shares the root's span start. But
        `map.Add(key, reg)` hands over a register held in a LOCAL, extended by
        `reg.DefineValueField(..)` in statements of its own -- different span,
        same register. Reading only the span meant those calls belonged to
        nothing, so the register was located and emitted empty."""
        node = self.arg_node(oid, param)
        if node is None:
            return None
        kind, sym = self.con.execute(
            "SELECT kind, symbol FROM operation WHERE id=?", (node,)).fetchone()
        if kind == "LocalReference" and sym:
            key = self.local_key(sym.split()[-1])
            if key is not None:
                return key
        return self.con.execute(
            "SELECT span_start FROM operation WHERE id=?", (node,)).fetchone()[0]

    def local_key(self, name: str) -> str | None:
        """A chain key naming a LOCAL, or None when the rule is not in force.

        The prefix is data (`chain_binding`) so the two producers -- a form
        that hands back a local, and a declarator that binds a whole chain to
        one -- cannot drift apart by one literal. Absent means OFF, not a
        default: a rule that emits the same output whether or not it is in the
        data is indistinguishable from no rule, and this one is load-bearing --
        without it a register reached only through a local has no fields."""
        spec = self.project.get("chain_binding")
        return None if not spec else spec.get("local_key_prefix", "local:") + name

    def chain_root_local(self, method_id: int, span: int) -> str | None:
        """The LOCAL a fluent chain starts from, if it starts from one.

        Every call in `a.WithX(..).WithY(..)` shares the span start of `a`, so
        the chain's root is the SHORTEST expression at that span start -- and
        the deepest one, since an `Argument` wrapper and the expression inside
        it span the same text.

        This replaced looking at the invocation's first child. That worked only
        for INSTANCE combinators (`reg.DefineValueField(..)`, where the first
        child is the receiver) and never for the extension form, which is the
        whole DSL: for `reg.WithFlag(..)` Roslyn puts the receiver in
        `Arguments[0]`, so the first child is an `Argument` and no local was
        ever seen. `.WithY(..)` on the RESULT of `.WithX(..)` has no local as a
        direct child at all, whichever form it is -- only the chain root does.

        Deliberately not a receiver walk: `foo[0].WithX(..)` also starts at
        `foo`'s span, and calling that a chain on `foo` is the over-match the
        rule's negatives record. It costs nothing here because a register is
        only ever bound to a local by a DECLARATION, which `builder_locals`
        matches on the whole initialiser."""
        row = self.con.execute(
            "SELECT kind, symbol FROM operation WHERE method_id=? AND span_start=? "
            "ORDER BY span_len, depth DESC LIMIT 1", (method_id, span)).fetchone()
        if not row or row[0] != "LocalReference" or not row[1]:
            return None
        return row[1].split()[-1]

    def builder_locals(self, method_id: int) -> dict[int, str]:
        """Chain span -> the local its result is DECLARED into.

        `var reg = Registers.X.Define(this).WithReservedBits(12, 4);` is one
        register with two names: the chain, and `reg`. A later statement extends
        it through the second, and the layout keyed only on the first -- so
        every combinator in that later statement belonged to no register and was
        dropped, taking a stored flag with it.

        Keyed by the initialiser expression's span start, which IS the chain
        span every call in the chain carries; nothing has to walk up from the
        form's own call to find the declaration."""
        out: dict[int, str] = {}
        for did, detail in self.con.execute(
                "SELECT id, detail FROM operation WHERE method_id=? AND "
                "kind='VariableDeclarator'", (method_id,)):
            try:
                name = json.loads(detail or "{}").get("local")
            except json.JSONDecodeError:
                name = None
            if not name:
                continue
            for iid, ikind, _s, _c, _t in self.children(did):
                if ikind != "VariableInitializer":
                    continue
                kids = self.children(iid)
                if kids:
                    out[self.con.execute(
                        "SELECT span_start FROM operation WHERE id=?",
                        (kids[0][0],)).fetchone()[0]] = name
        return out

    def arg_node(self, oid: int, param: str) -> int | None:
        """The expression node of a named argument."""
        for aid, kind, sym, _c, _t in self.children(oid):
            if kind != "Argument" or not sym or sym.split()[-1] != param:
                continue
            kids = self.children(aid)
            return kids[0][0] if kids else None
        return None

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
        chains: dict[int | str, list[tuple[int, int, str]]] = {}
        for oid, symbol, start, end in self.con.execute(
                "SELECT id, symbol, span_start, span_start + span_len FROM operation "
                "WHERE method_id=? AND kind='Invocation' AND symbol IS NOT NULL",
                (method_id,)):
            chains.setdefault(start, []).append((end, oid, symbol))
            # The same call, keyed a SECOND way: by the LOCAL its chain starts
            # from. A register handed to `map.Add(key, reg)` is extended by
            # `reg.DefineValueField(..)` in statements of its own, and one
            # declared `var reg = X.Define(this)..` is extended by
            # `reg.WithFlag(..)` in a loop; neither shares a span with the
            # statement that located the register.
            local = self.chain_root_local(method_id, start)
            key = self.local_key(local) if local else None
            if key is not None:
                chains.setdefault(key, []).append((end, oid, symbol))

        stmts: list[str] = []
        fields: list[str] = []
        gaps: list[str] = []

        found = self.find_registers(method_id)
        gaps.extend(getattr(self, "_form_gaps", []))
        emitted_spans: set[int | str] = set()

        for name, offset, reset, chain_keys, term, env in sorted(
                found, key=lambda r: r[1]):
            body: list[str] = []
            self.gaps = []
            self._current_reg = name or f"reg_{offset:x}"
            skipped: list[str] = []
            # One call may be reachable under two keys -- a chain declared into
            # a local carries both its span and the local's name -- so the
            # calls are UNIONED by operation id. Concatenating the buckets
            # emitted every combinator in the declaring statement twice, which
            # is two fields at one bit position and a register that no longer
            # matches the C#.
            calls = sorted({
                oid: (end, symbol)
                for key in chain_keys
                for end, oid, symbol in chains.get(key, [])
            }.items(), key=lambda kv: (kv[1][0], kv[0]))
            for oid, (_end, symbol) in calls:
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
                # A combinator inside a loop is emitted ONCE PER ITERATION, and
                # only for the iterations consistent with the register's own.
                # SYSCFG's inner loop defines four fields into each of the four
                # registers the outer loop defines; keeping one environment per
                # register and none per field would place all sixteen at the
                # same bit.
                call_envs = self.loop_envs(oid)
                if call_envs is None:
                    gaps.append(
                        f"{name or hex(offset)}: a field is defined inside a "
                        f"loop whose trip count is not a compile-time constant "
                        f"-- the field is not in the register")
                    continue
                call_envs = [e for e in call_envs
                             if all(e.get(k) == v for k, v in env.items())] or [{}]
                for call_env in call_envs:
                    self._loop_env = self.local_consts(oid, call_env) if call_env else {}
                    line = self.emit_call(oid, symbol)
                    gaps.extend(f"{name}: {g}" for g in self.gaps)
                    self.gaps = []
                    if line is None:
                        continue
                    f = self.out_field(oid, symbol) or self.assigned_field(oid)
                    if f and f not in fields:
                        fields.append(f)
                        # Which combinators yield a FLAG handle is data. It was
                        # the literal name `WithFlag`, so the instance form of
                        # the same combinator would have declared a ValueId for
                        # a one-bit field -- a type error the moment either one
                        # emitted.
                        if self.combinator(symbol) in self.project.get(
                                "combinator_providers", {}).get("flag_combinators", []):
                            self._flag_fields.add(f)
                            # `out arr[i]` collapses into ONE array declaration,
                            # and the declaration asks for the type by the BASE
                            # name -- which nothing had ever registered, so an
                            # array of flag handles was declared `[ValueId; N]`
                            # and every `with_flag` against it failed to
                            # compile. The elements decide the array's type.
                            self._flag_fields.add(f.partition("[")[0])
                    body.append(line)
                self._loop_env = {}
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
            emitted_spans.update(chain_keys)
            const_name = to_const(name or f"REG_{offset:X}")
            where = f"reg::{const_name}"
            if term is not None:
                where = f"{where} + ({term}) as u64"
            # Declared defects IN THE C# at this register, from the project
            # rules. Same mechanism as the hand-rolled path in
            # offset_switch_registers, so a defect is recorded once and marks
            # whichever way the register was found.
            stmts.extend(self.bug_lines(type_name, name, 1))
            stmts.append(f"    bank.define({where}, {reset})")
            stmts.extend(f"        {l}" for l in body)
            stmts.append("        .done();")
            stmts.append("")
        # AFTER the registers, not before: what the preamble reports depends on
        # which chains actually emitted, and a loop-replicated chain is only
        # known to have emitted once its iterations have been walked.
        pre, pre_gaps = self.register_preamble(
            method_id, [r[4] for r in found if r[4]], emitted_spans)
        gaps.extend(pre_gaps)
        return pre + stmts, fields, gaps

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
            "SELECT id, symbol, span_start FROM operation WHERE kind='Invocation' "
            "AND symbol IS NOT NULL AND span_start >= (SELECT span_start FROM "
            "operation WHERE id=?) AND span_start < (SELECT span_start + span_len "
            "FROM operation WHERE id=?) AND method_id=(SELECT method_id FROM "
            "operation WHERE id=?)", (oid, oid, oid)).fetchall()
        method_id, = self.con.execute(
            "SELECT method_id FROM operation WHERE id=?", (oid,)).fetchone()
        for _cid, s, start in rows:
            if self.combinator(s) is None:
                continue
            # BOTH keys, because a chain is identified by either. Checking only
            # the span reported a statement as dropped whose calls had all been
            # emitted through the chain-root-local key -- a gap describing work
            # that had just been done.
            keys = {start}
            local = self.chain_root_local(method_id, start)
            lk = self.local_key(local) if local else None
            if lk is not None:
                keys.add(lk)
            if not (keys & emitted_spans):
                return True
        return False

    def register_offsets(self, type_name: str, method_name: str) -> list[tuple[str, int]]:
        """Offsets via the same discovery path as the layout.

        This previously had its OWN `.Define(` search, so when register discovery
        became rule-driven the layout found six registers and the offset module
        found none -- generating code that referenced constants it had not
        emitted. One discovery path, used by both.

        `emit_file` calls this BEFORE it sets `_current_type` for the file
        being emitted, to compute the offset enum's name ahead of the
        declarations that need it. `find_registers` names a loop-replicated
        register through `offset_name`, which reads `_current_type` to scope
        its enum lookup -- unset (or still the PREVIOUS file's), it found no
        member for any iteration, so every one of them earned a name no C#
        enum contains, this file's real offset enum was no longer a superset
        of anything, and the whole `mod reg` list this function does not even
        return -- the OTHER constants `emit_file` adds from the same enum --
        silently emitted none. Restored after, so a nested call (a sub-block's
        own `register_offsets`, mid-`emit_registers`) cannot leak its type into
        the caller's."""
        row = self.con.execute("""
            SELECT m.member_id FROM method m
            JOIN member mb ON mb.id = m.member_id
            JOIN type t ON t.id = mb.type_id
            WHERE t.name = ? AND mb.name = ?""", (type_name, method_name)).fetchone()
        if not row:
            return []
        prev_type = self._current_type
        self._current_type = type_name
        try:
            seen = {name: off for name, off, *_rest in self.find_registers(row[0])
                    if name}
        finally:
            self._current_type = prev_type
        return sorted(seen.items(), key=lambda kv: kv[1])
