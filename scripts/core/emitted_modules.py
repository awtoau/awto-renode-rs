#!/usr/bin/env python3
"""Read back what the converter EMITS, as structure rather than as text.

Four structural checks cross-reference the emitted Rust against the corpus it
came from. Each of them needs the same two things -- run the emitter over every
type it can emit, and turn the resulting Rust into something queryable -- so
that lives here once instead of four times.

WHY PARSE THE OUTPUT AT ALL
---------------------------
The alternative is to ask the emitter what it did. That is the wrong oracle:
every defect these checks look for is one where the emitter believes it
succeeded. `.with_reserved(9, 23)` was invented by hand and survived a
33,000-access trace; a dead `*_writer` free function is emitted by a rule that
reports a match. Asking the producer whether it produced the right thing
re-uses the assumption under test.

Parsing the artefact is the same reason `check_generated.py` compares bytes and
`compile_check.py` runs rustc: the output is the only thing that is not the
emitter's own opinion of itself.

WHAT AN UNKNOWN COMBINATOR DOES
-------------------------------
It raises. This is the point of the module.

A parser that skips what it does not recognise reports "no defects found" for a
file it did not read, which is indistinguishable from a clean file -- the exact
failure this repo has now hit three times (a refactor oracle that recorded a
crash as its baseline, a concurrency suite that had never failed, a compile gate
that passed when cargo never ran). So `UnknownCombinator` propagates, every
check treats it as a hard failure, and adding a combinator to `renode_regs`
forces a decision here rather than silently shrinking what is checked.

Not a check itself; nothing here exits non-zero.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(SCRIPTS.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPTS.parent))  # for `emitter`


class UnknownCombinator(Exception):
    """An emitted `.with_*` this parser has no model for.

    Deliberately fatal. See the module docstring: silently ignoring it would
    make every check quietly stop covering the register it appeared in.
    """


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def setup_log(name: str) -> logging.Logger:
    """Logger writing to stdout and to tmp/logs/<name>.log, per the repo rules."""
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    log.handlers.clear()
    for h in (logging.FileHandler(root / "tmp" / "logs" / f"{name}.log",
                                  mode="w"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)
    return log


# ---------------------------------------------------------------------------
# The combinator model.
#
# One entry per `RegisterBuilder::with_*` in src/renode-regs/src/lib.rs. The
# `reserved` column is that combinator's third argument to `push()` -- whether
# the field it creates holds no state and reads back as zero. That single bit is
# what check 2 turns on, so it is recorded here from the runtime's own source
# rather than re-derived per check.
# ---------------------------------------------------------------------------

@dataclass
class Field:
    """One bit-field created by one emitted combinator call."""
    comb: str
    pos: int
    width: int
    mode: str            # the Rust FieldMode expression, verbatim
    reserved: bool
    provider: str | None  # callback fn named in the call, or None
    on_write: str | None
    line_no: int
    raw: str


@dataclass
class Register:
    """One `bank.define(...) ... .done()` chain."""
    offset_expr: str
    offset: int | None   # None when the offset is not a compile-time constant
    reset_expr: str
    reset: int | None
    fields: list[Field]
    line_no: int
    scope: str           # the Rust fn (and module) the chain sits in

    @property
    def reserved_mask(self) -> int:
        m = 0
        for f in self.fields:
            if f.reserved:
                m |= _mask(f.width) << f.pos
        return m

    @property
    def covered_mask(self) -> int:
        m = 0
        for f in self.fields:
            m |= _mask(f.width) << f.pos
        return m

    def rust_read_after_reset(self) -> int:
        """What `Bank::read` returns before any write.

        `Register::value` sums the readable, non-reserved fields' slots, and
        each slot was seeded with its slice of the reset value. Bits that no
        field covers contribute nothing, because the value is built from the
        fields rather than from an underlying word.
        """
        if self.reset is None:
            return 0
        v = 0
        for f in self.fields:
            if f.reserved:
                continue
            # A provider makes the field readable regardless of mode; renode_regs
            # asserts a provider implies READ, so this needs no separate case.
            if "READ" not in f.mode and f.provider is None:
                continue
            v |= ((self.reset >> f.pos) & _mask(f.width)) << f.pos
        return v

    def csharp_read_after_reset(self) -> int:
        """What the C# `PeripheralRegister` returns before any write.

        The C# holds `UnderlyingValue`, seeded with the reset value, and a read
        clears only the bits of REGISTER FIELDS that are not readable. A tag is
        not a register field -- it lives in a separate `tags` list that stores
        nothing and masks nothing -- so tagged bits keep their reset value
        forever. Bits covered by nothing keep it too.
        """
        if self.reset is None:
            return 0
        v = self.reset
        for f in self.fields:
            if f.reserved:
                continue
            if "READ" not in f.mode and f.provider is None:
                v &= ~(_mask(f.width) << f.pos)
        return v


@dataclass
class Module:
    """One emitted Rust module, and the C# it claims to come from."""
    type_name: str
    cs_method: str
    mod_name: str
    text: str
    consts: dict[str, int] = dc_field(default_factory=dict)
    registers: list[Register] = dc_field(default_factory=list)
    gaps: list[str] = dc_field(default_factory=list)
    free_fns: dict[str, int] = dc_field(default_factory=dict)   # name -> line
    define_fns: dict[str, str] = dc_field(default_factory=dict)  # name -> body


