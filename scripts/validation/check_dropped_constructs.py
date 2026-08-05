#!/usr/bin/env python3
"""A C# construct the converter drops must produce a GAP. Four kinds, exactly.

The project's own rule is that a path emitting nothing must say why. `csharp_emitter.py`
enforces it for the paths it wraps in `core.must_explain`. This checks the
paths it does not wrap, by cross-referencing the CORPUS against the EMITTED
TEXT rather than asking the emitter what it thinks it did.

SCOPE, AND WHY IT IS THIS NARROW
--------------------------------
"Every dropped construct" is unbounded -- a statement inside a withheld method
is dropped, and so is every operation under it, and counting those measures
nothing. This covers four classes that are each ENUMERABLE FROM THE CORPUS and
each individually decidable from the emitted text. A partial check that states
its boundary beats a broad one that quietly misses:

  1. CONSTRUCTORS. `member.kind='ctor'` with a body. `scripts/core/csharp_emitter.py` contains
     no reference to `.ctor` at all -- its member query is `kind='method'` --
     and no gap anywhere mentions a constructor. `NVIC`'s ctor writes 16
     fields; the emitted `State` derives `Default`, so every one of them that
     survives into the struct starts at 0/false instead of its constructed
     value. That includes `priorityMask` (0xFF in the C#) and
     `defaultHaltSystickOnDeepSleep` (true).

  2. METHODS WITH A BODY. `emit_file` keeps `emit_peripheral_method`'s output
     only `if lines:`, so a method that emits nothing and reports nothing
     vanishes with no trace. Every `has_body=1` method of the type and of its
     emitted base chain must appear as a function or be named in a gap.

  3. UNMAPPED `FieldMode` BITS. `render_mode()` maps six of the twelve bits the
     corpus records for `Antmicro.Renode.Core.Structure.Registers.FieldMode`.
     A mode built only from the other six renders `FieldMode::default()` -- a
     field answering neither reads nor writes. A mode that MIXES them, like
     `Read | ReadToClear`, is worse: it renders as plain `FieldMode::READ` and
     the clear-on-read is dropped in silence, with nothing to see in the
     output. The bit names come from the corpus's own `FieldMode` enum
     members, not from a table retyped here.

  4. FIELD-LEVEL CALLBACKS. Every `writeCallback:`, `valueProviderCallback:`,
     `readCallback:`, `changeCallback:` and `shadowReloadCallback:` actually
     SUPPLIED at a DSL call site in the register-defining method. `renode_regs`
     has a slot for two of those five; the other three have nowhere to go at
     all, so every supplied one is dropped by construction. Arguments Roslyn
     resolved to `DefaultValue` are not counted -- they were never written.

NOT COVERED, DELIBERATELY: properties and events, base types outside the cut,
statement-level constructs inside an emitted method (`compile_check.py` and the
gap census cover those from the other side), and anything about a type the
selector never reaches (`check_emitted_registers.py` owns that).

Run:  python3 scripts/check_dropped_constructs.py
      python3 scripts/check_dropped_constructs.py --self-test
Log:  ./tmp/logs/check_dropped_constructs.log
Exit: 1 when a construct is dropped with no gap. FAILS TODAY.

FLOOR: 63 findings at 2026-08-02 -- 32 constructors, 2 FieldMode sites, 13
callbacks `renode_regs` has no parameter for, 16 write/provider callbacks
supplied and neither wired nor gapped. Class 2 (methods) is at ZERO and should
be gated on zero immediately; the other three want a ratchet, because a gap is
cheap to add and every one of these is either a gap or a rule.

Note what a gap costs versus what it buys: 32 constructors are unemitted, and
adding 32 gap lines would move the number to zero WITHOUT translating anything.
That is the correct outcome -- the project's rule is that a dropped construct
must SAY SO, not that it must be translated -- but it means this count measures
silence, not incompleteness. Read it beside the gap census, never instead.
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `emitter`

from emitted_modules import (Module, UnknownCombinator, emit_all,  # noqa: E402
                             parse, repo_root, setup_log)
from emitter.core import snake  # noqa: E402

CALLBACK_PARAMS = ("writeCallback", "valueProviderCallback", "readCallback",
                   "changeCallback", "shadowReloadCallback")
# The two `renode_regs` has a parameter for. See RegisterBuilder::with_value_cb.
CALLBACK_MODELLED = ("writeCallback", "valueProviderCallback")

_STATE = re.compile(r"pub struct State \{(.*?)\n\}", re.S)
_FIELD = re.compile(r"^\s*pub ([a-z_][a-z0-9_]*):", re.M)


def field_mode_bits(con: sqlite3.Connection) -> dict[int, str]:
    """The C# FieldMode enum, read from the corpus rather than retyped.

    Retyping it here would be the second source of truth the project rules
    forbid: a Renode change would leave this check asserting the old enum while
    still passing.
    """
    out = {}
    for name, val in con.execute(
            "SELECT mb.name, mb.const_value FROM member mb "
            "JOIN type t ON t.id = mb.type_id "
            "WHERE t.name='FieldMode' AND mb.const_value IS NOT NULL"):
        try:
            out[int(val)] = name
        except (TypeError, ValueError):
            continue
    return out


def emitter_mode_bits(con: sqlite3.Connection) -> set[int]:
    """The bits `render_mode()` can express, asked of the emitter.

    It imported `emit.FIELD_MODE`; the table MOVED to the register-DSL plugin
    when the DSL families landed, and the import broke. Breaking loudly is the
    point: a check that kept its own copy of the six bits would have gone on
    passing while the emitter's table changed underneath it, measuring the copy
    rather than the emitter. Two scripts were caught doing exactly that today.

    There is no table any more. The emitter reads the C# enum from the corpus,
    so this now takes a connection and asks it -- and the count it reports is
    twelve of twelve rather than six.
    """
    from emitter.plugins.register_dsl import field_mode_bits as emitter_bits
    return set(emitter_bits(con))


def state_fields(mod: Module) -> set[str]:
    m = _STATE.search(mod.text)
    return set(_FIELD.findall(m.group(1))) if m else set()


def mentions(gaps: list[str], name: str) -> bool:
    """Does any gap name this C# member? Matched on both spellings."""
    sn = snake(name)
    return any(name in g or sn in g for g in gaps)


