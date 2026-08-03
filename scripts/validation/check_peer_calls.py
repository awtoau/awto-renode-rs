#!/usr/bin/env python3
"""Guard declaring-type resolution for ordinary C# invocations.

Issue #54 was not a name-formatting bug. Roslyn had resolved
`BitHelper.GetValueFromBitsArray`, including that it is static and declared on
`BitHelper`, but the receiver-less fallback emitted `self.get_value...`. The
callback pass then reported an invented GPIO peer dependency.

The positive control proves an external static call is withheld and names its
declaring type. The two negative controls prove the guard does not also reject
an instance peer call or a static helper declared on the type being emitted.

Run:  python3 scripts/check_peer_calls.py
Log:  ./tmp/logs/check_peer_calls.log
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], text=True).strip())
sys.path.insert(0, str(ROOT / "scripts"))

from emitter.lang.invocation import invocation  # noqa: E402


class FixtureEmitter:
    def __init__(self, *, is_static: bool, declaring: str, current: str):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript("""
            CREATE TABLE type (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE member (
                id INTEGER PRIMARY KEY, run_id INTEGER, type_id INTEGER, key TEXT,
                is_static INTEGER);
            CREATE TABLE parameter (
                method_id INTEGER, ordinal INTEGER, name TEXT,
                is_out INTEGER, is_ref INTEGER);
            CREATE TABLE operation (
                id INTEGER PRIMARY KEY, kind TEXT, symbol TEXT);
        """)
        self.symbol = f"N.{declaring}.Target()"
        self._run_id = 1
        self.con.execute("INSERT INTO type VALUES (1, ?)", (declaring,))
        self.con.execute("INSERT INTO member VALUES (1, 1, 1, ?, ?)",
                         (self.symbol, int(is_static)))
        self.con.execute("INSERT INTO operation VALUES (10, 'Invocation', ?)",
                         (self.symbol,))
        self.language = {
            "invocations": {
                "self": "self.{method}({args})",
                "instance": "{receiver}.{method}({args})",
            },
            "stdlib": {"members": {}},
        }
        self._current_type = current
        self._invocation_symbol_cache: dict[int, str | None] = {}
        self._callee_cache: dict[str, tuple | None] = {}
        self._callee_params_cache: dict[int, tuple[tuple, ...]] = {}
        self._operation_kind_cache: dict[int, str | None] = {}
        self.unhandled: dict[str, int] = {}
        self.gaps: list[str] = []

    def children(self, _oid):
        return []

    def emit_expr(self, _oid):
        raise AssertionError("fixture has no child expressions")

    def stdlib_member(self, _symbol):
        return None


def main() -> int:
    log_dir = ROOT / "tmp" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(message)s",
        handlers=[logging.FileHandler(log_dir / "check_peer_calls.log", mode="w"),
                  logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("check_peer_calls")
    bad = 0

    external = FixtureEmitter(
        is_static=True, declaring="BitHelper", current="Peripheral")
    text = invocation(external, 10)
    if text != "/* StaticInvocation:BitHelper.Target */":
        log.error("external static call was not withheld: %r", text)
        bad += 1
    if external.gaps != [
            "static call `BitHelper.Target` has no Rust mapping"]:
        log.error("declaring type absent from gap: %r", external.gaps)
        bad += 1
    if external.unhandled != {
            "expr:StaticInvocation:BitHelper.Target": 1}:
        log.error("external static call was not counted: %r", external.unhandled)
        bad += 1

    for label, static, declaring in (
            ("instance peer", False, "Peripheral"),
            ("same-type static helper", True, "Peripheral")):
        em = FixtureEmitter(
            is_static=static, declaring=declaring, current="Peripheral")
        got = invocation(em, 10)
        if got != "self.target()" or em.gaps or em.unhandled:
            log.error("%s was falsely rejected: %r gaps=%r unhandled=%r",
                      label, got, em.gaps, em.unhandled)
            bad += 1

    if bad:
        return 1
    log.info("ok: external static calls name their declaring type; peer and "
             "same-type calls still lower")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
