#!/usr/bin/env python3
"""The two runtimes must agree on the FIRST READ AFTER RESET.

Before any write, with no firmware involvement at all.

THE MECHANISM
-------------
In C# a tag is not a field. `PeripheralRegister.Tag()` appends to a separate
`tags` list; `Reserved()` is a wrapper that calls `Tag("RESERVED", ...)`.
Reads go through `ReadInner()`, which starts from `UnderlyingValue` -- seeded
with the reset value -- and clears only the bits of REGISTER FIELDS whose
`FieldMode.IsReadable()` is false:

    var valueToRead = UnderlyingValue;
    foreach(var registerField in registerFields)
        if(!registerField.FieldMode.IsReadable())
            BitHelper.ClearBits(ref valueToRead, ...);

    -- src/Infrastructure/src/Emulator/Main/Core/Structure/Registers/
       PeripheralRegister.cs

`tags` is never consulted. A tagged bit therefore reads back its reset value
forever, and so does a bit belonging to no field at all.

`renode_regs` composed its answer the other way round -- summing the readable,
non-reserved fields -- which looks equivalent and is not: it drops every tag
and every uncovered bit to zero. `Register::value` now has the C# shape, and
this check is what says whether it still does.

WHY IT IS STILL A CHECK NOW IT PASSES
-------------------------------------
The two models come from different places. `csharp_read_after_reset` is
written from `PeripheralRegister.cs`; `rust_read_after_reset` is written from
`Register::value` and keyed on `emitted_modules.READS_ZERO`, the set of
combinators renode_regs reads back as zero. That set is empty today. Put a
combinator in it -- which is what reverting the read path amounts to -- and
this goes red again, which the self-test proves by doing exactly that.

WHY THIS CHECK IS WORTH ITS OWN SCRIPT
--------------------------------------
The anonymous-field class is 171 sites across the emitted modules and mostly
invisible: a tag over a zero reset behaves identically in both runtimes, so no
trace can see it. This check finds the subset where the difference is
observable without any stimulus at all, which is the subset a trace WOULD have
caught had the peripheral been wired up -- and the loudest possible evidence
that the class is real rather than theoretical.

STATIC SCAN, NOT A RUNTIME ASSERT IN `done()`
---------------------------------------------
Both were considered. The scan wins on four counts:

  1. COVERAGE. An assert only fires for a bank somebody constructs. Two
     peripherals are wired into the workspace; the converter emits 24 modules,
     and every register this check reports today is in a module no test ever
     instantiates. The assert would be silent on all of them.
  2. ATTRIBUTION. The defect is the EMITTER choosing `with_tag` for a C# tag.
     A panic raised inside `renode_regs` names the runtime and a bit position,
     arrives during a trace run, and points at generated code rather than at
     the rule that generated it.
  3. DIRECTION. `renode_regs` exists to be faithful to the C#, and the C#
     explicitly ALLOWS a tag over a non-zero reset -- that permissiveness is
     precisely the behaviour being lost. An assert would encode "the C# is
     illegal" when what is true is "the translation is lossy". The runtime fix
     is a combinator that reads back its reset value the way a C# tag does;
     asserting first would outlaw the only thing the emitter can currently
     produce, before the replacement exists.
  4. BLAST RADIUS. An assert in `done()` runs inside every test that builds a
     bank. A scan cannot destabilise the runtime, and the instruction to keep
     every existing test passing is satisfied by construction.

Run:  python3 scripts/check_reset_bits_reserved.py
      python3 scripts/check_reset_bits_reserved.py --self-test
Log:  ./tmp/logs/check_reset_bits_reserved.log
Exit: 1 on any divergence. PASSES at 0; a hard gate, not a ratchet.

FLOOR: 0, at 2026-08-03. It was 5 registers across 3 modules on 2026-08-02 --
STM32F4_FlashController (2), STM32SPI (2), STM32_PWR (1), none of them wired
into the workspace, which is exactly why nothing had noticed. Closed the way
this file predicted: `renode_regs` was given a read path with the C# shape,
NO rule changed, and the emitted text is byte-identical to what it reports
zero on. Zero divergences is now the only acceptable value, because a
divergence here is observable with no stimulus at all.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from emitted_modules import (Module, Register, UnknownCombinator,  # noqa: E402
                             emit_all, parse, repo_root, setup_log)


def divergences(mod: Module) -> list[tuple[Register, int]]:
    """Registers the two runtimes read differently before any write.

    Compares the two models directly rather than looking for reset bits under
    a reserved field. That was the SYMPTOM while `Register::value` composed its
    answer out of the readable non-reserved fields; the property being asserted
    was always "the first read agrees", and stating it that way keeps the check
    pointed at the same thing now the symptom is gone.
    """
    out = []
    for r in mod.registers:
        if not r.reset:
            continue
        differ = r.csharp_read_after_reset() ^ r.rust_read_after_reset()
        if differ:
            out.append((r, differ))
    return out


def bits(mask: int) -> str:
    """Human-readable bit list, collapsing runs."""
    on = [i for i in range(64) if mask >> i & 1]
    if not on:
        return "-"
    runs, start = [], on[0]
    for a, b in zip(on, on[1:] + [None]):
        if b != (a + 1):
            runs.append(str(start) if start == a else f"{start}..{a}")
            start = b
    return ",".join(runs)


def run(mods: list[Module], log) -> int:
    total_reserved = sum(1 for m in mods for r in m.registers
                         for f in r.fields if f.reserved)
    found = 0
    for mod in sorted(mods, key=lambda m: m.type_name):
        divs = divergences(mod)
        if not divs:
            continue
        log.error("%s (%s):", mod.type_name, mod.mod_name)
        for r, overlap in divs:
            cs = r.csharp_read_after_reset()
            rs = r.rust_read_after_reset()
            found += 1
            log.error("    %-34s reset 0x%08X", r.offset_expr, r.reset)
            log.error("        bits the two runtimes disagree on: %s",
                      bits(overlap))
            log.error("        first read after reset:  C# 0x%08X   "
                      "Rust 0x%08X   differ by 0x%08X",
                      cs, rs, cs ^ rs)
            culprits = sorted({f.raw for f in r.fields
                               if overlap & (((1 << f.width) - 1) << f.pos)})
            for c in culprits:
                log.error("        from: %s", c)
        log.error("")

    log.info("%d module(s), %d register(s), %d reserved-modelled field(s)",
             len(mods), sum(len(m.registers) for m in mods), total_reserved)
    if found:
        log.error("")
        log.error("FAIL: %d register(s) read back a different value in Rust "
                  "than in C#", found)
        log.error("BEFORE ANY WRITE. C# `ReadInner` starts from "
                  "UnderlyingValue -- the reset")
        log.error("value -- and SUBTRACTS the unreadable FIELDS. Tags and "
                  "uncovered bits are")
        log.error("neither, so they read their reset value forever.")
        log.error("")
        log.error("Firmware that polls such a bit waits forever. No trace can "
                  "catch it where")
        log.error("the reset is zero, which is why the other %d tagged "
                  "field(s) are silent", total_reserved - found)
        log.error("rather than safe.")
        return 1
    log.info("OK: both runtimes read every register the same on the first "
             "read after reset")
    return 0


# ---------------------------------------------------------------------------
# Self-test. Both directions, on input whose right answer is arithmetic.
# ---------------------------------------------------------------------------

_TEMPLATE = """\
//! Register layout for `Synthetic`, GENERATED from the corpus.

