"""Registers located by a constant-case switch on the bus offset.

CORPUS LAYER. `ReadDoubleWord` and `GetValue` are conventions of this corpus,
not of C#, so this is a plugin. The generic half it rests on -- a `switch` whose
case labels are compile-time constants is a lookup table -- is ordinary C#, and
nothing here needs the language layer to know that.

The shape
---------

    public uint ReadDoubleWord(long offset)
    {
        switch((RegisterOffset)offset)
        {
        case RegisterOffset.CAN_MCR:  retval = registers.CAN_MCR.GetValue(); break;
        case RegisterOffset.CAN_TDT0R: retval = registers.CAN_TDT0R;         break;
        }
    }

and, for the first of those, a class that IS the register:

    public class MasterControlRegister
    {
        public void SetValue(uint value) { DebugFreeze = (value & DBF) != 0; ... }
        public uint GetValue() { return (DebugFreeze ? DBF : 0) | ...; }
        public const uint DBF = (1u << 16);
    }

There is no register DSL anywhere in such a peripheral, so the DSL forms find
nothing and `define_registers` came out empty -- with no gap saying why, which
is the failure this module exists to end.

Why this is a family and not one peripheral
-------------------------------------------

Measured, not asserted. Of the 388 types that serve a memory-mapped bus, 284
use the DSL and 104 do not (`scripts/census_memory_mapped.py`).

  * 59 of the 104 dispatch through a constant-case switch --  50 on a cast
    offset, 9 on the raw parameter (`scripts/census_handrolled_registers.py`).
    That is the OFFSET half, and it is broad.

  * The FIELD half splits (`scripts/census_case_bodies.py`, 467 case bodies
    over 55 types): 145 cases in 27 types read a plain field, and those are
    full-width storage registers. 3 types declare a `GetValue`/`SetValue`
    accessor class, and STMCAN alone reaches 13 of them.

So the offset rule and the storage rule are broad, and the accessor rule is
narrow -- three instances, which is the project's threshold and no more. They
are recorded as three rules rather than one so that the narrow one cannot
borrow the broad one's count.

What this deliberately does NOT do
----------------------------------

It emits LAYOUT and nothing else. Every case body that computes rather than
stores is a gap, every `SetValue` statement it cannot express leaves its bits
read-only and says so, and no field gets a handle -- the C# fields belong to a
nested class with no `out` parameter to take a name from, and inventing one per
field is exactly what made a hand-written peripheral unreproducible here once.
"""

from __future__ import annotations

from emitter.plugins.register_dsl import to_const


def _int(v) -> int | None:
    """A corpus `const_value` as an int, or None. Never raises."""
    if v is None:
        return None
    try:
        return int(str(v), 0)
    except (TypeError, ValueError):
        return None


def _contiguous_low(mask: int) -> int | None:
    """Width of `mask` if it is `(1 << w) - 1`, else None."""
    if mask <= 0:
        return None
    return mask.bit_length() if (mask & (mask + 1)) == 0 else None


def _single_bit(mask: int | None) -> int | None:
    """The bit position of a one-bit mask, else None."""
    if not mask or mask & (mask - 1):
        return None
    return mask.bit_length() - 1


# C# integral type -> width in bits. Only the types a register field can have;
# anything else is reported rather than assumed to be 32.
_WIDTH = {"byte": 8, "sbyte": 8, "ushort": 16, "short": 16,
          "uint": 32, "int": 32, "ulong": 64, "long": 64}


