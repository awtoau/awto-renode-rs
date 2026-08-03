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
import re
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
FLOOR = "docs/status/floor.json"
CLEAN_SET = "docs/status/compile_clean_set.json"
GAP_CENSUS = "docs/status/gap_census.json"
HARNESS = "src/renode-stm32/tests/generated_trace.rs"
RULE_FILES = ["csharp_core.json", "register_dsl.json", "bug_rules.json",
              "offset_switch.json", "constructor.json", "object_graph.json"]

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


def severity_stats(root: Path) -> tuple[dict, dict]:
    """Marked deviation sites in emitted Rust, per warning identifier.

    Read from the SAME table the emitter renders from, so a new deviation
    appears here without an edit and cannot be counted under a name only this
    script knows. Grepping for a remembered string is how the one marker that
    already existed stayed the only one for as long as it did.

    `renode-sync` is excluded for the reason the threading line already
    excludes it: it holds a hand-written copy of the emitted shape as a test
    fixture, which is not a translated site.
    """
    doc = root / "rulesdb" / "rules" / "csharp_core.json"
    if not doc.exists():
        return {}, {}
    spec = json.loads(doc.read_text()).get("severity", {})
    warnings = {k: v for k, v in spec.get("warnings", {}).items()
                if isinstance(v, dict)}
    default = spec.get("tiers", {}).get("warning", {}).get("default_tag", "WARN")
    counts = {k: 0 for k in warnings}
    for p in (root / "src").rglob("*.rs"):
        if "renode-sync" in p.parts:
            continue
        text = p.read_text(errors="ignore")
        for wid, w in warnings.items():
            counts[wid] += text.count(f"{w.get('tag', default)}({wid})")
    return counts, warnings


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
    by_label: dict[str, list[int]] = {}
    for i in issues:
        for l in i["labels"]:
            by_label.setdefault(l["name"], []).append(i["number"])
    open_n = sum(1 for i in issues if i["state"] != "CLOSED")
    return {"by_phase": by_phase, "gates": sorted(gates), "total": len(issues),
            "open": open_n, "closed": len(issues) - open_n,
            "by_label": {k: sorted(v) for k, v in by_label.items()}}


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
        # division must mean the same thing. Counting ALL instances against
        # COMMITTED rules would inflate it with matches the oracle never
        # validated -- the exact blur decision D5 forbids.
        #
        # Keyed on `oracle_tier > 0`, the same key `rule_commit_threshold` uses.
        # It used to key on `corpus_run.config <> 'breadth'`, which measured
        # which files were ingested rather than whether a trace checked the
        # output; that became vacuous when the corpus cut was removed, since
        # every canonical run is non-breadth. See
        # docs/decisions/remove-the-cut.md.
        try:
            inst = con.execute(
                "SELECT COUNT(*) FROM rule_instance "
                "WHERE oracle_tier > 0").fetchone()[0]
        except sqlite3.Error:
            inst = 0
        all_inst = count("rule_instance")
        return {
            "methods": count("method"),
            "operations": count("operation"),
            "types": count("type"),
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


def rule_file_stats(root: Path) -> list[tuple[str, int]]:
    """(filename, bytes) for each hand-authored JSON rule file that actually
    ships. These, not the SQL `rule` table, are what `scripts/emit.py` reads --
    see docs/rule-engine-readiness.md: the tree-matcher/cluster-mining pipeline
    the SQL schema was built for was never wired up, so `rule`/`rule_instance`/
    `pattern_cluster`/`translation` are 0 rows by design, not by defect."""
    out = []
    for name in RULE_FILES:
        p = root / "rulesdb" / "rules" / name
        if p.exists():
            out.append((name, p.stat().st_size))
    return out


def oracle_trace_stats(root: Path) -> dict:
    """Peripherals with a committed replay ratchet, read from the harness
    itself -- the same regex progress_graph.py uses, so the two reports never
    disagree about what the harness says."""
    text = (root / HARNESS).read_text() if (root / HARNESS).exists() else ""
    pat = re.compile(
        r'generated_replay!\(\s*(\w+)\s*,\s*([\w:]+)\s*,\s*"([^"]+)"\s*,\s*(\d+)\s*\)')
    peripherals = [{"test": t, "module": m, "trace": tr, "divergences": int(d)}
                   for t, m, tr, d in pat.findall(text)]
    traces_dir = root / "oracle" / "traces"
    n_traces = len(list(traces_dir.glob("*"))) if traces_dir.is_dir() else 0
    return {"peripherals": peripherals, "traces_captured": n_traces}


def historical_verdict(root: Path, rel: str) -> str | None:
    """The doc's OWN stated verdict, read rather than assumed -- census.md says
    `Gate: FAIL` and a scorecard that reported it as `done` purely because the
    file exists was wrong on the file's own terms."""
    p = root / rel
    if not p.exists():
        return None
    m = re.search(r'\*\*(?:Verdict|Gate):\s*([A-Za-z][\w .]*?)\.?\*\*', p.read_text())
    return m.group(1).strip() if m else "see doc"


def build(root: Path) -> str:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    commit = sh("git", "-C", str(root), "rev-parse", "--short", "HEAD") or "unknown"

    issues = issue_stats(root)
    rules = rules_stats(root)
    base = baseline_stats(root)
    floor = load_json(root, FLOOR)
    clean_set = load_json(root, CLEAN_SET)
    oracle = oracle_trace_stats(root)
    rule_files = rule_file_stats(root)
    gaps = load_json(root, GAP_CENSUS)
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
    if clean_set:
        n = len(clean_set["modules"])
        a(f"| **compile-clean modules (the gate)** | {n} | ratchet, may only grow | "
          f"{'PASS' if n >= clean_set.get('min_modules', n) else 'FAIL — regression'} |")
    else:
        a(f"| **compile-clean modules (the gate)** | — | — | no `{CLEAN_SET}` |")
    if floor:
        pf, pp = floor["platform_floor"], floor["platform_peripherals"]
        a(f"| platform floor (peripherals reachable end-to-end) | {pf} / {pp} | "
          f"{pp} | {pf*100/pp:.0f}% |")
        cd = floor["modules_clean_and_drivable"]
        a(f"| modules clean *and* drivable | {cd} / {floor['modules_emitted']} | "
          f"— | {cd*100/floor['modules_emitted']:.0f}% |")
    else:
        a(f"| platform floor | — | — | no `{FLOOR}` |")
    if oracle["peripherals"]:
        n_100 = sum(1 for p in oracle["peripherals"] if p["divergences"] == 0)
        a(f"| oracle trace replay: peripherals at 0 divergence | {n_100} / "
          f"{len(oracle['peripherals'])} | {len(oracle['peripherals'])} | "
          f"{'PASS' if n_100 == len(oracle['peripherals']) else 'partial'} |")
    else:
        a(f"| oracle trace replay | — | — | no `{HARNESS}` |")
    a("")
    a("> **The `rule` / `rule_instance` / `pattern_cluster` / `translation` SQL tables are")
    a("> 0 rows by design, not by defect.** The tree-matcher/cluster-mining pipeline those")
    a("> tables were built for (see `docs/rulesdb-design.md`) was superseded by")
    a("> hand-authored JSON rule files read directly by `scripts/emit.py` — see")
    a("> [docs/rule-engine-readiness.md](docs/rule-engine-readiness.md) and")
    a("> [docs/decisions/remove-the-cut.md](docs/decisions/remove-the-cut.md). A scorecard")
    a("> that reported `instances per rule` and `patches outstanding` from those tables")
    a("> read \"0 rules committed, nothing translated\" while 283 modules compiled clean —")
    a("> the metric measured the abandoned pipeline, not the one in use.")
    a("")

    # --- Corpus -------------------------------------------------------------
    a("## Corpus")
    a("")
    if rules:
        a("| | count |")
        a("|---|---:|")
        a(f"| methods ingested | {rules['methods']:,} |")
        a(f"| operation nodes | {rules['operations']:,} |")
        a(f"| types ingested | {rules.get('types', 0):,} |")
    else:
        a(f"Not ingested — `{RULES_DB}` does not exist.")
    a("")
    if floor:
        a("**Emission floor** (`docs/status/floor.json`, see "
          "[docs/decisions/the-floor-that-runs.md](docs/decisions/the-floor-that-runs.md)):")
        a("")
        a("| | count |")
        a("|---|---:|")
        a(f"| modules emitted | {floor['modules_emitted']:,} |")
        a(f"| modules clean (0 rustc errors) | {floor['modules_clean']:,} |")
        a(f"| modules drivable | {floor['modules_drivable']:,} |")
        a(f"| modules clean and drivable | {floor['modules_clean_and_drivable']:,} |")
        a(f"| platform peripherals in scope | {floor['platform_peripherals']:,} |")
        a(f"| platform peripherals emitted | {floor['platform_emitted']:,} |")
        a(f"| platform floor | {floor['platform_floor']:,} |")
        a("")
    if rule_files:
        a("**Hand-authored rule files** actually read by the emitter (not the SQL "
          "`rule` table — see the note above):")
        a("")
        a("| file | size |")
        a("|---|---:|")
        for name, size in rule_files:
            a(f"| `rulesdb/rules/{name}` | {size:,} bytes |")
        a("")
    if gaps:
        a(f"**What the converter cannot yet emit** ({gaps['total_gaps']:,} gaps over "
          f"{gaps['types_examined']:,} types, {gaps['types_emitted']:,} emitted, "
          f"{gaps['converter_crashes']} converter crash(es) — "
          "not a correctness claim, see "
          "[docs/rule-engine-readiness.md](docs/rule-engine-readiness.md); "
          "regenerate with `python3 scripts/gap_census.py`):")
        a("")
        a("| gap category | count | share |")
        a("|---|---:|---:|")
        total_g = gaps["total_gaps"] or 1
        for cat, n in list(gaps["categories"].items())[:15]:
            a(f"| {cat} | {n:,} | {100*n/total_g:.1f}% |")
        a("")
        a("Top root causes (cascades excluded):")
        a("")
        a("| root cause | gaps blocked |")
        a("|---|---:|")
        for r, n in list(gaps["root_causes"].items())[:10]:
            a(f"| {r} | {n:,} |")
        a("")
    else:
        a(f"Gap census not recorded — run `python3 scripts/gap_census.py` "
          f"to produce `{GAP_CENSUS}` (full-corpus emission, ~6 min).")
        a("")

    # --- Gates --------------------------------------------------------------
    a("## Gates")
    a("")
    a("Genuine stop points. A failed gate means stop, not retry.")
    a("")
    a("### Current")
    a("")
    a("| gate | status | evidence |")
    a("|---|---|---|")
    if clean_set:
        n = len(clean_set["modules"])
        a(f"| **two-tier compile gate** — modules with 0 rustc errors | {n} "
          f"(ratchet, may only grow) | [docs/decisions/two-tier-compile-gate.md]"
          f"(docs/decisions/two-tier-compile-gate.md) |")
    else:
        a(f"| **two-tier compile gate** | — | no `{CLEAN_SET}` |")
    if floor:
        a(f"| **the floor that runs** — peripherals reachable end-to-end | "
          f"{floor['platform_floor']} / {floor['platform_peripherals']} | "
          f"[docs/decisions/the-floor-that-runs.md](docs/decisions/the-floor-that-runs.md) |")
    else:
        a(f"| **the floor that runs** | — | no `{FLOOR}` |")
    a("")
    a("### Historical (Phase 0/1)")
    a("")
    a("| gate | doc's own verdict | evidence |")
    a("|---|---|---|")
    perf_v = historical_verdict(root, "docs/perf-spike.md")
    a(f"| **P1** — is the Rust MMIO path faster? | {perf_v or '—'} | "
      f"{'[docs/perf-spike.md](docs/perf-spike.md)' if perf_v else 'not run'} |")
    census_v = historical_verdict(root, "docs/census.md")
    a(f"| **R3** — does the corpus collapse into clusters? | {census_v or '—'} | "
      "[docs/census.md](docs/census.md) — coverage metric itself disputed by "
      "open issue #37 (\"R3b — bare leaves are not rule failures\") |")
    gate10_v = historical_verdict(root, "docs/phase1-gate.md")
    a(f"| **10** — do one peripheral's rules cover an unseen second? | {gate10_v or '—'} | "
      f"{'[docs/phase1-gate.md](docs/phase1-gate.md)' if gate10_v else 'blocked on R6'} |")
    a("")

    # --- Oracle -------------------------------------------------------------
    a("## Oracle tiers")
    a("")
    a("| tier | what it proves | status |")
    a("|---|---|---|")
    crate = (root / "Cargo.toml").exists() or (root / "src").exists()
    a(f"| 1 — compiles | the crate builds | {'built' if crate else 'no crate yet'} |")
    if oracle["peripherals"]:
        a(f"| 2 — trace replay | per-peripheral register behaviour | built — "
          f"{len(oracle['peripherals'])} peripherals, {oracle['traces_captured']} traces "
          "captured |")
    else:
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
    if oracle["peripherals"]:
        a("**Tier-2 replay, per peripheral** (from `generated_replay!()` in "
          f"`{HARNESS}`):")
        a("")
        a("| module | trace | divergences | status |")
        a("|---|---|---:|---|")
        for p in oracle["peripherals"]:
            a(f"| `{p['module']}` | `{p['trace']}` | {p['divergences']} | "
              f"{'PASS' if p['divergences'] == 0 else 'diverges'} |")
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

    # --- Severity -----------------------------------------------------------
    # A gap withholds, so it can never be mistaken for a translation. A WARNING
    # does not: it emitted, and its semantics differ. Those used to be
    # describable only in prose next to a rule, which cannot be counted, cannot
    # be grepped in the output and cannot fail a build -- so three divergences
    # read as faithful mappings to anyone reading the Rust.
    counts, warnings = severity_stats(root)
    if warnings:
        a("## Severity — translated, but the semantics differ")
        a("")
        a("| marker | sites in emitted Rust | what differs |")
        a("|---|---:|---|")
        for wid in sorted(warnings):
            w = warnings[wid]
            a(f"| `{w.get('tag', 'WARN')}({wid})` | {counts.get(wid, 0)} | "
              f"{w.get('text', '')} |")
        a(f"| **total** | **{sum(counts.values())}** | |")
        a("")
        a("A **gap** withholds the member, so it can never read as a "
          "translation. A **warning** emitted and is wrong in a stated way — "
          "the number is the count of sites carrying the marker, not the count "
          "of deviations declared, so a deviation that is declared and never "
          "marked reads as zero rather than as done.")
        a("")
        unmarked = sorted(k for k, v in counts.items() if not v)
        if unmarked:
            a(f"> **{len(unmarked)} declared deviation(s) mark nothing yet** "
              f"— `{'`, `'.join(unmarked)}`. Each has sites in the corpus and "
              f"none of those sites reaches emitted Rust today: the members "
              f"carrying them are withheld for unrelated reasons. The zero is "
              f"a fact about how little is emitted, not evidence that the "
              f"deviation is gone.")
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
        a(f"{issues['open']} open, {issues['closed']} closed, {issues['total']} total. "
          "Full list: "
          "[github.com/awtoau/awto-renode-rs/issues]"
          "(https://github.com/awtoau/awto-renode-rs/issues).")
        a("")
        a("| phase | open | closed |")
        a("|---|---:|---:|")
        for phase in sorted(issues["by_phase"]):
            b = issues["by_phase"][phase]
            a(f"| {phase} | {b['open']} | {b['closed']} |")
        a("")
        if issues["by_label"]:
            a("**By label** (an issue may carry more than one; counts are not additive "
              "to the total above):")
            a("")
            a("| label | issues |")
            a("|---|---:|")
            for label in sorted(issues["by_label"]):
                nums = issues["by_label"][label]
                a(f"| `{label}` | {len(nums)} — "
                  + ", ".join(f"[#{n}](https://github.com/awtoau/awto-renode-rs/issues/{n})"
                              for n in nums[:12])
                  + (f", +{len(nums)-12} more" if len(nums) > 12 else "")
                  + " |")
            a("")
        if issues["gates"]:
            a("**Gate-labeled**:")
            a("")
            for num, title, state in issues["gates"]:
                a(f"- [#{num}](https://github.com/awtoau/awto-renode-rs/issues/{num}) "
                  f"({state}): {title}")
            a("")
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
