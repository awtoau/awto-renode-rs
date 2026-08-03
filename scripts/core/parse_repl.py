#!/usr/bin/env python3
"""Derive platform configuration from the .repl files. Issue #14 follow-up.

The `.repl` is the source of truth for what peripherals exist, where they are
mapped, and what constructor parameters they take. Retyping any of that into a
test or a capture script creates a second source of truth that drifts silently:
change `modeResetValue` in the platform and the Rust tests keep asserting the
old value, passing while testing the wrong thing.

So nothing downstream hardcodes platform data. This parses the `.repl` chain
(following `using` for inheritance, child overriding parent) and emits
`docs/status/platform.json`, which the capture script and the generated Rust
platform module both consume.

Run:  python3 scripts/parse_repl.py
Log:  ./tmp/logs/parse_repl.log
Out:  docs/status/platform.json
      src/renode-stm32/src/platform.rs  (generated, do not edit)
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

# `name: Namespace.Type @ sysbus 0xADDR` / `@ sysbus <0xA, +0xB>` / `@ none`
ENTRY = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*"
    r"(?P<type>[A-Za-z_][A-Za-z0-9_.]*)?\s*"
    r"(?:@\s*(?P<where>.+))?$")
INDENTED = re.compile(r"^\s+(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.+?)\s*$")
USING = re.compile(r'^using\s+"(?P<path>[^"]+)"')
NUMBER = re.compile(r"^(0x[0-9A-Fa-f]+|\d+)$")


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True, check=True).stdout.strip())


def load_env(root: Path) -> dict[str, str]:
    env = {}
    for line in (root / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def parse(path: Path, renode_src: Path, seen: set[Path], log) -> dict[str, dict]:
    """Parse one .repl, following `using` first so children override parents."""
    if path in seen:
        return {}
    seen.add(path)
    out: dict[str, dict] = {}
    current: str | None = None

    for raw in path.read_text().splitlines():
        line = raw.split("//")[0].rstrip()
        if not line.strip():
            continue

        u = USING.match(line.strip())
        if u:
            parent = renode_src / u.group("path")
            if parent.exists():
                # Parent first: later entries here override what it defined.
                for k, v in parse(parent, renode_src, seen, log).items():
                    out[k] = v
            else:
                log.warning("using target not found: %s", u.group("path"))
            continue

        ind = INDENTED.match(raw)
        if ind and current:
            key, value = ind.group("key"), ind.group("value")
            # Skip IRQ wiring and init blocks; only constructor params matter.
            if key not in ("init", "IRQ") and "->" not in value:
                out[current]["params"][key] = value
            continue

        m = ENTRY.match(line.strip())
        if m and m.group("name"):
            name = m.group("name")
            entry = out.setdefault(name, {"type": None, "address": None, "params": {}})
            if m.group("type"):
                entry["type"] = m.group("type")
            where = (m.group("where") or "").strip()
            if where == "none":
                # `crc: @ none` detaches an inherited peripheral.
                entry["detached"] = True
            elif where:
                entry["detached"] = False
                addr = re.search(r"0x[0-9A-Fa-f]+", where)
                if addr:
                    entry["address"] = int(addr.group(0), 16)
            current = name
        else:
            current = None
    return out


def main() -> int:
    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("parse_repl")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "parse_repl.log"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    env = load_env(root)
    renode_src = Path(env["RENODE_SRC"])
    repl = Path(env["FIRMWARE_SRC"]) / "renode" / "platforms" / "awto_pdm.repl"
    if not repl.exists():
        log.error("platform description not found (FIRMWARE_SRC/renode/platforms)")
        return 1

    entries = parse(repl, renode_src, set(), log)
    live = {k: v for k, v in entries.items()
            if not v.get("detached") and v.get("type")}
    log.info("parsed %d peripherals (%d detached) from the .repl chain",
             len(live), sum(1 for v in entries.values() if v.get("detached")))

    out = {
        "source": "awto_pdm.repl + inherited stm32f4.repl",
        "peripherals": {k: live[k] for k in sorted(live)},
    }
    (root / "docs" / "status").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "status" / "platform.json").write_text(json.dumps(out, indent=2) + "\n")

    # Generated Rust: reset values and frequencies, so no test retypes them.
    def const(name: str, key: str, default: str = "0") -> str:
        v = live.get(name, {}).get("params", {}).get(key)
        if v is None:
            return default
        v = v.strip()
        return v if NUMBER.match(v) else default

    ports = [k for k in sorted(live) if k.startswith("gpioPort")]
    lines = [
        "//! GENERATED by scripts/parse_repl.py from the platform description.",
        "//! Do not edit: the .repl is the source of truth, and retyping any of",
        "//! this creates a second one that drifts silently.",
        "",
        "/// Constructor parameters for one GPIO port, as the .repl supplies them.",
        "pub struct GpioPortConfig {",
        "    pub mode_reset: u32,",
        "    pub output_speed_reset: u32,",
        "    pub pull_up_pull_down_reset: u32,",
        "}",
        "",
        "/// Look up a GPIO port's reset values by the name the .repl gives it.",
        "pub fn gpio_port(name: &str) -> Option<GpioPortConfig> {",
        "    let (m, o, p) = match name {",
    ]
    for portname in ports:
        lines.append(
            f'        "{portname}" => ({const(portname, "modeResetValue")}, '
            f'{const(portname, "outputSpeedResetValue")}, '
            f'{const(portname, "pullUpPullDownResetValue")}),')
    lines += [
        "        _ => return None,",
        "    };",
        "    Some(GpioPortConfig { mode_reset: m, output_speed_reset: o,",
        "                          pull_up_pull_down_reset: p })",
        "}",
        "",
        "/// Every peripheral the platform instantiates, in .repl order.",
        "pub const PERIPHERALS: &[&str] = &[",
    ]
    for k in sorted(live):
        lines.append(f'    "{k}",')
    lines.append("];")
    (root / "src" / "renode-stm32" / "src" / "platform.rs").write_text("\n".join(lines) + "\n")

    log.info("gpio ports found: %s", ", ".join(ports))
    for portname in ports:
        log.info("  %-12s mode=%s speed=%s pupd=%s", portname,
                 const(portname, "modeResetValue"),
                 const(portname, "outputSpeedResetValue"),
                 const(portname, "pullUpPullDownResetValue"))
    log.info("wrote docs/status/platform.json and src/renode-stm32/src/platform.rs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
