#!/usr/bin/env python3
"""Every emitted callback must be wired into a register, exactly once.

WHAT IT CATCHES
---------------
The emitter translates a C# `writeCallback:` / `valueProviderCallback:` lambda
into a free function -- a closure cannot borrow the object it lives inside, so
the lambda becomes `fn name(bank, st, idx, old, value)`. Then, separately, it
chooses a combinator for the field. When it picks the `out` form
(`with_flag` / `with_value`), that combinator takes NO callback argument:

    fn power_control_14_writer(bank: &Bank<State>, st: &mut State, ...)  <- emitted
    .with_value(14, 2, &mut f.vos_value, FieldMode::READ_WRITE)          <- no slot

The function is now dead, the behaviour it carried is gone, and nothing says
so: no gap, no warning, and no rustc complaint, because the scratch crate and
the workspace crates both carry `#![allow(dead_code)]`. rustc has exactly this
lint and it is switched off -- this check is that lint, restricted to the
callbacks, and not suppressible.

Confirmed cost, from the audit: `STM32_PWR` loses the write callbacks that set
**VOSRDY** (bit 14 of PWR_CSR) and **ODSWRDY** (bit 17). Both are
`FieldMode.Read` in the C#, so the write callback was the ONLY thing that could
ever set them. Firmware that polls either after enabling over-drive spins
forever. `STM32SPI` loses two more.

"EXACTLY ONCE", NOT "AT LEAST ONCE"
-----------------------------------
Zero references is the dropped behaviour above. More than one is also wrong:
each emitted function corresponds to one C# lambda at one bit position, so a
second reference means two fields share a callback that the C# gave to one --
`with_fields_cb` spreads one callback across a group, but that is a single call
site and so a single reference. Both directions are reported.

ALSO: `FieldMode::default()` AS A TRANSLATION
---------------------------------------------
`FieldMode::default()` is `FieldMode::empty()` -- a field that answers neither
reads nor writes. `with_reserved` passes it deliberately, and those are
excluded here. Anywhere else it is `render_mode()` in scripts/emit.py falling
off the end of its table:

    parts = [name for bit, name in sorted(FIELD_MODE.items()) if v & bit]
    return " | ".join(parts) if parts else "FieldMode::default()"

FIELD_MODE is gone: `render_mode` reads the enum from the corpus, and a mode it
cannot express withholds the field with a gap. `FieldMode::default()` is
therefore no longer reachable as a translation, and this check is what says so
if that changes.

Run:  python3 scripts/check_callback_wiring.py
      python3 scripts/check_callback_wiring.py --self-test
Log:  ./tmp/logs/check_callback_wiring.log
Exit: 1 on a dead callback or a `FieldMode::default()` translation. PASSES at
      0; a hard gate, never a ratchet -- an emitted function nothing calls is
      not a degree of incompleteness, it is a translation the emitter performed
      and then discarded.

FLOOR: 0, at 2026-08-03. It was 9 dead callbacks + 1 empty mode on 2026-08-02
-- STM32_GPIOPort (5), STM32SPI (2), STM32_PWR (2), NVIC (the empty mode). The
nine were closed by `with_flag_cb` / `with_value_out_cb` / `with_values_cb`,
which landed on a parallel branch and could not be seen from here because this
parser had no model for them; the empty mode was closed by deriving the enum.
Reproduced at 3c96741 to confirm the nine were real and not a parsing artefact.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from emitted_modules import (Module, UnknownCombinator, emit_all,  # noqa: E402
                             parse, repo_root, setup_log)

# The emitter's names for a translated lambda. Kept as a suffix test rather
# than a list of known names, because the point is to cover callbacks that do
# not exist yet.
CALLBACK_SUFFIX = ("_writer", "_provider")


def callback_fns(mod: Module) -> dict[str, int]:
    """Emitted free functions that exist only to be a register callback."""
    return {name: line for name, line in mod.free_fns.items()
            if name.rsplit("::", 1)[-1].endswith(CALLBACK_SUFFIX)}


def wiring(mod: Module) -> Counter:
    """How many times each callback name is named by a combinator call.

    Counted from the PARSED combinator arguments, not from a text search, so a
    mention in a comment or in another function's body cannot make a dead
    callback look wired.
    """
    c: Counter = Counter()
    for r in mod.registers:
        # The register-level `WithWriteCallback` is a real wiring site with no
        # field to hang off. Omitting it would report a live callback as dead.
        if r.on_write:
            c[r.on_write] += 1
        for f in r.fields:
            for nm in (f.provider, f.on_write):
                if nm:
                    c[nm] += 1
    return c


def default_modes(mod: Module) -> list:
    """Fields whose MODE is `FieldMode::default()` and that are not reserved.

    `with_reserved` legitimately builds a field with no behaviour. Everywhere
    else the empty mode is a C# FieldMode that `render_mode` could not express.
    """
    return [(r, f) for r in mod.registers for f in r.fields
            if not f.reserved and "default()" in f.mode]


def run(mods: list[Module], log) -> int:
    dead = extra = empty = 0
    for mod in sorted(mods, key=lambda m: m.type_name):
        fns = callback_fns(mod)
        used = wiring(mod)
        # References are by bare name; a leaf name appearing in two scopes
        # could not be attributed, so it is reported rather than guessed at.
        leaves = Counter(n.rsplit("::", 1)[-1] for n in fns)
        reported = []
        for qualified, line in sorted(fns.items()):
            leaf = qualified.rsplit("::", 1)[-1]
            if leaves[leaf] > 1:
                reported.append((qualified, line, -1))
                continue
            n = used.get(leaf, 0)
            if n != 1:
                reported.append((qualified, line, n))
        orphan_refs = sorted(set(used) - {n.rsplit("::", 1)[-1] for n in fns})
        defaults = default_modes(mod)
        if not reported and not defaults and not orphan_refs:
            continue

        log.error("%s (%s):", mod.type_name, mod.mod_name)
        for qualified, line, n in reported:
            if n == 0:
                dead += 1
                log.error("    DEAD CALLBACK  line %-4d fn %s", line, qualified)
                log.error("        emitted, referenced by no combinator. The "
                          "behaviour the C# lambda carried is gone, and no gap "
                          "records it.")
            elif n < 0:
                extra += 1
                log.error("    AMBIGUOUS      line %-4d fn %s -- the same leaf "
                          "name exists in another scope", line, qualified)
            else:
                extra += 1
                log.error("    WIRED %dx      line %-4d fn %s -- one C# lambda "
                          "belongs to one call site", n, line, qualified)
        for nm in orphan_refs:
            extra += 1
            log.error("    MISSING FN     combinator names `%s`, which this "
                      "module does not define", nm)
        for r, f in defaults:
            empty += 1
            log.error("    EMPTY MODE     line %-4d %s in %s", f.line_no,
                      f.raw, r.offset_expr)
            log.error("        `FieldMode::default()` answers neither reads "
                      "nor writes. As a TRANSLATION of a C# mode it means "
                      "render_mode() had no bit for it.")
        log.error("")

    n_fns = sum(len(callback_fns(m)) for m in mods)
    log.info("%d module(s), %d emitted callback function(s)", len(mods), n_fns)
    if dead or extra or empty:
        log.error("")
        log.error("FAIL: %d dead callback(s), %d mis-wired, %d empty-mode "
                  "field(s).", dead, extra, empty)
        log.error("A dead callback is behaviour the converter translated and "
                  "then dropped on")
        log.error("the floor. `#![allow(dead_code)]` is what stops rustc "
                  "saying so; this")
        log.error("check is that lint, aimed only at callbacks and not "
                  "suppressible.")
        return 1
    log.info("OK: every emitted callback is wired exactly once, and no field "
             "was given an empty mode")
    return 0


# ---------------------------------------------------------------------------
# Self-test.
# ---------------------------------------------------------------------------

_HEAD = """\
//! Register layout for `Synthetic`, GENERATED from the corpus.

