#!/usr/bin/env python3
"""Measure the seven C#/Rust semantic-difference rows in issue #58.

The old issue counts mixed constants, initializers, and mutable statics.  This
query is the executable definition of the replacement numbers.  It reads the
canonical full-tree corpus and the ownership census; it never scans C# text.

Run: python3 scripts/semantic_differences_census.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path


def root() -> Path:
    return Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], check=True,
        capture_output=True, text=True).stdout.strip())


def scalar(con: sqlite3.Connection, sql: str) -> int:
    return int(con.execute(sql).fetchone()[0])


def measure(repo: Path) -> dict:
    con = sqlite3.connect(f"file:{repo / 'rulesdb/patterns.db'}?mode=ro", uri=True)
    statics = con.execute("""
        WITH classified AS (
          SELECT field.id, field.const_value IS NOT NULL AS is_const,
                 field.is_readonly,
                 EXISTS (
                   SELECT 1 FROM field_access access
                   JOIN member writer ON writer.id=access.method_id
                   WHERE access.member_id=field.id AND access.is_write=1
                     AND writer.name <> '.cctor') AS runtime_written,
                 EXISTS (
                   SELECT 1 FROM field_access access
                   JOIN member writer ON writer.id=access.method_id
                   WHERE access.member_id=field.id AND access.is_write=1
                     AND writer.name = '.cctor') AS cctor_written
          FROM member field
          WHERE field.kind='field' AND field.is_static=1)
        SELECT COUNT(*), SUM(is_const),
               SUM(NOT is_const AND is_readonly),
               SUM(NOT is_const AND NOT is_readonly AND runtime_written),
               SUM(NOT is_const AND NOT is_readonly AND NOT runtime_written
                   AND cctor_written),
               SUM(NOT is_const AND NOT is_readonly AND NOT runtime_written
                   AND NOT cctor_written)
        FROM classified
        """).fetchone()
    mutable = [dict(owner=owner, field=name, type=dtype, writes=writes)
               for owner, name, dtype, writes in con.execute("""
        SELECT owner.key, field.name, field.declared_type,
               COUNT(DISTINCT access.id)
        FROM member field JOIN type owner ON owner.id=field.type_id
        JOIN field_access access ON access.member_id=field.id
        JOIN member writer ON writer.id=access.method_id
        WHERE field.kind='field' AND field.is_static=1
          AND field.is_readonly=0 AND field.const_value IS NULL
          AND access.is_write=1 AND writer.name <> '.cctor'
        GROUP BY field.id ORDER BY owner.key, field.name
        """)]
    ownership = repo / "docs/status/ownership-tree.tsv"
    shared = sum(line.split("\t")[3] == "SHARED"
                 for line in ownership.read_text().splitlines()[1:] if line)
    result = {
        "corpus": {
            "config": con.execute(
                "SELECT config FROM corpus_run ORDER BY id DESC LIMIT 1").fetchone()[0],
            "loc": scalar(con, "SELECT SUM(loc) FROM file"),
        },
        "finalizers": {
            "actual_destructors": scalar(con,
                "SELECT COUNT(*) FROM member WHERE name='Finalize' AND key LIKE '%.~%'")
        },
        "disposal": {
            "dispose_methods": scalar(con,
                "SELECT COUNT(*) FROM member WHERE kind='method' AND name='Dispose'"),
            "using_operations": scalar(con,
                "SELECT COUNT(*) FROM operation WHERE kind='Using'")
        },
        "statics": {
            "all_fields": statics[0], "const_valued": statics[1],
            "readonly_nonconst": statics[2], "genuinely_mutable": statics[3],
            "cctor_only_nonreadonly": statics[4],
            "nonreadonly_without_recorded_write": statics[5],
            "mutable_instances": mutable,
        },
        "events_delegates": {
            "event_declarations": scalar(con,
                "SELECT COUNT(*) FROM member WHERE kind='event'"),
            "event_assignments": scalar(con,
                "SELECT COUNT(*) FROM operation WHERE kind='EventAssignment'"),
            "event_references": scalar(con,
                "SELECT COUNT(*) FROM operation WHERE kind='EventReference'")
        },
        "shared_mutable": {"ownership_rows": shared},
        "by_reference": {
            "ref_parameters": scalar(con,
                "SELECT COUNT(*) FROM parameter WHERE is_ref=1"),
            "out_parameters": scalar(con,
                "SELECT COUNT(*) FROM parameter WHERE is_out=1")
        },
        "interop_pinning": {
            "address_of_operations": scalar(con,
                "SELECT COUNT(*) FROM operation WHERE kind='AddressOf'"),
            "retained_managed_object_fact_available": False
        }
    }
    con.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = measure(root())
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("issue #58 semantic census (full-tree corpus)")
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
