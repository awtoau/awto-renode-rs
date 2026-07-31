#!/usr/bin/env python3
"""Reproduce and archive the C# Renode baseline boot. Issue #2.

This is the reference the whole project diffs against, so it must be a pinned
artifact rather than "whatever it did today": every run records the Renode
commit, the firmware ELF hash, the ordered boot markers observed, and the
wall-clock/simulated-time ratio.

Paths come from .env (see .env.example); nothing here contains an absolute path.

Run:  python3 scripts/baseline_boot.py [--run-for SECONDS] [--label NAME]
Log:  ./tmp/logs/baseline_boot.log
Out:  ./tmp/baseline/<YYYYMMDD-HHMMSS>/  (boot.log, manifest.json)
Exit: 0 if every required marker was seen in order, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ordered boot markers, taken from an observed reference boot rather than from
# prose. The boot is only a valid reference if all appear IN THIS ORDER --
# ordering is a property the Rust port must reproduce, not just presence.
MARKERS = [
    ("shell_uart",   r"\[BOOT\] Shell UART initialized"),
    ("logger_init",  r"\[BOOT\] logger_init OK"),
    ("otp",          r"OTP:\s*block\s*0\s*active\s+product=PDM"),
    ("freertos",     r"\[BOOT\] FreeRTOS started OK"),
    ("banner",       r"awto-pdm"),
    ("shell_ready",  r"\[BOOT\] Shell commands ready"),
    ("boot_ok",      r"\[BOOT\] system_boot OK \+\d+ ms @ (\d+) ms"),
    ("boot_context", r"\[BOOT\] system_boot context build=PDM wire=htc"),
]

# Init steps that FAIL in the reference boot. These are part of the reference:
# the Rust port must reproduce them, and a port that "fixes" one has diverged
# and must record it as a declared deviation rather than quietly passing.
#
#   flash_init      -- NOT a defect. gen_images.py blanks flash to 0xFF every
#                      run, so the emulated EEPROM correctly reports "flash is
#                      corrupt or is new - applying factory defaults" and the
#                      step reports FAIL because no stored settings loaded.
#                      This is the right answer for a fresh device, and starting
#                      from a known-blank device every run is deliberate.
#   ism330dhcx_init -- no IMU model exists. IMU data quality is bench territory;
#                      only identity/config registers were ever worth stubbing.
EXPECTED_FAILURES = {"flash_init", "ism330dhcx_init"}

BOOT_STEP_RE = re.compile(r"\[BOOT\] (\w+) (OK|FAIL) \+(\d+) ms @ (\d+) ms")

# usart1 lines carry both host and virtual timestamps, which is where the
# real-time ratio and the LSI cost come from.
USART_TS_RE = re.compile(r"host:\s*([\d.]+)s[^|]*\|virt:\s*([\d.]+)s")


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def load_env(root: Path) -> dict[str, str]:
    env_file = root / ".env"
    if not env_file.exists():
        raise SystemExit("no .env -- copy .env.example and set it for this machine")
    env = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    for required in ("RENODE_SRC", "FIRMWARE_SRC"):
        if required not in env:
            raise SystemExit(f"{required} not set in .env")
    return env


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_describe(path: Path) -> str:
    out = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-for", type=float, default=12.0,
                    help="simulated seconds to run (default 12)")
    ap.add_argument("--label", default="", help="label for the archive directory")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger("baseline_boot")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "baseline_boot.log"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    env = load_env(root)
    renode_src = Path(env["RENODE_SRC"])
    fw_src = Path(env["FIRMWARE_SRC"])
    elf = Path(env.get("FIRMWARE_ELF") or fw_src / "build/Debug/awto-htc.elf")

    if not elf.exists():
        log.error("firmware ELF not found: set FIRMWARE_ELF in .env")
        return 1

    # Backing images: MappedMemory is zero-filled but erased flash reads 0xFF,
    # and the emulated EEPROM declares corruption on zeros. Regenerate every run
    # so the reference always starts from a known-blank device.
    log.info("generating backing images")
    subprocess.run([sys.executable, "scripts/renode/gen_images.py"],
                   cwd=fw_src, check=True, capture_output=True)

    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    outdir = root / "tmp" / "baseline" / (f"{stamp}-{args.label}" if args.label else stamp)
    outdir.mkdir(parents=True, exist_ok=True)
    boot_log = outdir / "boot.log"

    # -P -1 (no GUI, no monitor port) is required for scripted runs. Never
    # combine --console with redirected stdio: ConsoleIOSource spins on EOF
    # pushing -1 into a BlockingCollection until the semaphore overflows.
    cmd = [
        str(renode_src / "renode"), "-P", "-1", "--disable-xwt", "--plain",
        "-e", f'include @renode/scripts/pdm_boot.resc; emulation RunFor "{args.run_for}"; quit',
    ]
    log.info("booting: RunFor %.1fs simulated", args.run_for)
    started = time.monotonic()
    with boot_log.open("wb") as out:
        proc = subprocess.run(cmd, cwd=fw_src, stdout=out, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL)
    wall = time.monotonic() - started

    text = boot_log.read_text(errors="ignore")

    # Markers must appear in order, so scan forward rather than searching each
    # independently -- out-of-order boot is a failure the port must not hide.
    seen, pos, missing = {}, 0, []
    for name, pattern in MARKERS:
        m = re.compile(pattern, re.I).search(text, pos)
        if m:
            seen[name] = m.group(0).strip()
            pos = m.end()
        else:
            missing.append(name)

    boot_ms = None
    if "boot_ok" in seen:
        m = re.search(r"@ (\d+) ms", seen["boot_ok"])
        if m:
            boot_ms = int(m.group(1))

    # Every [BOOT] step with its verdict and timing. This is the per-step
    # reference the port is diffed against, not just the final marker.
    steps = [
        {"step": m.group(1), "verdict": m.group(2),
         "took_ms": int(m.group(3)), "at_ms": int(m.group(4))}
        for m in BOOT_STEP_RE.finditer(text)
    ]
    failed = {s["step"] for s in steps if s["verdict"] == "FAIL"}
    unexpected_failures = sorted(failed - EXPECTED_FAILURES)
    unexpected_passes = sorted(EXPECTED_FAILURES - failed)

    # The first firmware output arrives only after awto_rtc_measure_lsi()
    # finishes. Its host/virt timestamps quantify the documented LSI cost, and
    # are the single most useful number in this baseline for issue #3 (P1).
    lsi = None
    first = re.search(r"\[BOOT\] Shell UART initialized", text)
    if first:
        ts = USART_TS_RE.search(text, max(0, first.start() - 400), first.start() + 200)
        if ts:
            lsi = {"host_s": float(ts.group(1)), "virt_s": float(ts.group(2))}

    manifest = {
        "taken_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "renode_commit": git_describe(renode_src),
        "firmware_commit": git_describe(fw_src),
        "firmware_elf": elf.name,
        "firmware_elf_sha256": sha256(elf),
        "run_for_simulated_s": args.run_for,
        "wall_clock_s": round(wall, 2),
        "realtime_ratio": round(args.run_for / wall, 4) if wall else None,
        "boot_ms_simulated": boot_ms,
        "renode_exit": proc.returncode,
        "log_lines": text.count("\n"),
        "warning_lines": text.count("[WARNING]"),
        "markers_seen": seen,
        "markers_missing": missing,
        "boot_steps": steps,
        "expected_failures": sorted(EXPECTED_FAILURES),
        "unexpected_failures": unexpected_failures,
        "unexpected_passes": unexpected_passes,
        "first_output_at": lsi,
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # Also write a committed summary. tmp/baseline/ is gitignored (large logs),
    # but the scorecard and CI need these numbers without the logs, and tracking
    # them makes reference drift visible in the diff.
    status_dir = root / "docs" / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    (status_dir / "baseline.json").write_text(json.dumps(manifest, indent=2) + "\n")

    log.info("wall %.1fs for %.1fs simulated -> %.2fx real time",
             wall, args.run_for, manifest["realtime_ratio"] or 0)
    for name, _ in MARKERS:
        log.info("  %-13s %s", name, seen.get(name, "*** MISSING ***"))
    if lsi:
        log.info("first firmware output at host %.2fs / virt %.2fs "
                 "(this is the LSI-measurement cost)", lsi["host_s"], lsi["virt_s"])
    if boot_ms:
        log.info("system_boot OK at %d ms simulated, over %d init steps",
                 boot_ms, len(steps))
    for s in steps:
        if s["verdict"] == "FAIL":
            log.info("  FAIL %-22s +%d ms @ %d ms%s", s["step"], s["took_ms"],
                     s["at_ms"], "" if s["step"] in EXPECTED_FAILURES else "  <-- UNEXPECTED")
    log.info("archived to %s", outdir.relative_to(root))

    ok = True
    if missing:
        log.error("FAIL: %d marker(s) missing or out of order: %s",
                  len(missing), ", ".join(missing))
        ok = False
    if unexpected_failures:
        log.error("FAIL: init step(s) failed that the reference does not: %s",
                  ", ".join(unexpected_failures))
        ok = False
    if unexpected_passes:
        log.error("FAIL: init step(s) passed that the reference fails: %s "
                  "-- the reference has changed, re-baseline deliberately",
                  ", ".join(unexpected_passes))
        ok = False
    if not ok:
        return 1
    log.info("OK: %d markers in order, %d init steps, failures match reference",
             len(MARKERS), len(steps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
