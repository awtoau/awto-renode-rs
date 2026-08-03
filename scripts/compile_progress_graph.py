#!/usr/bin/env python3
"""Plot the compile-clean-module gate across git history.

`docs/status/compile_clean_set.json` is the RATCHET (see
`docs/decisions/two-tier-compile-gate.md`): a module in the set must never
leave it, so the set's SIZE only grows or holds. Reading it at each commit
that touched it is cheap -- `git show <sha>:<path>` -- and needs no rebuild,
unlike the error TOTAL, which is a live `cargo build` measurement
(`compile_check.py`) with no historical record: it is explicitly "a trend, not
a gate" and was never committed per-commit, so it cannot be graphed
retroactively without rebuilding every past commit's full corpus output.

So this graph has one line, not three: clean-module count. The current error
total is annotated as a single live data point (today only), not a series.

Self-contained SVG, no plotting library, matching progress_graph.py.

Run:  python3 scripts/compile_progress_graph.py
Out:  ./docs/status/compile_progress.svg and .html -- TRACKED.
Log:  ./tmp/logs/compile_progress_graph.log
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

PATH = "docs/status/compile_clean_set.json"


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def series(log: logging.Logger) -> list[tuple[str, str, int]]:
    """(sha, subject, clean module count), oldest first, one point per commit
    that touched the file -- most commits in between don't move this number."""
    revs = git("log", "--reverse", "--format=%H\t%s", "--", PATH).strip().splitlines()
    out: list[tuple[str, str, int]] = []
    for line in revs:
        sha, _, subject = line.partition("\t")
        blob = git("show", f"{sha}:{PATH}")
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
    log.info("%d commit(s) touched %s", len(out), PATH)
    return out


def svg(points: list[tuple[str, str, int]]) -> str:
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
        f'<title>{p[0]}  {p[1][:70]}\n{p[2]} clean module(s)</title></circle>'
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
    root = repo_root()
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("compile_progress")
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(root / "tmp" / "logs" / "compile_progress_graph.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(h)

    pts = series(log)
    chart = svg(pts)
    (root / "docs" / "status" / "compile_progress.svg").write_text(chart)

    rows = "".join(
        f"<tr><td class=m>{p[0]}</td><td>{p[1][:78]}</td><td class=n>{p[2]}</td></tr>"
        for p in reversed(pts))
    (root / "docs" / "status" / "compile_progress.html").write_text(f"""<!doctype html>
<meta charset=utf-8><title>renode-rs compile-clean progress</title>
<style>
 body{{font:15px/1.55 system-ui,sans-serif;margin:2rem auto;max-width:1160px;padding:0 1rem}}
 table{{border-collapse:collapse;width:100%;margin-top:1.5rem}}
 th,td{{padding:.35rem .6rem;border-bottom:1px solid #8883;text-align:left}}
 .n{{text-align:right;font-variant-numeric:tabular-nums}}
 .m{{font-family:ui-monospace,monospace;opacity:.7}}
 @media(prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}}}
</style>
<h1>Compile-clean-module progress</h1>
<p>The two-tier compile gate's clean-module set
(<code>docs/status/compile_clean_set.json</code>), read at each commit that
changed it. This is a ratchet: it only grows. The error TOTAL is a live
measurement with no historical record -- see
<code>docs/decisions/two-tier-compile-gate.md</code> -- so it is not graphed
here as a series, only reported as today's snapshot below.</p>
{chart}
<table><tr><th>commit</th><th>subject</th><th class=n>clean modules</th></tr>
{rows}</table>""")

    log.info("")
    log.info("%-9s %-56s %6s", "commit", "subject", "clean")
    for p in pts:
        log.info("%-9s %-56s %6d", p[0], p[1][:56], p[2])
    log.info("")
    log.info("wrote docs/status/compile_progress.svg and docs/status/compile_progress.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
