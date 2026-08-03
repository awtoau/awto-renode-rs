#!/usr/bin/env python3
"""Focused regression checks for issue #58's implemented semantic rules."""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emit import Emitter  # noqa: E402
from emitter.lang.mutable_static import accessed_mutable_statics  # noqa: E402
from semantic_differences_census import measure  # noqa: E402


def root() -> Path:
    return Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], check=True,
        capture_output=True, text=True).stdout.strip())


def main() -> int:
    repo = root()
    con = sqlite3.connect(repo / "rulesdb/patterns.db")
    log = logging.getLogger("semantic-differences")
    log.addHandler(logging.NullHandler())
    em = Emitter(con, log)

    # Positive control: a real ordinary method, not an interface signature or
    # the register DSL's special out-parameter path.
    rendered = "\n".join(em.emit_peripheral_method("ENC28J60", "SetLowByteOf"))
    assert "of_what: &mut i32" in rendered, rendered
    assert "*of_what =" in rendered, rendered
    assert "(*of_what &" in rendered, rendered

    # Positive call-boundary control: the callee declares two out parameters.
    call_id = con.execute(
        "SELECT o.id FROM operation o JOIN member callee ON callee.key=o.symbol "
        "WHERE o.kind='Invocation' "
        "AND (SELECT COUNT(*) FROM parameter p WHERE p.method_id=callee.id "
        "     AND p.is_out=1)=2 "
        "AND (SELECT COUNT(*) FROM parameter p WHERE p.method_id=callee.id "
        "     AND (p.is_out=1 OR p.is_ref=1))=2 LIMIT 1").fetchone()[0]
    call = em.emit_expr(call_id)
    assert call.count("&mut ") == 2, call

    # Positive and negative controls for mutable-static classification.
    logger = con.execute(
        "SELECT mb.id FROM member mb JOIN type t ON t.id=mb.type_id "
        "WHERE t.key='Antmicro.Renode.Logging.Logger' "
        "AND mb.name='UpdateMinimumLevel'").fetchone()[0]
    assert accessed_mutable_statics(em, logger) == [
        "Antmicro.Renode.Logging.Logger.minLevel"]
    ordinary = con.execute(
        "SELECT mb.id FROM member mb JOIN type t ON t.id=mb.type_id "
        "WHERE t.name='ENC28J60' AND mb.name='SetLowByteOf'").fetchone()[0]
    assert accessed_mutable_statics(em, ordinary) == []

    census = measure(repo)
    assert census["corpus"]["config"] == "tree"
    assert census["statics"]["all_fields"] == (
        census["statics"]["const_valued"]
        + census["statics"]["readonly_nonconst"]
        + census["statics"]["genuinely_mutable"]
        + census["statics"]["cctor_only_nonreadonly"]
        + census["statics"]["nonreadonly_without_recorded_write"])
    assert len(census["statics"]["mutable_instances"]) == (
        census["statics"]["genuinely_mutable"])
    print("ok: ref/out emission, call borrowing, mutable-static guard, census")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
