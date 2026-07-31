#!/usr/bin/env python3
"""Fail if derived data has been copied into hand-written source.

`check_paths.py` catches absolute paths. It caught nothing when platform reset
values were retyped from the `.repl` into Rust tests, because that is a
different class of violation: a *second source of truth*. Change the platform
and the copy keeps asserting the old value while passing — the failure is
silent, which is the worst kind.

So: any distinctive value that appears in a derived artifact must not also
appear literally in hand-written source. Derived files declare themselves
generated and are exempt; everything else must read the value, not repeat it.

Two deliberate limits, because a check that cries wolf gets disabled:

  - Only DISTINCTIVE values are checked. `0`, `1`, `16` occur everywhere and
    carry no provenance. Hex constants of >= 4 digits and multi-word names do.
  - A value is only a violation in a file that could reasonably have read it
    instead. Docs and commit-message-like prose are exempt: recording that
    `modeResetValue` is `0xA8000000` in a design note is documentation, not a
    second source of truth.

Run:  python3 scripts/check_derived.py
Log:  ./tmp/logs/check_derived.log
Exit: 0 clean, 1 duplication found.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

DERIVED = [
    ("docs/status/platform.json", "scripts/parse_repl.py"),
]

# Files that are themselves generated from the derived data, or are the
# generator, or are documentation rather than executable truth.
EXEMPT_SUFFIXES = (".md", ".json")
EXEMPT_FILES = {
    "src/renode-stm32/src/platform.rs",   # generated
    "scripts/parse_repl.py",              # the generator
    "scripts/check_derived.py",           # this file
}

# A hex literal of >=4 digits is distinctive enough to be provenance-bearing --
# with one exception. Round powers of two (0x1000, 0x10000, ...) are ubiquitous
# sizes that carry no provenance: flagging a 4 KiB test buffer as "bkpsram.size"
# is a false positive, and false positives are how a check gets disabled.
HEX = re.compile(r"^0x[0-9A-Fa-f]{4,}$")


def is_distinctive(literal: str) -> bool:
    if not HEX.match(literal):
        return False
    v = int(literal, 16)
    return v & (v - 1) != 0  # not a power of two


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files"],
                         capture_output=True, text=True, check=True)
    return [f for f in out.stdout.splitlines() if f]


def distinctive_values(data: dict) -> dict[str, str]:
    """Map a searchable literal -> what it is, for reporting."""
    found: dict[str, str] = {}
    for name, entry in data.get("peripherals", {}).items():
        for key, value in (entry.get("params") or {}).items():
            v = str(value).strip()
            if is_distinctive(v):
                found[v.lower()] = f"{name}.{key}"
        addr = entry.get("address")
        if isinstance(addr, int) and addr > 0xFFF and is_distinctive(hex(addr)):
            found[hex(addr)] = f"{name} address"
    return found


def variants(literal: str) -> set[str]:
    """Spellings the same constant can take in source."""
    body = literal[2:]
    out = {f"0x{body}", f"0x{body.upper()}", f"0x{body.lower()}"}
    # Rust/Python underscore grouping, e.g. 0xA800_0000
    if len(body) == 8:
        for b in (body, body.upper(), body.lower()):
            out.add(f"0x{b[:4]}_{b[4:]}")
    return out


def main() -> int:
    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_derived")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_derived.log"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    violations = 0
    for rel, generator in DERIVED:
        path = root / rel
        if not path.exists():
            log.info("skip %s (not generated yet -- run %s)", rel, generator)
            continue
        values = distinctive_values(json.loads(path.read_text()))
        log.info("checking %d distinctive value(s) from %s", len(values), rel)

        for f in tracked(root):
            if f in EXEMPT_FILES or f.endswith(EXEMPT_SUFFIXES):
                continue
            try:
                text = (root / f).read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for literal, what in values.items():
                    for spelling in variants(literal):
                        if spelling in line:
                            log.error("%s:%d: %s is %s, derived in %s",
                                      f, lineno, spelling, what, rel)
                            violations += 1
                            break

    if violations:
        log.error("FAIL: %d value(s) copied out of derived data.", violations)
        log.error("Read them from the derived artifact instead of repeating them; "
                  "a copy drifts silently when the source changes.")
        return 1
    log.info("OK: no derived values duplicated into hand-written source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