def _mask(width: int) -> int:
    return (1 << width) - 1 if width < 64 else (1 << 64) - 1


def _int(tok: str) -> int | None:
    """A Rust integer literal, or None when the token is not one."""
    t = tok.strip().replace("_", "")
    try:
        return int(t, 0)
    except ValueError:
        return None


def split_args(s: str) -> list[str]:
    """Split a Rust argument list on TOP-LEVEL commas only."""
    out, depth, cur, quote = [], 0, [], False
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == '"':
                quote = False
            continue
        if ch == '"':
            quote = True
            cur.append(ch)
        elif ch in "([{<":
            depth += 1
            cur.append(ch)
        elif ch in ")]}>":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _cb(tok: str) -> str | None:
    """`Some(name)` -> "name"; `None` -> None."""
    m = re.fullmatch(r"Some\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", tok.strip())
    return m.group(1) if m else None


def fields_of(comb: str, args: list[str], line_no: int, raw: str) -> list[Field]:
    """Model one combinator call as the bit-fields it installs.

    Mirrors `RegisterBuilder` in src/renode-regs/src/lib.rs argument for
    argument. Anything not listed raises -- see the module docstring.
    """
    def mk(pos, width, mode, reserved, provider=None, on_write=None):
        return Field(comb, pos, width, mode, reserved, provider, on_write,
                     line_no, raw)

    def n(i):
        v = _int(args[i])
        if v is None:
            raise UnknownCombinator(
                f"line {line_no}: `{comb}` argument {i} is `{args[i]}`, not a "
                f"literal, so its bit position cannot be modelled")
        return v

    if comb == "with_flag":
        return [mk(n(0), 1, args[2], False)]
    if comb == "with_value":
        return [mk(n(0), n(1), args[3], False)]
    if comb == "with_value_anon":
        return [mk(n(0), n(1), args[2], False)]
    if comb == "with_flag_anon":
        return [mk(n(0), 1, args[1], False)]
    if comb == "with_tagged_flag":
        # renode_regs: push(pos, 1, READ_WRITE, reserved=true)
        return [mk(n(0), 1, "FieldMode::READ_WRITE", True)]
    if comb == "with_tag":
        return [mk(n(0), n(1), "FieldMode::READ_WRITE", True)]
    if comb == "with_reserved":
        return [mk(n(0), n(1), "FieldMode::default()", True)]
    if comb in ("with_value_fields", "with_enum_fields"):
        pos, width, count, mode = n(0), n(1), n(2), args[4]
        return [mk(pos + i * width, width, mode, False) for i in range(count)]
    if comb == "with_value_cb":
        return [mk(n(0), n(1), args[2], False, _cb(args[3]), _cb(args[4]))]
    # The `out`-binding forms of the two above. They differ from `with_flag` /
    # `with_value` only in also carrying callbacks, so the field they install is
    # identical apart from the two callback slots.
    if comb == "with_flag_cb":
        return [mk(n(0), 1, args[2], False, _cb(args[3]), _cb(args[4]))]
    if comb == "with_value_out_cb":
        return [mk(n(0), n(1), args[3], False, _cb(args[4]), _cb(args[5]))]
    if comb == "with_values_cb":
        pos, width, count, mode = n(0), n(1), n(2), args[3]
        prov, onw = _cb(args[4]), _cb(args[5])
        return [mk(pos + i * width, width, mode, False, prov, onw)
                for i in range(count)]
    # Register-level, not field-level: it installs no bit-field at all, so an
    # empty list is the model rather than an omission. Named explicitly so it
    # does not fall through to the raise below.
    if comb == "with_write_callback":
        return []
    if comb == "with_fields_cb":
        pos, width, count, mode = n(0), n(1), n(2), args[4]
        prov, onw = _cb(args[5]), _cb(args[6])
        return [mk(pos + i * width, width, mode, False, prov, onw)
                for i in range(count)]
    raise UnknownCombinator(
        f"line {line_no}: `{comb}` is emitted but this parser has no model for "
        f"it. Add one -- skipping it would silently stop checking the register "
        f"it appears in.")


