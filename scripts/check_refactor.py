#!/usr/bin/env python3
"""Prove a refactor changed no output. The whole point of a byte oracle.

The converter takes N inputs and produces N files. So a refactor is not a
judgement call about risk -- it either produces the same bytes or it does not,
and this says which. Run it before starting (`--record`) and after every step.

It compares more than the seven committed peripherals, because those are the
ones already known to work and a refactor that only preserves them has proved
the easy half. It also compares the gap census and the compile census, which
between them cover every type in the cut.

Run:  python3 scripts/check_refactor.py --record   # before
      python3 scripts/check_refactor.py            # after, exits 1 on any diff
Log:  ./tmp/logs/check_refactor.log
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import logging
import subprocess
import sys
from pathlib import Path

# (type, method, module) -- the same list check_generated.py drives.
TARGETS = [
    ("STM32_UART", "DefineRegisters", "uart"),
    ("STM32_GPIOPort", "CreateRegisters", "gpio"),
    ("STM32_SYSCFG", "CreateRegisters", "syscfg"),
    ("STM32F4_EXTI", "DefineRegisters", "exti"),
    ("STM32_ADC", "DefineRegisters", "adc"),
    ("STM32DMA", "DefineRegisters", "dma"),
    ("STMCAN", "AddressIsWithinFilterRegistersArea", "can"),
]


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def produce(root: Path) -> tuple[dict[str, str], list[str]]:
    """Every artefact the converter emits, as text, keyed by name.

    The second return value is why this function is not just a dict. A crash is
    NOT an artefact. Recording one produces a baseline that compares equal to
    itself forever and proves nothing -- which is exactly what happened: a fresh
    worktree has no corpus database (it is gitignored), every emit died with
    `no such table: type`, and the recorded baseline was nine identical stack
    traces reported as green. The tool said OK and had verified nothing.

    Same failure class as the six silent no-ops this project has already paid
    for, in the check that was supposed to catch them.
    """
    out: dict[str, str] = {}
    bad: list[str] = []
    for ty, method, mod in TARGETS:
        r = subprocess.run(
            [sys.executable, str(root / "scripts" / "emit.py"),
             "--type", ty, "--method", method, "--file", mod],
            capture_output=True, text=True, cwd=root)
        if r.returncode != 0:
            bad.append(f"{mod}: emit.py exited {r.returncode}: "
                       f"{r.stderr.strip().splitlines()[-1] if r.stderr.strip() else '(no stderr)'}")
            out[f"{mod}.rs"] = f"EMIT FAILED ({r.returncode})\n{r.stderr}"
            continue
        # A plausible module has a header, a `reg` module and a layout fn. A
        # short or headerless one means emit succeeded at producing nothing.
        if "pub fn define_registers" not in r.stdout or len(r.stdout) < 500:
            bad.append(f"{mod}: emitted {len(r.stdout)} bytes with no layout "
                       f"function -- not a module")
        out[f"{mod}.rs"] = r.stdout
    for name, script in (("gaps.txt", "gap_census.py"),
                         ("compile.txt", "compile_check.py")):
        r = subprocess.run([sys.executable, str(root / "scripts" / script)],
                           capture_output=True, text=True, cwd=root)
        if r.returncode != 0:
            bad.append(f"{script} exited {r.returncode}")
        out[name] = r.stdout
    return out, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true",
                    help="write the baseline instead of comparing to it")
    ap.add_argument("--dir", default="tmp/golden")
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_refactor")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" / "check_refactor.log",
                                  mode="w"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    # Checked before anything runs, because its absence is the failure that
    # made a green baseline meaningless. The database is gitignored, so a fresh
    # clone or worktree does not have one.
    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus at rulesdb/patterns.db -- it is gitignored, so a")
        log.error("fresh worktree does not have one. Copy it in or re-ingest;")
        log.error("without it every emit fails and a baseline recorded now")
        log.error("would compare equal to itself forever.")
        return 1

    gold = root / args.dir
    current, bad = produce(root)
    if bad:
        log.error("REFUSING: the converter did not produce usable output.")
        for b in bad:
            log.error("    %s", b)
        log.error("A crash is not an artefact. Recording or comparing one gives")
        log.error("a result that is green and means nothing.")
        return 1

    if args.record:
        gold.mkdir(parents=True, exist_ok=True)
        for name, text in current.items():
            (gold / name).write_text(text)
        log.info("recorded %d artefact(s) under %s", len(current), args.dir)
        for name in sorted(current):
            log.info("    %-14s %s", name,
                     hashlib.sha256(current[name].encode()).hexdigest()[:16])
        return 0

    if not gold.is_dir():
        log.error("no baseline at %s -- run with --record first", args.dir)
        return 1

    bad = 0
    for name in sorted(current):
        want_p = gold / name
        if not want_p.exists():
            log.error("%-14s NO BASELINE", name)
            bad += 1
            continue
        want, got = want_p.read_text(), current[name]
        if want == got:
            log.info("%-14s identical", name)
            continue
        bad += 1
        log.error("%-14s DIFFERS", name)
        diff = list(difflib.unified_diff(
            want.splitlines(), got.splitlines(),
            fromfile=f"baseline/{name}", tofile=f"current/{name}", lineterm=""))
        for line in diff[:40]:
            log.error("    %s", line)
        if len(diff) > 40:
            log.error("    ... %d more diff line(s)", len(diff) - 40)

    log.info("")
    if bad:
        log.error("FAIL: %d artefact(s) changed. A refactor that changes output "
                  "is not a refactor -- either revert it, or if the change is "
                  "intended, re-record and say so in the commit.", bad)
        return 1
    log.info("OK: %d artefact(s) byte-identical to the baseline", len(current))
    return 0


if __name__ == "__main__":
    sys.exit(main())
