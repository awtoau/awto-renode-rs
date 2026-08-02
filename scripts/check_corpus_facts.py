#!/usr/bin/env python3
"""Fail when the converter ignores a fact the corpus already records.

Four omissions shared one shape, and none of them could fail: Roslyn had
answered the question, the answer was in the database, and nothing read it. A
dropped fact is not an error anywhere -- it is a default, a zero, or a shorter
array, all of which compile and all of which pass every test that does not
happen to look.

So each is turned into an assertion here, phrased against the CORPUS rather
than against a remembered number. `check_derived.py` guards a value copied out
of a source of truth; this guards a value never read from one.

  1. Every member of the C# field-mode enum has a `renode_regs::FieldMode`
     constant at the same bit, and renders to it. Six of twelve did not, so
     `ReadToClear` rendered as `FieldMode::default()`.
  2. Every register whose C# constructor passes a reset value emits it. The
     dictionary form declared `reset_from: null`, so all of them emitted 0.
  3. Every field-handle array is as long as the C# declares. They were sized
     from the highest index the register map bound, which is smaller.
  4. `mod reg` holds every member of the enum it names. It held only the
     registers that emitted, while saying otherwise.

Run:  python3 scripts/check_corpus_facts.py
Log:  ./tmp/logs/check_corpus_facts.log
Exit: 0 clean, 1 if the converter is ignoring a recorded fact.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def check_field_modes(root: Path, con: sqlite3.Connection, em, log) -> list[str]:
    """Every C# FieldMode member reaches Rust, at the same bit."""
    bad: list[str] = []
    spec = em.project.get("field_mode", {})
    key = spec.get("enum")
    members = con.execute(
        "SELECT mb.name, mb.const_value FROM member mb JOIN type t ON t.id = mb.type_id "
        "WHERE t.key = ? AND mb.kind = 'field' AND mb.const_value IS NOT NULL",
        (key,)).fetchall()
    if not members:
        return [f"the corpus holds no enum `{key}` -- the field-mode rule names "
                f"a type that is not there, so NOTHING is being checked"]
    src = (root / "src" / "renode-regs" / "src" / "lib.rs").read_text()
    consts = {m.group(1): int(m.group(2))
              for m in re.finditer(r"pub const ([A-Z0-9_]+): Self = Self\(1 << (\d+)\);", src)}
    from emitter.plugins.register_dsl import to_const
    for name, value in sorted(members, key=lambda r: int(r[1])):
        want = to_const(name)
        bit = int(value).bit_length() - 1
        if want not in consts:
            bad.append(f"C# `FieldMode.{name}` ({value}) has no "
                       f"`renode_regs::FieldMode::{want}`")
        elif consts[want] != bit:
            bad.append(f"C# `FieldMode.{name}` is 1 << {bit}, Rust "
                       f"`{want}` is 1 << {consts[want]}")
        # ... and the emitter must actually render it, not drop the bit.
        em.gaps = []
        rendered = em.render_mode(str(value))
        if f"FieldMode::{want}" not in rendered or em.gaps:
            bad.append(f"C# `FieldMode.{name}` renders as `{rendered}`, which "
                       f"does not name it")
        log.info("    %-22s 1 << %-2d  %s", name, bit, rendered)
    return bad


def check_reset_values(con: sqlite3.Connection, em, log) -> list[str]:
    """Every non-zero C# reset value reaches a `bank.define`.

    Read from the corpus, not from a list: every register-creating constructor
    call that passes a folded non-zero `resetValue`, in every type the forms
    can locate registers in."""
    bad: list[str] = []
    want: dict[tuple[str, str], list[int]] = {}
    for tname, mname, mid in con.execute(
            "SELECT t.name, mb.name, mb.id FROM member mb "
            "JOIN type t ON t.id = mb.type_id JOIN method m ON m.member_id = mb.id "
            "WHERE m.has_body = 1 ORDER BY t.name, mb.name"):
        for oid, in con.execute(
                "SELECT id FROM operation WHERE method_id=? AND kind='ObjectCreation' "
                "AND symbol LIKE '%Register.%Register(%'", (mid,)):
            for aid, sym in con.execute(
                    "SELECT id, symbol FROM operation WHERE parent_id=? AND kind='Argument'",
                    (oid,)):
                if not sym or sym.split()[-1] != "resetValue":
                    continue
                row = con.execute(
                    "SELECT const_value FROM operation WHERE parent_id=? "
                    "ORDER BY ordinal LIMIT 1", (aid,)).fetchone()
                if row and row[0] and int(row[0]) != 0:
                    want.setdefault((tname, mname), []).append(int(row[0]))
    total = sum(len(v) for v in want.values())
    log.info("    %d non-zero reset value(s) in %d method(s)", total, len(want))
    for (tname, mname), values in sorted(want.items()):
        mid = con.execute(
            "SELECT mb.id FROM member mb JOIN type t ON t.id = mb.type_id "
            "WHERE t.name=? AND mb.name=?", (tname, mname)).fetchone()
        found = {int(r[2]) for r in em.find_registers(mid[0])}
        missing = sorted(set(values) - found)
        log.info("    %-24s %-18s %d site(s), %s", tname, mname, len(values),
                 "ok" if not missing else f"MISSING {[hex(v) for v in missing]}")
        for v in missing:
            bad.append(f"{tname}.{mname}: the C# passes reset value 0x{v:X} and "
                       f"no register carries it")
    return bad


