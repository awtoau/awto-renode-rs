#!/usr/bin/env python3
"""Rewrite every generated file from the converter. The only way to change one.

`scripts/check_generated.py` says a listed file must be byte-identical to
converter output; it does not say how to make it so, and every agent that has
needed to has invented its own shell loop. That is a second source of truth for
the argv of each file, and it drifted at least once -- a file regenerated with a
different `--method` than the check uses looks hand-edited to the check and
correct to the person who wrote it.

So the list is IMPORTED, never retyped. Adding a file to `check_generated.py`
adds it here with no edit.

Run:  python3 scripts/regenerate.py            # rewrite them all
      python3 scripts/regenerate.py --dry-run  # say what would change
Log:  ./tmp/logs/regenerate.log
Exit: 0 always unless a generator failed, in which case nothing is written for
      that file -- a crash is not output, and overwriting a good file with a
      stack trace is worse than leaving it stale.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))
from check_generated import GENERATED  # noqa: E402


def repo_root() -> Path:
    return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True,
                               check=True).stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("regenerate")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "regenerate.log", mode="w"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    failed = 0
    changed = 0
    for rel, argv in GENERATED:
        r = subprocess.run([sys.executable, *argv], cwd=root,
                           capture_output=True, text=True)
        if r.returncode != 0:
            log.error("%s: generator exited %d -- NOT written: %s",
                      rel, r.returncode, r.stderr.strip()[:300])
            failed += 1
            continue
        path = root / rel
        old = path.read_text() if path.exists() else None
        if old == r.stdout:
            log.info("unchanged  %s", rel)
            continue
        changed += 1
        if args.dry_run:
            log.info("WOULD CHANGE  %s", rel)
            continue
        path.write_text(r.stdout)
        log.info("wrote      %s", rel)

    log.info("%d file(s) %s, %d unchanged, %d generator failure(s)",
             changed, "would change" if args.dry_run else "written",
             len(GENERATED) - changed - failed, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
