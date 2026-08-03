#!/usr/bin/env python3
"""Every emitted register reset must equal its C# construction reset.

The expected value comes directly from the chain root's `ObjectCreation`, not
from `RegisterDsl.find_registers`: sharing that parser would let a bad reset
value agree with itself. The actual value comes from parsing emitted Rust.

Run:  python3 scripts/check_reset_value.py
Log:  ./tmp/logs/check_reset_value.log
Exit: 1 on any emitted reset mismatch.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emit import Emitter  # noqa: E402
from emitted_modules import parse, repo_root, setup_log  # noqa: E402
from emitter.plugins.register_dsl import to_const  # noqa: E402
from register_owners import owners  # noqa: E402


def method_id(con: sqlite3.Connection, type_name: str, member: str) -> int | None:
    row = con.execute("""
        SELECT m.member_id FROM method m
        JOIN member mb ON mb.id = m.member_id
        JOIN type t ON t.id = mb.type_id
        WHERE t.name = ? AND mb.name = ?""", (type_name, member)).fetchone()
    return row[0] if row else None


def construction_reset(em: Emitter, invocation: int, form: dict) -> int | None:
    """Read argument 1 from the ObjectCreation at the declared chain root."""
    if form["chain_from"] == "$self":
        bound = em.bind(invocation, em.con.execute(
            "SELECT symbol FROM operation WHERE id=?", (invocation,)).fetchone()[0])
        value = bound.get("resetValue")
        try:
            return int(value[2]) if value and value[2] is not None else 0
        except (TypeError, ValueError):
            return None
    root_span = em.arg_span(invocation, form["chain_from"])
    if root_span is None:
        return None

    root = em.arg_node(invocation, form["chain_from"])
    if root is not None:
        kind, symbol = em.con.execute(
            "SELECT kind, symbol FROM operation WHERE id=?", (root,)).fetchone()
        if kind == "LocalReference" and symbol:
            start, method = em.con.execute(
                "SELECT span_start, method_id FROM operation WHERE id=?",
                (root,)).fetchone()
            local = symbol.split()[-1]
            for did, in em.con.execute(
                    "SELECT id FROM operation WHERE method_id=? AND "
                    "kind='VariableDeclarator' AND span_start < ? "
                    "ORDER BY span_start DESC", (method, start)):
                detail, = em.con.execute(
                    "SELECT detail FROM operation WHERE id=?", (did,)).fetchone()
                try:
                    declared = json.loads(detail or "{}").get("local")
                except json.JSONDecodeError:
                    declared = None
                if local != declared:
                    continue
                creation = em.con.execute("""
                    WITH RECURSIVE tree(id) AS (
                        SELECT ? UNION ALL
                        SELECT operation.id FROM operation JOIN tree
                          ON operation.parent_id = tree.id)
                    SELECT operation.id FROM operation JOIN tree
                      ON operation.id = tree.id
                    WHERE operation.kind = 'ObjectCreation' LIMIT 1""",
                    (did,)).fetchone()
                if creation:
                    root_span, = em.con.execute(
                        "SELECT span_start FROM operation WHERE id=?",
                        (creation[0],)).fetchone()
                break

    creation = em.con.execute("""
        SELECT id FROM operation
        WHERE method_id = (SELECT method_id FROM operation WHERE id = ?)
          AND span_start = ? AND kind = 'ObjectCreation'
        ORDER BY span_len DESC, depth LIMIT 1""", (invocation, root_span)).fetchone()
    if not creation:
        return None
    args = [c for c in em.children(creation[0]) if c[1] == "Argument"]
    if len(args) < 2:
        return None
    value = args[1][3]
    if value is None:
        kids = em.children(args[1][0])
        value = kids[0][3] if kids else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def expected_registers(em: Emitter, type_name: str, member: str,
                       log: logging.Logger
                       ) -> tuple[list[tuple[int, int]], list[str]]:
    """Return `(offset, reset)` per loop-expanded register construction."""
    mid = method_id(em.con, type_name, member)
    if mid is None:
        return [], [f"{type_name}.{member}: corpus member is missing"]
    out: list[tuple[int, int]] = []
    uncheckable: list[str] = []
    for oid, symbol in em.con.execute(
            "SELECT id, symbol FROM operation WHERE method_id=? "
            "AND kind='Invocation' AND symbol IS NOT NULL ORDER BY span_start",
            (mid,)):
        form = next((f for f in em.forms if f["symbol_contains"] in symbol), None)
        if form is None:
            continue
        envs = em.loop_envs(oid)
        if envs is None:
            uncheckable.append(
                f"{type_name}.{member} operation {oid}: loop cannot be expanded")
            continue
        for env in envs:
            _name, offset, _term = em.register_offset(oid, form, env)
            if offset is None:
                uncheckable.append(
                    f"{type_name}.{member} operation {oid}: offset is unknown")
                continue
            reset = construction_reset(em, oid, form)
            if reset is None:
                uncheckable.append(
                    f"{type_name}.{member} operation {oid}: construction reset "
                    "is not independently readable")
                continue
            out.append((offset, reset))
    return out, uncheckable


def run(db: Path, log: logging.Logger, only_type: str | None = None) -> int:
    """Compare independent corpus resets with parsed converter output."""
    def connect() -> sqlite3.Connection:
        return sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    owner_con = connect()
    try:
        rows = owners(owner_con)
    finally:
        owner_con.close()
    if only_type:
        rows = [row for row in rows if row[0] == only_type]
    log.info("examining %d register-owner method(s)", len(rows))
    jobs: list[tuple[str, str, Counter]] = []
    uncheckable: list[str] = []
    for type_name, member in rows:
        con = connect()
        try:
            em = Emitter(con, logging.getLogger("quiet"))
            registers, errors = expected_registers(em, type_name, member, log)
        finally:
            con.close()
        expected = Counter(registers)
        uncheckable.extend(errors)
        if expected:
            jobs.append((type_name, member, expected))
    log.info("discovered %d register-owner method(s) with checkable resets",
             len(jobs))

    def emit(job: tuple[str, str, Counter]):
        type_name, member, expected = job
        con = connect()
        try:
            em = Emitter(con, logging.getLogger("quiet"))
            statements, _fields, _gaps = em.emit_registers(type_name, member)
            constants = [f"pub const {to_const(name)}: u64 = 0x{offset:X};"
                         for name, offset in em.register_offsets(type_name, member)]
            text = "\n".join(constants + statements)
            mod = parse(type_name, member, "m", text)
        finally:
            con.close()
        return job, Counter((r.offset, r.reset) for r in mod.registers
                            if r.offset is not None and r.reset is not None)

    workers = min(8, max(1, len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        emitted = list(pool.map(emit, jobs))

    mismatches = checked = zero_while_nonzero = 0
    if uncheckable:
        log.info("skipped=%d register form(s) whose layout or reset is not "
                 "independently checkable", len(uncheckable))
    for (type_name, member, expected), actual in emitted:
        checked += sum(expected.values())
        if only_type:
            log.info("%s expected_nonzero=%d emitted_nonzero=%d",
                     type_name,
                     sum(n for (_off, reset), n in expected.items() if reset),
                     sum(n for (_off, reset), n in actual.items() if reset))
        for offset in sorted({off for off, _rst in expected | actual}):
            exp = Counter({reset: count for (off, reset), count in expected.items()
                           if off == offset})
            act = Counter({reset: count for (off, reset), count in actual.items()
                           if off == offset})
            rem_exp, rem_act = exp - act, act - exp
            paired = min(sum(rem_exp.values()), sum(rem_act.values()))
            if paired:
                mismatches += paired
                zero_while_nonzero += min(
                    rem_act.get(0, 0),
                    sum(n for reset, n in rem_exp.items() if reset != 0))
                log.error("%s.%s offset 0x%X: C# reset(s) %s, emitted %s",
                          type_name, member, offset,
                          ", ".join(f"0x{x:X}" for x in sorted(rem_exp)),
                          ", ".join(f"0x{x:X}" for x in sorted(rem_act)))
    log.info("checked=%d mismatches=%d zero_while_csharp_nonzero=%d",
             checked, mismatches, zero_while_nonzero)
    if mismatches:
        log.error("FAIL: emitted reset values disagree with C# constructions")
        return 1
    log.info("OK: every emitted reset equals its C# construction reset")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--type")
    args = ap.parse_args()
    root = repo_root()
    log = setup_log("check_reset_value")
    db = root / args.db
    if not db.exists():
        log.error("no corpus at %s", args.db)
        return 1
    return run(db, log, args.type)


if __name__ == "__main__":
    raise SystemExit(main())
