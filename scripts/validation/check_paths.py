#!/usr/bin/env python3
"""Fail if any tracked file contains a machine-specific absolute path.

This repo is public. Absolute paths leak the local filesystem layout, the
existence of private sibling repos, and sometimes usernames. They are also
simply wrong in a shared repo: nobody else's checkout lives where ours does.

The rule, in full:

  - Docs reference repos by name and files by REPO-RELATIVE path.
  - Scripts resolve this workspace with `git rev-parse --show-toplevel`
    (or Path(__file__).parents[N]) -- never a hardcoded root.
  - EXTERNAL trees (the Renode checkout, the firmware repo) come from
    environment variables, documented in the tracked `.env.example` and set
    in a gitignored `.env`.

Run:  python3 scripts/check_paths.py
Log:  ./tmp/logs/check_paths.log
Exit: 0 clean, 1 violations found.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

# Absolute-path shapes that must never appear in a tracked file.
FORBIDDEN = [
    (re.compile(r"/mnt/[A-Za-z0-9_.-]+"), "absolute /mnt path"),
    (re.compile(r"/home/[A-Za-z0-9_.-]+"), "absolute /home path"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+"), "absolute macOS /Users path"),
    (re.compile(r"[A-Za-z]:\\\\"), "absolute Windows path"),
]

# Files exempt from the scan: this checker (it names the patterns it forbids)
# and the env template (it documents what the variables are for).
EXEMPT = {"scripts/validation/check_paths.py", ".env.example"}


def repo_root() -> Path:
    """The workspace root, resolved from git rather than hardcoded."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    )
    return Path(out.stdout.strip())


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def scan(root: Path, log: logging.Logger) -> int:
    violations = 0
    for rel in tracked_files(root):
        if rel in EXEMPT:
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # binary or deleted-but-staged; nothing to check
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, label in FORBIDDEN:
                match = pattern.search(line)
                if match:
                    log.error("%s:%d: %s -- %s", rel, lineno, label, match.group(0))
                    violations += 1
    return violations


def main() -> int:
    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger("check_paths")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.FileHandler(logdir / "check_paths.log"),
                    logging.StreamHandler(sys.stdout)):
        handler.setFormatter(fmt)
        log.addHandler(handler)

    log.info("scanning tracked files under %s", root.name)
    violations = scan(root, log)

    if violations:
        log.error("FAIL: %d absolute path(s) in tracked files", violations)
        log.error("Fix: use repo-relative paths in docs; "
                  "git rev-parse --show-toplevel in scripts; "
                  "env vars from .env.example for external trees.")
        return 1

    log.info("OK: no absolute paths in tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
