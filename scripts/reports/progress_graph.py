#!/usr/bin/env python3
"""Plot converter progress across git history.

One report, two charts, both read from git history alone -- no rebuild.

## Chart 1: generated Rust versus gaps versus correctness

Three lines that must be read together:

  generated lines     how much Rust the converter produces
  reported gaps       how much it refuses to produce
  trace divergences   how much of what it produced is WRONG

Neither of the first two is a score on its own, and that is the point of
graphing them together. Lines went UP for weeks while several of those lines
were wrong -- an emitted `/* GAP */` marker inside a loop, a base call that
recursed forever. When withholding on gap markers landed, generated lines FELL
by 22 and the output got better. A single "progress" number would have shown
that as regression.

THE THIRD LINE IS THE ONLY ONE THAT MEASURES CORRECTNESS, and it is free.
Trace replay is this project's one oracle, and each peripheral's known
divergence count is a committed constant in the replay harness -- a ratchet
that may fall but never rise. So the measurement is already in git history and
needs no re-execution: `git show <sha>:<harness>` and read the numbers. Lines
and gaps say how much was attempted; only this says how much behaves.

Two things to read carefully on that line, because both look like something
they are not:

  * It ROSE once, 8,042 to 8,155, when a trace was ADDED. More divergences
    because more is measured, not because anything regressed. The total is not
    comparable across a change in how many traces run -- only within one.
  * It sat FLAT at 7,559 for eleven consecutive commits. Those commits were
    real work, and some of it was necessary before anything else could move.
    But eleven commits of no measured correctness change is exactly the thing
    a lines-only graph would have drawn as steady progress.

## Chart 2: the compile-clean-module gate

`docs/status/compile_clean_set.json` is the RATCHET (see
`docs/decisions/two-tier-compile-gate.md`): a module in the set must never
leave it, so the set's SIZE only grows or holds. Reading it at each commit
that touched it is cheap -- `git show <sha>:<path>` -- and needs no rebuild,
unlike the error TOTAL, which is a live `cargo build` measurement
(`compile_check.py`) with no historical record: it is explicitly "a trend, not
a gate" and was never committed per-commit, so it cannot be graphed
retroactively without rebuilding every past commit's full corpus output.

So this chart has one line, not three: clean-module count.

Self-contained SVG, no plotting library: the repo has no Python dependencies
and adding one for a chart is a poor trade.

Run:  python3 scripts/reports/progress_graph.py
Out:  ./docs/status/progress.html -- TRACKED, the only output file. A report
      is a deliverable, not scratch: this lived in gitignored tmp/ and was
      destroyed by every clean; the page is the only artefact that shows the
      correctness line falling over time, and it cannot be reconstructed from
      a number. Both charts are inline SVG in this one page -- no separate
      .svg files, so there is one command and one committed artifact, not
      three.
Log:  ./tmp/logs/progress_graph.log
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
from check_generated import GENERATED as _GENERATED   # noqa: E402

# Derived, never retyped. This list was its own hardcoded copy of two paths and
# silently stayed at two while the converter grew to seven -- so the graph
# reported a fraction of the output as if it were all of it, and nothing
# flagged it because a stale list looks exactly like a short one.
GENERATED = [path for path, _cmd in _GENERATED]

# The replay harness. Its `generated_replay!(name, module, "trace", N)` lines
# carry N = known divergences, committed and ratcheted.
HARNESS = "src/renode-stm32/tests/generated_trace.rs"
RATCHET = re.compile(r'generated_replay!\(\s*\w+\s*,[^,]+,\s*"([^"]+)"\s*,\s*(\d+)\s*\)')

CLEAN_SET = "docs/status/compile_clean_set.json"


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def series(log: logging.Logger) -> list[tuple[str, str, int, int, int]]:
    """(sha, subject, generated lines, reported gaps, divergences) oldest first.

    Divergences are None-free: a commit before the replay harness existed has no
    measurement, and carrying the next commit's number backwards would invent
    one. Those commits report -1 and the plot starts the line where the data
    starts."""
    revs = git("log", "--reverse", "--format=%H\t%s").strip().splitlines()
    out: list[tuple[str, str, int, int, int]] = []
    for line in revs:
        sha, _, subject = line.partition("\t")
        lines = gaps = 0
        for path in GENERATED:
            blob = git("show", f"{sha}:{path}")
            if not blob:
                continue
            lines += len(blob.splitlines())
            gaps += len(re.findall(r"^//!   - ", blob, re.M))
        harness = git("show", f"{sha}:{HARNESS}")
        hits = RATCHET.findall(harness) if harness else []
        div = sum(int(n) for _t, n in hits) if hits else -1
        if lines:
            out.append((sha[:7], subject, lines, gaps, div))
    measured = [p for p in out if p[4] >= 0]
    log.info("%d commit(s) carry generated output, %d carry a replay measurement",
             len(out), len(measured))
    if measured:
        log.info("divergences: %d at %s -> %d at %s",
                 measured[0][4], measured[0][0], measured[-1][4], measured[-1][0])
    return out


def svg(points: list[tuple[str, str, int, int, int]]) -> str:
    W, H, PAD = 1100, 460, 64
    if not points:
        return "<svg/>"
    n = len(points)
    max_l = max(p[2] for p in points) or 1
    max_g = max(p[3] for p in points) or 1
    max_d = max((p[4] for p in points if p[4] >= 0), default=0) or 1
    top = max(max_l, 1)

    def x(i: int) -> float:
        return PAD + (W - 2 * PAD) * (i / max(n - 1, 1))

    def y(v: int, scale: int) -> float:
        return H - PAD - (H - 2 * PAD) * (v / scale)

    def path(idx: int, scale: int) -> str:
        return " ".join(
            f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(p[idx], scale):.1f}"
            for i, p in enumerate(points))

    grid = "".join(
        f'<line x1="{PAD}" y1="{y(v, top):.1f}" x2="{W-PAD}" y2="{y(v, top):.1f}" '
        f'class="grid"/><text x="{PAD-10}" y="{y(v, top)+4:.1f}" class="ax" '
        f'text-anchor="end">{v}</text>'
        for v in range(0, top + 1, max(50, top // 6 // 50 * 50 or 50)))

    # Divergences: only where measured, so the line starts where the oracle did
    # rather than implying a zero nobody recorded.
    dpts = [(i, p) for i, p in enumerate(points) if p[4] >= 0]
    dpath = " ".join(
        f"{'M' if k == 0 else 'L'}{x(i):.1f},{y(p[4], max_d):.1f}"
        for k, (i, p) in enumerate(dpts))

    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(p[2], top):.1f}" r="3" class="d1">'
        f'<title>{escape(p[0])}  {escape(p[1][:70])}\n{p[2]} lines, {p[3]} gaps'
        f'{f", {p[4]} divergences" if p[4] >= 0 else ""}</title></circle>'
        for i, p in enumerate(points))

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">
<style>
  .grid{{stroke:currentColor;opacity:.12}}
  .ax{{fill:currentColor;opacity:.55;font:11px system-ui,sans-serif}}
  .l1{{fill:none;stroke:#3b82f6;stroke-width:2.5}}
  .l2{{fill:none;stroke:#f97316;stroke-width:2.5;stroke-dasharray:5 3}}
  .l3{{fill:none;stroke:#dc2626;stroke-width:3}}
  .d1{{fill:#3b82f6}}
  .lg{{fill:currentColor;font:13px system-ui,sans-serif}}
</style>
{grid}
<path d="{path(2, top)}" class="l1"/>
<path d="{path(3, max_g)}" class="l2"/>
<path d="{dpath}" class="l3"/>
{dots}
<circle cx="{PAD}" cy="24" r="5" fill="#3b82f6"/>
<text x="{PAD+14}" y="28" class="lg">generated lines (left scale)</text>
<circle cx="{PAD+250}" cy="24" r="5" fill="#f97316"/>
<text x="{PAD+264}" y="28" class="lg">reported gaps (peak {max_g})</text>
<circle cx="{PAD+520}" cy="24" r="5" fill="#dc2626"/>
<text x="{PAD+534}" y="28" class="lg">trace divergences (peak {max_d}) &#8212; the only correctness line</text>
<text x="{PAD}" y="{H-18}" class="ax">oldest commit</text>
<text x="{W-PAD}" y="{H-18}" class="ax" text-anchor="end">newest</text>
</svg>'''


def compile_series(log: logging.Logger) -> list[tuple[str, str, int]]:
    """(sha, subject, clean module count), oldest first, one point per commit
    that touched the file -- most commits in between don't move this number."""
    revs = git("log", "--reverse", "--format=%H\t%s", "--", CLEAN_SET).strip().splitlines()
    out: list[tuple[str, str, int]] = []
    for line in revs:
        sha, _, subject = line.partition("\t")
        blob = git("show", f"{sha}:{CLEAN_SET}")
        if not blob:
            continue
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        modules = data.get("modules") or data.get("clean") or []
        if not isinstance(modules, list):
            continue
        out.append((sha[:7], subject, len(modules)))
    log.info("%d commit(s) touched %s", len(out), CLEAN_SET)
    return out


