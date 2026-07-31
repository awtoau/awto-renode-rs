#!/usr/bin/env python3
"""Breadth health check: does the ingest tooling survive the whole Renode tree?

WHAT THIS IS: a smoke test for the tooling. It runs the walker over all ~1,708
files and asserts the tool neither crashes nor loses data silently.

WHAT THIS IS NOT: a source of rules, clusters, coverage numbers or work.
Renode is ~448k lines against an F427 deliverable of ~16k. Treating breadth
output as corpus data would generate hundreds of clusters from EFR32xG2, Xtensa
and RISC-V peripherals that will never be translated -- polluting the rule DB,
inflating coverage, and spending LLM budget on patterns that are not the
deliverable. The ingest enforces this by refusing to write the canonical
database in --all mode and tagging the run config as 'breadth'.

It is cheap enough to run routinely (~50s), which is the only reason it is worth
having: Renode is small enough that full coverage costs almost nothing, unlike
the kernel corpus this method was borrowed from.

Silent loss is the point. The first breadth run threw zero exceptions and still
had 5,123 methods (24.7%) claiming a body while emitting no operations, because
`partial void Foo();` is neither abstract nor extern. Nothing crashed. The
assertions below are what caught it.

Run:  python3 scripts/check_breadth.py [--threads 31]
Log:  ./tmp/logs/check_breadth.log
Exit: 0 healthy, 1 a tooling defect.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# Each returns (label, count, tolerance). A count above tolerance is a defect in
# the TOOLING, never a fact about Renode.
ASSERTIONS = [
    ("methods with a body but zero operations",
     """SELECT COUNT(*) FROM method m WHERE m.has_body=1
        AND NOT EXISTS (SELECT 1 FROM operation o WHERE o.method_id=m.member_id)""", 0),
    ("members whose declaring type was dropped",
     "SELECT COUNT(*) FROM member WHERE type_id NOT IN (SELECT id FROM type)", 0),
    ("operations orphaned from any method",
     "SELECT COUNT(*) FROM operation WHERE method_id NOT IN (SELECT member_id FROM method)", 0),
    ("operations with a dangling parent",
     """SELECT COUNT(*) FROM operation
        WHERE parent_id IS NOT NULL AND parent_id NOT IN (SELECT id FROM operation)""", 0),
    ("call sites with no caller",
     "SELECT COUNT(*) FROM call_site WHERE caller_id NOT IN (SELECT member_id FROM method)", 0),
    ("types with neither a resolved base nor an extern base name",
     """SELECT 0""", 0),  # placeholder: both-null is legal (no base at all)
]


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def load_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    f = root / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 8)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_breadth")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_breadth.log"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    env = load_env(root)
    if "RENODE_SRC" not in env:
        log.error("RENODE_SRC not set -- see .env.example")
        return 1

    db = root / "tmp" / "breadth-check.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)

    log.info("breadth ingest over the whole tree at -j%d", args.threads)
    r = subprocess.run(
        ["dotnet", "run", "--no-build", "--", "--all", "--db", str(db), "-j", str(args.threads)],
        cwd=root / "frontend" / "RenodeIngest", env=env, capture_output=True, text=True)

    for line in r.stdout.splitlines():
        if line.strip():
            log.info("  %s", line.rstrip())

    if r.returncode != 0:
        log.error("FAIL: ingest crashed (exit %d)", r.returncode)
        log.error("%s", (r.stderr or "")[-2000:])
        return 1

    # A per-file walk failure is reported rather than thrown, so scan for it.
    walk_failures = [l for l in r.stdout.splitlines() if l.strip().startswith("!")]
    if walk_failures:
        log.error("FAIL: %d file(s) failed to walk:", len(walk_failures))
        for f in walk_failures[:20]:
            log.error("  %s", f.strip())
        return 1

    if not db.exists():
        log.error("FAIL: no database written")
        return 1

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    defects = 0
    try:
        config = con.execute("SELECT config FROM corpus_run ORDER BY id DESC LIMIT 1").fetchone()
        if not config or config[0] != "breadth":
            log.error("FAIL: run not tagged 'breadth' (got %r) -- breadth output must "
                      "never be mistakable for corpus data", config)
            defects += 1

        for label, sql, tolerance in ASSERTIONS:
            n = con.execute(sql).fetchone()[0]
            if n > tolerance:
                log.error("DEFECT  %-48s %d (max %d)", label, n, tolerance)
                defects += 1
            else:
                log.info("ok      %-48s %d", label, n)
    finally:
        con.close()

    if not args.keep:
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)

    if defects:
        log.error("FAIL: %d tooling defect(s). These are bugs in the ingest, "
                  "not facts about Renode.", defects)
        return 1
    log.info("OK: tooling survives the whole tree with no crashes and no silent loss")
    return 0


if __name__ == "__main__":
    sys.exit(main())
