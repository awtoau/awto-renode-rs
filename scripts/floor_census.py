#!/usr/bin/env python3
"""What is the smallest set of translated types that could actually RUN?

`compile_check.py` answers "how much of what the converter emits is
well-formed". That is a necessary question and not a sufficient one: a module
that compiles is not a peripheral. A peripheral is something a bus can hand an
address to.

So this asks the next question down, and it is the one that decides whether
anything can be assembled and executed:

  1. **Does the module compile?**            -- reuses compile_check's crate
  2. **Is it DRIVABLE?**                     -- does it expose the
     `read_double_word` / `write_double_word` pair the system bus dispatches
     through, so a generic caller can reach it without knowing its type?
  3. **Is it ON THE PLATFORM?**              -- does `docs/status/platform.json`
     (derived from the `.repl` by `scripts/parse_repl.py`) place it at an
     address?

`--platform <name>` measures against a Renode-shipped `.repl` instead, reusing
`parse_repl.parse` rather than a second parser -- the acceptance criteria are
Renode's own Robot tests, and those load Renode's own platforms, so "the floor"
has to be answerable for a board this repo does not own.

The intersection of the three is the floor. Everything outside it is a module
that compiles and cannot be run, which is the state the whole 560 are in today.

Two negative results this reports deliberately, because they are the shape of
the remaining work rather than a defect in it:

  * a platform peripheral with NO emitted module at all -- the converter only
    emits types with a register-defining method, so memories, the CPU and the
    bus itself are structurally outside it;
  * a drivable module whose `reset` arrives under a different name, or not at
    all. A generic caller needs ONE name per contract; `docs/status/dispatch.json`
    already measured that `reset` arrives under two and is missing from some.

It also probes the INFRASTRUCTURE the floor needs and the converter is never
asked for -- the bus, the memories, the machine. `compile_check.py` emits only
types with a register-defining method, so those have never been put in front of
the emitter at all, and "the converter cannot do them" was an assumption. It is
now a measurement, and it re-runs: if the emitter later learns one, the number
moves on its own.

Nothing is written to the repo except `docs/status/floor.json`; the scratch
crate lives under `tmp/`.

Run:  python3 scripts/floor_census.py
      python3 scripts/floor_census.py --reuse   # keep an existing scratch crate
Log:  ./tmp/logs/floor_census.log
Out:  docs/status/floor.json
Exit: 0 always -- this is a measurement, not a gate.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import emit_pool  # noqa: E402  -- needs the path insert above

# The pair the system bus dispatches through. A module missing either cannot be
# reached generically, whatever else it compiles.
DRIVABLE_CONTRACT = ("read_double_word", "write_double_word")

# `reset` is a THIRD contract, tracked separately because it is already known to
# arrive under more than one name -- see docs/status/dispatch.json.
RESET_NAMES = ("reset", "basic_double_word_peripheral_reset")

# Infrastructure a running system needs and no peripheral supplies. None of
# these has a register-defining method, so `compile_check.py` never emits them
# and nothing has ever measured what the converter would do if asked. Each entry
# is (C# type, a method that exists on it) -- the emitter is keyed on a method,
# and which one is irrelevant since it emits the whole type either way.
INFRASTRUCTURE = [
    ("SystemBus", "ReadDoubleWord"),
    ("PeripheralCollection", "Add"),
    ("MappedMemory", "Reset"),
    ("ArrayMemory", "Reset"),
    ("Machine", "Reset"),
]


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def module_name(csharp_type: str) -> str:
    """The same mapping compile_check.py uses. Kept identical on purpose: two
    different spellings of the module name would make the two reports disagree
    about which module they are talking about."""
    return "".join(c if c.isalnum() else "_" for c in csharp_type).lower()


def emitted_types(db: Path) -> dict[str, str]:
    """module name -> C# type name, for every type the converter will emit."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("""
        SELECT t.name FROM type t
        JOIN member mb ON mb.type_id = t.id
        JOIN method m ON m.member_id = mb.id
        WHERE t.kind='class' AND m.has_body=1
          AND (mb.name LIKE '%Register%' OR mb.name LIKE '%DefineReg%')
        GROUP BY t.name ORDER BY t.name""").fetchall()
    return {module_name(n): n for (n,) in rows}


def why_not_emitted(db: Path, csharp: str) -> str:
    """The work list is a NAME HEURISTIC -- `compile_check.emit_all` selects
    types with a member matching `%Register%`/`%DefineReg%` that has a body. A
    peripheral that defines its registers inline in its constructor therefore
    never reaches the emitter, and looks identical from outside to one the
    emitter cannot do. They are not the same thing, so say which."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = con.execute("SELECT id FROM type WHERE name=?", (csharp,)).fetchone()
    if row is None:
        return "not a type in the corpus (a .repl reference, not a class)"
    tid = row[0]
    named = con.execute(
        """SELECT COUNT(*) FROM member mb JOIN method m ON m.member_id=mb.id
           WHERE mb.type_id=? AND m.has_body=1
             AND (mb.name LIKE '%Register%' OR mb.name LIKE '%DefineReg%')""",
        (tid,)).fetchone()[0]
    if named:
        return "selected but not emitted -- investigate"
    anyreg = con.execute(
        """SELECT COUNT(*) FROM member mb WHERE mb.type_id=?
           AND (mb.name LIKE '%Register%' OR mb.name LIKE '%egisters%')""",
        (tid,)).fetchone()[0]
    if anyreg:
        return ("HAS registers but defines them OUTSIDE a matching method "
                "(constructor-defined) -- the work-list heuristic misses it")
    return "no register-defining member at all (memory, CPU, bus, container)"