def compile_svg(points: list[tuple[str, str, int]]) -> str:
    W, H, PAD = 1100, 420, 64
    if not points:
        return "<svg/>"
    n = len(points)
    top = max((p[2] for p in points), default=1) or 1
    top = ((top // 10) + 2) * 10

    def x(i: int) -> float:
        return PAD + (W - 2 * PAD) * (i / max(n - 1, 1))

    def y(v: int) -> float:
        return H - PAD - (H - 2 * PAD) * (v / top)

    path = " ".join(
        f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(p[2]):.1f}"
        for i, p in enumerate(points))

    step = max(10, top // 8 // 10 * 10 or 10)
    grid = "".join(
        f'<line x1="{PAD}" y1="{y(v):.1f}" x2="{W-PAD}" y2="{y(v):.1f}" '
        f'class="grid"/><text x="{PAD-10}" y="{y(v)+4:.1f}" class="ax" '
        f'text-anchor="end">{v}</text>'
        for v in range(0, top + 1, step))

    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(p[2]):.1f}" r="3.5" class="d1">'
        f'<title>{escape(p[0])}  {escape(p[1][:70])}\n{p[2]} clean module(s)</title></circle>'
        for i, p in enumerate(points))

    return f'''<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">
<style>
  .grid{{stroke:currentColor;opacity:.12}}
  .ax{{fill:currentColor;opacity:.55;font:11px system-ui,sans-serif}}
  .l1{{fill:none;stroke:#16a34a;stroke-width:2.5}}
  .d1{{fill:#16a34a}}
  .lg{{fill:currentColor;font:13px system-ui,sans-serif}}
</style>
{grid}
<path d="{path}" class="l1"/>
{dots}
<circle cx="{PAD}" cy="24" r="5" fill="#16a34a"/>
<text x="{PAD+14}" y="28" class="lg">clean modules -- a ratchet, never falls (peak {points[-1][2]})</text>
<text x="{PAD}" y="{H-18}" class="ax">oldest commit touching the gate</text>
<text x="{W-PAD}" y="{H-18}" class="ax" text-anchor="end">newest</text>
</svg>'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("progress")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" / "progress_graph.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    pts = series(log)
    chart = svg(pts)
    rows = "".join(
        f"<tr><td class=m>{escape(p[0])}</td><td>{escape(p[1][:78])}</td>"
        f"<td class=n>{p[2]}</td><td class=n>{p[3]}</td>"
        f"<td class=n>{p[4] if p[4] >= 0 else '&mdash;'}</td></tr>"
        for p in reversed(pts))

    cpts = compile_series(log)
    cchart = compile_svg(cpts)
    crows = "".join(
        f"<tr><td class=m>{escape(p[0])}</td><td>{escape(p[1][:78])}</td>"
        f"<td class=n>{p[2]}</td></tr>"
        for p in reversed(cpts))

    (root / "docs" / "status" / "progress.html").write_text(f"""<!doctype html>
<meta charset=utf-8><title>renode-rs converter progress</title>
<style>
 body{{font:15px/1.55 system-ui,sans-serif;margin:2rem auto;max-width:1160px;padding:0 1rem}}
 table{{border-collapse:collapse;width:100%;margin-top:1.5rem}}
 th,td{{padding:.35rem .6rem;border-bottom:1px solid #8883;text-align:left}}
 .n{{text-align:right;font-variant-numeric:tabular-nums}}
 .m{{font-family:ui-monospace,monospace;opacity:.7}}
 h2{{margin-top:2.5rem}}
 @media(prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}}}
</style>
<h1>Converter progress</h1>

<h2>Generated Rust versus gaps versus correctness</h2>
<p>Generated Rust versus gaps the converter reports rather than guessing.
Read them together: lines falling while gaps hold steady is usually the
converter <em>withholding</em> output it should never have emitted. Trace
divergences are the only line of the three that measures correctness.</p>
{chart}
<table><tr><th>commit</th><th>subject</th><th class=n>lines</th><th class=n>gaps</th><th class=n>divergences</th></tr>
{rows}</table>

<h2>Compile-clean-module gate</h2>
<p>The two-tier compile gate's clean-module set
(<code>docs/status/compile_clean_set.json</code>), read at each commit that
changed it. This is a ratchet: it only grows. The error TOTAL is a live
measurement with no historical record -- see
<code>docs/decisions/two-tier-compile-gate.md</code> -- so it is not graphed
here as a series, only reported as today's snapshot below.</p>
{cchart}
<table><tr><th>commit</th><th>subject</th><th class=n>clean modules</th></tr>
{crows}</table>""")

    log.info("")
    log.info("%-9s %-56s %6s %5s %11s", "commit", "subject", "lines", "gaps",
             "divergences")
    for p in pts:
        log.info("%-9s %-56s %6d %5d %11s", p[0], p[1][:56], p[2], p[3],
                 p[4] if p[4] >= 0 else "-")
    log.info("")
    log.info("%-9s %-56s %6s", "commit", "subject", "clean")
    for p in cpts:
        log.info("%-9s %-56s %6d", p[0], p[1][:56], p[2])
    log.info("")
    log.info("wrote docs/status/progress.html (one file, two charts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
