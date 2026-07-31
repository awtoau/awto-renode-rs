#!/usr/bin/env python3
"""Capture per-peripheral register access traces from C# Renode. Issue #6.

These traces are the tier-2 oracle: replay the same (offset, value, width)
sequence against a Rust peripheral in isolation and assert identical read
results. That converts "port a peripheral" from a research task into a
test-driven one with an exact pass/fail, and it is the cheapest tier that says
anything real.

NO RENODE MODIFICATION IS NEEDED. `sysbus LogPeripheralAccess <p>` wraps a
peripheral's access methods and logs every read and write at Info level:

    ReadDoubleWord from 0x18 (Status), returned 0xC0
    WriteDoubleWord to 0xC (Control1), value 0x200C

so the trace is captured by enabling that and parsing the boot log. Wrapping
every access is slow -- this is a one-off capture, not something to run in a
loop.

Run:  python3 scripts/capture_traces.py [--run-for 12.0]
Log:  ./tmp/logs/capture_traces.log
Out:  oracle/traces/<peripheral>.jsonl  (committed: these are the reference)
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Peripherals to trace. Only those the Rust port will implement -- tracing
# everything would bloat the capture and slow the boot for no benefit.
PERIPHERALS = [
    "usart1", "uart8", "can1", "timer2", "timer5", "timer7",
    "rcc", "pwr", "crc_f4", "exti", "syscfg", "rtc", "iwdg", "rng",
    "dma1", "dma2", "spi2", "spi3", "adc1", "flash_ctrl",
    "gpioPortA", "gpioPortB", "gpioPortC", "gpioPortE", "nvic",
]

# Emitted by Read/WriteLoggingWrapper, after DecorateWithCPUNameAndPC:
#
#   [INFO] usart1: [cpu: 0x8017960] ReadUInt32 from 0xC (Control1), returned 0x0
#
# NOTE the width token is the .NET TYPE NAME -- the wrapper interpolates
# typeof(T).Name -- so it is UInt32, not DoubleWord. Guessing "DoubleWord"
# matched nothing, and for usart1 the pattern then accidentally matched UART
# character output, reporting 22,713 "accesses" across 1 offset. A trace parser
# that silently matches the wrong lines is worse than one that matches none.
ACCESS = re.compile(
    r"^(?P<ts>[\d:.]+)\s+\[INFO\]\s+(?P<periph>[A-Za-z0-9_]+):\s+"
    r"(?:\[(?P<ctx>[^\]]*)\]\s+)?"
    r"(?P<dir>Read|Write)(?P<width>Byte|UInt16|UInt32|UInt64)\s+"
    r"(?:from|to)\s+0x(?P<offset>[0-9A-Fa-f]+)"
    r"(?:\s+\((?P<reg>[^)]*)\))?,\s+"
    r"(?:returned|value)\s+0x(?P<value>[0-9A-Fa-f]+)")

WIDTH_BITS = {"Byte": 8, "UInt16": 16, "UInt32": 32, "UInt64": 64}


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def load_env(root: Path) -> dict[str, str]:
    env = {}
    f = root / ".env"
    if not f.exists():
        raise SystemExit("no .env -- copy .env.example")
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-for", type=float, default=12.0)
    ap.add_argument("--keep-log", action="store_true")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("capture_traces")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "capture_traces.log"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    env = load_env(root)
    renode = Path(env["RENODE_SRC"]) / "renode"
    fw = Path(env["FIRMWARE_SRC"])

    subprocess.run([sys.executable, "scripts/renode/gen_images.py"],
                   cwd=fw, check=True, capture_output=True)

    enable = "; ".join(f"sysbus LogPeripheralAccess {p}" for p in PERIPHERALS)
    script = (f'include @renode/scripts/pdm_boot.resc; {enable}; '
              f'emulation RunFor "{args.run_for}"; quit')

    raw = root / "tmp" / "trace_capture.log"
    log.info("booting with access logging on %d peripherals (this is slow)", len(PERIPHERALS))
    started = time.monotonic()
    with raw.open("wb") as out:
        subprocess.run([str(renode), "-P", "-1", "--disable-xwt", "--plain", "-e", script],
                       cwd=fw, stdout=out, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL)
    wall = time.monotonic() - started
    log.info("boot finished in %.0fs", wall)

    # --- parse ---------------------------------------------------------------
    traces: dict[str, list[dict]] = {p: [] for p in PERIPHERALS}
    seen_lines = matched = 0
    with raw.open(errors="ignore") as fh:
        for line in fh:
            seen_lines += 1
            m = ACCESS.match(line.strip())
            if not m:
                continue
            p = m.group("periph")
            if p not in traces:
                continue
            matched += 1
            traces[p].append({
                "seq": len(traces[p]),
                "dir": m.group("dir").lower(),
                "width": WIDTH_BITS[m.group("width")],
                "offset": int(m.group("offset"), 16),
                "value": int(m.group("value"), 16),
                "reg": (m.group("reg") or "").strip() or None,
            })

    log.info("parsed %d accesses from %d log lines", matched, seen_lines)
    if matched == 0:
        log.error("FAIL: no accesses parsed. Either LogPeripheralAccess did not "
                  "engage, or the log format has changed -- check tmp/trace_capture.log")
        return 1

    outdir = root / "oracle" / "traces"
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "captured_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "run_for_simulated_s": args.run_for,
        "wall_clock_s": round(wall, 1),
        "peripherals": {},
    }
    for p, rows in sorted(traces.items()):
        if not rows:
            continue
        # gzipped: these are committed as the tier-2 reference, and polling
        # traces are extremely repetitive (timer5 is 14,728 reads of one status
        # register), so they compress by ~95%.
        path = outdir / f"{p}.jsonl.gz"
        with gzip.open(path, "wt", compresslevel=9) as fh:
            for r in rows:
                fh.write(json.dumps(r, separators=(",", ":")) + "\n")
        offsets = len({r["offset"] for r in rows})
        if len(rows) > 100 and offsets <= 1:
            log.error("SUSPECT: %s has %d accesses across %d offset(s) -- almost "
                      "certainly a parse error, not a real trace", p, len(rows), offsets)
            return 1
        manifest["peripherals"][p] = {
            "accesses": len(rows),
            "distinct_offsets": offsets,
            "reads": sum(1 for r in rows if r["dir"] == "read"),
            "writes": sum(1 for r in rows if r["dir"] == "write"),
        }
        log.info("  %-12s %7d accesses, %3d distinct offsets", p, len(rows), offsets)

    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    empty = [p for p, r in traces.items() if not r]
    if empty:
        log.info("no accesses captured for: %s", ", ".join(sorted(empty)))
    if not args.keep_log:
        raw.unlink(missing_ok=True)
    log.info("wrote %d trace files to oracle/traces/", len(manifest["peripherals"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