def robot_surface(renode_src: Path, test_rel: str) -> dict:
    """What ONE Renode Robot test actually asks the server for.

    Read from the test, never retyped. The point of the measurement is that
    Renode reaches these through reflection and we do not have to: a transpiler
    knows statically what C# defers to runtime. So each required capability is
    classified by whether its TARGET SET is closed at generation time:

      * `static`  -- the set of things it can name comes from the corpus or
        from the platform description, both of which we hold before the binary
        exists. A generated match arm, not a reflective lookup.
      * `dynamic` -- the value genuinely arrives at run time and nothing in the
        corpus bounds it.

    "Reflection has no analogue in Rust" is the wrong test and inflates the
    floor with work nobody has to do. AOT pipelines do not translate a
    reflection engine; they emit the dispatch it would have computed. The
    residue after that is the real number.
    """
    path = renode_src / test_rel
    if not path.exists():
        return {"error": f"{test_rel} not found under RENODE_SRC"}

    # The server's keyword set is itself derivable: every C# method carrying
    # `[RobotFrameworkKeyword]`. Reading it beats deciding by eye which of the
    # names in a .robot file the SERVER has to implement and which are the
    # test's own or Robot's built-ins.
    served: set[str] = set()
    engine = renode_src / "src" / "Renode" / "RobotFrameworkEngine"
    for cs in sorted(engine.glob("*.cs")):
        text = cs.read_text(errors="replace")
        for m in re.finditer(r"\[RobotFrameworkKeyword[^\]]*\]\s*"
                             r"(?:public|internal|private)?\s*[\w<>\[\],?. ]+?"
                             r"\s(\w+)\s*\(", text):
            served.add(m.group(1))
    norm = lambda s: re.sub(r"[ _]", "", s).lower()          # noqa: E731
    served_norm = {norm(s): s for s in served}

    defined: set[str] = set()                # keywords this .robot defines
    used: set[str] = set()
    cmds: set[str] = set()
    section = None
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if stripped.startswith("***"):
            section = stripped.strip("* ").lower()
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if not raw[:1].isspace():
            if section and section.startswith("keyword"):
                defined.add(stripped.split("  ")[0].strip())
            continue
        cells = [c.strip() for c in re.split(r"\t|  +", stripped) if c.strip()]
        if not cells or cells[0].startswith("["):
            continue
        if re.match(r"^[\$@&]\{.*\}\s*=?$", cells[0]):
            cells = cells[1:]
            if not cells:
                continue
        used.add(cells[0])
        if norm(cells[0]) == "executecommand" and len(cells) > 1:
            # The whole monitor command sits in ONE Robot cell; the HEAD is the
            # verb, not the arguments, and only the verb needs resolving.
            toks = cells[1].split()
            head = toks[0] if toks else ""
            if len(toks) > 1 and re.match(r"^[A-Za-z_][\w.]*$", toks[1]):
                head = f"{head} {toks[1]}"
            if head:
                cmds.add(head)

    server_side = sorted({served_norm[norm(k)] for k in used if norm(k) in served_norm})
    return {
        "test": test_rel,
        "keywords_used": sorted(used),
        "keywords_server_side": server_side,
        "keywords_defined_by_the_test": sorted(defined),
        "keywords_served_by_renode_total": len(served),
        "monitor_command_heads": sorted(cmds),
    }


