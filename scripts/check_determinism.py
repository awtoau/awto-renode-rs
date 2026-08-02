#!/usr/bin/env python3
"""Verify the ingest produces byte-identical output at -j1 and -j31. Issue #36 (R7).

This is not a nicety. If a 1-thread and a 31-thread run differ, every diff
against the C# reference becomes scheduling noise and the differential oracle --
the thing the whole project rests on -- is worthless.

Ingest guarantees this by walking in parallel but WRITING in sorted path order,
with ids assigned during the serial write rather than by the workers. This script
proves the guarantee holds rather than trusting it.

Run:  python3 scripts/check_determinism.py [--threads 31]
Log:  ./tmp/logs/check_determinism.log
Exit: 0 identical, 1 divergent.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

# Column lists are explicit and ordered: SELECT * would make the check sensitive
# to column order and hide a real divergence behind a schema edit.
TABLES = {
    "file":         "id, path, sha256, loc",
    "type":         "id, file_id, key, namespace, name, kind, "
                    "COALESCE(base_type_id,-1), COALESCE(base_extern,'')",
    "member":       "id, type_id, key, kind, name, declared_type, accessibility",
    "method":       "member_id, signature, return_type, is_virtual, is_extension",
    # has_default/default_value and operation.detail are compared because a
    # column this check does not read is a column that can diverge unnoticed --
    # `detail` is the walker's whole per-kind extraction and was unchecked.
    "parameter":    "id, method_id, ordinal, name, type, is_out, is_ref, "
                    "has_default, COALESCE(default_value,'')",
    "operation":    "id, method_id, COALESCE(parent_id,-1), ordinal, depth, kind, "
                    "COALESCE(type,''), COALESCE(symbol,''), COALESCE(const_value,''), "
                    "COALESCE(detail,''), span_start, span_len",
    "call_site":    "id, caller_id, COALESCE(callee_id,-1), COALESCE(callee_extern,''), "
                    "operation_id, is_virtual",
    "field_access": "id, method_id, member_id, operation_id, is_write",
}


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


def build(root: Path, env: dict[str, str], log) -> bool:
    """Compile the ingest before the two `--no-build` runs below.

    `--no-build` runs whatever is already in bin/, so a Walker.cs change that
    was never compiled produces a re-ingest that SUCCEEDS while extracting the
    old facts. That is not hypothetical: the field-initialiser branch was
    reverted for "does not reproduce on a clean re-ingest" after a run that
    reported zero field-attached operations -- and its walker, rebuilt from
    source and re-run, produces 30,139 of them. The code was right; the binary
    was stale. One build, once, removes the whole failure mode.
    """
    r = subprocess.run(["dotnet", "build", "-v", "q"],
                       cwd=root / "frontend" / "RenodeIngest", env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        log.error("ingest build failed:\n%s", r.stdout[-2000:] + r.stderr[-2000:])
        return False
    return True


def ingest(root: Path, env: dict[str, str], db: Path, threads: int, log) -> bool:
    log.info("ingesting at -j%d -> %s", threads, db.name)
    r = subprocess.run(
        ["dotnet", "run", "--no-build", "--", "--db", str(db), "-j", str(threads)],
        cwd=root / "frontend" / "RenodeIngest", env=env,
        capture_output=True, text=True)
    if r.returncode != 0:
        log.error("ingest failed at -j%d:\n%s", threads, r.stdout[-2000:] + r.stderr[-2000:])
        return False
    return True


def table_hash(db: Path, table: str, cols: str) -> tuple[str, int]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        order = cols.split(",")[0].strip()
        rows = con.execute(f"SELECT {cols} FROM {table} ORDER BY {order}").fetchall()
    finally:
        con.close()
    h = hashlib.sha256()
    for row in rows:
        h.update(repr(row).encode())
        h.update(b"\n")
    return h.hexdigest(), len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 8)
    ap.add_argument("--keep", action="store_true", help="keep the two databases")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_determinism")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_determinism.log"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    env = load_env(root)
    if "RENODE_SRC" not in env:
        log.error("RENODE_SRC not set -- see .env.example")
        return 1

    tmp = root / "tmp"
    tmp.mkdir(exist_ok=True)
    db1, dbn = tmp / "determinism-j1.db", tmp / f"determinism-j{args.threads}.db"

    if not build(root, env, log):
        return 1
    if not ingest(root, env, db1, 1, log):
        return 1
    if not ingest(root, env, dbn, args.threads, log):
        return 1

    diverged = []
    for table, cols in TABLES.items():
        try:
            h1, n1 = table_hash(db1, table, cols)
            hn, nn = table_hash(dbn, table, cols)
        except sqlite3.Error as e:
            log.error("%-14s ERROR %s", table, e)
            diverged.append(table)
            continue
        if h1 == hn:
            log.info("%-14s MATCH   %6d rows  %s", table, n1, h1[:16])
        else:
            log.error("%-14s DIVERGE j1=%d rows %s  j%d=%d rows %s",
                      table, n1, h1[:16], args.threads, nn, hn[:16])
            diverged.append(table)

    if not args.keep:
        for p in (db1, dbn):
            for suffix in ("", "-wal", "-shm"):
                Path(str(p) + suffix).unlink(missing_ok=True)

    if diverged:
        log.error("FAIL: %d table(s) differ between -j1 and -j%d: %s",
                  len(diverged), args.threads, ", ".join(diverged))
        log.error("Ingest must write in sorted order with ids assigned serially.")
        return 1
    log.info("OK: ingest is deterministic across -j1 and -j%d", args.threads)
    return 0


if __name__ == "__main__":
    sys.exit(main())