def check_module(con: sqlite3.Connection, mod: Module, bits: dict[int, str],
                 mapped: set[int], base_chain: list[str], log,
                 fn_name=snake) -> int:
    """Report every dropped construct in one module. Returns the count."""
    found = 0
    header_done = False

    def head():
        nonlocal header_done
        if not header_done:
            log.error("%s (%s):", mod.type_name, mod.mod_name)
            header_done = True

    fn_leaves = {n.rsplit("::", 1)[-1] for n in mod.free_fns}
    types = [mod.type_name] + base_chain
    st_fields = state_fields(mod)

    # --- 1. constructors --------------------------------------------------
    for ty in types:
        for mid, key in con.execute(
                "SELECT mb.id, mb.key FROM member mb "
                "JOIN type t ON t.id = mb.type_id "
                "JOIN method m ON m.member_id = mb.id "
                "WHERE t.name=? AND mb.kind='ctor' AND m.has_body=1", (ty,)):
            if mentions(mod.gaps, f"{ty}..ctor") or \
                    any("constructor" in g or ".ctor" in g for g in mod.gaps):
                continue
            writes = [n for (n,) in con.execute(
                "SELECT DISTINCT tgt.name FROM field_access fa "
                "JOIN member tgt ON tgt.id = fa.member_id "
                "WHERE fa.method_id=? AND fa.is_write=1 ORDER BY tgt.name",
                (mid,))]
            lost = sorted(f for f in (snake(w) for w in writes)
                          if f in st_fields)
            found += 1
            head()
            log.error("    CTOR NOT EMITTED, NOT GAPPED  %s", key)
            log.error("        writes %d field(s); %d of them survive into the "
                      "emitted State and", len(writes), len(lost))
            log.error("        therefore start at Default (0/false) instead:")
            for f in lost:
                log.error("            st.%s", f)

    # --- 2. methods with a body ------------------------------------------
    for ty in types:
        for (name,) in con.execute(
                "SELECT mb.name FROM member mb JOIN method m ON m.member_id=mb.id "
                "JOIN type t ON t.id=mb.type_id WHERE t.name=? AND "
                "mb.kind='method' AND m.has_body=1 AND mb.name<>? ORDER BY mb.name",
                (ty, mod.cs_method)):
            # The emitter's OWN name mapping, not `snake` -- a property accessor
            # arrives as `get_Size` and is emitted as `fn size`, so comparing
            # raw snake() reported ten emitted functions as dropped. Reading the
            # mapping from the rules keeps the two from drifting apart.
            sn = fn_name(name)
            if sn in fn_leaves or any(f.endswith("_" + sn) for f in fn_leaves):
                continue
            if mentions(mod.gaps, name) or mentions(mod.gaps, sn):
                continue
            found += 1
            head()
            kind = " (property accessor)" if name.startswith(("get_", "set_")) \
                else ""
            log.error("    METHOD DROPPED, NOT GAPPED    %s.%s%s  (would be "
                      "`fn %s`)", ty, name, kind, sn)

    # --- 3. FieldMode bits the emitter cannot express ---------------------
    reg_mid = con.execute(
        "SELECT mb.id FROM member mb JOIN type t ON t.id=mb.type_id "
        "WHERE t.name=? AND mb.name=? AND mb.kind='method'",
        (mod.type_name, mod.cs_method)).fetchone()
    if reg_mid:
        unmapped_mask = 0
        for b in bits:
            if b not in mapped:
                unmapped_mask |= b
        for val, n in con.execute(
                "SELECT ch.const_value, COUNT(*) FROM operation o "
                "JOIN operation ch ON ch.parent_id = o.id "
                "WHERE o.method_id=? AND o.kind='Argument' "
                "AND o.symbol LIKE '% mode' AND ch.const_value IS NOT NULL "
                "GROUP BY 1", (reg_mid[0],)):
            try:
                v = int(val)
            except (TypeError, ValueError):
                continue
            lost = v & unmapped_mask
            if not lost:
                continue
            found += n
            head()
            names = " | ".join(nm for b, nm in sorted(bits.items()) if lost & b)
            kept = " | ".join(nm for b, nm in sorted(bits.items()) if v & ~lost & b)
            log.error("    FIELDMODE BIT LOST            %d site(s): C# mode "
                      "%d drops `%s`", n, v, names)
            log.error("        emitted as %s, and nothing records the "
                      "difference", f"`{kept}`" if kept else
                      "`FieldMode::default()` -- a field answering nothing")

    # --- 4. field-level callbacks supplied at a DSL call site -------------
    if reg_mid:
        wired = sum(1 for r in mod.registers for f in r.fields
                    for cb in (f.provider, f.on_write) if cb)
        supplied: dict[str, int] = {}
        for sym, in con.execute(
                "SELECT o.symbol FROM operation o WHERE o.method_id=? "
                "AND o.kind='Argument' AND o.symbol LIKE '%Callback' "
                "AND (SELECT ch.kind FROM operation ch WHERE ch.parent_id=o.id "
                "     ORDER BY ch.ordinal LIMIT 1) <> 'DefaultValue'",
                (reg_mid[0],)):
            p = sym.split()[-1]
            if p in CALLBACK_PARAMS:
                supplied[p] = supplied.get(p, 0) + 1
        modelled = sum(n for p, n in supplied.items() if p in CALLBACK_MODELLED)
        unmodellable = {p: n for p, n in supplied.items()
                        if p not in CALLBACK_MODELLED}
        gapped = sum(1 for g in mod.gaps if "allback" in g)
        if modelled > wired + gapped:
            found += modelled - wired - gapped
            head()
            log.error("    CALLBACKS DROPPED             C# supplies %d "
                      "write/provider callback(s); %d wired, %d gap(s) mention "
                      "one", modelled, wired, gapped)
        for p, n in sorted(unmodellable.items()):
            found += n
            head()
            log.error("    NO SLOT FOR CALLBACK          %d x `%s:` -- "
                      "renode_regs has no parameter for it, so it cannot be "
                      "emitted at all", n, p)

    if header_done:
        log.error("")
    return found