pub mod reg {
    pub const R: u64 = 0x00;
}

pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::R, RESET)
        .with_tag(0, 16)
        .with_value(16, 8, &mut f.v, FieldMode::READ_WRITE)
        .with_value(24, 8, &mut f.w, FieldMode::WRITE)
        .done();
}
"""


def self_test(log) -> int:
    fails = 0
    import emitted_modules

    # Reset sets tagged bits 0..2 and a real readable field at 16..23. Both
    # runtimes report 0x00010007: the tag keeps its reset slice, and only the
    # WRITE-only field at 24..31 is subtracted.
    clean = parse("Synthetic", "D", "s", _TEMPLATE.replace("RESET", "0x0F010007"))
    if divergences(clean):
        log.error("SELF-TEST FAIL: a tag over a non-zero reset was reported. "
                  "A C# tag reads its reset slice back and so does renode_regs "
                  "-- reporting it means the check fires on correct output")
        fails += 1
    r = clean.registers[0]
    cs, rs = r.csharp_read_after_reset(), r.rust_read_after_reset()
    if (cs, rs) != (0x00010007, 0x00010007):
        log.error("SELF-TEST FAIL: read-after-reset model is wrong. expected "
                  "C# 0x00010007 / Rust 0x00010007, got 0x%08X / 0x%08X",
                  cs, rs)
        fails += 1

    # The regression this check exists for, reintroduced deliberately: declare
    # `with_tag` to read back zero, the way `Register::value` did while it
    # composed its answer out of the stored fields.
    emitted_modules.READS_ZERO.add("with_tag")
    try:
        dirty = parse("Synthetic", "D", "s",
                      _TEMPLATE.replace("RESET", "0x0F010007"))
        got = divergences(dirty)
        if len(got) != 1 or got[0][1] != 0x7:
            log.error("SELF-TEST FAIL: a tag reading back zero over reset bits "
                      "0..2 was NOT reported. Got %r",
                      [(rg.offset_expr, hex(m)) for rg, m in got])
            fails += 1
        elif got[0][0].rust_read_after_reset() != 0x00010000:
            log.error("SELF-TEST FAIL: expected Rust 0x00010000, got 0x%08X",
                      got[0][0].rust_read_after_reset())
            fails += 1
        if run([dirty], log) == 0:
            log.error("SELF-TEST FAIL: run() returned 0 on diverging input")
            fails += 1
    finally:
        emitted_modules.READS_ZERO.discard("with_tag")

    if run([clean], log) != 0:
        log.error("SELF-TEST FAIL: run() returned non-zero on clean input")
        fails += 1
    if fails:
        return 1
    log.info("SELF-TEST OK: silent on a faithful tag, and still reports the "
             "divergence when a combinator reads back zero over reset bits")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    log = setup_log("check_reset_bits_reserved")
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
    return run(mods, log)


if __name__ == "__main__":
    sys.exit(main())
