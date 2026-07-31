#!/usr/bin/env python3
"""The rule engine. Issue #35 (R6).

The operation this exists to provide is `match`: given a rule proposed from ONE
exemplar, find EVERY structurally-equivalent occurrence in the corpus by query.
Without it a rule can only ever be justified by the file that motivated it --
which makes it a patch wearing a rule's label, and leaves per-file review as the
only quality mechanism. That is precisely how `linux-rs` reached 31 rules across
58 validation instances.

Subcommands:
  candidates   rank clusters by the nodes a rule would cover
  show ID      print the exemplar's source, so a rule can be written for it
  propose ID   create a proposed rule bound to a cluster, and populate its
               matches from the corpus
  validate ID  record validated instances (oracle tiers land in R5/#34)
  commit ID    promote to committed; the DB refuses below the threshold
  status       instances-per-rule and patch count

Run:  python3 scripts/rules.py <subcommand>
Log:  ./tmp/logs/rules.log
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

MIN_INSTANCES = 3


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def renode_src(root: Path) -> Path | None:
    f = root / ".env"
    if not f.exists():
        return None
    for line in f.read_text().splitlines():
        if line.startswith("RENODE_SRC="):
            return Path(line.split("=", 1)[1].strip())
    return None


def connect(root: Path, args) -> sqlite3.Connection:
    con = sqlite3.connect(root / args.db)
    cfg, = con.execute("SELECT config FROM corpus_run ORDER BY id DESC LIMIT 1").fetchone()
    if cfg == "breadth":
        raise SystemExit("BREADTH database -- diagnostic only, never a source of rules")
    return con


def cmd_candidates(con, args, log):
    log.info("%-6s %-7s %-6s %s", "id", "nodes", "sites", "exemplar")
    log.info("%s", "-" * 78)
    for cid, cnt, nodes, name, tname in con.execute("""
            SELECT pc.id, pc.member_count, pc.node_count, mb.name, t.name
            FROM pattern_cluster pc
            JOIN member mb ON mb.id = pc.exemplar_id
            JOIN type t ON t.id = mb.type_id
            WHERE pc.granularity='statement' AND pc.member_count >= ?
            ORDER BY pc.member_count * pc.node_count DESC LIMIT ?""",
            (MIN_INSTANCES, args.limit)):
        log.info("%-6d %-7d %-6d %s / %s", cid, cnt * nodes, cnt, name, tname)


def cmd_show(con, args, log):
    row = con.execute("""
        SELECT pc.member_count, pc.node_count, pc.exemplar_op, f.path,
               o.span_start, o.span_len, mb.name, t.name
        FROM pattern_cluster pc
        JOIN operation o ON o.id = pc.exemplar_op
        JOIN member mb ON mb.id = pc.exemplar_id
        JOIN type t ON t.id = mb.type_id
        JOIN file f ON f.id = t.file_id
        WHERE pc.id = ?""", (args.id,)).fetchone()
    if not row:
        log.error("no cluster %d (or it has no exemplar operation)", args.id)
        return 1
    cnt, nodes, _op, path, start, length, mname, tname = row
    log.info("cluster %d: %d sites, %d nodes each", args.id, cnt, nodes)
    log.info("exemplar: %s / %s", tname, mname)
    log.info("source:   %s", path)

    src = renode_src(repo_root())
    if src is None:
        log.warning("RENODE_SRC not set -- cannot print source")
        return 0
    # file.path is already relative to RENODE_SRC (Walker.Relative).
    full = src / path
    if not full.exists():
        log.warning("source file not found: %s", path)
        return 0
    text = full.read_text(errors="ignore")
    log.info("")
    for line in text[start:start + length].splitlines():
        log.info("    %s", line)

    log.info("")
    log.info("this shape also occurs in:")
    for tn, mn, n in con.execute("""
            SELECT t.name, mb.name, COUNT(*) FROM cluster_member cm
            JOIN operation o ON o.id = cm.operation_id
            JOIN member mb ON mb.id = o.method_id
            JOIN type t ON t.id = mb.type_id
            WHERE cm.cluster_id = ? GROUP BY t.name, mb.name
            ORDER BY COUNT(*) DESC LIMIT 12""", (args.id,)):
        log.info("    %-28s %-34s %4d", tn, mn, n)
    return 0


def cmd_propose(con, args, log):
    row = con.execute(
        "SELECT fingerprint, member_count FROM pattern_cluster WHERE id=?",
        (args.id,)).fetchone()
    if not row:
        log.error("no cluster %d", args.id)
        return 1
    fingerprint, count = row
    run_id, = con.execute("SELECT MAX(id) FROM corpus_run").fetchone()

    existing = con.execute("SELECT MAX(version) FROM rule WHERE name=?", (args.name,)).fetchone()[0]
    version = (existing or 0) + 1

    rid = con.execute("""
        INSERT INTO rule(name,version,family,description,matcher,emitter,status,
                         min_instances_required,requires_human_gate,created_run_id)
        VALUES (?,?,?,?,?,?, 'proposed', ?,?,?) RETURNING id""",
        (args.name, version, args.family, args.description,
         f"fingerprint:{fingerprint}", args.emitter or "TODO",
         MIN_INSTANCES, 1 if args.human_gate else 0, run_id)).fetchone()[0]

    # THE OPERATION THIS TOOL EXISTS FOR: every occurrence, found by query.
    matched = con.execute("""
        INSERT INTO rule_match(rule_id, operation_id, run_id)
        SELECT ?, cm.operation_id, ?
        FROM cluster_member cm WHERE cm.cluster_id = ? AND cm.operation_id IS NOT NULL""",
        (rid, run_id, args.id)).rowcount
    con.commit()

    log.info("rule %d: %s v%d [%s]", rid, args.name, version, args.family)
    log.info("  bound to cluster %d, %d matches found by query (cluster size %d)",
             args.id, matched, count)
    log.info("  status 'proposed' -- needs %d validated instances to commit", MIN_INSTANCES)
    return 0


def cmd_validate(con, args, log):
    """Record validated instances. The oracle that decides validity is R5 (#34);
    until it exists this records the tier as 0, which commit() must reject."""
    if args.tier == 0:
        log.error("refusing to record tier-0 'validations' -- the trace-replay "
                  "oracle (#34) does not exist yet, so nothing can be validated. "
                  "Recording them would manufacture the exact instances-per-rule "
                  "number the project uses to detect drift.")
        return 1
    n = con.execute("""
        INSERT OR REPLACE INTO rule_instance(rule_id,operation_id,validated_at,oracle_tier,evidence)
        SELECT ?, operation_id, datetime('now'), ?, ?
        FROM rule_match WHERE rule_id=? LIMIT ?""",
        (args.id, args.tier, args.evidence, args.id, args.limit)).rowcount
    con.commit()
    log.info("recorded %d instances for rule %d at oracle tier %d", n, args.id, args.tier)
    return 0


def cmd_commit(con, args, log):
    have, = con.execute(
        "SELECT COUNT(*) FROM rule_instance WHERE rule_id=?", (args.id,)).fetchone()
    need, = con.execute(
        "SELECT min_instances_required FROM rule WHERE id=?", (args.id,)).fetchone()
    try:
        con.execute("UPDATE rule SET status='committed' WHERE id=?", (args.id,))
        con.commit()
    except sqlite3.IntegrityError as e:
        log.error("REFUSED by the database: %s", e)
        log.error("  rule %d has %d validated instances, needs %d", args.id, have, need)
        log.error("  below the threshold this is a PATCH, not a rule -- record it as one")
        return 1
    log.info("rule %d committed with %d validated instances", args.id, have)
    return 0


def cmd_status(con, _args, log):
    rules, = con.execute("SELECT COUNT(*) FROM rule WHERE status='committed'").fetchone()
    proposed, = con.execute("SELECT COUNT(*) FROM rule WHERE status='proposed'").fetchone()
    inst, = con.execute("SELECT COUNT(*) FROM rule_instance").fetchone()
    matches, = con.execute("SELECT COUNT(*) FROM rule_match").fetchone()
    patches, = con.execute("SELECT COUNT(*) FROM translation WHERE is_patch=1").fetchone()
    log.info("rules committed     %d", rules)
    log.info("rules proposed      %d", proposed)
    log.info("matches (by query)  %d", matches)
    log.info("validated instances %d", inst)
    log.info("patches outstanding %d", patches)
    if rules:
        ipr = inst / rules
        log.info("instances per rule  %.2f   %s", ipr,
                 "OK" if ipr >= MIN_INSTANCES else "*** DRIFT ***")
    else:
        log.info("instances per rule  n/a (no committed rules)")
    log.info("")
    log.info("For reference, linux-rs reached 1.87 instances per rule with an "
             "empty corpus table.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("candidates"); c.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("show"); s.add_argument("id", type=int)
    p = sub.add_parser("propose")
    p.add_argument("id", type=int)
    p.add_argument("--name", required=True)
    p.add_argument("--family", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--emitter", default=None)
    p.add_argument("--human-gate", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("id", type=int)
    v.add_argument("--tier", type=int, default=0)
    v.add_argument("--evidence", default="")
    v.add_argument("--limit", type=int, default=10 ** 6)
    k = sub.add_parser("commit"); k.add_argument("id", type=int)
    sub.add_parser("status")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("rules")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    fh = logging.FileHandler(logdir / "rules.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt)
    log.addHandler(fh); log.addHandler(sh)

    con = connect(root, args)
    try:
        return {
            "candidates": cmd_candidates, "show": cmd_show, "propose": cmd_propose,
            "validate": cmd_validate, "commit": cmd_commit, "status": cmd_status,
        }[args.cmd](con, args, log)
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
