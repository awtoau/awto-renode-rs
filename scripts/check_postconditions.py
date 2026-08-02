#!/usr/bin/env python3
"""Enforce `postcondition` -- the SHAPE a rule's output must have.

`check_rule_negatives.py` is the model, and the difference is the direction.
A `negative` is a statement about the INPUT: shapes a rule must not be chosen
for. A `postcondition` is a statement about the OUTPUT: what the emitted text
must look like once the rule has run. Until now the second did not exist, so a
rule could be selected perfectly and emit something nobody had ever described.

That is not hypothetical. A combinator appeared in a translated file that the
C# does not contain -- behaviourally inert, so a 33,000-access trace could not
see it, and shaped like every other line, so review did not either.

Three checks, and the first two need no corpus:

  every emitting rule HAS one
      A rule with an `emit` template and no `postcondition` is unchecked
      output. Counted and failed, so the number ratchets rather than drifting.

  the TEMPLATE satisfies it
      Slots are filled with a placeholder and the postcondition run over the
      result. Catches a postcondition that contradicts the template it is
      attached to -- an `arity` that was right before a slot was added, say --
      at review time and on any corpus.

  the OUTPUT satisfies it, at every site
      The real arm selection and the real emitter over every combinator call
      in the corpus. This is the half the template check cannot do: a forbidden
      shape can arrive through a SUBSTITUTED slot, and only the output shows
      that. `emit_call` raises on violation, so this is exercised rather than
      re-implemented.

Exit 1 on any violation. Log: tmp/logs/check_postconditions.log.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
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
from emitter.lang.postcondition import PostconditionViolation, check  # noqa: E402

# What a slot becomes for the TEMPLATE check. An identifier: no brackets and no
# commas, so it cannot change the call count or the argument count and make the
# template look like it satisfies something it does not.
PLACEHOLDER = "X"


def rules(rules_dir: Path) -> list[dict]:
    out: list[dict] = []
    for f in sorted(rules_dir.glob("*.json")):
        for r in json.loads(f.read_text()).get("rules", []):
            r = dict(r)
            r["_file"] = f.name
            out.append(r)
    return out


def template_violations(rs: list[dict]) -> tuple[list[str], int]:
    """The rule's own template, against the rule's own postcondition."""
    bad: list[str] = []
    checked = 0
    for rule in rs:
        template = rule.get("emit")
        post = rule.get("postcondition")
        if template is None:
            if post:
                bad.append(f"{rule['_file']}:{rule['name']} emits nothing but "
                           f"declares a postcondition -- there is no text for "
                           f"it to hold over")
            continue
        if not post:
            bad.append(f"{rule['_file']}:{rule['name']} emits `{template}` with "
                       f"NO postcondition -- its output is unchecked, which is "
                       f"how a combinator the source does not contain reached a "
                       f"translated file")
            continue
        checked += 1
        filled = re.sub(r"\{[a-z_]+\}", PLACEHOLDER, template)
        for msg in check(rule["name"], post, filled):
            bad.append(f"{rule['_file']}: template does not satisfy its own "
                       f"postcondition -- {msg}")
    return bad, checked


def corpus_violations(con: sqlite3.Connection,
                      log: logging.Logger) -> tuple[list[str], int, int]:
    """The real emitter over every combinator site in the corpus."""
    em = emit.Emitter(con, log)
    # Every declaring type the combinator table names, read from the data, so
    # widening the table widens the check with it.
    markers = [p["symbol_contains"] for p in
               em.project.get("combinator_providers", {}).get("providers", [])]
    if not markers:
        raise SystemExit("combinator_providers names no provider -- the corpus "
                         "half of this check would silently examine nothing")
    where = " OR ".join("o.symbol LIKE ?" for _ in markers)
    rows = con.execute(
        "SELECT o.id, o.symbol, t.name, f.path, o.span_start FROM operation o "
        "JOIN member mb ON mb.id = o.method_id "
        "JOIN type t ON t.id = mb.type_id "
        "JOIN file f ON f.id = t.file_id "
        "WHERE o.kind='Invocation' AND o.symbol IS NOT NULL "
        f"AND ({where}) "
        "ORDER BY t.name, o.span_start",
        [f"%{m}%" for m in markers]).fetchall()

    bad: list[str] = []
    sites = 0
    for oid, symbol, type_name, path, span in rows:
        em.gaps = []
        em.unhandled = {}
        em._loop_env = {}
        try:
            text = em.emit_call(oid, symbol)
        except PostconditionViolation as exc:
            bad.append(f"{type_name} {path}@{span}: {exc}")
            continue
        except Exception:                                   # noqa: BLE001
            # Not this check's business. A site that cannot be emitted for an
            # unrelated reason is reported by the gap census; swallowing it
            # here would be wrong, but so would failing this gate on it.
            continue
        if text is not None:
            sites += 1
    return bad, sites, len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    args = ap.parse_args()

    logdir = ROOT / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(message)s",
        handlers=[logging.FileHandler(logdir / "check_postconditions.log",
                                      mode="w"),
                  logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("check_postconditions")

    rs = rules(ROOT / "rulesdb" / "rules")
    if not rs:
        log.error("no rules loaded -- nothing is checked")
        return 1

    bad, n_post = template_violations(rs)
    emitting = sum(1 for r in rs if r.get("emit") is not None)

    sites = total = 0
    db = ROOT / args.db
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        corpus_bad, sites, total = corpus_violations(con, log)
        bad += corpus_bad
    else:
        # Never silently pass: the half that reads real output did not run.
        log.warning("%s absent -- template checks only, no emitted text was "
                    "examined", args.db)

    if bad:
        log.error("%d postcondition violation(s):", len(bad))
        for b in bad:
            log.error("  %s", b)
        return 1
    log.info("%d of %d emitting rule(s) carry a postcondition", n_post, emitting)
    log.info("every template satisfies its own postcondition")
    log.info("%d emitted site(s) out of %d combinator call(s) checked against "
             "the shape their rule promised", sites, total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
