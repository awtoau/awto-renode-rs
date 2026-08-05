#!/usr/bin/env python3
"""Refuse to commit a hand-written peripheral. Pre-commit, hard failure.

THE FAILURE THIS EXISTS TO STOP
-------------------------------
An agent asked to "translate STM32_UART" writes the file by hand, it passes its
tests, and it gets described as a translation. It is not: it is a hand-written
file that happens to resemble one. The evidence, from this project:

  - `.with_reserved(9, 23)` was written into uart.rs. The C# has no such call.
    Invented, and behaviourally inert, so the trace oracle and mutation testing
    both passed it.
  - A dummy `ValueId::default()` handle was written where the C# has a computed
    field with no storage.
  - Four fields were renamed, making the file unreproducible without a per-file
    rename table.

None of that was caught by tests. It was caught by regenerating and diffing.

PLAN.md already required "recreatable from the C# source plus committed rules
and scripts alone", and stating it was not enough. So this is enforced:

  **A file listed in GENERATED must be byte-identical to what the converter
  produces from the corpus. Editing it by hand is a commit failure.**

The converter must be GENERAL — driven by the corpus database, working on any
C# input — never a per-peripheral special case. A "rule" that only ever matches
one site is a hand-written file wearing a rule's name.

Run:  python3 scripts/check_generated.py
Log:  ./tmp/logs/check_generated.log
Exit: 0 clean, 1 if any generated file was hand-edited.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Files the converter owns. Adding a file here is a commitment that it is
# machine-produced; it must never be edited by hand again.
#
# uart_registers.rs is the first file the converter owns. uart.rs itself is NOT
# listed: it holds behaviour the converter cannot yet emit, and listing it would
# assert something false. The split is deliberate -- the boundary between
# generated and hand-written is a FILE boundary, so it can be enforced
# byte-for-byte rather than by convention.
GENERATED: list[tuple[str, list[str]]] = [
    ("src/renode-stm32/src/uart_registers.rs",
     ["scripts/core/csharp_emitter.py", "--type", "STM32_UART", "--method", "DefineRegisters",
      "--file", "uart_registers"]),
    ("src/renode-stm32/src/gpio_registers.rs",
     ["scripts/core/csharp_emitter.py", "--type", "STM32_GPIOPort", "--method", "CreateRegisters",
      "--file", "gpio_registers"]),
    ("src/renode-stm32/src/syscfg_registers.rs",
     ["scripts/core/csharp_emitter.py", "--type", "STM32_SYSCFG", "--method", "CreateRegisters",
      "--file", "syscfg_registers"]),
    ("src/renode-stm32/src/exti_registers.rs",
     ["scripts/core/csharp_emitter.py", "--type", "STM32F4_EXTI", "--method", "DefineRegisters",
      "--file", "exti_registers"]),
    ("src/renode-stm32/src/adc_registers.rs",
     ["scripts/core/csharp_emitter.py", "--type", "STM32_ADC", "--method", "DefineRegisters",
      "--file", "adc_registers"]),
    ("src/renode-stm32/src/dma_registers.rs",
     ["scripts/core/csharp_emitter.py", "--type", "STM32DMA", "--method", "DefineRegisters",
      "--file", "dma_registers"]),
    ("src/renode-stm32/src/can_registers.rs",
     ["scripts/core/csharp_emitter.py", "--type", "STMCAN", "--method",
      "AddressIsWithinFilterRegistersArea", "--file", "can_registers"]),
    # Not keyed on a type: the corpus decides which interfaces appear, and one
    # that cannot be expressed completely is withheld and named in the header.
    # A hand edit here would be a trait asserting membership the C# does not.
    ("src/renode-stm32/src/interfaces.rs",
     ["scripts/core/csharp_emitter.py", "--interfaces"]),
    # Also keyed on no type: the trait spans the modules above, so it is a
    # function of ALL of them and moves whenever any one does. It reads this
    # list to know which, and regenerates each in memory rather than reading the
    # committed file -- otherwise a stale peripheral on disk would reshape the
    # trait and the two checks would disagree about which is wrong.
    ("src/renode-stm32/src/dispatch.rs",
     ["scripts/core/csharp_emitter.py", "--dispatch"]),
]

# Peripheral sources that must EVENTUALLY be generated. Their presence here is
# the outstanding debt, and the scorecard reports it.
MUST_BECOME_GENERATED = [
    "src/renode-stm32/src/uart.rs        (behaviour only; layout is generated)",
    "src/renode-stm32/src/gpio_port.rs   (behaviour only; layout is generated)",
]


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def main() -> int:
    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_generated")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_generated.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    # The generators are independent processes writing nothing but their own
    # stdout, so they run at once. `map` yields in GENERATED order, so the log
    # reads identically to the serial version -- this is a pre-commit gate, and
    # a gate whose report reshuffles run to run is one people stop reading.
    #
    # It was 25s serial. That is 25s on every commit of a hook that was already
    # being skipped for being slow, which is the whole reason this work exists.
    def generate(job):
        rel, argv = job
        if not (root / rel).exists():
            return None
        return subprocess.run([sys.executable, *argv], cwd=root,
                              capture_output=True, text=True)

    with ThreadPoolExecutor(max_workers=max(1, min(len(GENERATED) or 1,
                                                   os.cpu_count() or 8))) as p:
        produced_all = list(p.map(generate, GENERATED))

    violations = 0
    for (rel, _argv), produced in zip(GENERATED, produced_all):
        path = root / rel
        if produced is None:
            log.error("%s is listed as generated but does not exist", rel)
            violations += 1
            continue
        if produced.returncode != 0:
            log.error("%s: generator failed: %s", rel, produced.stderr.strip()[:300])
            violations += 1
            continue
        if produced.stdout != path.read_text():
            log.error("%s HAS BEEN HAND-EDITED -- it differs from generator output.",
                      rel)
            log.error("  Regenerate it, or change the converter. Do not edit the file.")
            violations += 1
        else:
            log.info("ok  %s matches generator output", rel)

    if not GENERATED:
        log.info("no generated files yet")
    if MUST_BECOME_GENERATED:
        log.info("")
        log.info("OUTSTANDING: %d peripheral(s) still hand-written, and therefore "
                 "not translations:", len(MUST_BECOME_GENERATED))
        for f in MUST_BECOME_GENERATED:
            log.info("    %s", f)
        log.info("Run scripts/verify_emit.py to see exactly what the converter "
                 "cannot yet reproduce.")

    if violations:
        log.error("FAIL: %d generated file(s) hand-edited", violations)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
