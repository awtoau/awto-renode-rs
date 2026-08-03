#!/usr/bin/env python3
"""Canonical development entry point for awto-renode-rs.

Agents: ``python3 scripts/dev.py describe`` emits machine-readable help.
Humans: ``python3 scripts/dev.py --help`` lists the same registry.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

PROJECT = "awto-renode-rs"
REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "tmp" / "logs" / "dev.log"
SKIPPED = 125

Handler = Callable[[list[str]], int]
COMMANDS: dict[str, dict[str, object]] = {}


def stamp() -> str:
    return datetime.now().astimezone().strftime("%H:%M:%S.%f%z")


def log(message: str, level: str = "INFO") -> None:
    line = f"{stamp()}  {level:<5} [dev.py] {message}"
    print(line, file=sys.stderr, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as output:
        output.write(line + "\n")


def command(summary: str, *, args: str = "", kind: str = "action"):
    def decorate(handler: Handler) -> Handler:
        name = handler.__name__.removeprefix("cmd_").replace("_", "-")
        COMMANDS[name] = {
            "summary": summary, "args": args, "kind": kind, "handler": handler,
        }
        return handler
    return decorate


def run(argv: list[str], *, label: str | None = None) -> int:
    shown = label or display(argv)
    log(f"START {shown}")
    result = subprocess.run(argv, cwd=REPO)
    log(f"{'PASS' if result.returncode == 0 else 'FAIL'} {shown} rc={result.returncode}",
        "INFO" if result.returncode == 0 else "ERROR")
    return result.returncode


def run_sequence(steps: list[tuple[str, list[str]]]) -> int:
    for name, argv in steps:
        rc = run(argv, label=name)
        if rc:
            log(f"stopped at {name}; later stages did not run", "FATAL")
            return rc
    return 0


def display(argv: list[str]) -> str:
    shown = ["python3", *argv[1:]] if argv and argv[0] == sys.executable else argv
    return " ".join(shown)


@command("machine-readable command registry", kind="meta")
def cmd_describe(_extra: list[str]) -> int:
    print(json.dumps({
        "project": PROJECT,
        "schema": 1,
        "entrypoint": "python3 scripts/dev.py",
        "log": str(LOG.relative_to(REPO)),
        "exit_codes": {"0": "success", "2": "usage", "125": "skipped", "other": "failure"},
        "commands": {
            name: {key: value for key, value in meta.items() if key != "handler"}
            for name, meta in sorted(COMMANDS.items())
        },
    }, indent=2))
    return 0


@command("check required development tools and shared awto-dan rules", kind="meta")
def cmd_doctor(_extra: list[str]) -> int:
    missing = [tool for tool in ("cargo", "git", "gh", "codex") if not shutil.which(tool)]
    for tool in ("cargo", "git", "gh", "codex"):
        log(f"{tool}: {'MISSING' if tool in missing else 'ok'}",
            "ERROR" if tool in missing else "INFO")
    shared = awto_dan()
    if shared is None:
        log("awto-dan: set AWTO_DAN or place it beside this checkout", "ERROR")
        missing.append("awto-dan")
    else:
        log("awto-dan: canonical Codex rules found")
    return 1 if missing else 0


@command("verify help, JSON registry, and exit-code contract", kind="meta")
def cmd_selftest(_extra: list[str]) -> int:
    failures: list[str] = []
    described = subprocess.run(
        [sys.executable, __file__, "describe"], cwd=REPO,
        capture_output=True, text=True,
    )
    try:
        payload = json.loads(described.stdout)
    except json.JSONDecodeError:
        payload = {}
    checks = {
        "describe exits 0": described.returncode == 0,
        "describe is JSON": bool(payload),
        "project and commands present": {"project", "commands"} <= payload.keys(),
        "standard commands present": {"build", "test", "gate", "ci", "report", "cycle", "codex"}
        <= payload.get("commands", {}).keys(),
        "every command summarized": all(
            meta.get("summary") for meta in payload.get("commands", {}).values()
        ),
        "registry handlers unique": len({id(meta["handler"]) for meta in COMMANDS.values()})
        == len(COMMANDS),
    }
    helped = subprocess.run(
        [sys.executable, __file__, "--help"], cwd=REPO,
        capture_output=True, text=True,
    )
    unknown = subprocess.run(
        [sys.executable, __file__, "no-such-command"], cwd=REPO,
        capture_output=True, text=True,
    )
    checks.update({
        "help exits with usage status": helped.returncode == 2,
        "help lists every command": all(name in helped.stdout for name in COMMANDS),
        "unknown command exits with usage status": unknown.returncode == 2,
    })
    for name, passed in checks.items():
        log(f"{name}: {'ok' if passed else 'FAIL'}", "INFO" if passed else "ERROR")
        if not passed:
            failures.append(name)
    return 1 if failures else 0


@command("compile the known-clean set plus types touched by the diff", kind="step")
def cmd_build(extra: list[str]) -> int:
    return run([sys.executable, "scripts/compile_check.py",
                "--working-set", "--ratchet", *extra])


@command("regenerate every converter-owned output", kind="action")
def cmd_regenerate(extra: list[str]) -> int:
    return run([sys.executable, "scripts/regenerate.py", *extra])


@command("run the Rust workspace test suite", kind="step")
def cmd_test(extra: list[str]) -> int:
    return run(["cargo", "test", "--workspace", *extra])


@command("run the fail-fast everyday validation tier", kind="aggregate")
def cmd_gate(extra: list[str]) -> int:
    return run([sys.executable, "scripts/gates.py", *extra])


@command("run the full push-tier validation census", kind="aggregate")
def cmd_ci(extra: list[str]) -> int:
    return run([sys.executable, "scripts/gates.py", "--full", *extra])


@command("run the full push-tier validation census in fail-fast mode",
         kind="aggregate")
def cmd_ci_fast(extra: list[str]) -> int:
    return run([sys.executable, "scripts/gates.py", "--full", "--fail-fast",
                *extra])


@command("run determinism proofs (ingest and emitter)", kind="aggregate")
def cmd_ci_determinism(extra: list[str]) -> int:
    if extra:
        log("ci-determinism accepts no extra arguments", "ERROR")
        return 2
    return run_sequence([
        ("ingest determinism", [sys.executable, "scripts/check_determinism.py"]),
        ("emitter determinism", [sys.executable, "scripts/check_emit_determinism.py"]),
    ])


@command("issue-62 crash census (compile + gap, fail if converter crashes)",
         kind="aggregate")
def cmd_issue_62(extra: list[str]) -> int:
    if extra:
        log("issue-62 accepts no extra arguments", "ERROR")
        return 2
    rc = run_sequence([
        ("compile census", [sys.executable, "scripts/compile_check.py", "--ratchet"]),
        ("gap census", [sys.executable, "scripts/gap_census.py"]),
    ])
    if rc:
        return rc

    crash_patterns = [
        re.compile(r"emit crashed on .*: list index out of range", re.I),
        re.compile(r"CONVERTER CRASH:\s*IndexError", re.I),
        re.compile(r"Traceback \(most recent call last\)", re.I),
    ]
    offenders: list[str] = []
    for rel in ("tmp/logs/compile_check.log", "tmp/logs/gap_census.log"):
        p = REPO / rel
        text = p.read_text(encoding="utf-8") if p.exists() else ""
        hits = sum(1 for pat in crash_patterns if pat.search(text))
        if hits:
            offenders.append(f"{rel} ({hits} crash pattern hit(s))")

    if offenders:
        log("issue-62 FAILED: converter crash signatures still present", "ERROR")
        for item in offenders:
            log(f"  {item}", "ERROR")
        return 1

    log("issue-62 OK: no converter crash signatures in compile/gap logs")
    return 0


REPORT_STEPS = [
    ("scorecard", [sys.executable, "scripts/reports/scorecard.py"]),
    ("progress report (docs/status/progress.html, two charts)",
     [sys.executable, "scripts/reports/progress_graph.py"]),
]


@command("refresh STATUS.md plus docs/status/progress.html", kind="aggregate")
def cmd_report(extra: list[str]) -> int:
    if extra:
        log("report accepts no extra arguments", "ERROR")
        return 2
    return run_sequence(REPORT_STEPS)


@command("regenerate, run full checks, then refresh reports", kind="aggregate")
def cmd_cycle(extra: list[str]) -> int:
    if extra == ["--dry-run"]:
        for name, argv in [
            ("regenerate", [sys.executable, "scripts/regenerate.py"]),
            ("check", [sys.executable, "scripts/gates.py", "--full"]),
            *REPORT_STEPS,
        ]:
            print(f"{name}: {display(argv)}")
        return 0
    if extra:
        log("cycle accepts only --dry-run", "ERROR")
        return 2
    return run_sequence([
        ("regenerate", [sys.executable, "scripts/regenerate.py"]),
        ("check", [sys.executable, "scripts/gates.py", "--full"]),
        *REPORT_STEPS,
    ])


def awto_dan() -> Path | None:
    configured = os.environ.get("AWTO_DAN")
    candidates = [Path(configured)] if configured else []
    candidates.append(REPO.parent / "awto-dan")
    for candidate in candidates:
        brief = candidate / "scripts" / "codex_brief.py"
        if brief.is_file():
            return candidate
    return None


@command(
    "run Codex in an isolated worktree using canonical awto-dan rules",
    args="--work TEXT --cd WORKTREE [--issue N] [--repo OWNER/REPO] [--extra FILE] [--model MODEL]",
    kind="action",
)
def cmd_codex(extra: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="scripts/dev.py codex")
    parser.add_argument("--work", required=True)
    parser.add_argument("--cd", required=True, dest="worktree")
    parser.add_argument("--issue", type=int)
    parser.add_argument("--repo")
    parser.add_argument("--extra", action="append", default=[])
    parser.add_argument("--model")
    try:
        args = parser.parse_args(extra)
    except SystemExit as exc:
        return int(exc.code)

    shared = awto_dan()
    if shared is None:
        log("cannot find awto-dan; set AWTO_DAN", "ERROR")
        return 1
    worktree = (REPO / args.worktree).resolve()
    if worktree == REPO or not (worktree / ".git").exists():
        log("--cd must name a linked worktree, never the main checkout", "ERROR")
        return 1
    database = worktree / "rulesdb" / "patterns.db"
    if not database.exists():
        log("worktree has no rulesdb/patterns.db corpus", "ERROR")
        return 1

    brief_command = [sys.executable, str(shared / "scripts" / "codex_brief.py"),
                     "--work", args.work]
    if args.issue is not None:
        brief_command += ["--issue", str(args.issue)]
    if args.repo:
        brief_command += ["--repo", args.repo]
    project_rules = REPO / "docs" / "codex-project.md"
    brief_command += ["--extra", str(project_rules)]
    for path in args.extra:
        brief_command += ["--extra", str((REPO / path).resolve())]
    assembled = subprocess.run(brief_command, cwd=REPO, capture_output=True, text=True)
    if assembled.returncode:
        sys.stderr.write(assembled.stderr)
        return assembled.returncode

    name = worktree.name
    output = REPO / "tmp" / "logs" / f"codex-{name}.log"
    final = REPO / "tmp" / "logs" / f"codex-{name}.last"
    argv = ["codex", "exec", "--cd", str(worktree), "--sandbox", "workspace-write",
            "--json", "-o", str(final), "-c", 'approval_policy="never"']
    if args.model:
        argv += ["--model", args.model]
    argv.append(assembled.stdout)
    log(f"Codex events: {output.relative_to(REPO)}")
    with output.open("w", encoding="utf-8") as stream:
        result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT)
    log(f"Codex exited {result.returncode}", "INFO" if result.returncode == 0 else "ERROR")
    return result.returncode


def register_tools() -> None:
    reserved = {"dev", "cycle", "run_codex"}
    paths = sorted((REPO / "scripts").glob("*.py")) + \
        sorted((REPO / "scripts" / "reports").glob("*.py"))
    for path in paths:
        if path.stem in reserved:
            continue
        name = path.stem.replace("_", "-")
        if name in COMMANDS:
            continue
        first = path.read_text(encoding="utf-8").splitlines()
        summary = next((line.strip(' "') for line in first[1:8]
                        if line.strip() and not line.startswith(("#!", '"""'))),
                       f"run {path.name}")

        def handler(extra: list[str], script: Path = path) -> int:
            return run([sys.executable, str(script.relative_to(REPO)), *extra])

        if path.stem.startswith("check_") or path.stem in {
                "compile_check", "prove_postconditions"}:
            kind = "validation"
        elif ("census" in path.stem or path.stem.startswith(("analyse_", "audit_"))
              or path.stem in {"floor_census", "gap_census", "oracle_coverage",
                               "prescan", "query_local_builders"}):
            kind = "analysis"
        elif path.stem in {"baseline_boot", "capture_traces", "diagnose_trace",
                           "measure_bug_switch", "mutate", "verify_emit"}:
            kind = "oracle"
        elif path.stem in {"issue_index", "progress_graph", "scorecard"}:
            kind = "reporting"
        else:
            kind = "tool"
        COMMANDS[name] = {
            "summary": summary[:100], "args": "[tool arguments]",
            "kind": kind, "handler": handler,
        }


def usage() -> int:
    print(__doc__.strip())
    print("\nUsage: python3 scripts/dev.py <command> [args]\n")
    order = ["aggregate", "step", "action", "validation", "analysis",
             "oracle", "reporting", "tool", "meta"]
    for kind in order:
        items = [(name, meta) for name, meta in sorted(COMMANDS.items())
                 if meta["kind"] == kind]
        if not items:
            continue
        print(f"  {kind}:")
        for name, meta in items:
            print(f"    {name:<30} {meta['summary']}")
        print()
    print(f"Log: {LOG.relative_to(REPO)}")
    return 2


def main(argv: list[str] | None = None) -> int:
    register_tools()
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments or arguments[0] in {"-h", "--help", "help"}:
        return usage()
    name, *extra = arguments
    meta = COMMANDS.get(name)
    if meta is None:
        print(f"unknown command: {name!r}; run 'python3 scripts/dev.py describe'", file=sys.stderr)
        return 2
    return int(meta["handler"](extra))  # type: ignore[operator]


if __name__ == "__main__":
    raise SystemExit(main())
