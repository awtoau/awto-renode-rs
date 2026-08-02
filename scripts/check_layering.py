#!/usr/bin/env python3
"""Fail if corpus knowledge has leaked into the language layer.

CLAUDE.md states the boundary as a hard rule:

    Nothing project-specific may reach the source. `csharp_core.json` must not
    mention Renode, a peripheral or a register.

That was enforced by nothing. The rule files were separate by convention, and
`emit.py` handled generic C# and Renode idioms side by side in one file. The
first time someone adds a Renode special case to the generic path, the
transpiler stops being reusable -- and it will look exactly like every other
handler, so review will not catch it.

This makes the boundary a build failure instead.

Checked:
  scripts/emitter/lang/**    generic C# to Rust; may not name the corpus
  rulesdb/rules/csharp_core.json    same, in data

Not checked: scripts/emitter/plugins/** and the project rule files, which are
corpus-specific by design and SHOULD name Renode.

Run:  python3 scripts/check_layering.py
Log:  ./tmp/logs/check_layering.log
Exit: 0 clean, 1 on any leak.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

# Words that mean the corpus rather than the language. Deliberately blunt: a
# false positive is a two-second rename, a false negative is a transpiler that
# only works on one codebase.
FORBIDDEN = [
    "renode", "antmicro", "peripheral", "register", "sysbus", "gpio", "uart",
    "irq", "stm32", "cortex", "bank",
]

# Words that are legitimately generic despite matching above. `registered` and
# `registry` are ordinary English; RegisterCollection is not.
ALLOWED = re.compile(
    r"register(ed|s|ing|ation|y)\b|registry|"      # register* as English
    r"\bre-register|unregister(ed)?\b",
    re.IGNORECASE,
)


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def scan_text(text: str, path: Path, log: logging.Logger) -> list[str]:
    bad: list[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        stripped = ALLOWED.sub("", line)
        low = stripped.lower()
        for word in FORBIDDEN:
            if re.search(rf"\b{word}", low):
                bad.append(f"{path}:{n}: says '{word}' -- {line.strip()[:72]}")
    return bad


def main() -> int:
    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_layering")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_layering.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    violations: list[str] = []
    checked = 0

    langdir = root / "scripts" / "emitter" / "lang"
    if langdir.is_dir():
        for py in sorted(langdir.rglob("*.py")):
            checked += 1
            violations += scan_text(py.read_text(),
                                    py.relative_to(root), log)

    # Every language-layer rule document, not just the first one written.
    # `csharp_core.json` was named literally here, so a second generic rule file
    # -- which the work protocol tells agents to create -- was unchecked, and an
    # unchecked file looks exactly like a checked one.
    lang_docs = [root / "rulesdb" / "rules" / "csharp_core.json"]
    for f in sorted((root / "rulesdb" / "rules").glob("*.json")):
        if f not in lang_docs and json.loads(f.read_text()).get("layer") == "language":
            lang_docs.append(f)

    for core in lang_docs:
        if not core.exists():
            continue
        checked += 1
        # Scan the DATA, not the prose: `note` fields explain WHY a mapping
        # exists and may cite the corpus that motivated it. A key or an emitted
        # template naming a peripheral is the actual leak.
        doc = json.loads(core.read_text())

        # Scan only EMITTED TEMPLATES and rule keys -- the things that shape
        # output. Prose fields (note, why, impact) exist precisely to record
        # which corpus motivated a mapping, and naming it there is the
        # documentation working, not a leak.
        TEMPLATE_KEYS = {
            "emit", "decl", "member", "impl", "arm", "closure", "free_fn",
            "reference", "instance", "self", "static", "with_value", "bare",
            "if", "if_else", "ternary", "with_init", "default", "interpolated",
            "hole", "nameof", "numeric", "float_suffix", "array_form",
            "generic_form", "For", "ForEach", "While", "Increment", "Decrement",
            "Read", "Write", "Reset",
        }

        def walk(node, path="", key=None):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{path}.{k}", k)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]", key)
            elif isinstance(node, str):
                if key in TEMPLATE_KEYS or "{" in node:
                    violations.extend(
                        scan_text(node, Path(f"{core.name}{path}"), log))

        walk(doc)

    log.info("checked %d file(s) in the language layer", checked)
    if violations:
        log.error("")
        log.error("LAYER VIOLATION: corpus knowledge in the generic layer.")
        log.error("These belong in scripts/emitter/plugins/ or a project rule")
        log.error("file. The transpiler must work on a corpus that has never")
        log.error("heard of this one.")
        for v in violations:
            log.error("    %s", v)
        return 1
    log.info("OK: the language layer names no corpus construct")
    return 0


if __name__ == "__main__":
    sys.exit(main())
