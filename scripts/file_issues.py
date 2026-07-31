#!/usr/bin/env python3
"""Create the project's GitHub issues from docs/issues-draft.md.

The draft is the source of truth for issue text; this script parses it and
creates one issue per `## <id> — <title>` heading, with the label line that
immediately follows the heading applied as labels.

Idempotent by title: an issue whose title already exists on the repo is skipped,
so a partial run can be resumed safely.

Run:  python3 scripts/file_issues.py [--dry-run]
Log:  ./tmp/logs/file_issues.log
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

DRAFT = "docs/issues-draft.md"

# Labels used by the draft, with colour and description.
LABELS = {
    "epic":       ("7057ff", "Tracking issue spanning multiple phases"),
    "phase-0":    ("0e8a16", "Environment, decisions, performance gate"),
    "phase-1":    ("1d76db", "The corpus database: ingest, analyse, cluster"),
    "phase-2":    ("1d76db", "Stubs and the test harness"),
    "phase-3":    ("1d76db", "Register DSL and rule-driven translation"),
    "phase-4":    ("1d76db", "Corpus-wide rule application"),
    "phase-5":    ("1d76db", "Boot the firmware"),
    "phase-6":    ("1d76db", "Drive the CLI test suite"),
    "phase-7":    ("1d76db", "Optimisation, against a clean differential record"),
    "gate":       ("b60205", "A genuine stop point -- failure means stop, not retry"),
    "decision":   ("d93f0b", "Whole-program decision needing a written verdict"),
    "oracle":     ("fbca04", "Differential validation against C# Renode"),
    "rules":      ("c2e0c6", "Pattern rule DB"),
    "frontend":   ("c5def5", "Roslyn IOperation walker"),
    "peripheral": ("bfd4f2", "A specific peripheral port"),
    "perf":       ("e99695", "Performance measurement or optimisation"),
    "deferred":   ("cccccc", "Research only -- not scheduled, blocks nothing"),
    "research":   ("d4c5f9", "Investigation, not implementation"),
}

HEADING = re.compile(r"^## ([EPR]?\d+) — (.+)$")
LABEL_LINE = re.compile(r"^`[a-z0-9-]+`(?: `[a-z0-9-]+`)*\s*$")


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def gh(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def parse(draft: str) -> list[dict]:
    """Split the draft into issues at `## <id> — <title>` headings."""
    lines = draft.splitlines()
    issues: list[dict] = []
    current: dict | None = None

    for line in lines:
        m = HEADING.match(line)
        if m:
            if current:
                issues.append(current)
            ident, title = m.group(1), m.group(2).strip()
            current = {"id": ident, "title": title, "labels": [], "body": []}
            continue
        if current is None:
            continue  # preamble before the first heading
        # The first non-blank line after the heading, if it is a bare
        # backticked-label line, sets the labels rather than joining the body.
        body_started = any(l.strip() for l in current["body"])
        if not body_started:
            if not line.strip():
                continue  # swallow blank lines between heading and labels/body
            if not current["labels"] and LABEL_LINE.match(line.strip()):
                current["labels"] = re.findall(r"`([a-z0-9-]+)`", line)
                continue
        current["body"].append(line)

    if current:
        issues.append(current)

    for issue in issues:
        # Trim leading/trailing blank lines from the body.
        body = issue["body"]
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        issue["body"] = "\n".join(body)
    return issues


def ensure_labels(log: logging.Logger, dry: bool) -> None:
    existing = {l["name"] for l in json.loads(gh("label", "list", "--json", "name", "--limit", "100"))}
    for name, (colour, desc) in LABELS.items():
        if name in existing:
            continue
        log.info("creating label %s", name)
        if not dry:
            gh("label", "create", name, "--color", colour, "--description", desc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="parse and report, create nothing")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger("file_issues")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "file_issues.log"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    issues = parse((root / DRAFT).read_text(encoding="utf-8"))
    log.info("parsed %d issues from %s", len(issues), DRAFT)

    ensure_labels(log, args.dry_run)

    existing_titles = {
        i["title"] for i in
        json.loads(gh("issue", "list", "--state", "all", "--limit", "200", "--json", "title"))
    }

    created = skipped = 0
    for issue in issues:
        title = f"{issue['id']} — {issue['title']}"
        if title in existing_titles:
            log.info("skip (exists): %s", title)
            skipped += 1
            continue
        log.info("create: %s  labels=%s  body=%d chars",
                 title, ",".join(issue["labels"]) or "-", len(issue["body"]))
        if args.dry_run:
            continue
        cmd = ["issue", "create", "--title", title, "--body", issue["body"]]
        for label in issue["labels"]:
            cmd += ["--label", label]
        url = gh(*cmd).strip()
        log.info("  -> %s", url)
        created += 1

    log.info("done: %d created, %d skipped%s",
             created, skipped, " (dry run)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