def check_handle_arrays(con: sqlite3.Connection, em, log) -> list[str]:
    """Every emitted handle array is as long as its C# declaration."""
    bad: list[str] = []
    seen = 0
    for tname, fname, dt in con.execute(
            "SELECT t.name, mb.name, mb.declared_type FROM member mb "
            "JOIN type t ON t.id = mb.type_id WHERE mb.kind = 'field' "
            "AND mb.declared_type LIKE '%RegisterField[]' ORDER BY t.name, mb.name"):
        from emitter.core import snake
        base = snake(fname)
        declared, why = em.declared_array_length(tname, base)
        if declared is None:
            log.info("    %-22s %-22s declaration states no length (%s)",
                     tname, fname, why)
            continue
        seen += 1
        log.info("    %-22s %-22s C# declares %d", tname, fname, declared)
    if not seen:
        bad.append("no array-of-handles field has a readable declared length -- "
                   "field initialisers are not in the corpus, so array sizes "
                   "are back to being inferred from usage")
    return bad


def check_offset_modules(root: Path, con: sqlite3.Connection, log) -> list[str]:
    """A `mod reg` that names a C# enum holds all of it.

    Counted against the CORPUS enum, not against a remembered number. The
    header used to say "from the C# `enum Register`" over a module holding
    only the registers that emitted -- 13 of ADC's 20, 1 of SYSCFG's 30 --
    which is the one thing generated output may never do."""
    from emitter.plugins.register_dsl import to_const
    bad: list[str] = []
    named = re.compile(r"Every member of the C# `enum (\w+)`")
    owner = re.compile(r"Register layout for `(\w+)`")
    for f in sorted((root / "src").rglob("*_registers.rs")):
        text = f.read_text()
        m, o = named.search(text), owner.search(text)
        if not m or not o:
            continue
        rel = f.relative_to(root)
        body = text.split("pub mod reg {", 1)[1].split("\n}", 1)[0]
        consts = set(re.findall(r"pub const ([A-Z0-9_]+): u64", body))
        want = {to_const(n) for n, v in con.execute(
            "SELECT mb.name, mb.const_value FROM member mb "
            "JOIN type t ON t.id = mb.type_id WHERE t.kind = 'enum' "
            "AND t.name = ? AND t.key LIKE ? AND mb.const_value IS NOT NULL",
            (m.group(1), f"%.{o.group(1)}.%")) if int(v) >= 0}
        missing = sorted(want - consts)
        log.info("    %-46s %-14s %d of %d member(s)%s", str(rel), m.group(1),
                 len(consts), len(want), "" if not missing else "  INCOMPLETE")
        if not want:
            bad.append(f"{rel}: names `enum {m.group(1)}`, which the corpus "
                       f"does not hold for `{o.group(1)}`")
        for name in missing:
            bad.append(f"{rel}: `mod reg` claims every member of "
                       f"`enum {m.group(1)}` and omits {name}")
    return bad


def main() -> int:
    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_corpus_facts")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_corpus_facts.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus database -- run the ingest first")
        return 1
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    import emit
    em = emit.Emitter(con, log, root / "rulesdb" / "rules")

    failures: list[str] = []
    for title, fn in (
        ("1. every C# field-mode member maps to a Rust constant",
         lambda: check_field_modes(root, con, em, log)),
        ("2. every C# reset value reaches the register",
         lambda: check_reset_values(con, em, log)),
        ("3. handle arrays are as long as the C# declares",
         lambda: check_handle_arrays(con, em, log)),
        ("4. `mod reg` holds what it says it holds",
         lambda: check_offset_modules(root, con, log)),
    ):
        log.info("")
        log.info("%s", title)
        failures.extend(fn())

    log.info("")
    if failures:
        log.error("%d fact(s) the corpus records and the converter does not read:",
                  len(failures))
        for f in failures:
            log.error("    %s", f)
        return 1
    log.info("every checked corpus fact reaches the output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
