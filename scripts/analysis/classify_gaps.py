#!/usr/bin/env python3
"""Split the gap census into "this is plain C#" and "this is Renode".

The question this answers: when the converter cannot emit something, is it
stuck on the C# language, or on Renode's own types?

It matters because the two have different fixes and different feedback loops.
A C# gap is fixed once in the language layer and every corpus benefits; it can
in principle be reproduced by a five-line program. A Renode gap needs Renode
knowledge and can only be checked by running a peripheral. Today both are
found the same way -- by a peripheral failing to emit -- so the cheap class is
being debugged through the expensive loop.

Reads `docs/status/gap_census.json` (written by gap_census.py), writes
`docs/status/gap_split.json`, logs to `tmp/logs/classify_gaps.log`.

The classification table below is the whole judgement in this script. It is
deliberately a literal table rather than a heuristic: every root cause is
named, so a wrong call is visible in review rather than buried in a regex.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

# Root causes that are the C# language itself, or the .NET base class library.
# Nothing here mentions Renode; each could be reproduced in a standalone
# program that does not reference the Renode tree at all.
CSHARP = {
    "construct  StaticInvocation",
    "construct  Throw",
    "construct  DefaultValue",
    "construct  DeclarationExpression",
    "construct  ArrayCreation",
    "construct  Using",
    "construct  DelegateCreation",
    "construct  DelegateInvokeInExpression",
    "construct  Coalesce",
    "construct  Block",
    "construct  Try",
    "construct  EventReference",
    "type  decimal",
    "type  object",
}

# Root causes that are Renode's own types and base classes. Fixing one needs
# to know what Renode means by it, and checking the fix needs a peripheral.
RENODE = {
    "type  DoubleWordRegister",
    "type  Response",
    "base class  BaseCPU",
    "base class  UARTBase",
    "type  IUART",
    "type  UARTFrame",
    "type  IPeripheral",
    "type  IGPIOSender",
    "type  Parity",
    "type  Bits",
    # Antmicro.Renode.Core.Range, not System.Range. If that ever changes this
    # moves to CSHARP and the split shifts by about one point.
    "type  Range",
}


def classify(cause: str) -> str:
    if cause in CSHARP:
        return "csharp"
    if cause in RENODE:
        return "renode"
    return "unclassified"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--census",
        default="docs/status/gap_census.json",
        help="gap census to read (repo-relative)",
    )
    args = ap.parse_args()

    log_path = ROOT / "tmp" / "logs" / "classify_gaps.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []

    def emit(line: str = "") -> None:
        print(line)
        log_lines.append(line)

    census_path = ROOT / args.census
    if not census_path.exists():
        emit(f"no census at {args.census} -- run scripts/analysis/gap_census.py first")
        log_path.write_text("\n".join(log_lines) + "\n")
        return 1

    census = json.loads(census_path.read_text())
    root_causes: dict[str, int] = census["root_causes"]

    buckets: dict[str, dict[str, int]] = {"csharp": {}, "renode": {}, "unclassified": {}}
    for cause, count in root_causes.items():
        buckets[classify(cause)][cause] = count

    totals = {k: sum(v.values()) for k, v in buckets.items()}
    named = totals["csharp"] + totals["renode"]

    emit("Gap root causes, split by what is actually blocking the converter")
    emit("=" * 66)
    emit()
    for bucket in ("csharp", "renode", "unclassified"):
        if not buckets[bucket]:
            continue
        emit(f"{bucket.upper()}  ({totals[bucket]} gaps over {len(buckets[bucket])} causes)")
        for cause, count in sorted(buckets[bucket].items(), key=lambda kv: -kv[1]):
            emit(f"  {count:6d}  {cause}")
        emit()

    if named:
        share = 100.0 * totals["csharp"] / named
        emit(f"Of the {named} gaps with a named root cause:")
        emit(f"  plain C#          {totals['csharp']:6d}   {share:.1f}%")
        emit(f"  Renode-specific   {totals['renode']:6d}   {100.0 - share:.1f}%")
        emit()
        emit(
            "The converter is mostly stuck on C#, but every one of these was\n"
            "found by a Renode peripheral failing to emit, and can only be\n"
            "confirmed fixed by that peripheral emitting again."
        )
    else:
        share = 0.0
        emit("no named root causes to split")

    emit()
    emit(
        f"total gaps in census: {census['total_gaps']} "
        f"(root causes account for {named}; the rest are cascades and "
        f"unattributed)"
    )

    out = {
        "note": (
            "Gap root causes split into plain-C# and Renode-specific. "
            "Generated by scripts/analysis/classify_gaps.py -- do not edit."
        ),
        "source_census": args.census,
        "total_gaps": census["total_gaps"],
        "named_root_cause_gaps": named,
        "csharp_gaps": totals["csharp"],
        "renode_gaps": totals["renode"],
        "unclassified_gaps": totals["unclassified"],
        "csharp_share_of_named": round(share, 1),
        "buckets": buckets,
    }
    out_path = ROOT / "docs" / "status" / "gap_split.json"
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    emit(f"wrote {out_path.relative_to(ROOT)}")

    log_path.write_text("\n".join(log_lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
