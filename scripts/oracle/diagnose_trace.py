#!/usr/bin/env python3
"""Break a recorded trace down by offset, so a divergence count becomes a diagnosis.

A row on the generated-trace scoreboard ("can1 228 accesses, 99 divergences")
says how much is wrong and nothing about WHY. The three causes look identical
from the count:

  * wrong-method selection -- no register map emitted at all, so every read
    returns 0 and every non-zero expected read diverges;
  * layout defect -- the register exists but the field is the wrong width,
    mode or position, so SOME reads diverge and the pattern is bit-shaped;
  * behaviour gap -- the map is right and nothing computes a value, so the
    diverging reads are exactly the ones no trace write can set.

Those are told apart by looking at WHICH offsets diverge and whether the trace
ever writes them. This prints that, per offset:

    offset  reg          reads  writes  non-zero reads  read-after-write?

Run:  python3 scripts/diagnose_trace.py <trace-name> [...]
Log:  ./tmp/logs/diagnose_trace.log
"""

from __future__ import annotations

import collections
import gzip
import json
import logging
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def load(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def report(log: logging.Logger, name: str, recs: list[dict]) -> None:
    reads = [r for r in recs if r["dir"] == "read"]
    writes = [r for r in recs if r["dir"] == "write"]
    nonzero = [r for r in reads if r["value"] != 0]

    log.info("=== %s ===", name)
    log.info("total %d, reads %d, writes %d, non-zero reads %d",
             len(recs), len(reads), len(writes), len(nonzero))
    log.info("An EMPTY register map returns 0 for every read, so it would score")
    log.info("exactly %d divergences here.", len(nonzero))
    log.info("")

    # Was this offset ever written before the diverging read? A read whose
    # expected value the trace itself supplied is reproducible by layout alone;
    # one whose value the trace never wrote needs the peripheral to compute it.
    written_before: dict[int, int] = {}
    seen_write: set[int] = set()
    for r in recs:
        if r["dir"] == "write":
            seen_write.add(r["offset"])
        elif r["value"] != 0 and r["offset"] in seen_write:
            written_before[r["offset"]] = written_before.get(r["offset"], 0) + 1

    offsets = sorted({r["offset"] for r in recs})
    log.info("%-7s %-12s %5s %6s %8s %9s  %s",
             "offset", "reg", "reads", "writes", "nonzero", "afterwr", "read values")
    for off in offsets:
        rs = [r for r in reads if r["offset"] == off]
        ws = [r for r in writes if r["offset"] == off]
        reg = next((r.get("reg") for r in recs
                    if r["offset"] == off and r.get("reg")), None)
        nz = sum(1 for r in rs if r["value"] != 0)
        vals = collections.Counter(r["value"] for r in rs)
        shown = ", ".join(f"0x{v:X}x{n}" for v, n in vals.most_common(6))
        log.info("0x%04X  %-12s %5d %6d %8d %9d  %s",
                 off, reg or "?", len(rs), len(ws), nz,
                 written_before.get(off, 0), shown)
    log.info("")

    # The classification that tells the three causes apart. A read whose value
    # the trace itself last wrote is reproducible by STORAGE alone; one the
    # trace never wrote needs the peripheral to COMPUTE it; one that differs
    # from the last write is the only shape a partial layout defect can take
    # (wrong width, wrong mode, wrong bit position).
    last: dict[int, int] = {}
    buckets: dict[str, collections.Counter] = {
        "exact echo of last write": collections.Counter(),
        "never written -- reset value or computed": collections.Counter(),
        "differs from last write -- LAYOUT DEFECT": collections.Counter(),
    }
    for r in recs:
        if r["dir"] == "write":
            last[r["offset"]] = r["value"]
            continue
        if r["value"] == 0:
            continue                     # an empty map returns 0, so this agrees
        off = r["offset"]
        if off not in last:
            key = "never written -- reset value or computed"
        elif last[off] == r["value"]:
            key = "exact echo of last write"
        else:
            key = "differs from last write -- LAYOUT DEFECT"
        buckets[key][r.get("reg") or f"0x{off:X}"] += 1

    log.info("The %d non-zero reads, classified:", len(nonzero))
    for key, counter in buckets.items():
        log.info("  %3d  %s", sum(counter.values()), key)
        for reg, n in counter.most_common():
            log.info("       %3d %s", n, reg)
    log.info("")
    if not buckets["differs from last write -- LAYOUT DEFECT"]:
        log.info("No read differs from the last write to its offset, so nothing")
        log.info("is present-but-wrong: this is not a layout defect.")
        log.info("")

    log.info("WRITE VALUES, per offset -- what a layout-only module could echo:")
    for off in sorted({r["offset"] for r in writes}):
        ws = [r for r in writes if r["offset"] == off]
        vals = collections.Counter(r["value"] for r in ws)
        reg = next((r.get("reg") for r in ws if r.get("reg")), None)
        log.info("  0x%04X  %-12s %s", off, reg or "?",
                 ", ".join(f"0x{v:X}x{n}" for v, n in vals.most_common(8)))
    log.info("")


def main(argv: list[str]) -> int:
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("diagnose_trace")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" / "diagnose_trace.log",
                                  mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    names = argv[1:] or ["can1"]
    for name in names:
        path = root / "oracle" / "traces" / f"{name}.jsonl.gz"
        if not path.exists():
            log.error("no trace named %s", name)
            return 1
        report(log, name, load(path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
