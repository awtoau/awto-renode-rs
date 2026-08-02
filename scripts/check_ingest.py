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

Two halves, because they answer different questions.

FACTS — one count per property the walker reads, each with a floor it must
hold. This is what catches a fact that STOPS arriving, which the kind table
cannot: a kind stays "covered" on its other facts while one of them silently
goes to zero. A field-initialiser fix was measured as producing zero rows and
reverted on that measurement; a count that must not reach zero is the cheapest
thing that would have shown which of the two was broken.

KINDS — for every `IOperation` kind present, how much detail was extracted. A
kind where nothing is extracted is either genuinely structural (a `Block` has
no symbol) or a gap — and the difference is declared here rather than assumed.

Run:  python3 scripts/check_ingest.py
Log:  ./tmp/logs/check_ingest.log
Exit: 0 if every fact still arrives and every kind is covered or declared.
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
    # Pattern-matching nodes whose whole meaning is their position. An arm is
    # (pattern, guard, value); `not p` is its child negated; `_` matches
    # anything and has nothing to say about itself. Their siblings
    # RelationalPattern and BinaryPattern are NOT here -- those carry an
    # OperatorKind, and the walker now reads it.
    "SwitchExpressionArm", "NegatedPattern", "DiscardPattern",
    # An initialiser node carries nothing itself: its single child is the value,
    # and the member it belongs to is `operation.method_id`. Present only since
    # field and property initialisers began to be walked -- before that they
    # were absent from the corpus entirely, so `private bool x = true;` and
    # `private bool x;` were the same rows.
    "FieldInitializer", "PropertyInitializer",
    "VariableInitializer", "Loop", "ConstructorBodyOperation",
    "YieldReturn", "YieldBreak", "InterpolatedStringAppendLiteral",
    "InterpolatedStringAppendFormatted",
    "InterpolatedStringHandlerArgumentPlaceholder",
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

# ---------------------------------------------------------------------------
# FACTS: one count per property the walker reads, with the floor it must hold.
#
# The kind table above answers "does this kind extract anything at all". It
# cannot answer "is the fact we added still being read", because a fact that
# stops arriving leaves the kind covered by its OTHER facts and the table stays
# green. Every ingest gap closed so far was invisible for exactly that reason,
# and one of them -- field initialisers -- was closed, measured as producing
# zero rows against a stale binary, and reverted. A number that must not fall
# to zero is the cheapest thing that would have caught it.
#
#   floor   the count must be >= this. 0 means "report it, do not require it":
#           used where the corpus legitimately may hold none.
#   exact   the count must equal the count of the second query. Used for facts
#           that are unconditional -- every Unary node HAS a checked-ness, so a
#           row without one is the walker not reading it, not the C# lacking it.
# ---------------------------------------------------------------------------
FACTS = [
    {
        "name": "field/property initialisers walked",
        "sql": "SELECT COUNT(*) FROM operation WHERE kind IN "
               "('FieldInitializer','PropertyInitializer')",
        "floor": 1,
        "why": "`private bool x = true;` is otherwise indistinguishable from "
               "`private bool x;`, and an array's DECLARED length exists "
               "nowhere else. Roslyn: GetOperation(EqualsValueClauseSyntax).",
    },
    {
        "name": "operations owned by a non-method member",
        "sql": "SELECT COUNT(*) FROM operation o JOIN member mb "
               "ON mb.id = o.method_id WHERE mb.kind NOT IN ('method','ctor')",
        "floor": 1,
        "why": "the initialiser bodies themselves. Zero here means the walk ran "
               "and the write discarded it -- the exact shape of the reverted "
               "attempt, which reported no error either.",
    },
    {
        "name": "parameter defaults with a value",
        "sql": "SELECT COUNT(*) FROM parameter "
               "WHERE has_default = 1 AND default_value IS NOT NULL",
        "floor": 1,
        "why": "`has_default` is a flag; an optional argument needs the VALUE. "
               "Roslyn: IParameterSymbol.ExplicitDefaultValue.",
    },
    {
        "name": "parameter defaults on a non-optional parameter",
        "sql": "SELECT COUNT(*) FROM parameter "
               "WHERE has_default = 0 AND default_value IS NOT NULL",
        "ceiling": 0,
        "why": "the encoding is (has_default = 1, default_value IS NULL) means "
               "the default IS null. A value without the flag breaks it.",
    },
    {
        "name": "Unary nodes carrying checked-ness",
        "sql": "SELECT COUNT(*) FROM operation "
               "WHERE kind = 'Unary' AND detail LIKE '%\"checked\"%'",
        "exact": "SELECT COUNT(*) FROM operation WHERE kind = 'Unary'",
        "why": "every Unary row's detail used to be empty where every Binary "
               "row carried one, so unary minus could not be routed to the "
               "runtime without assuming a context. Roslyn: "
               "IUnaryOperation.IsChecked.",
    },
    {
        "name": "CatchClause nodes carrying filter presence",
        "sql": "SELECT COUNT(*) FROM operation "
               "WHERE kind = 'CatchClause' AND detail LIKE '%\"filter\"%'",
        "exact": "SELECT COUNT(*) FROM operation WHERE kind = 'CatchClause'",
        "why": "`catch (E e) when (cond)` runs BEFORE unwinding and may "
               "decline, so it is not an `if` at the top of the handler. "
               "Roslyn: ICatchClauseOperation.Filter.",
    },
    {
        "name": "  of which have a filter",
        "sql": "SELECT COUNT(*) FROM operation "
               "WHERE kind = 'CatchClause' AND detail LIKE '%\"filter\":true%'",
        "floor": 0,
        "why": "reported, not required. The issue recorded this as 0 tree-wide; "
               "it is not, so a translation that drops the filter is a live "
               "wrong answer rather than a hypothetical one.",
    },
]


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

    failed_facts = 0
    log.info("%-46s %10s  %s", "fact", "count", "status")
    log.info("%s", "-" * 68)
    for fact in FACTS:
        n = con.execute(fact["sql"]).fetchone()[0]
        if "exact" in fact:
            want = con.execute(fact["exact"]).fetchone()[0]
            ok = n == want
            status = "ok" if ok else f"MISSING on {want - n} of {want} nodes"
        elif "ceiling" in fact:
            ok = n <= fact["ceiling"]
            status = "ok" if ok else f"MUST BE <= {fact['ceiling']}"
        else:
            ok = n >= fact["floor"]
            status = "ok" if ok else f"MUST BE >= {fact['floor']} -- fact not read"
        log.info("%-46s %10d  %s", fact["name"], n, status)
        if not ok:
            failed_facts += 1
            log.error("    %s", fact["why"])
    log.info("")

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
    if failed_facts:
        log.error("")
        log.error("%d recorded fact(s) are no longer arriving in the corpus.", failed_facts)
        log.error("Each was a property Roslyn exposes that the walker did not read;")
        log.error("a count back at its floor means the extraction was lost again.")
        return 1
    log.info("every kind is either covered or declared, and every fact still arrives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
