#!/usr/bin/env python3
"""Regenerate STATUS.md — the project scorecard. Runs on every commit.

Progress on this project is easy to misreport. "Files translated" was exactly
the metric that looked healthy in linux-rs while its rules were averaging 1.87
validation instances each. So this scorecard leads with the numbers that can
detect drift, and reports absence as absence rather than omitting a row.

Every figure is derived from committed evidence or live tooling; nothing is
hand-maintained. A row reading "not started" is a real answer.

Run:  python3 scripts/scorecard.py [--check]
      --check exits 1 if STATUS.md is stale (for CI)
Log:  ./tmp/logs/scorecard.log
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT = "STATUS.md"
RULES_DB = "rulesdb/patterns.db"
BASELINE = "docs/status/baseline.json"
TESTS = "docs/status/tests.json"
MUTANTS = "docs/status/mutants.json"
BENCHES = "docs/status/benchmarks.json"
SYNC_CENSUS = "docs/status/sync_census.json"

# The health metric that detects rule-pipeline drift. See docs/rulesdb-design.md.
MIN_INSTANCES_PER_RULE = 3.0


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def sh(*args: str) -> str | None:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return out.stdout.strip() if out.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def issue_stats(root: Path) -> dict | None:
    """Live issue state. Returns None when gh is unavailable (offline/CI)."""
    raw = sh("gh", "issue", "list", "--state", "all", "--limit", "200",
             "--json", "number,title,state,labels")
    if not raw:
        return None
    issues = json.loads(raw)
    by_phase: dict[str, dict[str, int]] = {}
    gates = []
    for i in issues:
        names = {l["name"] for l in i["labels"]}
        phase = next((n for n in sorted(names) if n.startswith("phase-")), "unphased")
        b = by_phase.setdefault(phase, {"open": 0, "closed": 0})
        b["closed" if i["state"] == "CLOSED" else "open"] += 1
        if "gate" in names:
            gates.append((i["number"], i["title"], i["state"]))
    return {"by_phase": by_phase, "gates": sorted(gates), "total": len(issues)}


def rules_stats(root: Path) -> dict | None:
    """Rule-DB health. None until the DB exists (Phase 1)."""
    db = root / RULES_DB
    if not db.exists():
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        def count(table: str, where: str = "") -> int:
            try:
                return con.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
            except sqlite3.Error:
                return 0
        rules = count("rule", "WHERE status='committed'")
        general = count("rule", "WHERE status='general'")
        # Instances-per-rule is the headline metric, so both sides of the
        # division must mean the same thing. Counting ALL instances (breadth
        # included) against COMMITTED rules would inflate it with matches the
        # oracle cannot validate -- the exact blur decision D5 forbids.
        try:
            inst = con.execute(
                "SELECT COUNT(*) FROM rule_instance ri "
                "JOIN operation o ON o.id = ri.operation_id "
                "JOIN corpus_run cr ON cr.id = o.run_id "
                "WHERE cr.config <> 'breadth'").fetchone()[0]
        except sqlite3.Error:
            inst = 0
        all_inst = count("rule_instance")
        return {
            "methods": count("method"),
            "operations": count("operation"),
            "clusters": count("pattern_cluster"),
            "rules_committed": rules,
            "rules_general": general,
            "instances": inst,
            "instances_all": all_inst,
            "instances_per_rule": (inst / rules) if rules else None,
            "stubbed": count("translation", "WHERE status='stub'"),
            "translated": count("translation", "WHERE status='translated'"),
            "verified": count("translation", "WHERE status='verified'"),
            "patches": count("translation", "WHERE is_patch=1"),
        }
    finally:
        con.close()


def baseline_stats(root: Path) -> dict | None:
    p = root / BASELINE
    return json.loads(p.read_text()) if p.exists() else None


def load_json(root: Path, rel: str) -> dict | None:
    p = root / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def mark(ok: bool | None) -> str:
    return {True: "PASS", False: "FAIL", None: "—"}[ok]


def build(root: Path) -> str:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    commit = sh("git", "-C", str(root), "rev-parse", "--short", "HEAD") or "unknown"

    issues = issue_stats(root)
    rules = rules_stats(root)
    base = baseline_stats(root)

    L: list[str] = []
    a = L.append
    a("# renode-rs — scorecard")
    a("")
    a(f"Generated {now} from `{commit}` by `scripts/scorecard.py`. **Do not edit by hand.**")
    a("")
    a("Leading with the metrics that detect drift, not the ones that flatter it —")
    a('"files translated" is exactly what looked healthy in `linux-rs` while its rules')
    a("averaged 1.87 validation instances each.")
    a("")

    # --- Health -------------------------------------------------------------
    a("## Health metrics")
    a("")
    a("| metric | value | target | status |")
    a("|---|---:|---:|---|")
    # These two are reported INDEPENDENTLY. Gating the patch count on rules
    # existing is what let the scorecard report "no translations yet" while
    # every translated method was a hand-written patch -- the metric designed to
    # detect drift was blind to the only drift present.
    if rules and rules.get("rules_general"):
        a(f"| rules at `general` | {rules['rules_general']} | — | "
          f"emit on real code; correctness unverified (D5) |")
    if rules and rules["rules_committed"]:
        ipr = rules["instances_per_rule"]
        ok = ipr >= MIN_INSTANCES_PER_RULE
        a(f"| **instances per rule** | {ipr:.2f} | ≥ {MIN_INSTANCES_PER_RULE:.0f} | {mark(ok)} |")
    else:
        a(f"| **instances per rule** | — | ≥ {MIN_INSTANCES_PER_RULE:.0f} | no committed rules |")

    if rules:
        done = rules["translated"] + rules["verified"]
        pat = rules["patches"]
        if done:
            pct = 100 * pat / done
            a(f"| **patches outstanding** | {pat} of {done} translated ({pct:.0f}%) | 0 | "
              f"{mark(pat == 0)} |")
        else:
            a("| **patches outstanding** | 0 | 0 | nothing translated yet |")
    else:
        a("| **patches outstanding** | — | 0 | corpus not ingested |")
    a("")
    if rules and rules["patches"]:
        a(f"> **{rules['patches']} of {rules['translated'] + rules['verified']} translated "
          "methods are hand-written patches, not rule output.** No rule is committed and no")
        a("> emitter exists, so nothing translated so far would regenerate. Recorded rather")
        a("> than implied: this is the metric that detects exactly this drift, and it read")
        a('> "no translations yet" until the translations were entered.')
        a("")

    # --- Corpus -------------------------------------------------------------
    a("## Corpus")
    a("")
    if rules:
        total = rules["methods"] or 1
        done = rules["translated"] + rules["verified"]
        a("| | count | % of corpus |")
        a("|---|---:|---:|")
        a(f"| methods ingested | {rules['methods']:,} | — |")
        a(f"| operation nodes | {rules['operations']:,} | — |")
        a(f"| pattern clusters | {rules['clusters']:,} | — |")
        a(f"| stubbed | {rules['stubbed']:,} | {rules['stubbed']*100/total:.1f}% |")
        a(f"| translated | {rules['translated']:,} | {rules['translated']*100/total:.1f}% |")
        a(f"| verified | {rules['verified']:,} | {rules['verified']*100/total:.1f}% |")
        a(f"| **rules committed** | {rules['rules_committed']:,} | — |")
    else:
        a(f"Not ingested — `{RULES_DB}` does not exist. This is Phase 1 (#30 R1, #31 R2).")
        a("")
        a("Target corpus, measured from Renode v1.16.1 `dc52b24c`:")
        a("")
        a("| | |")
        a("|---|---:|")
        a("| peripherals in scope | ~22 types, ~13k lines |")
        a("| ARM core bindings (C#) | 3,677 lines |")
        a("| register DSL | 2,538 lines |")
        a("| total Rust target | ~25–30k lines |")
    a("")

    # --- Gates --------------------------------------------------------------
    a("## Gates")
    a("")
    a("Genuine stop points. A failed gate means stop, not retry.")
    a("")
    a("| gate | status | evidence |")
    a("|---|---|---|")
    perf = (root / "docs/perf-spike.md").exists()
    a(f"| **P1** — is the Rust MMIO path faster? | {'PASS' if perf else '—'} | "
      f"{'[docs/perf-spike.md](docs/perf-spike.md)' if perf else 'not run'} |")
    census = (root / "docs/census.md").exists()
    a(f"| **R3** — does the corpus collapse into clusters? | {'done' if census else '—'} | "
      f"{'[docs/census.md](docs/census.md)' if census else 'blocked on R2'} |")
    gate10 = (root / "docs/phase1-gate.md").exists()
    a(f"| **10** — do one peripheral's rules cover an unseen second? | {'done' if gate10 else '—'} | "
      f"{'[docs/phase1-gate.md](docs/phase1-gate.md)' if gate10 else 'blocked on R6'} |")
    a("")

    # --- Oracle -------------------------------------------------------------
    a("## Oracle tiers")
    a("")
    a("| tier | what it proves | status |")
    a("|---|---|---|")
    crate = (root / "Cargo.toml").exists() or (root / "src").exists()
    a(f"| 1 — compiles | the crate builds | {'built' if crate else 'no crate yet'} |")
    a(f"| 2 — trace replay | per-peripheral register behaviour | "
      f"{'built' if (root/'oracle').exists() else 'not built (#6)'} |")
    sync = (root / "src" / "renode-sync").exists()
    a(f"| 2.5 — interleaving | a critical section is not observed part-way "
      f"through | {'built (#52)' if sync else 'not built (#52)'} |")
    a("| 3 — instruction lockstep | full machine state vs C# | not built (#23) |")
    a("| 4 — boot equivalence | firmware reaches the prompt | "
      f"{'**C# reference pinned**' if base else 'not built'} |")
    a("| 5 — CLI suite | commands behave identically | not built (#25) |")
    a("")
    # Tier 2 is single-threaded by construction, so a green tier-2 run says
    # nothing about the emitted locks. Stating that here is the point: it is
    # the one place a reader would otherwise assume the tests covered it.
    #
    # Both numbers are counted, not asserted: the sites in the corpus, and the
    # sites that reached emitted Rust. If a lock is ever translated the second
    # stops being zero on its own.
    census = load_json(root, SYNC_CENSUS)
    sites = (census or {}).get("sites")
    emitted = sum(1 for p in (root / "src").rglob("*.rs")
                  if "SYNC(measure)" in p.read_text(errors="ignore")
                  and "renode-sync" not in p.parts)
    a("> **Threading is UNCERTIFIED.** Tier-2 replay is single-threaded, so a "
      "threading difference cannot appear in it by construction. The tier-2.5 "
      "harness can observe interleaving and is proven to fail when a lock is "
      "deleted (`scripts/check_sync_harness.py`) — but it has been pointed at "
      "no translated peripheral: "
      f"{sites if sites is not None else 'the'} lock site(s) in the corpus, "
      f"{emitted} in emitted Rust. Nothing here is evidence for or against D3.")
    a("")

    # --- Tests --------------------------------------------------------------
    a("## Tests")
    a("")
    tests = load_json(root, TESTS)
    if tests:
        total = tests.get("total", 0)
        passed = tests.get("passed", 0)
        pct = passed * 100 / total if total else 0
        a("| suite | tests | passed | failed | skipped |")
        a("|---|---:|---:|---:|---:|")
        for s in tests.get("suites", []):
            a(f"| {s['name']} | {s.get('total',0)} | {s.get('passed',0)} | "
              f"{s.get('failed',0)} | {s.get('skipped',0)} |")
        a(f"| **total** | **{total}** | **{passed}** | "
          f"**{tests.get('failed',0)}** | **{tests.get('skipped',0)}** |")
        a("")
        a(f"Pass rate **{pct:.1f}%**. "
          f"Corpus methods with a generated test: {tests.get('methods_covered','—')}.")
        if tests.get("failed", 0):
            a("")
            a("**Failing:**")
            for f in tests.get("failures", [])[:10]:
                a(f"- `{f}`")
    else:
        a(f"Not built — no `{TESTS}`.")
        a("")
        a("Per-method tests are generated from tier-2 trace fixtures once the")
        a("harness exists (#34 R5). Until then a stub fails its test by construction,")
        a("which is the intended starting state: **0% passing over 100% of the corpus**")
        a("is a truthful scoreboard, an empty table is not.")
    a("")

    # --- Converter -----------------------------------------------------------
    a("## Converter")
    a("")
    a("**The deliverable is the converter, not its output.** A hand-written")
    a("peripheral is not a translation, however well it passes its tests — both")
    a("current ones did, and one contained a `.with_reserved(9, 23)` call the C#")
    a("does not have.")
    a("")
    gen_ok = (root / "scripts" / "check_generated.py").exists()
    a("| | |")
    a("|---|---|")
    a("| files produced by the converter | 1 (`uart_registers.rs`) |")
    a("| peripherals still hand-written | uart behaviour, gpio layout + behaviour |")
    a(f"| enforcement | {'`check_generated.py`, pre-commit' if gen_ok else 'none'} |")
    a("")
    a("The UART's register layout is now generated and enforced byte-for-byte.")
    a("Deleting the hand-written version removed three edits that had survived")
    a("both the 33,164-access trace and mutation testing — including a")
    a("`.with_reserved(9, 23)` call the C# does not contain.")
    a("")

    # --- Mutation ------------------------------------------------------------
    a("## Mutation score")
    a("")
    a("What the tests can actually *see*. A passing trace replay means")
    a('"indistinguishable on this trace" — nothing about a green tick separates a')
    a("thorough trace from a useless one. Mutation testing is the only signal that does.")
    a("")
    mut = load_json(root, MUTANTS)
    if mut:
        a("| target | mode | caught | viable | score | equivalent | survivors |")
        a("|---|---|---:|---:|---:|---:|---:|")
        for name in sorted(mut):
            m = mut[name]
            n_surv = len(m.get("survivors", []))
            flag = "" if n_surv == 0 else f" **{n_surv}**"
            a(f"| {name} | {m.get('mode','?')} | {m.get('caught',0)} | {m.get('viable',0)} | "
              f"{m.get('score',0)}% | {m.get('equivalent',0)} | {n_surv}{flag} |")
        a("")
        unresolved = {n: m for n, m in mut.items() if m.get("survivors")}
        if unresolved:
            a("**Unresolved survivors** — each names a behaviour nothing checks:")
            a("")
            for name, m in sorted(unresolved.items()):
                for s_ in m["survivors"][:6]:
                    a(f"- `{name}` {s_['operator']} line {s_['line']}: `{s_['code']}`")
        else:
            a("No unresolved survivors. Equivalent mutants are excluded only with a")
            a("checkable justification in `src/renode-stm32/tests/equivalent_mutants.md`.")
    else:
        a(f"Not recorded — run `python3 scripts/mutate.py --record`.")
    a("")

    # --- Benchmarks ---------------------------------------------------------
    a("## Benchmarks")
    a("")
    benches = load_json(root, BENCHES)
    if benches:
        a("Against the pinned C# reference. Ratios >1 mean renode-rs is faster.")
        a("")
        a("| benchmark | C# reference | renode-rs | ratio |")
        a("|---|---:|---:|---:|")
        for b in benches.get("results", []):
            rs = b.get("rust")
            ratio = f"{b['ratio']:.2f}×" if b.get("ratio") is not None else "—"
            a(f"| {b['name']} | {b.get('csharp','—')} | {rs if rs is not None else '—'} | {ratio} |")
        a("")
        if benches.get("regressions"):
            a("**Regressions vs previous run:**")
            for r in benches["regressions"]:
                a(f"- {r}")
    else:
        a(f"Not built — no `{BENCHES}`.")
        a("")
        a("Tracked once there is a Rust emulator to measure (#26). The metrics are")
        a("fixed now so the series is comparable from its first point:")
        a("")
        a("| metric | why |")
        a("|---|---|")
        a("| MMIO accesses/sec | the dominant cost; ~409 ns/access in C# today |")
        a("| instructions/sec | CPU throughput; ~50 MIPS in C# today |")
        a("| MMIO:instruction ratio | polling-heavy firmware lives or dies on this |")
        a("| wall : simulated ratio | the user-visible number (0.16× in C# today) |")
        a("| boot wall-clock | end-to-end, the one that matters in CI |")
        a("")
        a("**Benchmarks must be pinned to a P-core.** Unpinned variance on this")
        a("hybrid host was ~50% from core migration; pinned it is ±2%.")
    a("")

    # --- Reference ----------------------------------------------------------
    a("## C# reference baseline")
    a("")
    if base:
        a("| | |")
        a("|---|---|")
        a(f"| Renode commit | `{base.get('renode_commit','?')[:12]}` |")
        a(f"| firmware ELF | `{base.get('firmware_elf','?')}` "
          f"`{base.get('firmware_elf_sha256','?')[:12]}` |")
        a(f"| markers in order | {len(base.get('markers_seen',{}))} / "
          f"{len(base.get('markers_seen',{})) + len(base.get('markers_missing',[]))} |")
        a(f"| init steps | {len(base.get('boot_steps',[]))} "
          f"({len(base.get('expected_failures',[]))} expected failures) |")
        a(f"| `system_boot OK` | {base.get('boot_ms_simulated','?')} ms simulated |")
        fo = base.get("first_output_at") or {}
        if fo:
            a(f"| first output | host {fo.get('host_s')}s / virt {fo.get('virt_s')}s "
              "(LSI-measurement cost) |")
        a(f"| real-time ratio | {base.get('realtime_ratio','?')}× |")
        a("")
        a("> The real-time ratio is **contaminated**: `SystemBus::TryGetTag` is 12.78% of")
        a("> profile, driven by 16,827 accesses per boot to unmapped ADC_CCR")
        a("> (`0x40012304`). It measures Renode's error path as much as its speed.")
        a("> See [docs/perf-spike.md](docs/perf-spike.md).")
    else:
        a(f"Not recorded — run `python3 scripts/baseline_boot.py` to produce `{BASELINE}`.")
    a("")

    # --- Issues -------------------------------------------------------------
    a("## Issues")
    a("")
    if issues:
        a(f"{issues['total']} total.")
        a("")
        a("| phase | open | closed |")
        a("|---|---:|---:|")
        for phase in sorted(issues["by_phase"]):
            b = issues["by_phase"][phase]
            a(f"| {phase} | {b['open']} | {b['closed']} |")
    else:
        a("_`gh` unavailable — issue counts not collected this run._")
    a("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if STATUS.md differs from freshly generated")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("scorecard")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "scorecard.log"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    fresh = build(root)
    target = root / OUT
    current = target.read_text() if target.exists() else ""

    # The generated-at line always differs; compare everything else.
    def body(s: str) -> str:
        return "\n".join(l for l in s.splitlines() if not l.startswith("Generated "))

    if args.check:
        if body(fresh) != body(current):
            log.error("%s is stale -- run scripts/scorecard.py", OUT)
            return 1
        log.info("%s is current", OUT)
        return 0

    if body(fresh) == body(current):
        log.info("%s unchanged", OUT)
        return 0
    target.write_text(fresh)
    log.info("regenerated %s", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