def compile_errors(crate: Path, log: logging.Logger) -> dict[str, int] | None:
    proc = subprocess.run(["cargo", "check", "--message-format=json", "--quiet"],
                          cwd=crate, capture_output=True, text=True)
    # Cargo failing to RUN is not zero errors -- the same false green
    # compile_check.py documents. No JSON at all means nothing was compiled.
    if not proc.stdout.strip():
        log.error("cargo produced NO output: it compiled nothing. exit %d",
                  proc.returncode)
        for line in (proc.stderr or "(no stderr)").strip().splitlines()[:15]:
            log.error("    %s", line)
        return None
    per_mod: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("reason") != "compiler-message":
            continue
        d = msg.get("message", {})
        if d.get("level") != "error":
            continue
        for span in d.get("spans", []):
            f = span.get("file_name", "")
            if f.endswith(".rs"):
                per_mod[Path(f).stem] = per_mod.get(Path(f).stem, 0) + 1
                break
    return per_mod


def module_contracts(path: Path) -> dict[str, bool | str | None]:
    src = path.read_text()
    fns = set(re.findall(r"^pub fn ([a-z_0-9]+)", src, re.M))
    reset = next((n for n in RESET_NAMES if n in fns), None)
    return {
        "drivable": all(n in fns for n in DRIVABLE_CONTRACT),
        "reset": reset,
        "has_define_registers": "define_registers" in fns,
        "lines": len(src.splitlines()),
    }


