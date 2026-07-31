#!/usr/bin/env python3
"""Derive metrics, purity and the translation work queue. Issue #31 (R2).

Reads the corpus database the ingest produced and fills the derived tables:
method_metrics, and translation_order.

The work queue is a topological sort of the call graph, leaves first, ranked by
AST size within each level. That ordering is for rule DISCOVERY, not rule
application -- once a rule is committed, applying it is a pure function of
(subtree, rule set) and parallelises freely. Discovery is ordered because simple
methods yield general rules; a rule derived from a 300-node method is usually
over-specific, and starting there is how a rule DB ends up at 1.87 instances.

Run:  python3 scripts/analyse_corpus.py [--db rulesdb/patterns.db]
Log:  ./tmp/logs/analyse_corpus.log
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# IOperation kinds that introduce a branch, for cyclomatic complexity.
BRANCHING = {
    "Conditional", "Loop", "Switch", "SwitchCase", "CaseClause",
    "Coalesce", "ConditionalAccess", "Binary",  # Binary covers && and ||
    "CatchClause",
}

# A method is impure if it writes a field, or performs I/O. Renode's peripherals
# reach the outside world through logging and bus access, so calls that leave the
# corpus are treated as impure -- conservative, and being wrong in that direction
# only shrinks the pure set rather than corrupting it.
def analyse(con: sqlite3.Connection, log: logging.Logger) -> None:
    log.info("computing per-method metrics")

    methods = {row[0] for row in con.execute("SELECT member_id FROM method")}

    # --- raw counts from the operation tree ---------------------------------
    ast_nodes: dict[int, int] = defaultdict(int)
    max_depth: dict[int, int] = defaultdict(int)
    cyclomatic: dict[int, int] = defaultdict(lambda: 1)
    for mid, kind, depth in con.execute("SELECT method_id, kind, depth FROM operation"):
        ast_nodes[mid] += 1
        if depth > max_depth[mid]:
            max_depth[mid] = depth
        if kind in BRANCHING:
            cyclomatic[mid] += 1

    n_locals: dict[int, int] = defaultdict(int)
    for mid, n in con.execute(
            "SELECT method_id, COUNT(*) FROM local GROUP BY method_id"):
        n_locals[mid] = n

    reads: dict[int, int] = defaultdict(int)
    writes: dict[int, int] = defaultdict(int)
    for mid, w, n in con.execute(
            "SELECT method_id, is_write, COUNT(*) FROM field_access "
            "GROUP BY method_id, is_write"):
        (writes if w else reads)[mid] = n

    # --- call graph ----------------------------------------------------------
    callees: dict[int, set[int]] = defaultdict(set)   # in-corpus edges only
    leaves_extern: dict[int, bool] = defaultdict(bool)  # calls anything external
    for caller, callee in con.execute(
            "SELECT caller_id, callee_id FROM call_site WHERE callee_id IS NOT NULL"):
        if callee in methods:
            callees[caller].add(callee)
    for (caller,) in con.execute(
            "SELECT DISTINCT caller_id FROM call_site WHERE callee_id IS NULL"):
        leaves_extern[caller] = True

    # is_leaf: calls nothing INSIDE the corpus. A method calling only BCL helpers
    # is still a leaf for translation ordering -- there is nothing to wait for.
    is_leaf = {m: not callees[m] for m in methods}

    # --- purity fixpoint -----------------------------------------------------
    log.info("purity fixpoint over %d methods", len(methods))
    impure = {m for m in methods if writes.get(m, 0) > 0 or leaves_extern[m]}
    changed = True
    rounds = 0
    while changed:
        changed = False
        rounds += 1
        for m in methods:
            if m in impure:
                continue
            if any(c in impure for c in callees[m]):
                impure.add(m)
                changed = True
    log.info("  converged in %d rounds: %d pure, %d impure",
             rounds, len(methods) - len(impure), len(impure))

    con.execute("DELETE FROM method_metrics")
    con.executemany(
        "INSERT INTO method_metrics(method_id,ast_nodes,cyclomatic,max_depth,n_locals,"
        "n_calls,n_field_reads,n_field_writes,is_leaf,is_pure) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(m, ast_nodes.get(m, 0), cyclomatic.get(m, 1) if m in ast_nodes else 0,
          max_depth.get(m, 0), n_locals.get(m, 0), len(callees[m]),
          reads.get(m, 0), writes.get(m, 0),
          1 if is_leaf[m] else 0, 0 if m in impure else 1)
         for m in sorted(methods)])

    # --- topological work queue ----------------------------------------------
    log.info("building translation_order")
    # Call graphs contain genuine cycles: mutual recursion, and virtual dispatch
    # back-edges where a base method calls an override that calls back. A naive
    # level relaxation grows those without bound, so condense strongly-connected
    # components with Tarjan first and order the resulting DAG. Every method in a
    # cycle gets the same level, which is the correct answer -- none of them can
    # be translated strictly before the others.
    sccs, scc_of = tarjan_scc(sorted(methods), callees)
    log.info("  %d SCCs over %d methods; largest has %d",
             len(sccs), len(methods), max(len(s) for s in sccs))

    # Level of an SCC = 1 + max level of the SCCs it calls. Tarjan emits SCCs in
    # reverse topological order, so one forward pass suffices -- no iteration,
    # no cap, no approximation.
    scc_level = [0] * len(sccs)
    for i, comp in enumerate(sccs):
        best = 0
        for m in comp:
            for c in callees[m]:
                j = scc_of[c]
                if j != i and scc_level[j] + 1 > best:
                    best = scc_level[j] + 1
        scc_level[i] = best
    level = {m: scc_level[scc_of[m]] for m in methods}

    ordered = sorted(methods, key=lambda m: (level[m], ast_nodes.get(m, 0), m))
    con.execute("DELETE FROM translation_order")
    con.executemany(
        "INSERT INTO translation_order(method_id,topo_level,rank) VALUES (?,?,?)",
        [(m, level[m], i) for i, m in enumerate(ordered)])
    con.commit()

    depth_hist = defaultdict(int)
    for m in methods:
        depth_hist[level[m]] += 1
    cyclic = sum(len(s) for s in sccs if len(s) > 1)
    log.info("  %d levels; level 0 (leaves) has %d methods; %d in cycles",
             max(depth_hist) + 1, depth_hist[0], cyclic)


def tarjan_scc(nodes, edges):
    """Strongly-connected components, iterative so deep graphs cannot blow the
    Python stack. Returns (components in reverse topological order, node->index)."""
    index = {}
    low = {}
    on_stack = set()
    stack = []
    comps = []
    counter = 0

    for root in nodes:
        if root in index:
            continue
        # (node, iterator over its successors) simulating the recursion
        work = [(root, iter(sorted(edges[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)

        while work:
            node, it = work[-1]
            advanced = False
            for succ in it:
                if succ not in index:
                    index[succ] = low[succ] = counter
                    counter += 1
                    stack.append(succ)
                    on_stack.add(succ)
                    work.append((succ, iter(sorted(edges[succ]))))
                    advanced = True
                    break
                if succ in on_stack and index[succ] < low[node]:
                    low[node] = index[succ]
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                if low[node] < low[parent]:
                    low[parent] = low[node]
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                comps.append(comp)

    scc_of = {}
    for i, comp in enumerate(comps):
        for m in comp:
            scc_of[m] = i
    return comps, scc_of


def report(con: sqlite3.Connection, log: logging.Logger) -> None:
    def q(sql: str):
        return con.execute(sql).fetchone()

    total, = q("SELECT COUNT(*) FROM method_metrics")
    leaves, = q("SELECT COUNT(*) FROM method_metrics WHERE is_leaf=1")
    pure, = q("SELECT COUNT(*) FROM method_metrics WHERE is_pure=1")
    empty, = q("SELECT COUNT(*) FROM method_metrics WHERE ast_nodes=0")

    log.info("")
    log.info("methods              %d", total)
    log.info("  leaves             %d (%.0f%%)", leaves, 100 * leaves / total)
    log.info("  pure               %d (%.0f%%)", pure, 100 * pure / total)
    log.info("  no body            %d", empty)

    log.info("")
    log.info("size distribution (AST nodes):")
    for lo, hi, label in [(1, 10, "trivial   1-10"), (11, 50, "small    11-50"),
                          (51, 200, "medium  51-200"), (201, 1000, "large 201-1000"),
                          (1001, 10 ** 9, "huge      1000+")]:
        n, = q(f"SELECT COUNT(*) FROM method_metrics WHERE ast_nodes BETWEEN {lo} AND {hi}")
        bar = "#" * int(50 * n / max(total, 1))
        log.info("  %-15s %5d  %s", label, n, bar)

    log.info("")
    log.info("first 10 in the work queue (leaves, simplest first):")
    for name, type_name, nodes, pure_f in con.execute("""
            SELECT mb.name, t.name, mm.ast_nodes, mm.is_pure
            FROM translation_order o
            JOIN method_metrics mm ON mm.method_id = o.method_id
            JOIN member mb ON mb.id = o.method_id
            JOIN type t ON t.id = mb.type_id
            WHERE mm.ast_nodes > 0
            ORDER BY o.rank LIMIT 10"""):
        log.info("  %-34s %-24s %3d nodes%s", name, type_name, nodes,
                 "  pure" if pure_f else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    args = ap.parse_args()

    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("analyse_corpus")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "analyse_corpus.log"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    db = root / args.db
    if not db.exists():
        log.error("no corpus database at %s -- run the ingest first", args.db)
        return 1

    con = sqlite3.connect(db)
    try:
        cfg, = con.execute(
            "SELECT config FROM corpus_run ORDER BY id DESC LIMIT 1").fetchone()
        if cfg == "breadth":
            log.error("this database is a BREADTH run -- diagnostic only, never a "
                      "source of rules or work. Re-ingest without --all.")
            return 1
        analyse(con, log)
        report(con, log)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
