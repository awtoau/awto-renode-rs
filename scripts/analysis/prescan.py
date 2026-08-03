#!/usr/bin/env python3
"""Classify every instance field's ownership, with the evidence for each.

The ownership decision has been made globally so far -- D1 says "every
reference-typed field becomes Rc<RefCell<T>>" -- and all four research reports
independently found that every working system does it PER SITE, with recorded
evidence and a legal UNKNOWN. Bun's LIFETIMES.tsv is the production example:
columns `file · struct · field · type · class · rust_type · evidence`, and the
instruction to its agents was "trust it over local guessing".

This is that table, computed from the corpus.

WHAT THIS IS NOT
----------------
STATIC evidence only. It sees declared types, reachability in the type graph,
and how often each field is read and written -- not what actually happens at
run time. A field that is never null in every real execution still looks
nullable here, and a cycle that is never traversed still looks like a cycle.

The dynamic half is the more valuable one and is not built: instrument C#
Renode, record which objects are genuinely shared, cyclic and long-lived, and
merge that in. c2rust-analyze runs the program to build a pointer derivation
graph precisely because static analysis cannot answer this; `pyrs` used
MonkeyType the same way. We can already run Renode and already capture traces,
so the instrumentation point exists.

Until then every row says `static` in its evidence column, and that word is
load-bearing: it means the classification is a starting point, not a verdict.

Run:  python3 scripts/prescan.py
Out:  docs/status/ownership.tsv   (the table)
      docs/status/ownership.mmd   (the object graph, Mermaid)
Log:  ./tmp/logs/prescan.log
"""

from __future__ import annotations

import argparse
import collections
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

# Declared types that are NOT object references, and why. Kept as data so the
# reasoning is visible rather than buried in a regex.
NOT_A_REFERENCE = {
    "IFlagRegisterField": "register handle -- D2 makes it a typed arena index",
    "IValueRegisterField": "register handle -- D2 makes it a typed arena index",
    "IEnumRegisterField": "register handle -- D2 makes it a typed arena index",
    "DoubleWordRegisterCollection": "the bank itself; elided, see register_collection",
    "RegisterMapper": "the bank's offset mapping; elided",
}

