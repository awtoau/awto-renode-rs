#!/usr/bin/env python3
"""Mutation-test the peripherals to measure what the oracle can actually see.

A passing trace replay means "indistinguishable from C# Renode ON THIS TRACE",
which is a much weaker claim than it looks. Measured by hand:

  STM32_UART      RXNE W0C->W1C survived a 33,164-access trace
  STM32_GPIOPort  a peripheral returning ZERO FOR EVERY PIN READ passed all
                  four of its traces

Nothing about a green tick distinguishes a thorough trace from a useless one.
Mutation testing is the only signal that does: introduce a defect, and if the
tests still pass, the tests cannot see that defect.

The important output is not the score. It is the SURVIVOR LIST — each survivor
is a behaviour nothing currently checks, and therefore a unit test that should
exist.

Run:  python3 scripts/mutate.py [--target uart] [--tests trace|all]
Log:  ./tmp/logs/mutate.log
Exit: 0 if no survivors, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Mutation operators. The first group is generic; the second is specific to
# register-peripheral semantics, which is where the subtle bugs live and where
# generic operators say nothing useful.
OPERATORS: list[tuple[str, str, str]] = [
    # --- register semantics -------------------------------------------------
    ("w0c->w1c", r"FieldMode::WRITE_ZERO_TO_CLEAR", "FieldMode::WRITE_ONE_TO_CLEAR"),
    ("w1c->w0c", r"FieldMode::WRITE_ONE_TO_CLEAR", "FieldMode::WRITE_ZERO_TO_CLEAR"),
    ("rw->read", r"FieldMode::READ_WRITE", "FieldMode::READ"),
    ("read->rw", r"FieldMode::READ\b(?!_)", "FieldMode::READ_WRITE"),
    ("write->read", r"FieldMode::WRITE\b(?!_)", "FieldMode::READ"),
    # --- generic ------------------------------------------------------------
    ("neq->eq", r"!=", "=="),
    ("eq->neq", r"(?<![!<>=])==", "!="),
    ("and->or", r"&&", "||"),
    ("or->and", r"\|\|", "&&"),
    ("not-removed", r"(?<![!=<>])!(?=[a-z_A-Z(])", ""),
    ("shl-off-by-one", r"<< (\d+)\b", lambda m: f"<< {int(m.group(1)) + 1}"),
    ("true->false", r"\btrue\b", "false"),
    ("false->true", r"\bfalse\b", "true"),
]

# Mutants that provably cannot change behaviour, keyed (target, operator, line
# fragment). Every entry needs a justification in
# src/renode-stm32/tests/equivalent_mutants.md -- an unjustified exclusion is
# indistinguishable from hiding a real survivor.
EQUIVALENT: dict[str, list[tuple[str, str]]] = {
    "gpio": [
        ("read->rw", "f.input_data"),
        ("read->rw", "FieldMode::READ, Some(read_pin_state)"),
        ("rw->read", "FieldMode::READ_WRITE,"),
        ("write->read", "Some(bsrr_set)"),
        ("write->read", "Some(bsrr_reset)"),
    ],
}


def is_equivalent(target: str, mut: "Mutant") -> bool:
    # Match the FULL line: `before` is truncated for display, and matching a
    # truncated string silently failed to exclude a justified mutant.
    return any(op == mut.operator and frag in mut.full
               for op, frag in EQUIVALENT.get(target, []))


TARGETS = {
    "uart": ("src/renode-stm32/src/uart.rs", "uart_trace"),
    "gpio": ("src/renode-stm32/src/gpio_port.rs", "gpio_trace"),
}


@dataclass
class Mutant:
    operator: str
    line: int
    before: str      # truncated, for display only
    after: str
    full: str = ""   # the untruncated source line, for exclusion matching


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def generate(source: str) -> list[tuple[Mutant, str]]:
    """One mutant per applicable site. Mutating every site at once would only
    prove that breaking everything is detectable."""
    out: list[tuple[Mutant, str]] = []
    lines = source.splitlines(keepends=True)
    for name, pattern, repl in OPERATORS:
        rx = re.compile(pattern)
        for i, line in enumerate(lines):
            # Skip comments: mutating comment text changes no behaviour and
            # inflates the survivor count with noise. Trailing comments matter
            # as much as full-line ones -- `// ORE always reads false` was
            # yielding a `false->true` "survivor" that mutated prose.
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            # NB: a distinct index name -- reusing `i` here shadowed the outer
            # enumerate and corrupted every mutant's reported line number.
            code_end = len(line)
            in_str = False
            j = 0
            while j < len(line) - 1:
                if line[j] == '"' and (j == 0 or line[j - 1] != "\\"):
                    in_str = not in_str
                elif not in_str and line[j] == "/" and line[j + 1] == "/":
                    code_end = j
                    break
                j += 1
            for m in rx.finditer(line):
                if m.start() >= code_end:
                    continue
                new_line = line[:m.start()] + (
                    repl(m) if callable(repl) else rx.sub(repl, m.group(0), count=1)
                ) + line[m.end():]
                if new_line == line:
                    continue
                mutated = "".join(lines[:i]) + new_line + "".join(lines[i + 1:])
                out.append((
                    Mutant(name, i + 1, line.strip()[:60], new_line.strip()[:60], line),
                    mutated,
                ))
    return out


def run_tests(root: Path, test: str | None) -> tuple[bool, bool]:
    """Returns (compiled, tests_passed)."""
    cmd = ["cargo", "test", "-p", "renode-stm32", "-q"]
    if test:
        cmd += ["--test", test]
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    compiled = "error[E" not in r.stderr and "could not compile" not in r.stderr
    return compiled, r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=sorted(TARGETS) + ["all"], default="all")
    ap.add_argument("--tests", choices=["trace", "all"], default="trace",
                    help="'trace' measures what the CAPTURED TRACE can see; "
                         "'all' adds the hand-written unit tests")
    ap.add_argument("--limit", type=int, default=0, help="cap mutants (0 = no cap)")
    ap.add_argument("--record", action="store_true",
                    help="write docs/status/mutants.json for the scorecard")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("mutate")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "mutate.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    targets = sorted(TARGETS) if args.target == "all" else [args.target]
    total_survivors = 0
    record: dict[str, dict] = {}

    for name in targets:
        rel, test = TARGETS[name]
        src = root / rel
        backup = src.read_text()
        mutants = generate(backup)
        if args.limit:
            mutants = mutants[:args.limit]

        which = test if args.tests == "trace" else None
        log.info("")
        log.info("%s: %d mutants, judged by %s", name, len(mutants),
                 f"the {test} replay only" if which else "trace + unit tests")

        caught = survived = uncompilable = equivalent = 0
        survivors: list[Mutant] = []
        try:
            for i, (mut, text) in enumerate(mutants, 1):
                src.write_text(text)
                compiled, passed = run_tests(root, which)
                if not compiled:
                    # An equivalent-by-construction mutant: the type system
                    # already rejected it, so no test was ever needed.
                    uncompilable += 1
                elif passed:
                    if is_equivalent(name, mut):
                        equivalent += 1
                    else:
                        survived += 1
                        survivors.append(mut)
                else:
                    caught += 1
                if i % 20 == 0:
                    log.info("  ... %d/%d", i, len(mutants))
        finally:
            src.write_text(backup)

        viable = caught + survived
        score = 100 * caught / viable if viable else 0
        log.info("  compiled-away %d (rejected by the type system)", uncompilable)
        if equivalent:
            log.info("  equivalent    %d (justified in tests/equivalent_mutants.md)",
                     equivalent)
        log.info("  caught %d / %d viable  =  %.0f%% mutation score", caught, viable, score)

        if survivors:
            log.info("  SURVIVORS -- each is a behaviour nothing checks:")
            by_op: dict[str, list[Mutant]] = {}
            for s in survivors:
                by_op.setdefault(s.operator, []).append(s)
            for op in sorted(by_op):
                for s in by_op[op][:4]:
                    log.info("    %-16s line %-4d %s", s.operator, s.line, s.before)
                if len(by_op[op]) > 4:
                    log.info("    %-16s ... and %d more", op, len(by_op[op]) - 4)
        record[name] = {
            "mode": args.tests,
            "caught": caught,
            "viable": viable,
            "score": round(score, 1),
            "equivalent": equivalent,
            "uncompilable": uncompilable,
            "survivors": [{"operator": s.operator, "line": s.line, "code": s.before}
                          for s in survivors],
        }
        total_survivors += survived

    if args.record:
        out = root / "docs" / "status" / "mutants.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        # Merge, so recording one target does not erase the other's result.
        existing = json.loads(out.read_text()) if out.exists() else {}
        existing.update(record)
        out.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
        log.info("recorded %s", out.relative_to(root))

    log.info("")
    if total_survivors:
        log.info("%d surviving mutant(s). Each names a behaviour the current tests "
                 "cannot see -- write the test, do not adjust the score.", total_survivors)
        return 1
    log.info("no survivors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
