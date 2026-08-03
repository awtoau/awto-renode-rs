#!/usr/bin/env python3
"""`renode_regs::FieldMode` must be the C# `FieldMode`, member for member.

WHY THIS EXISTS
---------------
The emitter no longer keeps a table of FieldMode bits: it reads the enum from
the corpus and renders each member as the same name in SCREAMING_SNAKE. That
removes one second source of truth and creates a smaller one -- the ASSUMPTION
that `renode_regs` declares a constant of that name, with that value.

Nothing else would notice if it did not. `render_mode` would emit
`FieldMode::WRITE_TO_SET` for a corpus member the runtime has never heard of,
and the failure would surface as a rustc error in a scratch crate, attributed
to generated code rather than to the runtime that is missing a constant --
or, worse, as a constant that exists with the WRONG VALUE, which compiles
perfectly and silently gives the field somebody else's behaviour.

The C# enum has holes: `1 << 9` and `1 << 10` are unassigned, and `ReadToSet`
is `1 << 11`. A runtime that renumbered them densely would look right and be
wrong at every site, so the values are compared and not just the names.

WHAT IT DOES NOT CHECK
----------------------
That each mode BEHAVES like its C# counterpart. That is what the `renode_regs`
unit tests do, one test per mode, written against `WriteInner`'s switch. This
check is about the vocabulary, not the semantics.

Run:  python3 scripts/check_field_mode.py
      python3 scripts/check_field_mode.py --self-test
Log:  ./tmp/logs/check_field_mode.log
Exit: 1 on any mismatch in either direction. A hard gate; it passes at zero.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # for `emitter`

from emitted_modules import repo_root, setup_log  # noqa: E402

# `pub const READ_TO_CLEAR: Self = Self(1 << 6);` -- the only form the runtime
# uses. A constant written any other way is reported as missing rather than
# guessed at, because a lenient parser here would defeat the check.
_CONST = re.compile(
    r"^\s*pub const ([A-Z][A-Z0-9_]*): Self = Self\(1 << (\d+)\);", re.M)

# Composites, which name no C# member and must not be compared against one.
_COMPOSITE = {"READ_WRITE"}


def runtime_mode_bits(text: str) -> dict[int, str]:
    """The `FieldMode` constants `renode_regs` declares, from its source.

    Reads the artefact rather than asking the emitter, for the same reason
    `emitted_modules.py` parses emitted Rust: the thing under test must not be
    the thing consulted.
    """
    body = text.split("impl FieldMode {", 1)
    if len(body) < 2:
        return {}
    body = body[1].split("\n}", 1)[0]
    return {1 << int(shift): name
            for name, shift in _CONST.findall(body)
            if name not in _COMPOSITE}


def corpus_mode_bits(con: sqlite3.Connection) -> dict[int, str]:
    """The C# enum, as the emitter reads it. Same function, not a copy."""
    from emitter.plugins.register_dsl import field_mode_bits
    return {bit: name.removeprefix("FieldMode::")
            for bit, name in field_mode_bits(con).items()}


def run(corpus: dict[int, str], runtime: dict[int, str], log) -> int:
    found = 0
    for bit in sorted(set(corpus) | set(runtime)):
        c, r = corpus.get(bit), runtime.get(bit)
        if c == r:
            continue
        found += 1
        if r is None:
            log.error("    MISSING FROM renode_regs   1 << %-2d  C# `%s`",
                      bit.bit_length() - 1, c)
            log.error("        the emitter renders this member as "
                      "`FieldMode::%s`, which does not exist", c)
        elif c is None:
            log.error("    NOT IN THE C# ENUM         1 << %-2d  Rust `%s`",
                      bit.bit_length() - 1, r)
            log.error("        a constant no corpus member maps to: either the "
                      "value is wrong or the mode is invented")
        else:
            log.error("    NAME MISMATCH              1 << %-2d  C# `%s` vs "
                      "Rust `%s`", bit.bit_length() - 1, c, r)

    log.info("C# declares %d member(s); renode_regs declares %d constant(s)",
             len(corpus), len(runtime))
    if found:
        log.error("")
        log.error("FAIL: %d FieldMode member(s) do not line up.", found)
        log.error("`render_mode` names a Rust constant per corpus member by "
                  "convention, so a")
        log.error("member the runtime lacks emits a name that does not "
                  "compile, and a member")
        log.error("whose VALUE differs emits a field with somebody else's "
                  "behaviour -- which")
        log.error("does compile.")
        return 1
    log.info("OK: every C# FieldMode member has a renode_regs constant of the "
             "same name and value")
    return 0


def self_test(log) -> int:
    fails = 0
    src = """
impl FieldMode {
    pub const READ: Self = Self(1 << 0);
    pub const WRITE: Self = Self(1 << 1);
    pub const READ_TO_SET: Self = Self(1 << 11);
    pub const READ_WRITE: Self = Self(Self::READ.0 | Self::WRITE.0);
}
"""
    got = runtime_mode_bits(src)
    if got != {1: "READ", 2: "WRITE", 1 << 11: "READ_TO_SET"}:
        log.error("SELF-TEST FAIL: the constant parser read %r. READ_WRITE is "
                  "a composite and must not be treated as a C# member.", got)
        fails += 1

    corpus = {1: "READ", 2: "WRITE", 1 << 11: "READ_TO_SET"}
    if run(corpus, got, log) != 0:
        log.error("SELF-TEST FAIL: matching sets reported a mismatch")
        fails += 1
    # A member the runtime lacks.
    if run({**corpus, 1 << 6: "READ_TO_CLEAR"}, got, log) == 0:
        log.error("SELF-TEST FAIL: a C# member with no runtime constant was "
                  "not reported")
        fails += 1
    # The dense-renumbering mistake: right name, wrong bit.
    if run(corpus, {1: "READ", 2: "WRITE", 1 << 6: "READ_TO_SET"}, log) == 0:
        log.error("SELF-TEST FAIL: READ_TO_SET at the wrong bit was not "
                  "reported -- comparing names alone would miss it")
        fails += 1
    if fails:
        return 1
    log.info("SELF-TEST OK: parses the constants, ignores composites, and "
             "reports a missing member and a wrong value")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    log = setup_log("check_field_mode")
    if args.self_test:
        return self_test(log)

    root = repo_root()
    db = root / args.db
    if not db.exists():
        log.error("no corpus at %s -- it is gitignored, so a fresh worktree "
                  "does not have one. Copy it in or re-ingest.", args.db)
        return 1
    lib = root / "src" / "renode-regs" / "src" / "lib.rs"
    runtime = runtime_mode_bits(lib.read_text())
    if not runtime:
        log.error("found no `impl FieldMode` constants in "
                  "src/renode-regs/src/lib.rs -- a silent pass would be a lie")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    corpus = corpus_mode_bits(con)
    if not corpus:
        log.error("the corpus has no `FieldMode` enum -- re-ingest")
        return 1
    return run(corpus, runtime, log)


if __name__ == "__main__":
    sys.exit(main())