def probe_infrastructure(root: Path, db: Path,
                         log: logging.Logger) -> dict[str, dict]:
    """Ask the converter for the types a running system needs and no peripheral
    supplies. Reports what fraction of each type survives, so "the bus does not
    translate" is a number rather than an opinion."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out: dict[str, dict] = {}
    for csharp, method in INFRASTRUCTURE:
        row = con.execute("""SELECT f.path, f.loc,
                                (SELECT COUNT(*) FROM member mb WHERE mb.type_id=t.id)
                             FROM type t JOIN file f ON f.id=t.file_id
                             WHERE t.name=?""", (csharp,)).fetchone()
        if row is None:
            log.warning("%s is not in the corpus at all", csharp)
            continue
        path, loc, members = row
        proc = subprocess.run(
            [sys.executable, "scripts/emit.py", "--type", csharp,
             "--method", method, "--file", "probe"],
            cwd=root, capture_output=True, text=True)
        if proc.returncode != 0:
            out[csharp] = {"csharp_file": path, "csharp_loc": loc,
                           "csharp_members": members, "emit_failed":
                           proc.stderr.strip()[:200]}
            continue
        text = proc.stdout
        out[csharp] = {
            "csharp_file": path,
            "csharp_loc": loc,
            "csharp_members": members,
            "emitted_lines": len(text.splitlines()),
            "gap_lines": sum(1 for l in text.splitlines() if l.startswith("//!   - ")),
            "emitted_fns": sorted(re.findall(r"^pub fn ([a-z_0-9]+)", text, re.M)),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rulesdb/patterns.db")
    ap.add_argument("--reuse", action="store_true",
                    help="use the scratch crate left by compile_check.py --keep")
    ap.add_argument("--out", default="docs/status/floor.json")
    ap.add_argument("--robot-test",
                    default="tests/unit-tests/stm32f4-erase.robot",
                    help="the Renode Robot test the floor is aimed at, "
                         "repo-relative under RENODE_SRC")
    emit_pool.add_jobs_arg(ap)
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("floor_census")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" / "floor_census.log",
                                  mode="w"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    crate = root / "tmp" / "compile_check"
    if not (args.reuse and (crate / "Cargo.toml").exists()):
        from compile_check import emit_all
        # Timing to stderr, never stdout -- compile_check keeps its stdout as a
        # golden artefact and a clock in one makes every run differ.
        timing = logging.getLogger("floor_census.timing")
        timing.setLevel(logging.INFO)
        timing.propagate = False
        timing.addHandler(logging.StreamHandler(sys.stderr))
        log.info("emitting every module the converter can produce ...")
        emit_all(root, root / args.db, log, timing, args.jobs)
    else:
        log.info("reusing the scratch crate at tmp/compile_check")

    per_mod = compile_errors(crate, log)
    if per_mod is None:
        return 0

    types = emitted_types(root / args.db)
    mods: dict[str, dict] = {}
    for f in sorted((crate / "src").glob("*.rs")):
        if f.stem == "lib":
            continue
        info = module_contracts(f)
        info["csharp_type"] = types.get(f.stem)
        info["errors"] = per_mod.get(f.stem, 0)
        info["clean"] = info["errors"] == 0
        mods[f.stem] = info

    # The platform is the .repl, derived. Nothing here retypes an address.
    plat = json.loads((root / "docs" / "status" / "platform.json").read_text())
    on_platform: dict[str, dict] = {}
    for name, entry in plat["peripherals"].items():
        csharp = (entry.get("type") or "").split(".")[-1]
        mod = module_name(csharp) if csharp else None
        on_platform[name] = {
            "csharp_type": entry.get("type"),
            "module": mod if mod in mods else None,
            "address": entry.get("address"),
            "emitted": mod in mods,
            "clean": bool(mod in mods and mods[mod]["clean"]),
            "drivable": bool(mod in mods and mods[mod]["drivable"]),
        }

    clean = [m for m, i in mods.items() if i["clean"]]
    drivable = [m for m, i in mods.items() if i["drivable"]]
    floor = sorted(m for m, i in mods.items() if i["clean"] and i["drivable"])
    plat_floor = sorted(n for n, i in on_platform.items()
                        if i["clean"] and i["drivable"] and i["address"] is not None)
    plat_unemitted = sorted(n for n, i in on_platform.items() if not i["emitted"])

    log.info("")
    log.info("%-46s %5d", "modules emitted", len(mods))
    log.info("%-46s %5d", "  ... that compile clean", len(clean))
    log.info("%-46s %5d", "  ... that expose read/write_double_word", len(drivable))
    log.info("%-46s %5d", "  ... BOTH (the floor's raw material)", len(floor))
    log.info("")
    log.info("%-46s %5d", "peripherals on the platform (.repl)", len(on_platform))
    log.info("%-46s %5d", "  ... with an emitted module at all", len(on_platform) - len(plat_unemitted))
    log.info("%-46s %5d", "  ... clean + drivable + addressed = THE FLOOR", len(plat_floor))
    log.info("")
    log.info("THE FLOOR, by .repl name:")
    for n in plat_floor:
        i = on_platform[n]
        log.info("    %-22s %-28s 0x%08X  %s", n, i["csharp_type"],
                 i["address"], mods[i["module"]]["reset"] or "NO reset")
    log.info("")
    log.info("On the platform and NOT emitted at all (%d), with the reason. "
             "The work list is a", len(plat_unemitted))
    log.info("NAME HEURISTIC, so 'not emitted' and 'cannot be emitted' are "
             "different states:")
    for n in plat_unemitted:
        why = why_not_emitted(root / args.db,
                              (on_platform[n]["csharp_type"] or "").split(".")[-1])
        on_platform[n]["why_not_emitted"] = why
        log.info("    %-22s %-34s %s", n, on_platform[n]["csharp_type"], why)

    infra = probe_infrastructure(root, root / args.db, log)
    log.info("")
    log.info("INFRASTRUCTURE the floor needs and no peripheral supplies.")
    log.info("These have no register-defining method, so compile_check never")
    log.info("emits them and nothing had measured this:")
    log.info("")
    log.info("    %-22s %6s %6s  %6s %5s  %s", "C# type", "C# loc", "members",
             "lines", "gaps", "public fns emitted")
    for name, i in infra.items():
        if "emitted_lines" not in i:
            log.info("    %-22s %6d %6d  emit failed", name, i["csharp_loc"],
                     i["csharp_members"])
            continue
        fns = ", ".join(i["emitted_fns"]) or "(none)"
        log.info("    %-22s %6d %6d  %6d %5d  %s", name, i["csharp_loc"],
                 i["csharp_members"], i["emitted_lines"], i["gap_lines"],
                 fns[:70])

    resets = sorted({(mods[m]["reset"] or "NONE") for m in floor})
    log.info("")
    log.info("reset arrives under %d name(s) across the floor: %s",
             len(resets), ", ".join(resets))
    log.info("A generic caller needs ONE name per contract.")

    # --- what the first Robot test asks for, and what of it is static -------
    surface: dict = {}
    try:
        from parse_repl import load_env
        renode_src = Path(load_env(root)["RENODE_SRC"])
        surface = robot_surface(renode_src, args.robot_test)
    except Exception as exc:                                   # noqa: BLE001
        surface = {"error": f"RENODE_SRC unreadable: {exc}"}

    # Every name the monitor must resolve for this test. Renode finds these by
    # reflection at run time; the set is closed at GENERATION time, because it
    # is exactly the platform's peripherals plus the bus itself.
    monitor_targets = sorted(set(on_platform) | {"sysbus", "machine"})
    dispatch_entries = (len(on_platform) - len(plat_unemitted)) * len(DRIVABLE_CONTRACT)
    static_resolution = {
        "why": "Reflection does not have to be translated, it has to be "
               "RESOLVED AT COMPILE TIME. Counting a reflection engine as a "
               "translation cost counts work nobody has to do -- every AOT C# "
               "pipeline emits the dispatch instead. These are the sets that "
               "close at generation time.",
        "monitor_target_names": len(monitor_targets),
        "monitor_target_source": "docs/status/platform.json (derived from the "
                                 ".repl) -- closed before the binary exists",
        "peripheral_dispatch_entries": dispatch_entries,
        "peripheral_dispatch_source": "the emitted modules' read/write_double_"
                                      "word pair -- closed at generation time; "
                                      "src/renode-stm32/src/dispatch.rs already "
                                      "generates exactly this table",
        "monitor_commands_required": len(surface.get("monitor_command_heads", [])),
        "robot_keywords_required": len(surface.get("keywords_server_side", [])),
        "robot_keywords_renode_serves": surface.get(
            "keywords_served_by_renode_total"),
        "genuinely_dynamic": [
            "the command STRING arrives from the Robot client, so it must be "
            "tokenised at run time -- but every name it can resolve to is in "
            "the closed sets above",
            "scalar argument coercion (a hex token to u32/u64/bool), because "
            "the token's type is not known until it is parsed",
            "how many machines exist, if a suite creates more than one",
        ],
        "statically_resolvable": [
            "which peripherals exist and where (platform.json)",
            "which method a peripheral name plus a command word reaches "
            "(the emitted modules' contract)",
            "which Rust type implements the bus contract (dispatch.rs, already "
            "generated from the corpus)",
            "the Robot keyword table returned by get_keyword_names (ours, and "
            "fixed at build time)",
        ],
    }
    log.info("")
    log.info("WHAT THE FIRST ROBOT TEST ASKS FOR (read from the test, not typed):")
    if "error" in surface:
        log.info("    %s", surface["error"])
    else:
        log.info("    test:            %s", surface["test"])
        log.info("    server keywords: %s (of %d Renode serves)",
                 ", ".join(surface["keywords_server_side"]),
                 surface["keywords_served_by_renode_total"])
        log.info("    the test's own:  %s",
                 ", ".join(surface["keywords_defined_by_the_test"]))
        log.info("    monitor verbs:   %s",
                 ", ".join(surface["monitor_command_heads"]))
    log.info("")
    log.info("STATIC RESOLUTION -- reflection is not translated, it is resolved")
    log.info("at generation time. The sets that close before the binary exists:")
    log.info("    %-42s %5d", "monitor target names (from platform.json)",
             static_resolution["monitor_target_names"])
    log.info("    %-42s %5d", "peripheral dispatch table entries",
             static_resolution["peripheral_dispatch_entries"])
    log.info("    %-42s %5d", "monitor commands this test needs",
             static_resolution["monitor_commands_required"])
    log.info("    %-42s %5d", "Robot keywords this test names",
             static_resolution["robot_keywords_required"])
    log.info("  genuinely dynamic:")
    for d in static_resolution["genuinely_dynamic"]:
        log.info("    - %s", d)

    out = {
        "note": "GENERATED by scripts/floor_census.py. Read by docs/decisions/; "
                "do not retype these numbers into prose.",
        "modules_emitted": len(mods),
        "modules_clean": len(clean),
        "modules_drivable": len(drivable),
        "modules_clean_and_drivable": len(floor),
        "platform_peripherals": len(on_platform),
        "platform_emitted": len(on_platform) - len(plat_unemitted),
        "platform_floor": len(plat_floor),
        "floor": {n: on_platform[n] for n in plat_floor},
        "platform_not_emitted": {n: on_platform[n] for n in plat_unemitted},
        "reset_names_across_floor": resets,
        "clean_and_drivable_modules": floor,
        "infrastructure": infra,
        "robot_surface": surface,
        "static_resolution": static_resolution,
    }
    (root / args.out).write_text(json.dumps(out, indent=2) + "\n")
    log.info("")
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
