#!/usr/bin/env python3
"""Enforce `rule_negative` -- the shapes a rule must NOT match.

The project rule this implements: *a rule that over-matches is worse than one
that under-matches, because the oracle may not catch it.* It did not catch this
one. 171 anonymous `WithValueField` / `WithFlag` sites were emitted as tags, so
their writes were dropped, and every trace still scored zero divergences.

Recording the negative as prose next to the rule is not enough -- prose is
exactly what a later edit walks past. So each `negative` entry is a PREDICATE,
and this script runs all of them:

  `must_not_match`   pipe-separated callee names the rule must never be the
                     chosen arm for. Checked statically against the rule's own
                     `matches`, and dynamically against every corpus site, so a
                     rule cannot acquire the shape through a `when` change
                     either.

  `emit_must_not_contain`
                     substrings the rule's `emit` template must not contain.
                     This is the one that catches the actual regression: an
                     anonymous field routed back to `with_tag`, `with_reserved`
                     or `with_tagged_flag` is reserved, and `Bank::write` skips
                     reserved fields.

Exit 1 on any violation. Log: tmp/logs/check_rule_negatives.log.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True).strip())


ROOT = repo_root()
sys.path.insert(0, str(ROOT / "scripts"))

import emit  # noqa: E402


def rules_with_negatives(rules_dir: Path) -> list[dict]:
    out: list[dict] = []
    for f in sorted(rules_dir.glob("*.json")):
        for r in json.loads(f.read_text()).get("rules", []):
            if r.get("negative"):
                r = dict(r)
                r["_file"] = f.name
                out.append(r)
    return out


def static_violations(rules: list[dict]) -> list[str]:
    """Checks that need no corpus: the rule's own declaration contradicts it."""
    bad: list[str] = []
    for rule in rules:
        matches = set(rule.get("matches", "").split("|"))
        template = rule.get("emit") or ""
        for neg in rule["negative"]:
            forbidden = set((neg.get("must_not_match") or "").split("|")) - {""}
            overlap = sorted(matches & forbidden)
            if overlap:
                bad.append(
                    f"{rule['_file']}:{rule['name']} matches {', '.join(overlap)}, "
                    f"which its own negative forbids -- {neg['why']}")
            for frag in neg.get("emit_must_not_contain", []):
                if frag in template:
                    bad.append(
                        f"{rule['_file']}:{rule['name']} emits `{template}`, "
                        f"containing forbidden `{frag}` -- {neg['why']}")
    return bad


def corpus_violations(con: sqlite3.Connection, rules: list[dict],
                      log: logging.Logger) -> tuple[list[str], int]:
    """Run the real arm selection over every corpus site.

    A negative that is only checked against the rule TEXT would miss a rule that
    acquires the shape through its `when` condition instead of its `matches`.
    """
    em = emit.Emitter(con, log)
    forbidden: dict[str, set[str]] = {}
    for rule in rules:
        for neg in rule["negative"]:
            names = set((neg.get("must_not_match") or "").split("|")) - {""}
            forbidden.setdefault(rule["name"], set()).update(names)

    rows = con.execute(
        "SELECT o.id, o.symbol, t.name, f.path, o.span_start FROM operation o "
        "JOIN member mb ON mb.id = o.method_id "
        "JOIN type t ON t.id = mb.type_id "
        "JOIN file f ON f.id = t.file_id "
        "WHERE o.kind='Invocation' AND o.symbol IS NOT NULL "
        "AND o.symbol LIKE '%PeripheralRegisterExtensions.%' "
        "ORDER BY t.name, o.span_start").fetchall()

    bad: list[str] = []
    checked = 0
    for oid, symbol, type_name, path, span in rows:
        name = em.combinator(symbol)
        if name is None:
            continue
        b = em.bind(oid, symbol)

        def present(param: str, b=b) -> bool:
            v = b.get(param)
            return v is not None and v[0] != "DefaultValue"

        flags = {
            "field": em.out_field(oid, symbol) is not None,
            "provider": present("valueProviderCallback"),
            "writer": present("writeCallback"),
        }
        for rule in em.rules:
            if name not in rule["matches"].split("|"):
                continue
            cond = rule.get("when")
            if cond and not any(flags.get(tok.strip(), False)
                                for tok in cond.split(" or ")):
                continue
            checked += 1
            if name in forbidden.get(rule["name"], ()):
                bad.append(f"{type_name} {path}@{span}: `{name}` selected rule "
                           f"{rule['name']}, which must not match it")
            break
    return bad, checked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    args = ap.parse_args()

    logdir = ROOT / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(message)s",
        handlers=[logging.FileHandler(logdir / "check_rule_negatives.log", mode="w"),
                  logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("check_rule_negatives")

    rules = rules_with_negatives(ROOT / "rulesdb" / "rules")
    if not rules:
        log.error("no rule declares a `negative` -- nothing is guarded")
        return 1

    bad = static_violations(rules)
    checked = 0
    db = ROOT / args.db
    if db.exists():
        con = sqlite3.connect(db)
        corpus_bad, checked = corpus_violations(con, rules, log)
        bad += corpus_bad
    else:
        # Never silently pass: the corpus half of the check did not run.
        log.warning("%s absent -- static checks only, corpus arms NOT verified",
                    args.db)

    n_neg = sum(len(r["negative"]) for r in rules)
    if bad:
        log.error("%d negative-shape violation(s):", len(bad))
        for b in bad:
            log.error("  %s", b)
        return 1
    log.info("%d negative shape(s) on %d rule(s) hold over %d corpus site(s)",
             n_neg, len(rules), checked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
