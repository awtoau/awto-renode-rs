#!/usr/bin/env python3
"""Is a hand-written translation reproducible from the corpus? Issue #35.

PLAN.md's standard: *a landed translation must be recreatable from the C# source
plus committed rules and scripts alone. File-specific hand edits are evidence the
generic process is incomplete.*

This tests that claim for the declarative half. It emits a peripheral's register
layout from the corpus and diffs it against the layout in the hand-written Rust.
Agreement means the file is rule output that happens to have been typed by hand,
and its `is_patch` flag can drop. Disagreement names exactly what the emitter
cannot yet produce.

Comparison is on the SEQUENCE OF COMBINATOR CALLS, not on text: whitespace,
line breaks and comments are formatting, and treating them as differences would
report noise. Argument values are compared exactly, because those are semantics.

Run:  python3 scripts/verify_emit.py [--target uart]
Log:  ./tmp/logs/verify_emit.log
Exit: 0 if every target is reproducible, 1 otherwise.
"""

from __future__ import annotations

import argparse
import difflib
import logging
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
from emit import Emitter  # noqa: E402

# (C# type, C# method, Rust file, the fn holding the layout)
TARGETS = {
    # uart is no longer listed: its layout is GENERATED and enforced
    # byte-for-byte by check_generated.py, which is a stronger guarantee than
    # this diff. This tool is for layouts still written by hand.
    "gpio": ("STM32_GPIOPort", "CreateRegisters",
             "src/renode-stm32/src/gpio_port.rs", "create_registers"),
}

CALL = re.compile(r"\.(with_[a-z_]+)\(([^;]*?)\)\s*(?://.*)?$")


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def normalise(call: str) -> str:
    """Reduce an emitted or hand-written call to comparable form.

    Drops comments and collapses whitespace. Keeps every argument, since those
    carry the semantics the oracle would otherwise have to catch.
    """
    call = re.sub(r"//.*$", "", call).strip()
    call = re.sub(r"\s+", " ", call)
    call = call.replace("( ", "(").replace(" )", ")")
    # Rustfmt leaves a trailing comma on multi-line argument lists. That is
    # formatting, not semantics, and treating it as a difference reported two
    # identical calls as divergent.
    call = re.sub(r",\s*\)", ")", call)
    return call.rstrip(",")


def hand_written_calls(path: Path, fn_name: str) -> list[str]:
    """Extract the combinator sequence from the hand-written Rust."""
    text = path.read_text()
    start = text.find(f"fn {fn_name}(")
    if start < 0:
        return []
    body = text[start:]
    # Join continuation lines so a call split across lines reads as one.
    flat = re.sub(r"\n\s+", " ", body)
    out = []
    for m in re.finditer(r"\.(with_[a-z_]+)\(((?:[^()]|\([^()]*\))*)\)", flat):
        out.append(normalise(f".{m.group(1)}({m.group(2)})"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=sorted(TARGETS) + ["all"], default="all")
    ap.add_argument("--db", default="rulesdb/patterns.db")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("verify_emit")
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(logdir / "verify_emit.log", mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(fh)
    log.addHandler(sh)

    import sqlite3
    con = sqlite3.connect(root / args.db)
    em = Emitter(con, log)

    targets = sorted(TARGETS) if args.target == "all" else [args.target]
    failed = 0

    for name in targets:
        cs_type, cs_method, rust_rel, rust_fn = TARGETS[name]
        generated = [normalise(l) for l in em.emit_method(cs_type, cs_method)]
        handwritten = hand_written_calls(root / rust_rel, rust_fn)

        log.info("")
        log.info("%s: %d generated vs %d hand-written combinator calls",
                 name, len(generated), len(handwritten))

        if generated == handwritten:
            log.info("  REPRODUCIBLE — the hand-written layout is exactly what the "
                     "emitter produces")
            continue

        failed += 1
        matcher = difflib.SequenceMatcher(None, generated, handwritten)
        same = sum(b.size for b in matcher.get_matching_blocks())
        log.info("  %d/%d calls agree (%.0f%%)", same, max(len(generated), 1),
                 100 * same / max(len(generated), 1))
        shown = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal" or shown >= 12:
                continue
            for line in generated[i1:i2]:
                log.info("    emitted only:  %s", line)
                shown += 1
            for line in handwritten[j1:j2]:
                log.info("    hand-written:  %s", line)
                shown += 1

    con.close()
    log.info("")
    if failed:
        log.info("%d target(s) not yet reproducible. Each difference is either an "
                 "emitter gap or a hand edit that should not exist.", failed)
        return 1
    log.info("all targets reproducible from the corpus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
