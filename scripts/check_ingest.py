#!/usr/bin/env python3
"""Report what the ingest is NOT extracting, before something needs it.

Raised in review: the converter kept being "patched" to record one more fact.
Four times so far — `HasBody` (partial methods), generic call targets,
argument-to-parameter bindings, binary operator kinds. Each was invisible until
a downstream consumer needed it, and each looked like a converter change when it
was really an incomplete corpus.

The problem is not any individual fix. It is that the corpus was shaped by what
happened to be needed next, so a gap could only be found by tripping over it.
This makes the gaps enumerable instead.

For every `IOperation` kind present, it reports how much detail was extracted.
A kind where nothing is extracted is either genuinely structural (a `Block` has
no symbol) or a gap — and the difference is declared here rather than assumed.

Run:  python3 scripts/check_ingest.py
Log:  ./tmp/logs/check_ingest.log
Exit: 0 if every kind is either covered or declared structural, 1 otherwise.
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

# Kinds that legitimately carry no symbol, constant or type. Roslyn defines no
# such property for them; their meaning is entirely their position in the tree.
STRUCTURAL = {
    "Block", "ExpressionStatement", "MethodBodyOperation", "Return",
    "Conditional", "VariableDeclarationGroup", "VariableDeclaration",
    "Empty", "Branch", "Labeled", "Try", "Using", "Lock", "Throw",
    "AnonymousFunction", "DelegateCreation", "ObjectOrCollectionInitializer",
    "Argument", "InstanceReference", "DefaultValue", "Discard",
    "ExpressionBody", "Switch", "SwitchCase", "SingleValueCaseClause",
    "DefaultCaseClause", "CaseClause", "CatchClause", "Finally", "While",
    "ForLoop", "ForEachLoop", "ForToLoop", "Tuple", "Parenthesized",
    "ArrayInitializer", "IsPattern", "DeclarationPattern", "ConstantPattern",
    "VariableInitializer", "Loop", "ConstructorBodyOperation",
    "YieldReturn", "YieldBreak", "InterpolatedStringAppendLiteral",
    "InterpolatedStringAppendFormatted",
    "InterpolatedStringHandlerArgumentPlaceholder",
    # An initialiser node carries nothing itself; its single child is the
    # value, and the member it belongs to is `operation.method_id`. Present
    # only since field and property initialisers began to be walked -- they
    # were absent from the corpus entirely, which is how a C# array's DECLARED
    # length was unavailable and handle arrays were sized from usage instead.
    "FieldInitializer", "PropertyInitializer",
    "CoalesceAssignment", "Coalesce", "ConditionalAccess",
    "ConditionalAccessInstance", "InterpolatedString", "InterpolatedStringText",
    "Interpolation", "NameOf", "TypeOf", "SizeOf", "Await", "AnonymousObjectCreation",
}

# Kinds we know are gaps, with what is missing. Listed so they are tracked
# rather than rediscovered.
KNOWN_GAPS = {
    "AnonymousFunction": "lambdas all display as 'lambda expression', so the "
                         "extracted symbol does not distinguish them; needs the "
                         "containing member plus source span to be useful",
}


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def main() -> int:
    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("check_ingest")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "check_ingest.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus database -- run the ingest first")
        return 1

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("""
        SELECT kind,
               COUNT(*),
               SUM(CASE WHEN symbol IS NOT NULL OR const_value IS NOT NULL
                          OR type IS NOT NULL OR detail IS NOT NULL
                        THEN 1 ELSE 0 END)
        FROM operation GROUP BY kind ORDER BY COUNT(*) DESC""").fetchall()
    con.close()

    undeclared: list[tuple[str, int]] = []
    tracked = 0
    log.info("%-30s %8s %8s  %s", "operation kind", "nodes", "detailed", "status")
    log.info("%s", "-" * 68)
    for kind, total, detailed in rows:
        detailed = detailed or 0
        pct = 100 * detailed // total if total else 0
        if detailed:
            status = "ok"
        elif kind in KNOWN_GAPS:
            status = f"GAP: {KNOWN_GAPS[kind]}"
            tracked += 1
        elif kind in STRUCTURAL:
            status = "structural"
        else:
            status = "UNDECLARED -- gap or structural?"
            undeclared.append((kind, total))
        if detailed == 0 or pct < 100:
            log.info("%-30s %8d %7d%%  %s", kind, total, pct, status)

    log.info("")
    log.info("%d kind(s) with a tracked gap, %d undeclared", tracked, len(undeclared))
    if undeclared:
        log.error("")
        log.error("UNDECLARED kinds extract nothing and are not marked structural.")
        log.error("Each is either a missing fact or a kind that genuinely has none;")
        log.error("decide which and record it, rather than waiting to trip over it:")
        for kind, n in undeclared:
            log.error("    %-28s %d nodes", kind, n)
        return 1
    log.info("every kind is either covered or declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