def run(con: sqlite3.Connection, mods: list[Module], chains: dict[str, list],
        log, fn_name=snake) -> int:
    bits = field_mode_bits(con)
    mapped = emitter_mode_bits(con)
    if not bits:
        log.error("the corpus has no `FieldMode` enum -- class 3 of this check "
                  "cannot run, and a silent pass would be a lie")
        return 1
    log.info("FieldMode: corpus declares %d bit(s), render_mode() expresses "
             "%d -- %s are unmappable", len(bits), len(mapped & set(bits)),
             ", ".join(nm for b, nm in sorted(bits.items()) if b not in mapped))
    log.info("")
    total = sum(check_module(con, m, bits, mapped, chains.get(m.type_name, []),
                             log, fn_name)
                for m in sorted(mods, key=lambda m: m.type_name))
    log.info("%d module(s) checked", len(mods))
    if total:
        log.error("")
        log.error("FAIL: %d dropped construct(s) produce no gap.", total)
        log.error("A gap tells the next agent what to pick up. Silence is "
                  "indistinguishable")
        log.error("from a construct that needed nothing done -- which is how a "
                  "constructor")
        log.error("setting priorityMask = 0xFF becomes a State field that "
                  "starts at 0.")
        return 1
    log.info("OK: every enumerated construct is emitted or gapped")
    return 0


