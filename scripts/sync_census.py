#!/usr/bin/env python3
"""Census of every `lock` site in the corpus: WHICH LOCK PROTECTS WHICH DATA.

Issue #52 asks for contention and hold times at the `// SYNC(measure)` sites.
Neither is derivable from source -- both are properties of a running program.
What IS derivable, and what the measurement needs first, is the *structure*:
for each lock, the fields it guards, the calls made while holding it, and every
access to those same fields that happens under NO lock at all.

That last set is the one worth having. A field guarded at nine sites and touched
bare at a tenth tells you the lock's job is narrower than it looks, and it is
found by query rather than by reading 56 call sites.

WHAT THIS CANNOT TELL YOU, AND WHY
----------------------------------
**The corpus does not record threads.** C# does not declare which thread enters
a method, so no query over Roslyn output can say whether two accesses to a
guarded field are ever concurrent. This census localises the DATA; deciding D3
additionally needs to know the THREADS, and that information does not exist in
any static artefact -- it comes from running the emulator.

So nothing here is evidence for or against removing a lock. It is the map you
would point an instrument at, and the instrument is `src/renode-sync`.

`body_operations` is likewise a static size, NOT a hold time. It is reported
because a critical section holding 4 operations and one holding 180 are
different risks, not because either is a duration.

Run:  python3 scripts/sync_census.py
      python3 scripts/sync_census.py --db tmp/breadth.db      # whole tree
      python3 scripts/sync_census.py --json docs/status/sync_census.json
Log:  ./tmp/logs/sync_census.log
Exit: 0 always -- this is a measurement, not a gate.
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

# A field access in the corpus includes reads of enum members and of `static
# readonly` constants -- `state == IRQState.Pending` is a FieldReference to
# `Pending`. Those are immutable by construction and cannot be raced, so
# counting them as guarded data would inflate every lock's footprint with
# things no lock has ever protected.
#
# The exclusion is derived, not judged: enum member, compile-time constant, or
# `static readonly`. A static *mutable* field stays in -- it is the most
# raceable thing there is.
MUTABLE_STATE = """
    mb.const_value IS NULL
    AND NOT (mb.is_static = 1 AND mb.is_readonly = 1)
    AND mb.type_id NOT IN (SELECT id FROM type WHERE kind = 'enum')