_CONST = re.compile(r"pub const ([A-Z0-9_]+): u64 = (0x[0-9A-Fa-f]+|\d+);")
_FN = re.compile(r"^\s*(?:pub )?fn ([a-z_][a-z0-9_]*)\(")
_MOD = re.compile(r"^\s*pub mod ([a-z_][a-z0-9_]*)\s*\{")
_DEFINE = re.compile(r"bank\.define\((.*)\)\s*$")
_COMB = re.compile(r"^\s*\.(with_[a-z_0-9]+)\((.*)\)\s*$")


def parse(type_name: str, cs_method: str, mod_name: str, text: str) -> Module:
    """Turn one emitted module into structure. Raises on an unmodelled call."""
    m = Module(type_name, cs_method, mod_name, text)
    lines = text.splitlines()

    for line in lines:
        if line.startswith("//!   - "):
            m.gaps.append(line[len("//!   - "):])
    for name, val in _CONST.findall(text):
        m.consts[name] = int(val, 0)

    # A nested `pub mod` is a sub-block. It defines into the PARENT's bank, so
    # its registers belong to the same bank as the parent's -- but its function
    # names live in their own namespace, and `define_registers` appears in both.
    # Qualifying by module path keeps the two apart; not qualifying silently
    # dropped one of them.
    scope, path, depth_stack = "<file>", [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        md = _MOD.match(line)
        if md and md.group(1) != "reg":
            path.append(md.group(1))
            depth_stack.append(len(line) - len(line.lstrip()))
        elif path and line.strip() == "}" and \
                len(line) - len(line.lstrip()) == depth_stack[-1]:
            path.pop()
            depth_stack.pop()
        fn = _FN.match(line)
        if fn:
            scope = "::".join(path + [fn.group(1)])
            m.free_fns[scope] = i + 1
        d = _DEFINE.search(line)
        if not d:
            i += 1
            continue
        args = split_args(d.group(1))
        off_expr, reset_expr = args[0], args[1] if len(args) > 1 else ""
        off = m.consts.get(off_expr.replace("reg::", "").strip()) \
            if re.fullmatch(r"(super::)?reg::[A-Z0-9_]+", off_expr.strip()) \
            else _int(off_expr)
        reg = Register(off_expr, off, reset_expr, _int(reset_expr), [], i + 1,
                       scope)
        i += 1
        while i < len(lines):
            c = _COMB.match(lines[i])
            if c:
                reg.fields.extend(fields_of(c.group(1), split_args(c.group(2)),
                                            i + 1, lines[i].strip()))
                i += 1
                continue
            if ".done()" in lines[i]:
                i += 1
                break
            if lines[i].strip() == "" or "bank.define(" in lines[i]:
                break
            i += 1
        m.registers.append(reg)

    # Bodies of the register-defining functions, for reference counting.
    for name, start in m.free_fns.items():
        if not name.endswith("define_registers"):
            continue
        body, depth, seen = [], 0, False
        for line in lines[start - 1:]:
            depth += line.count("{") - line.count("}")
            body.append(line)
            if "{" in line:
                seen = True
            if seen and depth <= 0:
                break
        m.define_fns[name] = "\n".join(body)
    return m


def selector_rows(con: sqlite3.Connection) -> list[tuple[str, str]]:
    """(type, register-defining member) exactly as compile_check.py selects them.

    One selector, imported from `scripts/register_owners.py`. It used to be a
    copy of the query, chosen by member NAME, and the copy was deliberate --
    two checks disagreeing about which types exist is worse than both being
    wrong the same way. The selector is now chosen by what a body CONTAINS, and
    it is still exactly one selector: this function stays so that the four
    checks in this module keep naming their dependency, not so that it can
    diverge.
    """
    from register_owners import owners
    return owners(con)


def emit_all(db: Path, log: logging.Logger) -> list[Module]:
    """Emit and parse every module the converter can produce."""
    from emit import Emitter
    from emitter.plugins.sub_blocks import sub_blocks

    quiet = logging.getLogger("quiet")
    quiet.handlers.clear()
    quiet.addHandler(logging.NullHandler())

    def con():
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    rows = selector_rows(con())
    probe = Emitter(con(), quiet)
    # A sub-block has no standalone module: its registers go into the PARENT's
    # bank, and it is emitted inside the parent. compile_check.py skips these
    # for the same reason.
    nested = {s["child"] for name, _m in rows for s in sub_blocks(probe, name)[0]}

    out: list[Module] = []
    for name, method in rows:
        if name in nested:
            continue
        em = Emitter(con(), quiet)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                text = em.emit_file(name, method, "m")
        except Exception as exc:                              # noqa: BLE001
            log.warning("emit crashed on %s: %s -- not checked", name, exc)
            continue
        mod = "".join(c if c.isalnum() else "_" for c in name).lower()
        out.append(parse(name, method, mod, text))
    return out
