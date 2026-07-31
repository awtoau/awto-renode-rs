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
import logging
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


def snake(name: str) -> str:
    """C# camelCase field name -> Rust snake_case.

    A naming rule, not a cosmetic one: emitted code must be idiomatic Rust or it
    will not survive review, and hand-fixing every name afterwards is exactly the
    per-file patching this pipeline exists to avoid.
    """
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper():
            prev_lower = i > 0 and name[i - 1].islower()
            next_lower = i + 1 < len(name) and name[i + 1].islower()
            if i > 0 and (prev_lower or next_lower):
                out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


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


class Emitter:
    def __init__(self, con: sqlite3.Connection, log: logging.Logger):
        self.con = con
        self.log = log
        self.unhandled: dict[str, int] = {}

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
        """Map parameter name -> the argument's (kind, symbol, const) triple."""
        names = self.params(symbol)
        out: dict[str, tuple] = {}
        for i, (arg_id, kind, _s, _c, _t) in enumerate(self.children(oid)):
            if kind != "Argument":
                continue
            inner = self.children(arg_id)
            if not inner:
                continue
            _iid, ikind, isym, iconst, _ityp = inner[0]
            if i < len(names):
                out[names[i]] = (ikind, isym, iconst)
        return out

    def combinator(self, symbol: str) -> str | None:
        """Bare combinator name, e.g. `WithFlag`, from a full symbol."""
        if "PeripheralRegisterExtensions." not in symbol:
            return None
        after = symbol.split("PeripheralRegisterExtensions.", 1)[1]
        return after.split("<")[0].split("(")[0]

    def emit_call(self, oid: int, symbol: str) -> str | None:
        name = self.combinator(symbol)
        if name is None:
            return None
        b = self.bind(oid, symbol)

        def const(param: str):
            v = b.get(param)
            return v[2] if v else None

        def has(param: str) -> bool:
            v = b.get(param)
            return v is not None and v[0] not in ("DefaultValue",)

        pos = const("position")
        width = const("width")
        mode = render_mode(const("mode"))
        field = self.out_field(oid, symbol)

        # Only an `out` parameter produces a bound field handle. A callback
        # WITHOUT one is a computed field -- the C# `WithFlag(3, FieldMode.Read,
        # valueProviderCallback: _ => false)` shape -- which has no storage and
        # is emitted as a tag plus a note, never as a fabricated handle.
        if name == "WithFlag":
            if field:
                return f".with_flag({pos}, &mut f.{field}, {mode})"
            if has("valueProviderCallback"):
                return f".with_tagged_flag({pos})  // computed: needs a dispatch arm"
            return f".with_tagged_flag({pos})"
        if name in ("WithValueField", "WithEnumField"):
            if field:
                return f".with_value({pos}, {width}, &mut f.{field}, {mode})"
            if has("valueProviderCallback") or has("writeCallback"):
                return f".with_tag({pos}, {width})  // computed: needs a dispatch arm"
            return f".with_tag({pos}, {width})"
        if name == "WithTaggedFlag":
            return f".with_tagged_flag({pos})"
        if name == "WithTag":
            return f".with_tag({pos}, {width})"
        if name == "WithReservedBits":
            return f".with_reserved({pos}, {width})"
        if name in ("WithWriteCallback", "WithReadCallback", "WithChangeCallback"):
            return None  # register-level callbacks are dispatch, not layout
        self.unhandled[name] = self.unhandled.get(name, 0) + 1
        return None

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