class OffsetSwitchRegisters:
    """Mixin: the register map of a peripheral that uses no register DSL.

    Consulted only when the DSL forms found nothing. A type using the DSL is
    never touched by this -- the two shapes do not co-occur, and preferring the
    DSL keeps every peripheral that already works byte-identical.
    """

    # ------------------------------------------------------------------
    # the two hooks the driver already calls
    # ------------------------------------------------------------------

    def emit_registers(self, type_name: str, method_name: str):
        stmts, fields, gaps = super().emit_registers(type_name, method_name)
        if stmts:
            return stmts, fields, gaps
        built = self._osr(type_name)
        return stmts + built["stmts"], fields, gaps + built["gaps"]

    def register_offsets(self, type_name: str, method_name: str):
        offsets = super().register_offsets(type_name, method_name)
        if offsets:
            return offsets
        return self._osr(type_name)["offsets"]

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------

    def _osr_spec(self) -> dict:
        return self.project.get("offset_switch", {})

    def _osr(self, type_name: str) -> dict:
        """Everything derived for one type, computed once.

        Cached because the driver asks for the offsets and the layout in two
        separate calls, and the two must not be able to disagree about which
        registers exist -- that disagreement, in the DSL path, once generated
        code referencing constants it had not emitted.
        """
        cache = getattr(self, "_osr_cache", None)
        if cache is None:
            cache = self._osr_cache = {}
        if type_name not in cache:
            cache[type_name] = self._osr_build(type_name)
        return cache[type_name]

    def _method_id(self, type_name: str, method_name: str) -> int | None:
        row = self.con.execute(
            "SELECT m.member_id FROM method m JOIN member mb ON mb.id = m.member_id "
            "JOIN type t ON t.id = mb.type_id WHERE t.name = ? AND mb.name = ? "
            "AND mb.kind = 'method' AND m.has_body = 1", (type_name, method_name)
        ).fetchone()
        return row[0] if row else None

    def _offset_param(self, method_id: int) -> str | None:
        row = self.con.execute(
            "SELECT name FROM parameter WHERE method_id = ? ORDER BY ordinal LIMIT 1",
            (method_id,)).fetchone()
        return row[0] if row else None

    def _osr_switch_cases(self, method_id: int) -> list[tuple[int, str | None, int]]:
        """(offset, offset name, case operation id) for one bus method.

        A switch qualifies only if every case label is a compile-time constant.
        `default:` carries no label operand, so it neither counts nor
        disqualifies -- reading it as a non-constant clause hid this shape
        entirely on the first attempt.
        """
        param = self._offset_param(method_id)
        out: list[tuple[int, str | None, int]] = []
        for oid, kind, _s, _c, _t in self.con.execute(
                "SELECT id, kind, symbol, const_value, type FROM operation "
                "WHERE method_id = ? AND kind = 'Switch' ORDER BY id", (method_id,)):
            kids = self.children(oid)
            if not kids:
                continue
            if param is not None and not self._osr_mentions_param(kids[0][0], param):
                continue
            labels: list[tuple[int, str | None, int]] = []
            ok = True
            for case in kids:
                if case[1] != "SwitchCase":
                    continue
                for clause in self.children(case[0]):
                    if clause[1] != "CaseClause":
                        continue
                    operands = self.children(clause[0])
                    if not operands:
                        continue                    # `default:`
                    value = _int(operands[0][3])
                    if value is None:
                        ok = False
                        break
                    name = self._osr_label_name(operands[0])
                    labels.append((value, name, case[0]))
                if not ok:
                    break
            if ok:
                out.extend(labels)
        return out

    def _osr_label_name(self, operand: tuple) -> str | None:
        """The enum member a case label names, through a cast if present.

        `case (long)Offset.Scratch:` folds to a constant on the `Conversion`
        node, not the `FieldReference` beneath it -- but the conversion's own
        symbol is `Conversion.IsImplicit` recorded as the literal string
        "Implicit"/"Explicit", read here as though it were the label's name.
        Every label under the same cast kind collided into that one name
        (E0428)."""
        cid, kind, sym, _const, _typ = operand
        if kind == "FieldReference":
            return (sym or "").split(".")[-1] or None
        if kind == "Conversion":
            kids = self.children(cid)
            if kids:
                return self._osr_label_name(kids[0])
        return None

    def _osr_mentions_param(self, oid: int, param: str) -> bool:
        """Is the switch subject the offset parameter, cast or not."""
        stack = [oid]
        row = self.con.execute(
            "SELECT kind, symbol FROM operation WHERE id = ?", (oid,)).fetchone()
        if row and row[0] == "ParameterReference" and (row[1] or "").endswith(param):
            return True
        while stack:
            for cid, kind, sym, _c, _t in self.children(stack.pop()):
                if kind == "ParameterReference" and (sym or "").endswith(param):
                    return True
                stack.append(cid)
        return False

    def _osr_outside_switch(self, method_id: int) -> list[tuple[int, int]]:
        """Offsets the bus method decodes WITHOUT the switch.

        A range test in front of the switch --
        `if(offset >= F0R1 && offset <= F27R2) { retval = banks[i].FR[j]; }` --
        is a whole region of the address map, and the switch never mentions it.
        Emitting the switch and saying nothing about the region would leave a
        block of addresses silently absent, which is the exact failure this
        module was written to end; reporting it costs one gap.

        Only a conditional that PRODUCES A VALUE counts. The `IsSlave` warning
        in front of it also reads the offset and only logs, and calling that a
        missing register would be a gap about nothing.
        """
        param = self._offset_param(method_id)
        if param is None:
            return []
        body = self.con.execute(
            "SELECT id FROM operation WHERE method_id = ? AND kind = 'Block' "
            "ORDER BY id LIMIT 1", (method_id,)).fetchone()
        if not body:
            return []
        out: list[tuple[int, int]] = []
        for sid, kind, _s, _c, _t in self.children(body[0]):
            if kind != "Conditional":
                continue
            kids = self.children(sid)
            if not kids:
                continue
            if not self._osr_mentions_param(kids[0][0], param):
                continue
            produces = False
            consts: list[int] = []
            # The THEN branch only. The switch itself commonly lives in the
            # ELSE -- `if(in range) {...} else { switch(...) }` -- so walking
            # both branches finds the switch and concludes, wrongly, that the
            # range test is the switch's own statement.
            stack = [kids[1][0]]
            while stack:
                for cid, ckind, _sy, const, _ty in self.children(stack.pop()):
                    if ckind in ("SimpleAssignment", "Return"):
                        produces = True
                    stack.append(cid)
            stack = [kids[0][0]]
            while stack:
                for cid, _ckind, _sy, const, _ty in self.children(stack.pop()):
                    v = _int(const)
                    if v is not None and v > 1:
                        consts.append(v)
                    stack.append(cid)
            if produces and len(consts) >= 2:
                out.append((min(consts), max(consts)))
        return sorted(set(out))

    def _osr_case_stmts(self, case_id: int) -> list[tuple]:
        return [k for k in self.children(case_id)
                if k[1] not in ("CaseClause", "Branch")]

    def _osr_find_call(self, case_id: int, leaf: str) -> tuple[int, str] | None:
        """The one `X.<leaf>(..)` invocation in a case body, and its owner type."""
        found: list[tuple[int, str]] = []
        stack = [case_id]
        while stack:
            for cid, kind, sym, _c, _t in self.children(stack.pop()):
                if kind == "Invocation" and sym:
                    head = sym.split("(")[0]
                    if head.split(".")[-1] == leaf:
                        owner = ".".join(head.split(".")[:-1]).split(".")[-1]
                        found.append((cid, owner))
                stack.append(cid)
        return found[0] if len(found) == 1 else None

    def _osr_guarded(self, case_id: int, oid: int) -> bool:
        """Is `oid` reached only through a condition inside the case body?

        Walk up to the case's own statement list and ask what KIND of statement
        contains the access. An `ExpressionStatement` runs whenever the case
        does; a `Conditional` or a loop does not, and the C# then performs the
        access only sometimes.

        Asking merely `is an ancestor one of the case's statements` answers yes
        for both -- the `if` is itself a statement of the case -- so every
        guarded write read as unguarded and no warning was emitted at all.
        """
        direct = {s[0]: s[1] for s in self._osr_case_stmts(case_id)}
        node = oid
        while node is not None:
            if node in direct:
                return direct[node] != "ExpressionStatement"
            row = self.con.execute(
                "SELECT parent_id FROM operation WHERE id = ?", (node,)).fetchone()
            node = row[0] if row else None
        return True

    def _osr_plain_field(self, case_id: int, param: str | None) -> tuple[str, str] | None:
        """`retval = someField` / `return someField` -- a plain storage read.

        Strict: a DIRECT statement of the case body only. A field reached
        through a queue or a conditional is computed, and a full-width storage
        register there would answer reads with a word nothing ever wrote.
        """
        stmts = self._osr_case_stmts(case_id)
        if len(stmts) != 1:
            return None
        kind = stmts[0][1]
        if kind == "Return":
            rhs = self.children(stmts[0][0])
        elif kind == "ExpressionStatement":
            inner = self.children(stmts[0][0])
            if not inner or inner[0][1] != "SimpleAssignment":
                return None
            operands = self.children(inner[0][0])
            if len(operands) < 2:
                return None
            # `retval = X`, not `X = retval`: the target must be the local the
            # method returns, never a field. Reversed, this would read a WRITE.
            if operands[0][1] != "LocalReference":
                return None
            rhs = [operands[1]]
        else:
            return None
        if not rhs:
            return None
        node = rhs[0]
        if node[1] == "Conversion":
            under = self.children(node[0])
            if not under:
                return None
            node = under[0]
        if node[1] != "FieldReference" or not node[2]:
            return None
        return node[2].split(".")[-1], (node[4] or "")

    def _osr_plain_write(self, case_id: int, param: str) -> str | None:
        """`someField = value` -- a plain storage write, direct statement only."""
        for sid, kind, _s, _c, _t in self._osr_case_stmts(case_id):
            if kind != "ExpressionStatement":
                continue
            inner = self.children(sid)
            if not inner or inner[0][1] != "SimpleAssignment":
                continue
            operands = self.children(inner[0][0])
            if len(operands) < 2:
                continue
            target, source = operands[0], operands[1]
            if source[1] == "Conversion":
                under = self.children(source[0])
                source = under[0] if under else source
            if (target[1] == "FieldReference" and target[2]
                    and source[1] == "ParameterReference"
                    and (source[2] or "").endswith(param)):
                return target[2].split(".")[-1]
        return None

    # ------------------------------------------------------------------
    # the accessor class: GetValue gives the bits, SetValue gives the modes
    # ------------------------------------------------------------------

    def _osr_read_expr(self, method_id: int) -> int | None:
        """The expression `GetValue` returns.

        Two forms, and both are common: `return <expr>;`, and
        `var retVal = <expr>; return retVal;`.
        """
        rows = list(self.con.execute(
            "SELECT id, kind FROM operation WHERE method_id = ? AND kind IN "
            "('Return','VariableInitializer') ORDER BY id", (method_id,)))
        for oid, kind in rows:
            kids = self.children(oid)
            if not kids:
                continue
            if kind == "Return" and kids[0][1] == "LocalReference":
                continue          # the `return retVal` half of the second form
            return kids[0][0]
        return None

    def _osr_or_terms(self, oid: int) -> list[int]:
        """Flatten an `a | b | c` chain into its leaves, left to right."""
        row = self.con.execute(
            "SELECT kind, symbol FROM operation WHERE id = ?", (oid,)).fetchone()
        if row and row[0] == "Binary" and row[1] == "Or":
            kids = self.children(oid)
            out: list[int] = []
            for k in kids:
                out.extend(self._osr_or_terms(k[0]))
            return out
        return [oid]

    def _osr_read_term(self, oid: int, width: int):
        """One term of the read word -> (pos, width, storage), or a reason."""
        row = self.con.execute(
            "SELECT kind, symbol, type FROM operation WHERE id = ?", (oid,)).fetchone()
        if row is None:
            return None, "missing operation"
        kind, sym, ctype = row
        kids = self.children(oid)

        if kind == "Conversion" and kids:
            return self._osr_read_term(kids[0][0], width)

        # `(Flag ? MASK : 0)` -- one bit, position from the mask constant.
        if kind == "Conditional" and len(kids) == 3:
            cond, then, other = kids
            if cond[1] != "FieldReference" or not cond[2]:
                return None, "the condition is not a field"
            if _int(other[3]) != 0:
                return None, "the else branch is not 0"
            bit = _single_bit(_int(then[3]))
            if bit is None:
                return None, "the set value is not a single-bit constant"
            return (bit, 1, cond[2].split(".")[-1]), None

        # `((Field & MASK) << SHIFT)` -- a value field.
        if kind == "Binary" and sym == "LeftShift" and len(kids) == 2:
            shift = _int(kids[1][3])
            if shift is None:
                return None, "the shift is not constant"
            inner, why = self._osr_read_term(kids[0][0], width)
            if inner is None:
                return None, why
            pos, w, storage = inner
            if pos:
                return None, "a shifted term is itself shifted"
            return (shift, w, storage), None

        # `(Field & MASK)` -- a value field at bit 0.
        if kind == "Binary" and sym == "And" and len(kids) == 2:
            mask = _int(kids[1][3])
            w = _contiguous_low(mask) if mask is not None else None
            if w is None:
                return None, "the mask is not a low run of set bits"
            target = kids[0]
            if target[1] == "Conversion":
                under = self.children(target[0])
                target = under[0] if under else target
            if target[1] != "FieldReference" or not target[2]:
                return None, "the masked operand is computed, not stored"
            return (0, w, target[2].split(".")[-1]), None

        # `return RegValue` -- the whole word is one stored field.
        if kind == "FieldReference" and sym and _int(kids[0][3] if kids else None) is None:
            w = _WIDTH.get((ctype or "").split(".")[-1])
            if w is None:
                return None, f"field type `{ctype}` has no known bit width"
            return (0, min(w, width), sym.split(".")[-1]), None

        return None, f"unhandled term kind `{kind}`"

    def _osr_write_model(self, method_id: int, width: int):
        """Per storage field: which register bits `SetValue` writes, and how.

        Returns ({storage: {bit: 'w'|'w1c'}}, [reasons it could not express]).
        """
        param = self._offset_param_named(method_id)
        model: dict[str, dict[int, str]] = {}
        why: list[str] = []
        shadow: list[str] = []
        block = self.con.execute(
            "SELECT id FROM operation WHERE method_id = ? AND kind = 'Block' "
            "ORDER BY id LIMIT 1", (method_id,)).fetchone()
        if not block:
            return model, ["SetValue has no body"], shadow
        for sid, kind, _s, _c, _t in self.children(block[0]):
            if kind == "ExpressionStatement":
                got = self._osr_write_assign(sid, param, width)
                if got is None:
                    why.append("an assignment this rule cannot read")
                    continue
                storage, bits = got
                model.setdefault(storage, {}).update({b: "w" for b in bits})
            elif kind == "Conditional":
                got = self._osr_write_w1c(sid, param)
                if got is None:
                    why.append("a conditional this rule cannot read")
                    continue
                storage, bit = got
                model.setdefault(storage, {})[bit] = "w1c"
            else:
                why.append(f"a `{kind}` statement")
        return model, why, shadow

    def _offset_param_named(self, method_id: int) -> str:
        row = self.con.execute(
            "SELECT name FROM parameter WHERE method_id = ? ORDER BY ordinal LIMIT 1",
            (method_id,)).fetchone()
        return row[0] if row else "value"

    def _osr_write_assign(self, stmt_id: int, param: str, width: int):
        """`F = ...value...` -> (storage, [register bits written]) or None."""
        inner = self.children(stmt_id)
        if not inner or inner[0][1] != "SimpleAssignment":
            return None
        operands = self.children(inner[0][0])
        if len(operands) < 2:
            return None
        target, source = operands[0], operands[1]
        if target[1] != "FieldReference" or not target[2]:
            return None
        storage = target[2].split(".")[-1]
        bits = self._osr_written_bits(source, param, width)
        return (storage, bits) if bits is not None else None

    def _osr_written_bits(self, node, param: str, width: int) -> list[int] | None:
        kind, sym = node[1], node[2]
        kids = self.children(node[0])
        if kind == "Conversion" and kids:
            return self._osr_written_bits(kids[0], param, width)
        # `(value & MASK) != 0` -- a flag.
        if kind == "Binary" and sym == "NotEquals" and len(kids) == 2:
            if _int(kids[1][3]) != 0:
                return None
            lhs = kids[0]
            if lhs[1] != "Binary" or lhs[2] != "And":
                return None
            pair = self.children(lhs[0])
            if len(pair) != 2 or not self._osr_is_param(pair[0], param):
                return None
            bit = _single_bit(_int(pair[1][3]))
            return None if bit is None else [bit]
        if kind == "Binary" and sym == "And" and len(kids) == 2:
            mask = _int(kids[1][3])
            if mask is None:
                return None
            lhs = kids[0]
            # `(value >> SHIFT) & MASK` -- a value field.
            if lhs[1] == "Binary" and lhs[2] == "RightShift":
                pair = self.children(lhs[0])
                shift = _int(pair[1][3]) if len(pair) == 2 else None
                w = _contiguous_low(mask)
                if (shift is None or w is None or len(pair) != 2
                        or not self._osr_is_param(pair[0], param)):
                    return None
                return list(range(shift, min(shift + w, width)))
            # `value & MASK` -- the whole word, masked.
            if self._osr_is_param(lhs, param):
                return [b for b in range(width) if mask >> b & 1]
            return None
        # `value` -- the whole word.
        if self._osr_is_param(node, param):
            return list(range(width))
        return None

    def _osr_is_param(self, node, param: str) -> bool:
        if node[1] == "Conversion":
            kids = self.children(node[0])
            return bool(kids) and self._osr_is_param(kids[0], param)
        return node[1] == "ParameterReference" and (node[2] or "").endswith(param)

    def _osr_write_w1c(self, stmt_id: int, param: str):
        """`if((value & M) != 0) { F = false; }` -> (storage, bit) or None."""
        kids = self.children(stmt_id)
        if len(kids) != 2:
            return None
        cond, body = kids
        bits = self._osr_written_bits(cond, param, 64)
        if bits is None or len(bits) != 1:
            return None
        stmts = self.children(body[0]) if body[1] == "Block" else [body]
        if len(stmts) != 1 or stmts[0][1] != "ExpressionStatement":
            return None
        inner = self.children(stmts[0][0])
        if not inner or inner[0][1] != "SimpleAssignment":
            return None
        operands = self.children(inner[0][0])
        if len(operands) < 2 or operands[0][1] != "FieldReference":
            return None
        if str(operands[1][3]).lower() not in ("false", "0"):
            return None
        return operands[0][2].split(".")[-1], bits[0]

    def _osr_receiver_field(self, call_id: int) -> tuple[str, str] | None:
        """(declaring type, field name) of the object an accessor call is on.

        `registers.CAN_MCR.GetValue()` and `registers.CAN_RFR[0].GetValue()`
        both answer `(DeviceRegisters, CAN_MCR|CAN_RFR)` -- the index is not
        part of the identity, because the C# reset assigns through the same
        indexed expression.
        """
        stack = [call_id]
        while stack:
            for cid, kind, sym, _c, _t in self.children(stack.pop()):
                if kind == "FieldReference" and sym and "." in sym:
                    parts = sym.split(".")
                    return parts[-2], parts[-1]
                if kind in ("ArrayElementReference", "Conversion"):
                    stack.append(cid)
        return None

    def _osr_reset_word(self, holder: str, field: str, w1c: bool):
        """The word the source writes into this register when it resets.

        Read from the HOLDER's own methods: a call on the accessor field whose
        only argument is a compile-time constant. An ordinary bus write passes a
        parameter, so nothing but a reset matches this.

        A register map without reset values is not complete -- this project has
        already measured what that costs, with `FLASH_OPTCR` reading 0x0FFFAA01
        against Renode's 0x0FFFAAED on the first read after reset, before any
        firmware ran.
        """
        found: dict[int, set[str]] = {}
        rows = self.con.execute(
            "SELECT o.id, o.symbol FROM operation o "
            "JOIN member mb ON mb.id = o.method_id "
            "JOIN type t ON t.id = mb.type_id "
            "WHERE t.name = ? AND o.kind = 'Invocation' AND o.symbol IS NOT NULL",
            (holder,))
        for oid, sym in rows:
            leaf = sym.split("(")[0].split(".")[-1]
            if not leaf.startswith("Set"):
                continue
            recv = self._osr_receiver_field(oid)
            if recv is None or recv[1] != field:
                continue
            args = [k for k in self.children(oid) if k[1] == "Argument"]
            if len(args) != 1:
                continue
            inner = self.children(args[0][0])
            value = _int(inner[0][3]) if inner else None
            if value is None:
                continue
            found.setdefault(value, set()).add(leaf)
        if not found:
            return 0, None
        if len(found) > 1:
            return 0, (f"{holder}.{field} is reset to {len(found)} different "
                       f"words by different paths, so none is used")
        word, leafs = next(iter(found.items()))
        if word and w1c and "SetResetValue" not in leafs:
            return 0, (f"{holder}.{field} is reset through the ordinary write "
                       f"path, which clears rather than stores on some bits, so "
                       f"the word cannot be used as a reset value")
        return word, None

    def _osr_accessor_layout(self, acc: str, width: int):
        """The bit layout of one hand-rolled register class.

        Read side first: `GetValue` is what a bus read returns, so it decides
        which bits EXIST and where. `SetValue` then decides how each of them
        answers a write. A bit `SetValue` writes and `GetValue` never returns is
        write-only, and is emitted as such rather than dropped -- dropping it
        would leave the write unhandled, which is a different thing from a write
        the source accepts and does not read back.
        """
        spec = self._osr_spec()
        names = spec.get("accessor_methods", {})
        gaps: list[str] = []
        get_id = self._method_id(acc, names.get("read", "GetValue"))
        set_id = self._method_id(acc, names.get("write", "SetValue"))
        if get_id is None:
            return [], [("read", f"`{acc}` declares no "
                                 f"{names.get('read', 'GetValue')}()")]

        expr = self._osr_read_expr(get_id)
        if expr is None:
            return [], [("read", f"`{acc}`: nothing identifies the word it returns")]
        read: dict[int, str] = {}          # register bit -> storage field
        for term in self._osr_or_terms(expr):
            got, why = self._osr_read_term(term, width)
            if got is None:
                gaps.append(("read", why))
                continue
            pos, w, storage = got
            for b in range(pos, min(pos + w, width)):
                read[b] = storage

        write: dict[str, dict[int, str]] = {}
        if set_id is not None:
            write, why, _shadow = self._osr_write_model(set_id, width)
            for reason in sorted(set(why)):
                gaps.append(("write", (why.count(reason), reason)))

        # Storage a write touches and a read never returns: write-only bits.
        written_only: dict[int, str] = {}
        for storage, bits in write.items():
            if storage in read.values():
                continue
            for b, how in bits.items():
                if b < width and b not in read and how == "w":
                    written_only[b] = storage

        modes = spec.get("modes", {})
        bits: dict[int, tuple[str, str]] = {}
        for b in range(width):
            storage = read.get(b)
            if storage is not None:
                how = write.get(storage, {}).get(b)
                key = ("read_w1c" if how == "w1c"
                       else "read_write" if how == "w" else "read")
                bits[b] = (storage, key)
            elif b in written_only:
                bits[b] = (written_only[b], "write")
        return self._osr_runs(bits, modes), gaps

    def _osr_runs(self, bits: dict[int, tuple[str, str]], modes: dict) -> list[dict]:
        """Adjacent bits with the same storage AND the same mode become one field.

        Bounded by storage identity on purpose: two neighbouring C# fields that
        happen to share a mode are two fields, and merging them would make the
        emitted layout state something the source does not.
        """
        out: list[dict] = []
        run: dict | None = None
        for b in sorted(bits):
            storage, key = bits[b]
            if run and run["end"] + 1 == b and run["key"] == (storage, key):
                run["end"] = b
                continue
            if run:
                out.append(run)
            run = {"pos": b, "end": b, "key": (storage, key)}
        if run:
            out.append(run)
        return [{"pos": r["pos"], "width": r["end"] - r["pos"] + 1,
                 "mode": modes.get(r["key"][1], "FieldMode::READ"),
                 "storage": r["key"][0]} for r in out]

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------

    def _osr_build(self, type_name: str) -> dict:
        spec = self._osr_spec()
        empty = {"stmts": [], "offsets": [], "gaps": []}
        if not spec:
            return empty
        buses = spec.get("bus_methods", {})
        gap_text = spec.get("gaps", {})

        reads: list[tuple[int, str | None, int, int]] = []
        regions: list[tuple[int, int]] = []
        for name, width in sorted(buses.get("read", {}).items()):
            mid = self._method_id(type_name, name)
            if mid is None:
                continue
            for off, oname, case in self._osr_switch_cases(mid):
                reads.append((off, oname, case, width))
            regions.extend(self._osr_outside_switch(mid))
        if not reads:
            # Nothing was found, and the caller must be told which of the two
            # possible reasons applies. Silence here is what shipped an empty
            # `define_registers` with forty gaps, none of them about registers.
            if self._osr_serves_a_bus(type_name):
                return {"stmts": [], "offsets": [],
                        "gaps": [gap_text.get("no_switch", "{type}: no register map")
                                 .format(type=type_name)]}
            return empty

        writes: dict[int, int] = {}
        write_param: dict[int, str] = {}
        for name, _width in sorted(buses.get("write", {}).items()):
            mid = self._method_id(type_name, name)
            if mid is None:
                continue
            param = self._osr_value_param(mid)
            for off, _oname, case in self._osr_switch_cases(mid):
                writes.setdefault(off, case)
                write_param[off] = param

        regs: list[dict] = []
        gaps: list[str] = []
        for lo, hi in sorted(set(regions)):
            gaps.append(gap_text.get(
                "region", "offsets {lo}..{hi} are decoded outside the switch")
                .format(lo=f"0x{lo:X}", hi=f"0x{hi:X}"))
        acc_cache: dict[tuple[str, int], tuple] = {}
        seen: set[int] = set()
        for off, oname, case, width in sorted(reads):
            if off in seen:
                continue
            seen.add(off)
            label = oname or f"REG_{off:X}"
            fields, reg_gaps, warn, reset = self._osr_register(
                type_name, label, off, case, width, writes.get(off),
                write_param.get(off, "value"), acc_cache, gap_text)
            gaps.extend(reg_gaps)
            if not fields:
                continue
            regs.append({"name": label, "offset": off, "fields": fields,
                         "warn": warn, "reset": reset})

        emit = spec.get("emit", {})
        stmts: list[str] = []
        for reg in sorted(regs, key=lambda r: r["offset"]):
            if reg["warn"]:
                stmts.extend(self.warn_line(reg["warn"], 1))
            # DEFECTS IN THE C#, declared as data in the project rules and
            # matched here by (type, register name). The marker says the source
            # is wrong and that this reproduces it on purpose -- the opposite
            # direction from the WARNING above it, which says our mapping is
            # narrower than the source. Two of these lived in a doc comment in
            # a hand-written file, where nothing counted them and nothing
            # stopped the next reader "fixing" one and breaking a trace.
            stmts.extend(self.bug_lines(type_name, reg["name"], 1))
            reset = reg["reset"]
            stmts.append(emit.get("define", "    bank.define(reg::{name}, {reset})")
                         .format(name=to_const(reg["name"]),
                                 reset=f"0x{reset:X}" if reset else "0"))
            # A no-op unless a stanza has been SWITCHED by id on the command
            # line. Fidelity is the default because the oracle certifies
            # equivalence with the C#, so the committed output never takes this
            # branch.
            reg["fields"] = self.conformance_fields(
                type_name, reg["name"], reg["fields"])
            for f in reg["fields"]:
                if f["width"] == 1:
                    stmts.append(emit.get("flag", "        .with_flag_anon({pos}, {mode})")
                                 .format(pos=f["pos"], mode=f["mode"]))
                else:
                    stmts.append(emit.get(
                        "value", "        .with_value_anon({pos}, {width}, {mode})")
                        .format(pos=f["pos"], width=f["width"], mode=f["mode"]))
            stmts.append(emit.get("done", "        .done();"))
            stmts.append("")
        offsets = sorted(((r["name"], r["offset"]) for r in regs),
                         key=lambda kv: kv[1])
        return {"stmts": stmts, "offsets": offsets, "gaps": gaps}

    def _osr_serves_a_bus(self, type_name: str) -> bool:
        names = list(self._osr_spec().get("bus_methods", {}).get("read", {}))
        if not names:
            return False
        marks = ",".join("?" * len(names))
        return self.con.execute(
            "SELECT 1 FROM member mb JOIN method m ON m.member_id = mb.id "
            "JOIN type t ON t.id = mb.type_id WHERE t.name = ? AND m.has_body = 1 "
            f"AND mb.name IN ({marks}) LIMIT 1", (type_name, *names)).fetchone() is not None

    def _osr_value_param(self, method_id: int) -> str:
        rows = list(self.con.execute(
            "SELECT name FROM parameter WHERE method_id = ? ORDER BY ordinal",
            (method_id,)))
        return rows[1][0] if len(rows) > 1 else "value"

    def _osr_register(self, type_name: str, label: str, off: int, case: int,
                      width: int, write_case: int | None, write_param: str,
                      acc_cache: dict, gap_text: dict):
        """One register: its fields, its gaps, and the warning it carries."""
        spec = self._osr_spec()
        names = spec.get("accessor_methods", {})
        gaps: list[str] = []
        warn = None

        got = self._osr_find_call(case, names.get("read", "GetValue"))
        if got is not None:
            call, acc = got
            key = (acc, width)
            if key not in acc_cache:
                acc_cache[key] = self._osr_accessor_layout(acc, width)
            fields, acc_gaps = acc_cache[key]
            for side, detail in acc_gaps:
                if side == "write":
                    n, why = detail
                    gaps.append(gap_text.get(
                        "write_stmt", "{reg}: {why}").format(
                        reg=label, accessor=acc, n=n, why=why))
                else:
                    gaps.append(gap_text.get("read_term", "{reg}: {why}").format(
                        reg=label, accessor=acc, why=detail))
            if self._osr_guarded(case, call):
                warn = spec.get("deviations", {}).get(
                    "conditional_write", {}).get("id", "condwrite")
            if write_case is None:
                gaps.append(gap_text.get(
                    "write_missing", "{reg}: read-only").format(reg=label))
                fields = self._osr_read_only(fields, spec)
            else:
                wrote = self._osr_find_call(write_case, names.get("write", "SetValue"))
                if wrote is None:
                    gaps.append(gap_text.get(
                        "write_missing", "{reg}: read-only").format(reg=label))
                    fields = self._osr_read_only(fields, spec)
                elif self._osr_guarded(write_case, wrote[0]):
                    warn = spec.get("deviations", {}).get(
                        "conditional_write", {}).get("id", "condwrite")
            if not fields:
                gaps.append(gap_text.get("no_bits", "{reg}: no bits").format(
                    reg=label, offset=f"0x{off:X}"))
            reset = 0
            recv = self._osr_receiver_field(call)
            if recv is not None:
                w1c = any("WRITE_ONE_TO_CLEAR" in f["mode"] for f in fields)
                reset, why = self._osr_reset_word(recv[0], recv[1], w1c)
                if why:
                    gaps.append(gap_text.get("reset", "{reg}: {why}").format(
                        reg=label, why=why))
            return fields, gaps, warn, reset

        plain = self._osr_plain_field(case, None)
        if plain is not None:
            _field, ctype = plain
            w = _WIDTH.get((ctype or "").split(".")[-1])
            if w is None:
                gaps.append(gap_text.get("case_not_layout", "{reg}: {why}").format(
                    reg=label, why=f"the field's type `{ctype}` has no bit width"))
                return [], gaps, None, 0
            modes = spec.get("modes", {})
            writable = (write_case is not None
                        and self._osr_plain_write(write_case, write_param) is not None)
            if not writable:
                gaps.append(gap_text.get(
                    "write_missing", "{reg}: read-only").format(reg=label))
            return ([{"pos": 0, "width": min(w, width),
                      "mode": modes.get("read_write" if writable else "read",
                                        "FieldMode::READ"),
                      "storage": _field}], gaps, None, 0)

        stmts = self._osr_case_stmts(case)
        why = ("it is empty" if not stmts else
               f"{len(stmts)} statement(s), the first a `{stmts[0][1]}`, compute "
               f"rather than store")
        gaps.append(gap_text.get("case_not_layout", "{reg}: {why}").format(
            reg=label, why=why))
        return [], gaps, None, 0

    def _osr_read_only(self, fields: list[dict], spec: dict) -> list[dict]:
        ro = spec.get("modes", {}).get("read", "FieldMode::READ")
        write_only = spec.get("modes", {}).get("write", "FieldMode::WRITE")
        return [dict(f, mode=ro) for f in fields if f["mode"] != write_only]