pub mod reg {
    pub const R: u64 = 0x00;
}

fn r_0_writer(bank: &Bank<State>, st: &mut State, _idx: usize, _o: u64, v: u64) -> () {
}

fn r_8_provider(bank: &Bank<State>, st: &mut State, _idx: usize, _c: u64) -> u64 {
    return 0;
}

pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::R, 0)
%s
        .done();
}
"""

_CLEAN = _HEAD % (
    "        .with_value_cb(0, 1, FieldMode::WRITE, None, Some(r_0_writer))\n"
    "        .with_value_cb(8, 1, FieldMode::READ, Some(r_8_provider), None)\n"
    "        .with_reserved(16, 16)")

# The STM32_PWR shape: the callback is emitted, then the `out` form is chosen.
_DEAD = _HEAD % (
    "        .with_value_cb(0, 1, FieldMode::WRITE, None, Some(r_0_writer))\n"
    "        .with_flag(8, &mut f.x, FieldMode::READ)\n"
    "        .with_reserved(16, 16)")

# The nvic.rs shape: a C# mode with no bit in FIELD_MODE.
_EMPTY = _HEAD % (
    "        .with_value_cb(0, 1, FieldMode::WRITE, None, Some(r_0_writer))\n"
    "        .with_value_cb(8, 1, FieldMode::default(), Some(r_8_provider), None)\n"
    "        .with_reserved(16, 16)")


def self_test(log) -> int:
    fails = 0
    clean = parse("Synthetic", "D", "s", _CLEAN)
    dead = parse("Synthetic", "D", "s", _DEAD)
    empty = parse("Synthetic", "D", "s", _EMPTY)

    if len(callback_fns(clean)) != 2:
        log.error("SELF-TEST FAIL: expected 2 callback fns, found %r",
                  sorted(callback_fns(clean)))
        fails += 1
    if wiring(clean) != Counter({"r_0_writer": 1, "r_8_provider": 1}):
        log.error("SELF-TEST FAIL: clean wiring miscounted: %r", wiring(clean))
        fails += 1
    if wiring(dead).get("r_8_provider", 0) != 0:
        log.error("SELF-TEST FAIL: r_8_provider is unreferenced in the dead "
                  "sample and was counted as wired")
        fails += 1
    if default_modes(clean):
        log.error("SELF-TEST FAIL: `with_reserved`'s empty mode was reported "
                  "as a translation -- it is deliberate")
        fails += 1
    if len(default_modes(empty)) != 1:
        log.error("SELF-TEST FAIL: an explicit FieldMode::default() on a real "
                  "field was not reported: %r", default_modes(empty))
        fails += 1

    if run([clean], log) != 0:
        log.error("SELF-TEST FAIL: run() returned non-zero on clean input")
        fails += 1
    if run([dead], log) == 0:
        log.error("SELF-TEST FAIL: run() returned 0 with a dead callback")
        fails += 1
    if run([empty], log) == 0:
        log.error("SELF-TEST FAIL: run() returned 0 with an empty-mode field")
        fails += 1
    if fails:
        return 1
    log.info("SELF-TEST OK: catches the unreferenced callback and the empty "
             "mode, and passes the wired case")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    log = setup_log("check_callback_wiring")
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
