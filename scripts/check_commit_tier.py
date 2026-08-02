#!/usr/bin/env python3
"""`committed` must be keyed on the ORACLE, not on which files were ingested.

WHY THIS EXISTS
---------------
`rule_commit_threshold` in rulesdb/schema.sql is the only thing standing between
"a rule emits" and "a rule is right". It used to count instances whose
`corpus_run.config <> 'breadth'` -- that is, it keyed on WHICH FILES THE INGEST
WALKED, and never read `oracle_tier`, the column that records whether a trace
actually checked the instance's output.

That was already wrong while the corpus cut existed: adding one file to the cut
promoted matches into the counting set without any trace looking at them. When
the cut was removed (docs/decisions/remove-the-cut.md) it would have become
vacuous, because every canonical run is non-breadth -- so `committed` would have
degraded to `general` in silence, which is the precise failure the two tiers
exist to prevent.

The trigger now counts `oracle_tier > 0`.

WHAT THIS PROVES
----------------
Three instances, identical in every respect except `oracle_tier`:

  * at tier 0 the CURRENT trigger REFUSES `committed`   -- and the OLD trigger,
    reconstructed here from the schema it replaced, ACCEPTS the same data. That
    contrast is the point: the old key could not see the difference.
  * at tier > 0 the current trigger ACCEPTS.

Both triggers are exercised against a scratch database built from the real
schema.sql, so this cannot pass by describing a trigger that is not installed.

It also checks the door beside it: both threshold triggers fire on UPDATE only,
so a rule INSERTED at 'committed' bypassed them entirely. Nothing populates these
tables yet, so the population path is still to be written -- and inserting a rule
with its status already set is the obvious way to write it.

Run:  python3 scripts/check_commit_tier.py
Log:  ./tmp/logs/check_commit_tier.log
Exit: 0 the key is the oracle, 1 it is not.
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

# The trigger as it stood before docs/decisions/remove-the-cut.md, kept here
# ONLY so the comparison is a real execution rather than an assertion about
# history. Nothing else may use it.
OLD_TRIGGER = """
CREATE TRIGGER old_rule_commit_threshold
BEFORE UPDATE OF status ON rule
WHEN NEW.status = 'committed'
     AND (SELECT COUNT(*) FROM rule_instance ri
          JOIN operation o   ON o.id = ri.operation_id
          JOIN corpus_run cr ON cr.id = o.run_id
          WHERE ri.rule_id = NEW.id AND cr.config <> 'breadth')
         < NEW.min_instances_required
BEGIN
    SELECT RAISE(ABORT, 'old trigger: below threshold');
