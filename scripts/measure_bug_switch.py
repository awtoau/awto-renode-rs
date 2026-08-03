#!/usr/bin/env python3
"""Measure what switching a source defect to conformance actually costs.

THE FIELD THIS EXISTS TO FILL
-----------------------------
A bug rule records which traces fail if you throw its switch. The decision that
created the class is explicit that this field is the one that makes switching
safe rather than a coin flip, and that it must be MEASURED:

    switch the rule, regenerate, run the traces, record what moved, switch it
    back. A bug rule whose switch-impact is unknown is not finished.

An asserted number is worth nothing here. "No trace moves" and "we did not
look" produce the same JSON, and the second one is how the invented
`.with_reserved(9, 23)` survived a 33,000-access trace: behaviourally inert
wrong code is invisible until something runs it.

WHAT IT DOES
------------
For each stanza:
  1. regenerate its module with `emit.py` -- once plain, once with
     `--conformance ID`
  2. report whether the two differ at all, and how
  3. replay every trace that maps to the stanza's C# type against BOTH, and
     count divergences

The replay uses the project's own oracle harness, so the number this prints is
the same number the ratchet in tests/generated_trace.rs asserts on. The
committed file is restored before the script exits, including on failure --
leaving a conformance module on disk would silently change what every other
gate is measuring.

Traces are found through `docs/status/platform.json`, which is derived from the
`.repl`. A trace is named for a platform INSTANCE and the stanza names a C#
TYPE, so the platform is the only thing that can join them; matching the names
directly finds almost nothing.

Run:  python3 scripts/measure_bug_switch.py [BUG_ID ...]     (default: all)
      python3 scripts/measure_bug_switch.py --write          (update the data)
Log:  ./tmp/logs/measure_bug_switch.log
Exit: 0 if every stanza was measured, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def stanzas(root: Path) -> list[tuple[Path, dict]]:
    out = []
    for f in sorted((root / "rulesdb" / "rules").glob("*.json")):
        for s in json.loads(f.read_text()).get("bug_rules", []):
            out.append((f, s))
    return out


def module_for(root: Path, type_name: str) -> tuple[str, list[str]] | None:
    """(committed path, emit argv) for the module that owns this C# type.

    From check_generated.GENERATED, so the set of files the converter owns is
    stated once.
    """
    sys.path.insert(0, str(root / "scripts"))
    from check_generated import GENERATED
    for rel, argv in GENERATED:
        if "--type" in argv and argv[argv.index("--type") + 1] == type_name:
            return rel, argv
    return None


def traces_for(root: Path, type_name: str) -> list[str]:
    """Captured traces of instances of this C# type, per the platform."""
    plat = json.loads((root / "docs" / "status" / "platform.json").read_text())
    out = []
    for name, entry in plat.get("peripherals", {}).items():
        if entry.get("type", "").split(".")[-1] != type_name:
            continue
        if (root / "oracle" / "traces" / f"{name}.jsonl.gz").exists():
            out.append(name)
    return sorted(out)


def generate(root: Path, argv: list[str], conformance: str | None) -> str:
    cmd = [sys.executable, *argv]
    if conformance:
        cmd += ["--conformance", conformance]
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"emit failed: {r.stderr.strip()[:400]}")
    return r.stdout


#: `NAME (GENERATED): N accesses (M reads), D divergences, P%`
#: SEARCHED, not matched from the start: at `--test-threads=1 --nocapture` the
#: harness interleaves its own `test <name> ... ` prefix onto the same line, so
#: an anchored pattern finds nothing and reports it as "the harness printed no
#: report" -- which reads exactly like a build failure.
REPORT = re.compile(r"(\S+) \(GENERATED\): \d+ accesses \(\d+ reads\), "
                    r"(\d+) divergences")


#: The bug tier's own marker, whatever tag the data gives it. Read from the
#: rule document rather than written here, so a change to the tag cannot leave
#: this silently matching nothing.
def _bug_tag(root: Path) -> str:
    core = json.loads(
        (root / "rulesdb" / "rules" / "csharp_core.json").read_text())
    return (core.get("severity", {}).get("tiers", {})
            .get("bug", {}).get("default_tag", "SRCBUG"))


def code_of(text: str, _cache: dict = {}) -> str:
    """`text` with every source-defect marker line removed.

    Markers are comments and can never change what the output does, so two
    outputs that differ only in their markers are the SAME CODE. Saying so is
    what lets `unavailable` conformance be reported as unavailable.
    """
    root = repo_root()
    tag = _cache.setdefault("tag", _bug_tag(root))
    return "\n".join(l for l in text.splitlines() if tag not in l)


