"""Ranks 'static call `X.Y` has no Rust mapping' gaps by (declaring type, method).

Companion to gap_census.py --blocking: that ranks root causes by AST construct
kind, which lumps every unmapped static call under one "StaticInvocation"
bucket. This ranks the same gaps by the actual (declaring type, method) pair,
which is what says which specific static helper to map next.

Run: python3 scripts/census_static_calls.py
"""
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import emit_pool
from register_owners import owners

PATTERN = re.compile(r"static call `([^`]+)` has no Rust mapping")


def main():
    root = Path(__file__).resolve().parents[1]
    db = root / "rulesdb" / "patterns.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = owners(con)

    results = emit_pool.emit_many(str(db), [(n, m, "x") for n, m in rows], 31,
                                  lpt=True)

    counter: collections.Counter = collections.Counter()
    type_counter: collections.Counter = collections.Counter()
    for r in results:
        if r.err_type is not None:
            continue
        for line in r.text.splitlines():
            if not line.startswith("//!   - "):
                continue
            m = PATTERN.search(line[8:].strip())
            if m:
                counter[m.group(1)] += 1
                type_counter[m.group(1).split(".")[0]] += 1

    print("=== top (type.method) ===")
    for k, v in counter.most_common(40):
        print(f"{v:6d}  {k}")
    print()
    print("=== top declaring type ===")
    for k, v in type_counter.most_common(30):
        print(f"{v:6d}  {k}")
    print()
    print("total distinct calls:", len(counter),
          "total instances:", sum(counter.values()))


if __name__ == "__main__":
    main()
