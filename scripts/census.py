#!/usr/bin/env python3
"""Fingerprint, cluster, and answer the census gate. Issue #32 (R3).

THE GATE: does the corpus collapse into hundreds of clusters rather than
thousands? If the unmatched tail dominates, the rule thesis is wrong for this
corpus and the project stops, having spent only tooling.

This is the gate `linux-rs` skipped. Its rule track then reached 31 rules across
58 validation instances -- 1.87 each -- with `functions` and `statement_families`
both at 0 rows.

## Fingerprint design

Normalisation decides what collapses, so it decides the answer. Two rules:

  KEEP semantics. `WithFlag` and `WithValueField` are structurally identical and
  semantically different; collapsing them would merge patterns that must stay
  apart and inflate coverage with a lie. Call targets are therefore PART of the
  fingerprint. This is linux-rs's hard rule -- semantics-bearing primitives never
  match on structural family alone -- applied here.

  DROP incidentals. Field and local names, and literal values, are dropped:
  `.WithFlag(2, out receiverEnabled, name: "RE")` and
  `.WithFlag(5, out usartEnabled, name: "UE")` are the same idiom and must
  collapse, or every register bit becomes its own "pattern".

Run:  python3 scripts/census.py [--db rulesdb/patterns.db]
Log:  ./tmp/logs/census.log
Out:  docs/census.md
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Operation kinds whose resolved symbol is semantics-bearing and must be kept.
# An invocation of WithFlag is a different idiom from an invocation of
# WithValueField even though the trees are the same shape.
SYMBOL_SIGNIFICANT = {"Invocation", "ObjectCreation", "MethodReference"}

# Kinds whose symbol is an incidental name (which local, which field) and is
# normalised away so instances of one idiom collapse together.
# A subtree must be at least this large to be worth a rule; below it the "rule"
# is a single node and carries no structure.
MIN_SUBTREE = 3

# Occurrences required before a shape counts as generalisable. Matches
# rule.min_instances_required -- below it, it is a patch, not a rule.
MIN_INSTANCES = 3

SYMBOL_INCIDENTAL = {
    "LocalReference", "ParameterReference", "FieldReference",
    "PropertyReference", "EventReference",
}


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def fingerprint_tree(rows: list[tuple], log: logging.Logger):
    """Return (fp_by_op, children) for one method's operation rows.

    rows: (id, parent_id, ordinal, kind, symbol) ordered by id, parents first.
    """
    children: dict[int, list[int]] = defaultdict(list)
    info: dict[int, tuple[str, str | None]] = {}
    roots: list[int] = []
    for oid, parent, _ordinal, kind, symbol in rows:
        info[oid] = (kind, symbol)
        if parent is None:
            roots.append(oid)
        else:
            children[parent].append(oid)

    # Compiler-inserted nodes carry no idiom. An implicit Conversion is not
    # written by anyone, and an omitted optional argument (DefaultValue) is the
    # ABSENCE of source. Letting either distinguish patterns splits one idiom
    # into many: `.WithFlag(3, out x, name: "A")` and
    # `.WithFlag(3, FieldMode.Read, name: "B")` are the same rule with different
    # optionals supplied.
    TRANSPARENT = {"Conversion"}      # elide: contribute the child directly
    ERASED = {"DefaultValue"}         # erase: contribute nothing

    fp: dict[int, str] = {}
    # Children were inserted in source order and ids ascend with that order, so
    # post-order is simply reverse id order -- no recursion needed.
    for oid in sorted(info, reverse=True):
        kind, symbol = info[oid]
        if kind in ERASED:
            fp[oid] = ""
            continue
        if kind in TRANSPARENT and children[oid]:
            fp[oid] = fp[sorted(children[oid])[0]]
            continue
        parts = [kind]
        if kind in SYMBOL_SIGNIFICANT and symbol:
            parts.append(symbol)
        elif kind in SYMBOL_INCIDENTAL:
            parts.append("#")          # normalised: which name does not matter
        kids = [c for c in sorted(children[oid]) if fp.get(c) != ""]
        # FLUENT-CHAIN HOLE. In `a.WithFlag(..).WithValueField(..)` the receiver of
        # each call is the entire preceding chain, so without this every combinator
        # call in every chain is unique and nothing collapses. A real rule matches
        # `<any>.WithFlag(lit, out field, lit)` with the receiver as a hole, which
        # is what this models: when an invocation's receiver is itself an
        # invocation, the receiver contributes a wildcard rather than its shape.
        # The DSL is EXTENSION METHODS, so an invocation's children are all
        # Argument nodes and the receiver is the first Argument wrapping the
        # preceding chain -- not a direct Invocation child. Checking one level
        # too high moved coverage by 0.5%, which is how this was found.
        receiver_is_chain = (
            kind == "Invocation" and kids
            and info.get(kids[0], ("", None))[0] == "Argument"
            and any(info.get(g, ("", None))[0] == "Invocation" for g in children[kids[0]]))
        if receiver_is_chain:
            parts.append("^")
            parts.extend(fp[c] for c in kids[1:])
        else:
            parts.extend(fp[c] for c in kids)
        h = hashlib.blake2b("|".join(parts).encode(), digest_size=12).hexdigest()
        fp[oid] = h
    return fp, children, roots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("census")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "census.log"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    con = sqlite3.connect(root / args.db)
    cfg, = con.execute("SELECT config FROM corpus_run ORDER BY id DESC LIMIT 1").fetchone()
    if cfg == "breadth":
        log.error("BREADTH database -- diagnostic only, never a source of clusters")
        return 1
    run_id, = con.execute("SELECT MAX(id) FROM corpus_run").fetchone()

    # --- fingerprint ---------------------------------------------------------
    by_method: dict[int, list[tuple]] = defaultdict(list)
    for row in con.execute(
            "SELECT method_id, id, parent_id, ordinal, kind, symbol FROM operation ORDER BY id"):
        by_method[row[0]].append(row[1:])
    log.info("fingerprinting %d methods", len(by_method))

    method_fp: dict[int, tuple[str, int]] = {}          # method -> (fp, nodes)
    subtree_index: dict[str, list[tuple[int, int, int]]] = defaultdict(list)  # fp -> [(op, method, size)]
    per_method: dict[int, tuple] = {}

    for mid, rows in by_method.items():
        fp, children, roots = fingerprint_tree(rows, log)
        if not roots:
            continue
        # Method-level: the whole body.
        method_fp[mid] = (fp[roots[0]], len(rows))

        # Fingerprint EVERY subtree, not just statements. A register definition
        # is one 100-node statement whose combinator SEQUENCE is unique, so it is
        # a singleton by construction -- while each `.WithFlag(...)` inside it has
        # hundreds of siblings corpus-wide. Measuring at statement granularity
        # therefore reports a dominant tail that is an artifact of the question,
        # not a property of the corpus.
        kind_of = {r[0]: r[3] for r in rows}
        size = {}
        for oid in sorted(kind_of, reverse=True):
            size[oid] = 1 + sum(size[c] for c in children[oid])
        for oid, parent, _ord, kind, _sym in rows:
            if size[oid] >= MIN_SUBTREE:
                subtree_index[fp[oid]].append((oid, mid, size[oid]))
        per_method[mid] = (fp, children, size, roots[0])

    # --- persist -------------------------------------------------------------
    con.execute("DELETE FROM cluster_member")
    con.execute("DELETE FROM pattern_cluster")
    con.execute("DELETE FROM method_fingerprint")
    con.executemany(
        "INSERT INTO method_fingerprint(method_id,fingerprint,norm_version) VALUES (?,?,?)",
        [(m, f, "v1") for m, (f, _n) in sorted(method_fp.items())])

    method_clusters: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for m, (f, n) in method_fp.items():
        method_clusters[f].append((m, n))

    # --- greedy top-down cover -----------------------------------------------
    # This models what the rule engine actually does: at each node, if its shape
    # is one a rule could generalise (>= MIN_INSTANCES occurrences corpus-wide),
    # emit it and stop descending; otherwise descend and try the children. What
    # is left uncovered at the leaves is the genuine tail.
    sizes_by_fp = {f: len(v) for f, v in subtree_index.items()}
    kind_by_op = dict(con.execute("SELECT id, kind FROM operation"))
    covered_nodes = 0
    total_nodes = 0
    used_fps: set[str] = set()
    uncovered_kinds: dict[str, int] = defaultdict(int)

    for mid, (fp, children, size, method_root) in per_method.items():
        total_nodes += size[method_root]
        stack = [method_root]
        while stack:
            oid = stack.pop()
            f = fp[oid]
            if size[oid] >= MIN_SUBTREE and sizes_by_fp.get(f, 0) >= MIN_INSTANCES:
                covered_nodes += size[oid]
                used_fps.add(f)
            else:
                if not children[oid]:
                    uncovered_kinds[kind_by_op.get(oid, "?")] += 1
                stack.extend(children[oid])

    cover_pct = 100.0 * covered_nodes / max(total_nodes, 1)
    log.info("")
    log.info("greedy cover: %.1f%% of %d AST nodes covered by %d distinct patterns",
             cover_pct, total_nodes, len(used_fps))
    log.info("uncovered leaf nodes by kind:")
    for k, n in sorted(uncovered_kinds.items(), key=lambda kv: -kv[1])[:10]:
        log.info("    %-24s %6d", k, n)

    stmt_clusters = subtree_index
    for gran, groups in (("method", method_clusters), ("statement", stmt_clusters)):
        for f, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            if gran == "method":
                exemplar_m, nodes = min(members, key=lambda x: (x[1], x[0]))
                exemplar_op = None
            else:
                op, exemplar_m, nodes = min(members, key=lambda x: (x[2], x[0]))
                exemplar_op = op
            cid = con.execute(
                "INSERT INTO pattern_cluster(run_id,granularity,fingerprint,member_count,"
                "node_count,exemplar_id,exemplar_op) VALUES (?,?,?,?,?,?,?) RETURNING id",
                (run_id, gran, f, len(members), nodes, exemplar_m, exemplar_op)).fetchone()[0]
            con.executemany(
                "INSERT OR IGNORE INTO cluster_member(cluster_id,operation_id,method_id) "
                "VALUES (?,?,?)",
                [(cid, (mm[0] if gran == "statement" else None),
                  (mm[1] if gran == "statement" else mm[0])) for mm in members])
    con.commit()

    # --- the gate ------------------------------------------------------------
    def coverage(gran: str):
        rows = con.execute(
            "SELECT member_count FROM pattern_cluster WHERE granularity=? "
            "ORDER BY member_count DESC", (gran,)).fetchall()
        counts = [r[0] for r in rows]
        total = sum(counts)
        out = {}
        run = 0
        for pct in (50, 80, 95):
            need = 0
            run = 0
            for c in counts:
                run += c
                need += 1
                if run * 100 >= total * pct:
                    break
            out[pct] = need
        singles = sum(1 for c in counts if c == 1)
        return len(counts), total, out, singles

    lines = []
    lines_extra = (cover_pct, len(used_fps), total_nodes)
    log.info("")
    for gran in ("statement", "method"):
        nclust, total, cov, singles = coverage(gran)
        log.info("%s-level: %d instances in %d clusters", gran, total, nclust)
        log.info("  clusters covering 50%% / 80%% / 95%%: %d / %d / %d",
                 cov[50], cov[80], cov[95])
        log.info("  singleton clusters: %d (%.0f%% of clusters, %.0f%% of instances)",
                 singles, 100 * singles / max(nclust, 1), 100 * singles / max(total, 1))
        lines.append((gran, nclust, total, cov, singles))
    con.close()
    return write_report(root, lines, lines_extra, log)


def write_report(root: Path, lines, extra, log) -> int:
    cover_pct, n_patterns, total_nodes = extra

    stmt = next(l for l in lines if l[0] == "statement")
    _gran, nclust, total, cov, singles = stmt

    # A gate with no data must FAIL. An earlier version reported PASS on zero
    # statement instances because the statement detector was broken -- a gate
    # that passes when it has nothing to measure is worse than no gate.
    if total == 0 or nclust == 0:
        log.error("GATE INCONCLUSIVE: no statement-level instances were found. "
                  "This is a bug in the census, not a property of the corpus.")
        return 1

    # THE GATE, stated correctly: can a few hundred rules cover most of the
    # corpus by AST NODE? Statement-cluster counts are the wrong measure -- a
    # register definition is one unique 100-node statement built from twenty
    # highly-repeated combinator calls, so it reads as a singleton while being
    # almost entirely rule-coverable.
    # Two readings, reported separately because they disagree and the
    # disagreement is the finding:
    #   ORIGINAL question (PLAN.md): "hundreds of families, not tens of
    #     thousands?" -- 653 patterns is emphatically hundreds.
    #   OPERATIONAL threshold (invented here): >= 80% of AST nodes coverable.
    collapse_ok = n_patterns <= 800
    coverage_ok = cover_pct >= 80.0
    passed = collapse_ok and coverage_ok

    out = ["# Corpus census — R3 gate", "",
           f"Generated by `scripts/census.py`. **Gate: {'PASS' if passed else 'FAIL'}**", "",
           "## The result that matters", "",
           f"**{cover_pct:.1f}% of {total_nodes:,} AST nodes** are covered by "
           f"**{n_patterns} distinct patterns**, each occurring at least "
           f"{MIN_INSTANCES} times corpus-wide.", "",
           "Coverage is measured by a greedy top-down cover, which is what a rule",
           "engine actually does: at each node, if its shape occurs often enough to",
           "generalise, emit and stop descending; otherwise descend. Counting",
           "*clusters* instead badly understates coverage — a register definition is",
           "one unique 100-node statement assembled from twenty heavily-repeated",
           "combinator calls, so it reads as a singleton while being almost entirely",
           "rule-coverable.", ""]
    out += ["## Coverage", "",
            "| granularity | instances | clusters | 50% | 80% | 95% | singletons |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for g, nc, tot, c, s in lines:
        out.append(f"| {g} | {tot:,} | {nc:,} | {c[50]} | {c[80]} | {c[95]} | {s:,} |")
    out += ["",
            "**Statement-level is the number that matters** — it is the granularity a rule",
            "matches. Method-level is reported for comparison only.", "",
            "## Fingerprint normalisation", "",
            "- **Call targets are kept.** `WithFlag` and `WithValueField` are structurally",
            "  identical and semantically different; collapsing them would inflate coverage",
            "  with a lie.",
            "- **Names and literal values are dropped.** `.WithFlag(2, out receiverEnabled)`",
            "  and `.WithFlag(5, out usartEnabled)` are one idiom, not two.", ""]
    (root / "docs" / "census.md").write_text("\n".join(out) + "\n")
    log.info("")
    log.info("GATE: collapse %s (%d patterns, limit 800) | coverage %s (%.1f%%, target 80%%)",
             "PASS" if collapse_ok else "FAIL", n_patterns,
             "PASS" if coverage_ok else "FAIL", cover_pct)
    log.info("wrote docs/census.md")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