# ---------------------------------------------------------------------------
# Self-test. Uses an in-memory corpus, so the assertions are about the CHECK
# and not about whatever the real corpus happens to contain today.
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE type(id INTEGER PRIMARY KEY, name TEXT, kind TEXT);
CREATE TABLE member(id INTEGER PRIMARY KEY, type_id INT, key TEXT, kind TEXT,
                    name TEXT, const_value TEXT);
CREATE TABLE method(member_id INTEGER PRIMARY KEY, has_body INT);
CREATE TABLE operation(id INTEGER PRIMARY KEY, method_id INT, parent_id INT,
                       ordinal INT, kind TEXT, symbol TEXT, const_value TEXT);
CREATE TABLE field_access(id INTEGER PRIMARY KEY, method_id INT, member_id INT,
                          is_write INT);
"""

_MOD = """\
//! Register layout for `Synth`, GENERATED from the corpus.
//!
//! GAPS the converter reports rather than guessing:
//!   - Helper: withheld, reaches state this peripheral does not have: st.x

pub mod reg {
    pub const R: u64 = 0x00;
}

pub struct State {
    pub f: Fields,
    pub priority_mask: u8,
}

fn helper2(bank: &Bank<State>, st: &mut State) -> () {
}

fn size(bank: &Bank<State>, st: &mut State) -> i64 {
    return (1024 as i64);
}

pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::R, 0)
        .with_value_cb(0, 1, FieldMode::READ, None, None)
        .done();
}
"""


def _fixture(with_defects: bool) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(_SCHEMA)
    con.execute("INSERT INTO type VALUES (1,'Synth','class')")
    con.execute("INSERT INTO type VALUES (2,'FieldMode','enum')")
    for i, (nm, v) in enumerate([("Read", "1"), ("Write", "2"), ("Set", "4"),
                                 ("Toggle", "8"), ("WriteOneToClear", "16"),
                                 ("WriteZeroToClear", "32"),
                                 ("ReadToClear", "64")]):
        con.execute("INSERT INTO member VALUES (?,2,?,'field',?,?)",
                    (100 + i, f"FieldMode.{nm}", nm, v))
    # The register-defining method, always present.
    con.execute("INSERT INTO member VALUES (1,1,'Synth.DefineRegisters()',"
                "'method','DefineRegisters',NULL)")
    con.execute("INSERT INTO method VALUES (1,1)")
    # Two methods with bodies: `Helper` is gapped, `Helper2` is emitted.
    con.execute("INSERT INTO member VALUES (2,1,'Synth.Helper()','method',"
                "'Helper',NULL)")
    con.execute("INSERT INTO method VALUES (2,1)")
    con.execute("INSERT INTO member VALUES (3,1,'Synth.Helper2()','method',"
                "'Helper2',NULL)")
    con.execute("INSERT INTO method VALUES (3,1)")
    con.execute("INSERT INTO member VALUES (5,1,'priorityMask','field',"
                "'priorityMask',NULL)")
    # A property accessor. Roslyn hands it over as `get_Size`; the emitter
    # strips the prefix and writes `fn size`. Comparing raw snake() reported
    # ten of these as dropped when they were emitted -- so the clean fixture
    # contains one, and the check must stay silent about it.
    con.execute("INSERT INTO member VALUES (6,1,'Synth.get_Size()','method',"
                "'get_Size',NULL)")
    con.execute("INSERT INTO method VALUES (6,1)")
    if with_defects:
        # A constructor that writes a State field, and a mode the emitter
        # cannot express.
        #
        # It used to be `ReadToClear`, because `render_mode` kept a six-entry
        # table against a twelve-member enum. The table is gone -- the emitter
        # reads the enum from the corpus -- so the only way a bit is now
        # unexpressible is a member the emitter has never seen, which is what
        # an upstream Renode addition looks like on the ingest before the
        # runtime catches up. `Sideband` is that member.
        con.execute("INSERT INTO member VALUES (200,2,'FieldMode.Sideband',"
                    "'field','Sideband','512')")
        con.execute("INSERT INTO member VALUES (4,1,'Synth.Synth()','ctor',"
                    "'.ctor',NULL)")
        con.execute("INSERT INTO method VALUES (4,1)")
        con.execute("INSERT INTO field_access VALUES (1,4,5,1)")
        con.execute("INSERT INTO operation VALUES (10,1,NULL,0,'Argument',"
                    "'Antmicro.Renode.Core.Structure.Registers.FieldMode mode',"
                    "NULL)")
        con.execute("INSERT INTO operation VALUES (11,1,10,0,'FieldReference',"
                    "NULL,'512')")
        # A supplied writeCallback with nowhere to land.
        con.execute("INSERT INTO operation VALUES (20,1,NULL,1,'Argument',"
                    "'System.Action<bool, bool> writeCallback',NULL)")
        con.execute("INSERT INTO operation VALUES (21,1,20,0,'DelegateCreation',"
                    "NULL,NULL)")
        # A readCallback, which renode_regs has no slot for at all.
        con.execute("INSERT INTO operation VALUES (30,1,NULL,2,'Argument',"
                    "'System.Action<bool, bool> readCallback',NULL)")
        con.execute("INSERT INTO operation VALUES (31,1,30,0,'DelegateCreation',"
                    "NULL,NULL)")
        # An unsupplied one, which must NOT be counted.
        con.execute("INSERT INTO operation VALUES (40,1,NULL,3,'Argument',"
                    "'System.Action<bool, bool> changeCallback',NULL)")
        con.execute("INSERT INTO operation VALUES (41,1,40,0,'DefaultValue',"
                    "NULL,NULL)")
    con.commit()
    return con


def self_test(log) -> int:
    fails = 0
    mod = parse("Synth", "DefineRegisters", "synth", _MOD)
    bits_clean = field_mode_bits(_fixture(False))
    # What the emitter can express, asked of the CLEAN fixture's enum. The
    # dirty fixture declares one member more, and that member is the one the
    # check must report -- the same asymmetry the real run has when Renode
    # gains a member the ingest has seen and the runtime has not.
    mapped = emitter_mode_bits(_fixture(False))

    quiet = logging.getLogger("q_dropped")
    quiet.handlers.clear()
    quiet.addHandler(logging.NullHandler())
    quiet.propagate = False

    # The real Emitter's name mapping, over the fixture. `fn_name` reads only
    # the rules, so the fixture connection is enough -- and using the real one
    # means the self-test exercises the same code path as the run.
    from csharp_emitter import Emitter
    fn_name = Emitter(_fixture(False), quiet).fn_name

    clean = check_module(_fixture(False), mod, bits_clean, mapped, [], quiet,
                         fn_name)
    if clean:
        log.error("SELF-TEST FAIL: clean fixture reported %d defect(s). "
                  "`Helper` is gapped and `Helper2` is emitted; reporting "
                  "either means the check fires on correct output.", clean)
        fails += 1

    dirty_con = _fixture(True)
    dirty = check_module(dirty_con, mod, field_mode_bits(dirty_con), mapped,
                         [], quiet, fn_name)
    # 1 ctor + 1 ReadToClear site + 1 unwired writeCallback + 1 readCallback
    if dirty != 4:
        log.error("SELF-TEST FAIL: expected 4 findings (ctor, lost FieldMode "
                  "bit, dropped writeCallback, unmodellable readCallback); "
                  "got %d", dirty)
        fails += 1

    if run(_fixture(False), [mod], {}, quiet, fn_name) != 0:
        log.error("SELF-TEST FAIL: run() returned non-zero on the clean fixture")
        fails += 1
    if run(_fixture(True), [mod], {}, quiet, fn_name) == 0:
        log.error("SELF-TEST FAIL: run() returned 0 on the defective fixture")
        fails += 1

    # Class 2 both ways: with the gap line removed, `Helper` -- which is
    # neither emitted nor mentioned anywhere -- must be reported. Without this,
    # "clean fixture reported 0" would also be true of a check that never looks
    # at methods at all.
    ungapped = parse("Synth", "DefineRegisters", "synth",
                     _MOD.replace("//!   - Helper: withheld, reaches state "
                                  "this peripheral does not have: st.x\n", ""))
    if "Helper" in "".join(ungapped.gaps):
        log.error("SELF-TEST FAIL: the gap line was not actually removed")
        fails += 1
    n = check_module(_fixture(False), ungapped, bits_clean, mapped, [], quiet,
                     fn_name)
    if n != 1:
        log.error("SELF-TEST FAIL: an un-emitted, un-gapped method was not "
                  "reported (got %d finding(s), expected 1)", n)
        fails += 1

    # The unsupplied `changeCallback:` must never be counted -- an argument
    # Roslyn resolved to its default was never written by anyone.
    con2 = _fixture(True)
    con2.execute("DELETE FROM operation WHERE id IN (10,11,20,21,30,31)")
    con2.execute("DELETE FROM member WHERE id=4")
    if check_module(con2, mod, field_mode_bits(con2), mapped, [], quiet,
                    fn_name) != 0:
        log.error("SELF-TEST FAIL: a DefaultValue callback argument was "
                  "counted as supplied")
        fails += 1

    if fails:
        return 1
    log.info("SELF-TEST OK: catches the un-gapped ctor, the lost FieldMode "
             "bit, the dropped and the unmodellable callback; ignores gapped "
             "methods, emitted methods and unsupplied arguments")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    log = setup_log("check_dropped_constructs")
    if args.self_test:
        return self_test(log)

    db = repo_root() / args.db
    if not db.exists():
        log.error("no corpus at %s -- it is gitignored, so a fresh worktree "
                  "does not have one. Copy it in or re-ingest.", args.db)
        return 1
    try:
        mods = emit_all(db, log)
    except UnknownCombinator as exc:
        log.error("PARSE FAIL: %s", exc)
        return 1

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    from csharp_emitter import Emitter
    quiet = logging.getLogger("quiet")
    quiet.handlers.clear()
    quiet.addHandler(logging.NullHandler())
    em = Emitter(sqlite3.connect(f"file:{db}?mode=ro", uri=True), quiet)
    # The same base chain emit_file flattens, so a base method it emitted is
    # not reported as missing and one it dropped is.
    chains = {m.type_name: em.base_chain(m.type_name) for m in mods}
    return run(con, mods, chains, log, em.fn_name)


if __name__ == "__main__":
    sys.exit(main())
