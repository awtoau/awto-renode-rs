#!/usr/bin/env python3
"""No two `bank.define` calls in one bank may share an offset.

WHAT IT CATCHES
---------------
`Bank::done()` finishes with

    self.bank.registers.insert(self.offset, reg);

and `registers` is a `BTreeMap`. `insert` on an occupied key REPLACES. So a
second `bank.define` at an offset the module already defined does not error,
does not warn, and does not leave a gap -- it destroys the first register and
the module still compiles, still runs, and still passes its trace for every
offset that was not overwritten.

`STM32F4_FlashController` does exactly this today. The C# has TWO register
collections:

    Registers.AccessControl          = 0x0     reached via the flash region
    OptionBytesRegisters.ReadProtectionAndUser = 0x0   via the option-bytes region
    Registers.OptionKey              = 0x8
    OptionBytesRegisters.WriteProtection       = 0x8

Two collections, two connection regions, offsets deliberately reused. The
emitter drops the collection argument and merges both into one bank, so
FLASH_ACR and FLASH_OPTKEYR are silently replaced by the option-bytes
registers that follow them.

WHY THIS IS A CONVERTER CHECK AND NOT A FLASH CHECK
---------------------------------------------------
The defect is not "FlashController is wrong". It is "the converter has no model
of a peripheral with more than one register collection", and the shape of the
loss -- a later definition eating an earlier one -- is a property of the
emitted DSL, not of any peripheral. Any C# type with two collections will do
this, and the corpus scan below is how we know how many do (one, today).

Reported as a named failure rather than a warning: a warning about a register
that no longer exists is indistinguishable from noise once there are twenty of
them, and the register really is gone.

SCOPE, STATED
-------------
Offsets are compared only where they are compile-time constants. A sub-block
defines at `reg::BASE + (stream_offset) as u64`, where the addend is a runtime
value, and those are counted and listed as unresolved rather than guessed at.
Today that is the DMA streams and nothing else. A collision hidden inside a
sub-block's computed offset would not be caught -- said here so that it is a
known limit rather than an assumed absence.

Run:  python3 scripts/check_offset_collisions.py
      python3 scripts/check_offset_collisions.py --self-test
Log:  ./tmp/logs/check_offset_collisions.log
Exit: 1 on a collision. FAILS TODAY (FlashController); do not put it in the
      pre-commit hook until it is fixed.

FLOOR: 1 module / 2 colliding offsets, at 2026-08-02. The right floor for this
one is ZERO, not a ratchet: a collision is not a rough edge to be traded down
over time, it is a register that does not exist. Wire it into the hook the day
the emitter carries the collection argument through, and let it be a hard
gate from then on.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emitted_modules import (Module, UnknownCombinator, emit_all,  # noqa: E402
                             parse, repo_root, setup_log)


def collisions(mod: Module) -> list[tuple[int, list]]:
    """Offsets defined more than once in this module's single bank.

    Every `define_registers` in the file -- the parent's and any sub-block's --
    writes into the SAME `Bank`, so the grouping unit is the file, not the
    function. Grouping per function would miss a parent/sub-block clash.
    """
    by_off: dict[int, list] = defaultdict(list)
    for r in mod.registers:
        if r.offset is not None:
            by_off[r.offset].append(r)
    return sorted((off, regs) for off, regs in by_off.items() if len(regs) > 1)


def unresolved(mod: Module) -> list:
    return [r for r in mod.registers if r.offset is None]


def run(mods: list[Module], log) -> int:
    bad = skipped = 0
    for mod in sorted(mods, key=lambda m: m.type_name):
        cols = collisions(mod)
        skipped += len(unresolved(mod))
        if not cols:
            continue
        bad += 1
        log.error("COLLIDING OFFSETS in %s (%s):", mod.type_name, mod.mod_name)
        for off, regs in cols:
            log.error("    offset 0x%02X defined %d times -- only the LAST "
                      "survives `BTreeMap::insert`:", off, len(regs))
            for r in regs:
                log.error("        line %-4d in %s:  bank.define(%s, %s)"
                          "  %d field(s)", r.line_no, r.scope, r.offset_expr,
                          r.reset_expr, len(r.fields))
            log.error("        LOST: %s", ", ".join(
                r.offset_expr for r in regs[:-1]))
        log.error("")

    log.info("%d module(s) checked, %d register definition(s)",
             len(mods), sum(len(m.registers) for m in mods))
    if skipped:
        log.info("%d definition(s) have a run-time offset (sub-block base + "
                 "index) and are NOT compared -- see SCOPE in the docstring",
                 skipped)
    if bad:
        log.error("")
        log.error("FAIL: %d module(s) define two registers at one offset.", bad)
        log.error("Each collision destroys a register with no error, no gap and")
        log.error("no compile failure -- the C# reaches the two through separate")
        log.error("connection regions, and the emitted bank has only one.")
        return 1
    log.info("OK: every bank's register offsets are distinct")
    return 0


# ---------------------------------------------------------------------------
# Self-test: the check must be able to FAIL, and must not fire on clean input.
#
# A check that has never been seen to fail is not evidence; three in this repo
# reported success while verifying nothing. Both directions are asserted,
# because a detector that always fires is as useless as one that never does.
# ---------------------------------------------------------------------------

_CLEAN = """\
//! Register layout for `Synthetic`, GENERATED from the corpus.

pub mod reg {
    pub const A: u64 = 0x00;
    pub const B: u64 = 0x04;
}

pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::A, 0)
        .with_flag(0, &mut f.x, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::B, 0)
        .with_flag(0, &mut f.y, FieldMode::READ_WRITE)
        .done();
}
"""

# The FlashController shape, minimised: two names, one offset.
_DIRTY = _CLEAN.replace("pub const B: u64 = 0x04;", "pub const B: u64 = 0x00;")


def self_test(log) -> int:
    clean = parse("Synthetic", "DefineRegisters", "synthetic", _CLEAN)
    dirty = parse("Synthetic", "DefineRegisters", "synthetic", _DIRTY)

    fails = 0
    if collisions(clean):
        log.error("SELF-TEST FAIL: clean input reported a collision -- the "
                  "check fires on correct output and is worthless as a gate")
        fails += 1
    got = collisions(dirty)
    if len(got) != 1 or got[0][0] != 0x00 or len(got[0][1]) != 2:
        log.error("SELF-TEST FAIL: two registers at 0x00 were NOT reported. "
                  "Got %r. This is the defect the check exists for; if it is "
                  "silent here it is silent on FlashController too.", got)
        fails += 1
    if run([dirty], log) == 0:
        log.error("SELF-TEST FAIL: run() returned 0 on colliding input")
        fails += 1
    if run([clean], log) != 0:
        log.error("SELF-TEST FAIL: run() returned non-zero on clean input")
        fails += 1
    if fails:
        return 1
    log.info("SELF-TEST OK: reports the collision, stays silent without one")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the detector can fail, on synthetic input")
    args = ap.parse_args()

    log = setup_log("check_offset_collisions")
    if args.self_test:
        return self_test(log)

    root = repo_root()
    db = root / args.db
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
