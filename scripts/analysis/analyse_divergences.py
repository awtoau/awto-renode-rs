#!/usr/bin/env python3
"""Group a full trace-divergence dump so a layout gap can be told from a
behaviour gap.

The trace harness prints five divergences. Five lines cannot distinguish
"this register is not in the map" from "this register is in the map and
nothing ever writes it" -- and that distinction has already been got wrong
once on DMA, where the accepted explanation was a missing layout and the
truth was a missing writer.

So this reads the whole dump (write it with `TRACE_DUMP_DIR=... cargo test
-p renode-stm32 --test generated_trace`) and reports, per offset:

  * how many divergences, and how many reads of that offset in total
  * the distinct (expected, got) pairs, most common first
  * the FIRST diverging access index, and whether reads of that offset ever
    matched before it -- a register absent from the map diverges from the
    first non-zero read, a register present but unwritten diverges only
    after the C# behaviour would have set it
  * which bits differ, ORed over every divergence at that offset

The bit mask is the load-bearing column. A layout gap shows the whole
register; a missing writer shows exactly the bits that writer sets.

Run:  python3 scripts/analyse_divergences.py adc1
Log:  ./tmp/logs/analyse_divergences.log
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

LINE = re.compile(
    r"access #(\d+) read(\d+) 0x([0-9A-Fa-f]+)(?: \(([^)]*)\))? -> "
    r"expected 0x([0-9A-Fa-f]+), got 0x([0-9A-Fa-f]+)"
)


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", help="trace name, e.g. adc1")
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("analyse_divergences")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    for h in (logging.FileHandler(root / "tmp" / "logs" /
                                  "analyse_divergences.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    dump = root / "tmp" / "logs" / f"{args.trace}-divergences.txt"
    if not dump.exists():
        log.error("no dump at %s -- run the harness with TRACE_DUMP_DIR set",
                  dump.relative_to(root))
        return 1

    div = []
    for line in dump.read_text().splitlines():
        m = LINE.match(line.strip())
        if not m:
            log.error("unparsed dump line: %s", line)
            return 1
        div.append({
            "seq": int(m.group(1)),
            "offset": int(m.group(3), 16),
            "reg": m.group(4) or "",
            "expected": int(m.group(5), 16),
            "got": int(m.group(6), 16),
        })

    trace_path = root / "oracle" / "traces" / f"{args.trace}.jsonl.gz"
    accesses = [json.loads(l) for l in gzip.open(trace_path, "rt")]
    by_seq = {a["seq"]: a for a in accesses}
    reads = collections.Counter(a["offset"] for a in accesses
                                if a["dir"] == "read")
    writes = collections.Counter(a["offset"] for a in accesses
                                 if a["dir"] == "write")

    log.info("%s: %d accesses, %d divergences", args.trace, len(accesses),
             len(div))
    log.info("")

    per = collections.defaultdict(list)
    for d in div:
        per[d["offset"]].append(d)

    log.info("%-8s %-22s %7s %7s %7s %9s %12s", "offset", "register",
             "reads", "writes", "diverge", "first_seq", "diff_bits")
    for off in sorted(per):
        ds = per[off]
        mask = 0
        for d in ds:
            mask |= d["expected"] ^ d["got"]
        log.info("%-8s %-22s %7d %7d %7d %9d %12s", hex(off), ds[0]["reg"],
                 reads[off], writes[off], len(ds), ds[0]["seq"],
                 f"0x{mask:X}")
    log.info("")

    for off in sorted(per):
        ds = per[off]
        log.info("--- 0x%X %s: %d divergences of %d reads", off, ds[0]["reg"],
                 len(ds), reads[off])
        pairs = collections.Counter((d["expected"], d["got"]) for d in ds)
        for (exp, got), n in pairs.most_common(12):
            log.info("    expected 0x%-10X got 0x%-10X  x%d  (diff 0x%X)",
                     exp, got, n, exp ^ got)
        if len(pairs) > 12:
            log.info("    ... %d further distinct pairs", len(pairs) - 12)

        # Did reads of this offset ever match before the first divergence?
        first = ds[0]["seq"]
        ok_before = sum(1 for a in accesses
                        if a["dir"] == "read" and a["offset"] == off
                        and a["seq"] < first)
        log.info("    first divergence at access #%d; %d earlier read(s) of "
                 "this offset matched", first, ok_before)

        # What happened immediately before the first divergence?
        prev = [by_seq[s] for s in range(max(0, first - 4), first)
                if s in by_seq]
        for p in prev:
            log.info("    prior #%d %-5s 0x%X = 0x%X", p["seq"], p["dir"],
                     p["offset"], p["value"])
        log.info("")

    return 0


if __name__ == "__main__":
    sys.exit(main())