PRIMITIVES = {
    "int", "uint", "long", "ulong", "bool", "byte", "sbyte", "short", "ushort",
    "char", "double", "float", "decimal", "string", "object", "void",
}


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def short(t: str | None) -> str:
    return (t or "").split(".")[-1].strip("[]?").split("<")[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("prescan")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" / "prescan.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    con = sqlite3.connect(f"file:{root / args.db}?mode=ro", uri=True)
    _cfg = con.execute("SELECT config FROM corpus_run LIMIT 1").fetchone()
    breadth = bool(_cfg and _cfg[0] == "breadth")
    # Only CLASSES are object references. An enum-typed field is a VALUE --
    # classifying it SHARED because its type happens to be in the corpus was
    # wrong, and inflated both the shared count and the edge list.
    corpus_types = {r[0] for r in con.execute(
        "SELECT name FROM type WHERE kind IN ('class','interface')")}
    corpus_values = {r[0] for r in con.execute(
        "SELECT name FROM type WHERE kind IN ('enum','struct')")}

    # Reuse the EMITTER's type mapping rather than a second table here: a field
    # the converter can already type is not "unknown ownership", it is a value
    # or a callback slot. Two tables would drift.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
    from emit import Emitter
    quiet = logging.getLogger("prescan_quiet")
    quiet.addHandler(logging.NullHandler())
    em = Emitter(sqlite3.connect(f"file:{root / args.db}?mode=ro", uri=True), quiet)

    # reads/writes per field, which is the "how often is this touched" column
    touch: dict[int, tuple[int, int]] = {}
    for mid, w, n in con.execute(
            "SELECT member_id, is_write, COUNT(*) FROM field_access "
            "GROUP BY member_id, is_write"):
        r, wr = touch.get(mid, (0, 0))
        touch[mid] = (r + (n if not w else 0), wr + (n if w else 0))

    rows = con.execute("""
        SELECT mb.id, t.name, mb.name, mb.declared_type, mb.is_readonly
        FROM member mb JOIN type t ON t.id = mb.type_id
        WHERE mb.kind='field' AND mb.is_static=0
        ORDER BY t.name, mb.name""").fetchall()

    # Which types hold a field of which other type -- the object graph.
    edges: set[tuple[str, str]] = set()
    out: list[tuple[str, ...]] = []
    classes: collections.Counter = collections.Counter()

    for mid, owner, field, dt, readonly in rows:
        s = short(dt)
        reads, writes = touch.get(mid, (0, 0))
        if s in PRIMITIVES:
            cls, ev = "VALUE", "primitive"
        elif s in corpus_values:
            cls, ev = "VALUE", "enum or struct -- copied, not referenced"
        elif s in ("Action", "Func"):
            cls, ev = "CALLBACK", "delegate slot -- Option<Box<dyn FnMut>>"
        elif s in NOT_A_REFERENCE:
            cls, ev = "ARENA", NOT_A_REFERENCE[s]
        elif s in corpus_types:
            edges.add((owner, s))
            # A field never written after construction and pointing at another
            # corpus object is a back-reference in every case seen so far; one
            # that is written is shared mutable state.
            if writes == 0:
                cls, ev = "BACKREF", f"static: never written, {reads} reads"
            else:
                cls, ev = "SHARED", f"static: {writes} writes, {reads} reads"
        elif s.startswith("I") and len(s) > 1 and s[1].isupper():
            cls, ev = "BACKREF", "static: interface-typed, implementation outside cut"
        elif em.rust_type(dt or ""):
            cls, ev = "VALUE", f"static: maps to {em.rust_type(dt or '')}"
        else:
            cls, ev = "UNKNOWN", f"static: `{s}` not classified"
        classes[cls] += 1
        out.append((owner, field, s, cls, str(reads), str(writes), ev))

    # cycles: A -> B and B -> A, or longer. Only 2-cycles are reported; the
    # graph is small enough that longer ones are visible in the diagram.
    cycles = sorted({tuple(sorted((a, b))) for a, b in edges if (b, a) in edges})

    # Name outputs by the RUN, not by scope: since the corpus cut was removed
    # both runs read the same files, so the only distinction left is canonical
    # corpus vs scratch health check. Kept separate because a health-check
    # database can be half-written, and clobbering the canonical graph with one
    # is how a readable 52-edge diagram became an unreadable 1,278-edge one.
    scope = "breadth" if breadth else "tree"
    status = root / "docs" / "status"
    status.mkdir(parents=True, exist_ok=True)
    tsv = status / f"ownership-{scope}.tsv"
    tsv.write_text(
        "owner\tfield\ttype\tclass\treads\twrites\tevidence\n"
        + "\n".join("\t".join(r) for r in out) + "\n")

    # Mermaid: the object graph only -- values and arena handles are noise here.
    lines = ["graph LR"]
    for a, b in sorted(edges):
        lines.append(f"    {a.replace('.', '_')} --> {b.replace('.', '_')}")
    for a, b in cycles:
        lines.append(f"    %% cycle: {a} <-> {b}")
    (status / f"ownership-{scope}.mmd").write_text("\n".join(lines) + "\n")

    log.info("%d instance field(s) classified", len(out))
    log.info("")
    for cls, n in classes.most_common():
        log.info("  %-9s %4d", cls, n)
    log.info("")
    log.info("object-reference edges: %d", len(edges))
    log.info("2-cycles found: %d", len(cycles))
    for a, b in cycles:
        log.info("    %s <-> %s", a, b)
    log.info("")
    log.info("wrote docs/status/ownership-%s.tsv and ownership-%s.mmd", scope, scope)
    log.info("")
    log.info("EVERY ROW SAYS `static`. It sees declared types and access counts,")
    log.info("never what happens at run time. The dynamic half -- instrument C#")
    log.info("Renode, record what is genuinely shared and cyclic -- is the more")
    log.info("valuable one and is not built. Treat these as starting points.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
