#!/usr/bin/env python3
"""Where does a register builder live in a LOCAL rather than in one chain?

`emit_registers` associates combinator calls with a register by the span start
of the chain's ROOT. That is exact for `Registers.X.Define(this).WithFlag(..)`,
where every call in the fluent expression shares the root's span. It says
nothing at all about

    var reg = Registers.X.Define(this).WithReservedBits(12, 4);
    ...
    reg.WithTaggedFlag(..).WithFlag(..);

because the second statement's chain root is a LOCAL REFERENCE with a span of
its own. Those calls belonged to no chain and were dropped.

This script answers the question the fix has to be written against: how many
sites are that shape, and in how many methods -- so the rule is measured rather
than fitted to the one that was noticed.

It reports two things per site:

  * the combinator calls whose chain root is a local reference, and
  * whether the local is DECLARED from a register form (`var reg = X.Define(..)`)
    or arrives some other way, because only the first can be resolved back to a
    register offset without more information.

Run:  python3 scripts/query_local_builders.py [--db rulesdb/patterns.db]
Log:  ./tmp/logs/query_local_builders.log
Exit: 0 always -- this is a measurement, not a gate.
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
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def load_project(root: Path) -> dict:
    """The register-DSL data: what counts as a combinator, and what locates a
    register. Read from the rules rather than retyped, so widening the provider
    list widens this measurement too."""
    out: dict = {}
    for f in sorted((root / "rulesdb" / "rules").rglob("*.json")):
        doc = json.loads(f.read_text())
        for k in ("combinator_providers", "register_forms"):
            if k in doc:
                out[k] = doc[k]
    return out


def combinator(project: dict, symbol: str) -> str | None:
    """Same selection `RegisterDsl.combinator` makes: longest marker wins, and
    a provider's `leaf_starts_with` says which of its members are combinators."""
    best: tuple[int, str] | None = None
    for prov in project.get("combinator_providers", {}).get("providers", []):
        marker = prov["symbol_contains"]
        if marker not in symbol:
            continue
        leaf = symbol.split(marker, 1)[1].split("<")[0].split("(")[0]
        starts = prov.get("leaf_starts_with")
        if starts and not leaf.startswith(tuple(starts)):
            continue
        if best is None or len(marker) > best[0]:
            best = (len(marker), leaf)
    return best[1] if best else None


def chain_root(con: sqlite3.Connection, oid: int) -> tuple[str, str | None]:
    """Walk the receiver (child ordinal 0) down to the expression the chain
    starts from.

    `Argument` is in the descent list because the DSL is EXTENSION methods: for
    `Registers.X.Define(this)` Roslyn puts the receiver in `Arguments[0]`, not
    in `Instance`, so stopping at the first `Argument` reports every fluent
    chain in the corpus as rooted at an argument and none at anything else."""
    node = oid
    for _ in range(64):
        row = con.execute(
            "SELECT id, kind, symbol FROM operation WHERE parent_id=? "
            "ORDER BY ordinal LIMIT 1", (node,)).fetchone()
        if row is None:
            break
        cid, kind, sym = row
        if kind in ("Invocation", "Conversion", "Parenthesized", "Argument"):
            node = cid
            continue
        return kind, sym
    return "?", None


def main() -> int:
    root = repo_root()
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(root / "rulesdb" / "patterns.db"))
    args = ap.parse_args()

    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("query_local_builders")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(logdir / "query_local_builders.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    project = load_project(root)
    forms = project.get("register_forms", [])
    con = sqlite3.connect(args.db)

    # Every combinator call, bucketed by its chain root's kind.
    by_root: dict[str, int] = {}
    sites: dict[tuple[str, str], dict[str, set]] = {}
    for oid, sym, mid in con.execute(
            "SELECT id, symbol, method_id FROM operation "
            "WHERE kind='Invocation' AND symbol IS NOT NULL"):
        if combinator(project, sym) is None:
            continue
        kind, rsym = chain_root(con, oid)
        by_root[kind] = by_root.get(kind, 0) + 1
        if kind != "LocalReference":
            continue
        tn, mn = con.execute(
            "SELECT t.name, mb.name FROM member mb JOIN type t ON t.id=mb.type_id "
            "WHERE mb.id=?", (mid,)).fetchone()
        entry = sites.setdefault((tn, mn), {"locals": set(), "calls": set()})
        entry["locals"].add((rsym or "?").split()[-1])
        entry["calls"].add(oid)

    log.info("combinator calls by chain-root kind (cut corpus):")
    for kind, n in sorted(by_root.items(), key=lambda kv: -kv[1]):
        log.info("    %-24s %d", kind, n)
    log.info("")

    # Which of those locals are DECLARED from a register form? A declarator
    # whose initialiser subtree contains a form call is a register held in a
    # local; anything else is a builder that arrived by another route and
    # cannot be resolved to an offset from the declaration alone.
    log.info("methods whose combinator chain root is a LOCAL: %d", len(sites))
    total_calls = 0
    resolvable_calls = 0
    for (tn, mn), e in sorted(sites.items()):
        mid, = con.execute(
            "SELECT mb.id FROM member mb JOIN type t ON t.id=mb.type_id "
            "WHERE t.name=? AND mb.name=?", (tn, mn)).fetchone()
        defined: set[str] = set()
        for did, in con.execute(
                "SELECT id FROM operation WHERE method_id=? AND "
                "kind='VariableDeclarator'", (mid,)):
            # The name is in `detail`, not `symbol` -- `symbol` is null on a
            # VariableDeclarator, which is the same trap `declared_in` records.
            try:
                name = json.loads(con.execute(
                    "SELECT detail FROM operation WHERE id=?",
                    (did,)).fetchone()[0] or "{}").get("local") or "?"
            except json.JSONDecodeError:
                name = "?"
            start, length = con.execute(
                "SELECT span_start, span_len FROM operation WHERE id=?",
                (did,)).fetchone()
            hit = con.execute(
                "SELECT count(*) FROM operation WHERE method_id=? AND "
                "kind='Invocation' AND symbol IS NOT NULL AND span_start>=? "
                "AND span_start<? AND (" +
                " OR ".join("symbol LIKE ?" for _ in forms) + ")",
                (mid, start, start + length,
                 *[f"%{f['symbol_contains']}%" for f in forms])).fetchone()[0]
            if hit:
                defined.add(name)
        total_calls += len(e["calls"])
        # Only the ROOT local matters. Reporting any form-declared local in the
        # method credited STM32_Timer with the shape because its `registersMap`
        # is form-declared, while the local actually at the chain root is an
        # unrelated `register` built by `new DoubleWordRegister(this)`.
        resolvable = sorted(e["locals"] & defined)
        other = sorted(e["locals"] - defined)
        log.info("    %-28s %-22s %2d call(s); resolvable: %-52s other: %s",
                 tn, mn, len(e["calls"]),
                 ", ".join(resolvable) or "-", ", ".join(other) or "-")
        resolvable_calls += sum(
            1 for oid in e["calls"]
            if (chain_root(con, oid)[1] or "?").split()[-1] in defined)
    log.info("")
    log.info("total combinator calls rooted at a local: %d", total_calls)
    log.info("of those, rooted at a local DECLARED from a register form: %d",
             resolvable_calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