"""

# Descendants of an operation, excluding the operation itself. Used for both
# "what is in this lock body" and "what is in this method".
DESCENDANTS = """
WITH RECURSIVE sub(id) AS (
    SELECT id FROM operation WHERE parent_id = :root
    UNION ALL
    SELECT o.id FROM operation o JOIN sub ON o.parent_id = sub.id
)
SELECT id FROM sub
"""


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def setup_log(root: Path) -> logging.Logger:
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("sync_census")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    for h in (logging.FileHandler(root / "tmp" / "logs" / "sync_census.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def descendants(con: sqlite3.Connection, root_op: int) -> list[int]:
    return [r[0] for r in con.execute(DESCENDANTS, {"root": root_op})]


def lock_sites(con: sqlite3.Connection) -> list[dict]:
    """Every `lock (target) { body }`, with where it lives and what it locks.

    The target is the lock operation's first child; the body is its second.
    A `Lock` with fewer than two children is malformed and is reported as
    such rather than skipped, because a silently dropped site is exactly the
    failure this project keeps finding.
    """
    rows = con.execute("""
        SELECT o.id, m.signature, t.name, f.path
        FROM operation o
        JOIN member mb ON mb.id = o.method_id
        JOIN method m  ON m.member_id = o.method_id
        JOIN type t    ON t.id = mb.type_id
        JOIN file f    ON f.id = t.file_id
        WHERE o.kind = 'Lock'
        ORDER BY f.path, m.signature, o.ordinal, o.id
    """).fetchall()

    out = []
    for op_id, signature, type_name, path in rows:
        kids = con.execute(
            "SELECT id, kind, symbol FROM operation WHERE parent_id = ? "
            "ORDER BY ordinal, id", (op_id,)).fetchall()
        site = {
            "operation": op_id,
            "file": path,
            "type": type_name,
            "method": signature,
            "target_kind": kids[0][1] if kids else None,
            "target": kids[0][2] if kids else None,
            "target_op": kids[0][0] if kids else None,
            "malformed": len(kids) < 2,
        }
        site["body"] = kids[1][0] if len(kids) > 1 else None
        out.append(site)
    return out


def guarded_fields(con: sqlite3.Connection, body_op: int) -> dict[str, dict]:
    """Fields read or written directly in a lock body.

    Direct only: a field touched by a method CALLED from the body is guarded
    too, and that is reported separately as the transitive set, because the
    two have very different confidence. A direct access is a fact about this
    lock; a transitive one assumes the callee is not also reached unlocked
    from somewhere else.
    """
    ids = descendants(con, body_op)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = con.execute(f"""
        SELECT mb.name, mb.id, fa.is_write, COUNT(*)
        FROM field_access fa
        JOIN member mb ON mb.id = fa.member_id
        WHERE fa.operation_id IN ({marks}) AND {MUTABLE_STATE}
        GROUP BY 1, 2, 3
    """, ids).fetchall()
    out: dict[str, dict] = {}
    for name, member_id, is_write, n in rows:
        e = out.setdefault(name, {"member": member_id, "reads": 0, "writes": 0})
        e["writes" if is_write else "reads"] += n
    return out


def calls_under(con: sqlite3.Connection, body_op: int) -> dict:
    """What is invoked while the lock is held.

    Relevant to hold time in the only way source can be: a critical section
    that calls out to another type can be extended arbitrarily by that type,
    and a call back into corpus code is where lock-ordering deadlocks come
    from. Counted, never timed.
    """
    ids = descendants(con, body_op)
    if not ids:
        return {"internal": [], "external": 0, "nested_locks": 0, "operations": 0}
    marks = ",".join("?" * len(ids))
    internal = [r[0] for r in con.execute(f"""
        SELECT DISTINCT o.symbol FROM operation o
        WHERE o.id IN ({marks}) AND o.kind = 'Invocation' AND o.symbol IS NOT NULL
          AND o.symbol LIKE 'Antmicro.%'
        ORDER BY 1
    """, ids)]
    external = con.execute(f"""
        SELECT COUNT(*) FROM operation o
        WHERE o.id IN ({marks}) AND o.kind = 'Invocation'
          AND (o.symbol IS NULL OR o.symbol NOT LIKE 'Antmicro.%')
    """, ids).fetchone()[0]
    nested = con.execute(
        f"SELECT COUNT(*) FROM operation WHERE id IN ({marks}) AND kind = 'Lock'",
        ids).fetchone()[0]
    return {"internal": internal, "external": external,
            "nested_locks": nested, "operations": len(ids)}


def transitive_fields(con: sqlite3.Connection, body_op: int,
                      max_depth: int) -> list[str]:
    """Fields reachable through calls made under the lock, to `max_depth`.

    Bounded because the closure over a corpus this size otherwise reaches most
    of it, and a set that contains everything distinguishes nothing.
    """
    ids = descendants(con, body_op)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    frontier = {r[0] for r in con.execute(
        f"SELECT DISTINCT callee_id FROM call_site WHERE operation_id IN ({marks}) "
        "AND callee_id IS NOT NULL", ids)}
    seen: set[int] = set()
    fields: set[str] = set()
    for _ in range(max_depth):
        frontier -= seen
        if not frontier:
            break
        seen |= frontier
        fm = ",".join("?" * len(frontier))
        args = list(frontier)
        fields |= {r[0] for r in con.execute(
            f"SELECT DISTINCT mb.name FROM field_access fa "
            f"JOIN member mb ON mb.id = fa.member_id "
            f"WHERE fa.method_id IN ({fm}) AND {MUTABLE_STATE}", args)}
        frontier = {r[0] for r in con.execute(
            f"SELECT DISTINCT callee_id FROM call_site WHERE caller_id IN ({fm}) "
            "AND callee_id IS NOT NULL", args)}
    return sorted(fields)


def unlocked_accesses(con: sqlite3.Connection, member_ids: set[int],
                      locked_ops: set[int]) -> dict[str, list[dict]]:
    """Accesses to guarded fields that are under no lock at all.

    This is the reason the census exists. `lock (sync) { count++ }` in nine
    methods and a bare `count++` in a tenth is a structural fact the emitted
    `Mutex` reproduces faithfully -- including the hole.
    """
    if not member_ids:
        return {}
    marks = ",".join("?" * len(member_ids))
    rows = con.execute(f"""
        SELECT mb.name, m.signature, t.name, fa.operation_id, fa.is_write
        FROM field_access fa
        JOIN member mb ON mb.id = fa.member_id
        JOIN member mm ON mm.id = fa.method_id
        JOIN method m  ON m.member_id = fa.method_id
        JOIN type t    ON t.id = mm.type_id
        WHERE fa.member_id IN ({marks})
    """, list(member_ids)).fetchall()

    out: dict[str, list[dict]] = collections.defaultdict(list)
    for name, signature, type_name, op_id, is_write in rows:
        if op_id in locked_ops:
            continue
        # A constructor touches the field before any other thread can reach the
        # object, so an unguarded access there is not a hole. Flagged rather
        # than filtered: the distinction is worth seeing, and one day somebody
        # will publish `this` from a constructor.
        method_name = signature.split("(")[0].rsplit(".", 1)[-1]
        out[name].append({"method": signature, "type": type_name,
                          "is_write": bool(is_write),
                          "during_construction": method_name == type_name})
    for v in out.values():
        v.sort(key=lambda e: (e["method"], e["is_write"]))
    return dict(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--json", default="docs/status/sync_census.json")
    ap.add_argument("--depth", type=int, default=2,
                    help="call depth for the transitive guarded set")
    args = ap.parse_args()

    root = repo_root()
    log = setup_log(root)
    db = root / args.db
    if not db.exists():
        log.error("no corpus at %s -- run the ingest first", args.db)
        return 0
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cfg = con.execute("SELECT config FROM corpus_run ORDER BY id LIMIT 1").fetchone()
    config = cfg[0] if cfg else "unknown"

    sites = lock_sites(con)
    log.info("%d lock site(s) in the `%s` corpus", len(sites), config)

    # State the exclusion out loud. A filter nobody can see is how a census
    # starts measuring something other than what it says it measures.
    immutable = con.execute(f"""
        SELECT COUNT(*) FROM field_access fa JOIN member mb ON mb.id = fa.member_id
        WHERE NOT ({MUTABLE_STATE})""").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM field_access").fetchone()[0]
    log.info("field accesses: %d, of which %d are to enum members or constants "
             "and are excluded (immutable, unraceable)", total, immutable)

    locked_ops: set[int] = set()
    member_ids: set[int] = set()
    for s in sites:
        if s["body"] is None:
            log.warning("MALFORMED lock at operation %d in %s -- reported, not skipped",
                        s["operation"], s["method"])
            s["guards"] = {}
            s["calls"] = {"internal": [], "external": 0, "nested_locks": 0,
                          "operations": 0}
            s["guards_transitively"] = []
            continue
        s["guards"] = guarded_fields(con, s["body"])
        s["calls"] = calls_under(con, s["body"])
        s["guards_transitively"] = transitive_fields(con, s["body"], args.depth)
        locked_ops.update(descendants(con, s["body"]))
        # `lock (receiveBuffer)` reads `receiveBuffer`, and that read is the
        # acquisition itself, not an unguarded use of the data. Counting it
        # would report every self-locking field as its own worst offender --
        # `irqs` showed 28 "unlocked" accesses, 14 of which were its own
        # `lock (irqs)` statements.
        locked_ops.add(s["target_op"])
        locked_ops.update(descendants(con, s["target_op"]))
        member_ids.update(g["member"] for g in s["guards"].values())

    bare = unlocked_accesses(con, member_ids, locked_ops)

    by_target: dict[str, dict] = {}
    for s in sites:
        t = s["target"] or f"<{s['target_kind']}>"
        e = by_target.setdefault(t, {"sites": 0, "guards": set(), "methods": set(),
                                     "calls_out": 0, "nested_locks": 0})
        e["sites"] += 1
        e["guards"] |= set(s["guards"])
        e["methods"].add(s["method"])
        e["calls_out"] += len(s["calls"]["internal"]) + s["calls"]["external"]
        e["nested_locks"] += s["calls"]["nested_locks"]

    log.info("")
    log.info("%-52s %5s %6s %7s %6s", "lock target", "sites", "fields", "callout", "nested")
    for t, e in sorted(by_target.items(), key=lambda kv: (-kv[1]["sites"], kv[0])):
        log.info("%-52s %5d %6d %7d %6d", t.split(".")[-1] + f"  ({t.rsplit('.', 2)[0]})",
                 e["sites"], len(e["guards"]), e["calls_out"], e["nested_locks"])

    log.info("")
    if bare:
        log.info("GUARDED FIELDS ALSO TOUCHED WITH NO LOCK HELD")
        log.info("(structure the translation reproduces faithfully, holes included)")
        runtime = 0
        for name, uses in sorted(bare.items()):
            live = [u for u in uses if not u["during_construction"]]
            if not live:
                continue
            runtime += 1
            writes = sum(1 for u in live if u["is_write"])
            log.info("  %-28s %3d access(es), %d write(s), in %d method(s)",
                     name, len(live), writes, len({u["method"] for u in live}))
        log.info("  (%d field(s) after excluding construction-time access)", runtime)
    else:
        log.info("every access to every guarded field is under a lock")

    widest = max(sites, key=lambda s: s["calls"]["operations"], default=None)
    if widest:
        log.info("")
        log.info("widest critical section: %d operations in %s",
                 widest["calls"]["operations"], widest["method"])
        log.info("  (a static size, NOT a hold time -- source cannot supply one)")

    out = {
        "corpus": config,
        "sites": len(sites),
        "targets": {t: {"sites": e["sites"],
                        "guards": sorted(e["guards"]),
                        "methods": sorted(e["methods"]),
                        "nested_locks": e["nested_locks"]}
                    for t, e in sorted(by_target.items())},
        "site_detail": sites,
        "unlocked_accesses_to_guarded_fields": bare,
        "not_derivable": [
            "which thread enters a method -- C# does not declare it",
            "hold time, contention, interleaving -- properties of a running program",
        ],
    }
    dest = root / args.json
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, sort_keys=True, default=sorted) + "\n")
    log.info("")
    log.info("wrote %s", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
