#!/usr/bin/env python3
"""Count register-DSL combinator sites by which rule arm they take.

The question this answers: how many `WithValueField` / `WithFlag` calls bind no
`out` handle and carry no callback? Those are ANONYMOUS STORED fields in C# --
the register keeps the written value and reads it back -- and they must not be
confused with `WithTag` / `WithTaggedFlag`, which are genuine tags that store
nothing.

It reads the SAME rules and the SAME binding code the emitter uses, so the
counts describe what the converter actually does rather than a re-derivation
that can drift from it.

    python3 scripts/audit_anon_fields.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True).strip())


ROOT = repo_root()
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "core"))

import emit  # noqa: E402
# FieldMode rendering lives with the register DSL, not with the driver -- it is
# a Renode type, so it moved into the plugin. Importing it from `emit` raised
# AttributeError the moment it moved, which is how this call was found.
from emitter.plugins.register_dsl import render_mode  # noqa: E402


def audit(con: sqlite3.Connection, log: logging.Logger) -> dict:
    em = emit.Emitter(con, log)

    combinators = sorted({
        m for r in em.rules for m in r["matches"].split("|")})
    aliases = em.callback_aliases()

    # Every invocation in the corpus whose target is one of the DSL combinators.
    rows = con.execute(
        "SELECT o.id, o.symbol, t.name, f.path, o.span_start FROM operation o "
        "JOIN member mb ON mb.id = o.method_id "
        "JOIN type t ON t.id = mb.type_id "
        "JOIN file f ON f.id = t.file_id "
        "WHERE o.kind='Invocation' AND o.symbol IS NOT NULL "
        "AND o.symbol LIKE '%PeripheralRegisterExtensions.%' "
        "ORDER BY t.name, o.span_start").fetchall()

    by_rule: Counter[str] = Counter()
    anon_by_type: Counter[str] = Counter()
    anon_sites: list[dict] = []
    per_type_combinator: dict[str, Counter[str]] = defaultdict(Counter)

    for oid, symbol, type_name, path, span in rows:
        name = em.combinator(symbol)
        if name is None or name not in combinators:
            continue
        b = em.bind(oid, symbol)

        def present(param: str, b=b) -> bool:
            v = b.get(param)
            return v is not None and v[0] != "DefaultValue"

        # The emitter's OWN flags and the emitter's OWN arm selection. The copy
        # that used to be here knew three flags and read `when` as a
        # disjunction, so the moment the rules grew `a and b` conditions and
        # three more callback kinds this audit counted arms the converter does
        # not take -- while its docstring promised the opposite.
        flags = {"field": (em.out_field(oid, symbol)
                           or em.assigned_field(oid)) is not None}
        for param in em.bound_callbacks(b):
            flags[aliases.get(param, param)] = True
        rule = em.select_rule(name, flags)
        if rule is not None:
            by_rule[rule["name"]] += 1
            # The arm under investigation, read off the arm the converter
            # ACTUALLY took rather than re-derived from the flags: a site whose
            # chosen rule emits an anonymous STORED field. Re-deriving it as
            # "no flag set" under-counted by four the moment `emit_call` began
            # detecting changeCallback -- those sites still take this arm, they
            # simply stopped looking flagless.
            if "_anon" in (rule.get("emit") or ""):
                anon_by_type[type_name] += 1
                pos = (b.get("position") or (None, None, None))[2]
                width = (b.get("width") or (None, None, None))[2]
                mode = render_mode((b.get("mode") or (None, None, None))[2])
                # Callback kinds no rule template consumes. These are now
                # DETECTED -- `emit_call` reads every callback the corpus binds
                # and reports one it cannot place -- so a site carrying one no
                # longer loses its behaviour in silence. Counted here to say
                # how much behaviour that gap covers.
                unmodelled = [c for c in ("changeCallback", "readCallback",
                                          "shadowReloadCallback")
                              if present(c)]
                anon_sites.append({
                    "type": type_name, "combinator": name, "pos": pos,
                    "width": width, "mode": mode, "file": path, "span": span,
                    "unmodelled_callbacks": unmodelled})

    return {
        "by_rule": dict(sorted(by_rule.items())),
        "anonymous_stored_by_type": dict(
            sorted(anon_by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
        "anonymous_stored_total": sum(anon_by_type.values()),
        "sites": anon_sites,
        "per_type_combinator": {k: dict(v) for k, v in per_type_combinator.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    logdir = ROOT / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(message)s",
        handlers=[logging.FileHandler(logdir / "audit_anon_fields.log", mode="w"),
                  logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("audit_anon_fields")

    con = sqlite3.connect(ROOT / args.db)
    res = audit(con, log)

    if args.json:
        log.info(json.dumps(res, indent=2))
        return 0

    log.info("combinator sites by rule arm")
    for k, v in res["by_rule"].items():
        log.info("  %-24s %4d", k, v)
    log.info("")
    log.info("anonymous STORED fields (no out, no callback), by peripheral")
    for k, v in res["anonymous_stored_by_type"].items():
        log.info("  %-28s %4d", k, v)
    log.info("  %-28s %4d", "TOTAL", res["anonymous_stored_total"])
    log.info("")
    log.info("anonymous STORED fields by (peripheral, combinator, mode)")
    grouped: Counter[tuple[str, str, str]] = Counter(
        (s["type"], s["combinator"], s["mode"]) for s in res["sites"])
    for (t, c, m), n in sorted(grouped.items()):
        log.info("  %4d  %-28s %-15s %s", n, t, c, m)

    # Not this fix's problem, but it is this fix's rule arm: the anonymous arm
    # owns these sites and no template consumes their callback, so the
    # behaviour is still missing. It is no longer SILENT -- `emit_call` now
    # inspects every callback the corpus binds and reports one it cannot place
    # -- so this list is the size of that gap, not a count of unseen drops.
    withcb = [s for s in res["sites"] if s["unmodelled_callbacks"]]
    log.info("")
    log.info("of those, %d carry a callback no rule template consumes "
             "(behaviour missing; emit_call reports it as a gap):", len(withcb))
    for s in withcb:
        log.info("  %-28s %-15s pos=%s %s",
                 s["type"], s["combinator"], s["pos"],
                 ", ".join(s["unmodelled_callbacks"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