END;
"""


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def fixture(schema: str, *, config: str, oracle_tier: int,
            old_trigger: bool) -> sqlite3.Connection:
    """One rule, three instances, all at the given oracle_tier.

    The run is tagged `config` so the old key can be exercised on exactly the
    data the new key sees. Everything else is the minimum the foreign keys need.
    """
    con = sqlite3.connect(":memory:")
    con.executescript(schema)
    if old_trigger:
        con.execute("DROP TRIGGER IF EXISTS rule_commit_threshold")
        con.executescript(OLD_TRIGGER)
    con.execute("INSERT INTO corpus_run(id,started_at,renode_commit,tool_version,"
                "config) VALUES (1,'2026-08-02T00:00:00+10:00','x','x',?)",
                (config,))
    con.execute("INSERT INTO file(id,run_id,path,sha256,loc) "
                "VALUES (1,1,'A.cs','x',1)")
    con.execute("INSERT INTO type(id,run_id,file_id,key,namespace,name,kind,"
                "accessibility) VALUES (1,1,1,'N.A','N','A','class','public')")
    con.execute("INSERT INTO member(id,run_id,type_id,key,kind,name,"
                "declared_type,accessibility) "
                "VALUES (1,1,1,'N.A.M()','method','M','void','public')")
    con.execute("INSERT INTO method(member_id,signature,return_type,has_body) "
                "VALUES (1,'M()','void',1)")
    for op in (1, 2, 3):
        con.execute("INSERT INTO operation(id,run_id,method_id,ordinal,depth,"
                    "kind,span_start,span_len) VALUES (?,1,1,?,0,'Invocation',0,1)",
                    (op, op))
    con.execute("INSERT INTO rule(id,name,version,family,description,matcher,"
                "emitter,created_run_id) "
                "VALUES (1,'r',1,'F','d','m','e',1)")
    for op in (1, 2, 3):
        con.execute("INSERT INTO rule_instance(rule_id,operation_id,validated_at,"
                    "oracle_tier,evidence) VALUES (1,?,'2026-08-02',?,'e')",
                    (op, oracle_tier))
    return con


def commits(con: sqlite3.Connection) -> tuple[bool, str]:
    try:
        con.execute("UPDATE rule SET status='committed' WHERE id=1")
        return True, ""
    except sqlite3.IntegrityError as exc:
        return False, str(exc)


def inserts_as(con: sqlite3.Connection, status: str) -> tuple[bool, str]:
    """Can a rule be created already carrying a validated status?"""
    try:
        con.execute("INSERT INTO rule(id,name,version,family,description,matcher,"
                    "emitter,status,created_run_id) "
                    "VALUES (2,'r2',1,'F','d','m','e',?,1)", (status,))
        return True, ""
    except sqlite3.IntegrityError as exc:
        return False, str(exc)


def main() -> int:
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_commit_tier")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" / "check_commit_tier.log",
                                  mode="w"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    schema = (root / "rulesdb" / "schema.sql").read_text()

    # (label, config, tier, old_trigger, must_commit)
    cases = [
        ("current trigger, 3 instances at oracle_tier=0",
         "tree", 0, False, False),
        ("current trigger, 3 instances at oracle_tier=1",
         "tree", 1, False, True),
        # Same rows, same run, the trigger that used to be there. It commits --
        # which is what makes the old key unusable once every run is non-breadth.
        ("OLD trigger, 3 instances at oracle_tier=0",
         "tree", 0, True, True),
        # And the old key's own escape hatch, for completeness: it only ever
        # refused when the RUN was tagged breadth, never when the oracle was
        # silent.
        ("OLD trigger, 3 instances at oracle_tier=0, run tagged breadth",
         "breadth", 0, True, False),
    ]

    bad = 0
    for label, config, tier, old, want in cases:
        con = fixture(schema, config=config, oracle_tier=tier, old_trigger=old)
        got, why = commits(con)
        con.close()
        verdict = "commits" if got else "REFUSED"
        if got == want:
            log.info("ok    %-56s %s", label, verdict)
            if not got:
                log.info("      %s", why)
        else:
            bad += 1
            log.error("FAIL  %-56s %s (wanted %s)", label, verdict,
                      "commits" if want else "REFUSED")

    # The UPDATE-only hole. Same fixture, but the status arrives with the row.
    for status, want in (("committed", False), ("general", False),
                         ("proposed", True)):
        con = fixture(schema, config="tree", oracle_tier=0, old_trigger=False)
        got, why = inserts_as(con, status)
        con.close()
        label = f"INSERT a new rule already at status={status!r}"
        if got == want:
            log.info("ok    %-56s %s", label, "inserts" if got else "REFUSED")
            if not got:
                log.info("      %s", why)
        else:
            bad += 1
            log.error("FAIL  %-56s %s (wanted %s)", label,
                      "inserts" if got else "REFUSED",
                      "inserts" if want else "REFUSED")

    log.info("")
    if bad:
        log.error("FAIL: %d case(s) wrong. `committed` is not keyed on the "
                  "oracle, so it claims a correctness guarantee nothing "
                  "supplies.", bad)
        return 1
    log.info("OK: `committed` requires oracle_tier > 0, and the key it replaced "
             "would have accepted the same unvalidated rule.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