def replay(root: Path, log: logging.Logger) -> dict[str, int]:
    """Divergences per trace, from the project's own replay harness.

    `--no-fail-fast` and a tolerated non-zero exit: switching a defect to
    conformance is EXPECTED to break the ratchet, and the count is printed
    before the assertion that fails. A script that only read the number on
    success could never measure the interesting direction.
    """
    r = subprocess.run(
        ["cargo", "test", "-p", "renode-stm32", "--test", "generated_trace",
         "--no-fail-fast", "--", "--nocapture", "--test-threads=1"],
        cwd=root, capture_output=True, text=True)
    got: dict[str, int] = {}
    for line in r.stdout.splitlines():
        m = REPORT.search(line)
        if m:
            got[m.group(1)] = int(m.group(2))
    if not got:
        log.error("the replay harness printed no report line; cargo said:")
        for line in (r.stdout + r.stderr).splitlines()[-20:]:
            log.error("    %s", line)
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="bug rule ids; default all")
    ap.add_argument("--write", action="store_true",
                    help="write the measured counts back into the rule data")
    args = ap.parse_args()

    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("measure_bug_switch")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" /
                                  "measure_bug_switch.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    todo = [(f, s) for f, s in stanzas(root)
            if not args.ids or s.get("id") in args.ids]
    if not todo:
        log.error("no such bug rule: %s", ", ".join(args.ids))
        return 1

    log.info("baseline: replaying every generated module on fidelity")
    base = replay(root, log)
    if not base:
        return 1
    for t in sorted(base):
        log.info("    %-12s %d divergence(s)", t, base[t])
    log.info("")

    results: dict[str, dict] = {}
    failed = 0
    for _f, s in todo:
        sid = s["id"]
        type_name = s.get("site", {}).get("type", "")
        mod = module_for(root, type_name)
        traces = traces_for(root, type_name)
        log.info("=== %s", sid)
        log.info("    type %s -> module %s", type_name,
                 mod[0] if mod else "<none>")
        log.info("    traces: %s", ", ".join(traces) or "<none>")
        if not mod:
            log.error("    no generated module owns %s -- cannot measure",
                      type_name)
            failed += 1
            continue
        rel, argv = mod
        path = root / rel
        committed = path.read_text()
        try:
            fid = generate(root, argv, None)
            con = generate(root, argv, sid)
            # Did the CODE change, or only the marker? A switched stanza always
            # relabels its own marker -- that is deliberate, because output
            # that diverges from the source on purpose is the more dangerous
            # state to leave unlabelled -- and comparing the raw text would
            # therefore report every stanza as CHANGES, including the ones
            # whose conformance is `unavailable`. That would turn the
            # distinction this script exists to draw into a constant.
            changed = code_of(fid) != code_of(con)
            log.info("    emitted CODE %s under conformance",
                     "CHANGES" if changed else "is UNCHANGED")
            if not changed:
                action = s.get("conformance", {}).get("action")
                log.info("    (conformance.action = %s -- only the marker "
                         "moves)", action)
            if fid != committed:
                # The committed file must already be the fidelity output, or
                # every number below is measured against something else.
                log.error("    %s is not what the converter produces -- run "
                          "check_generated.py first", rel)
                failed += 1
                continue
            if changed:
                path.write_text(con)
                after = replay(root, log)
            else:
                after = dict(base)
        finally:
            path.write_text(committed)

        counts = {}
        for t in traces:
            if t not in base:
                log.info("    %-12s no replay entry in tests/generated_trace.rs",
                         t)
                continue
            counts[t] = {"fidelity": base[t], "conformance": after.get(t, -1)}
            delta = counts[t]["conformance"] - counts[t]["fidelity"]
            log.info("    %-12s %d -> %d  (%+d)", t, counts[t]["fidelity"],
                     counts[t]["conformance"], delta)
        # A module can be shared: dma_registers backs dma1 and dma2. Report any
        # OTHER trace that moved too, or a switch could shift a number nobody
        # attributed to it.
        for t in sorted(set(after) | set(base)):
            if t not in counts and after.get(t) != base.get(t):
                log.info("    %-12s %s -> %s  COLLATERAL", t, base.get(t),
                         after.get(t))
                counts[t] = {"fidelity": base.get(t, -1),
                             "conformance": after.get(t, -1)}
        results[sid] = {"changed": changed, "traces": counts}
        log.info("")

    if args.write:
        for f in sorted({f for f, _ in todo}):
            doc = json.loads(f.read_text())
            for s in doc.get("bug_rules", []):
                r = results.get(s.get("id"))
                if not r:
                    continue
                imp = s.setdefault("switch_impact", {})
                imp["measured"] = True
                imp["how"] = f"scripts/measure_bug_switch.py {s['id']}"
                imp["traces"] = r["traces"]
                imp["generated_files_changed"] = (
                    [module_for(root, s["site"]["type"])[0]] if r["changed"]
                    else [])
            f.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
            log.info("wrote measured counts into %s", f.name)
        log.info("`reading` is NOT written: a number needs an interpretation "
                 "and that is a person's job.")

    log.info("%d measured, %d could not be", len(results), failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
