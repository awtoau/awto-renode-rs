#!/usr/bin/env python3
"""Re-apply phase labels from docs/issues-draft.md to existing GitHub issues.

`file_issues.py` only creates issues it has not seen. When the draft's phase
ordering changes, the labels on already-filed issues go stale. This script
reconciles them: for every issue whose title matches a draft heading, it removes
phase labels the draft no longer specifies and adds the ones it does.

Only `phase-*` labels are touched; other labels are left alone.

Run:  python3 scripts/sync_issue_labels.py [--dry-run]
Log:  ./tmp/logs/sync_issue_labels.log
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from file_issues import DRAFT, gh, parse, repo_root  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = repo_root()
    logdir = root / "tmp" / "logs"
    logdir.mkdir(parents=True, exist_ok=True)

    log = logging.getLogger("sync_issue_labels")
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(logdir / "sync_issue_labels.log"),
              logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)

    want = {
        f"{i['id']} — {i['title']}": {l for l in i["labels"] if l.startswith("phase-")}
        for i in parse((root / DRAFT).read_text(encoding="utf-8"))
    }

    live = json.loads(gh("issue", "list", "--state", "all", "--limit", "200",
                         "--json", "number,title,labels"))

    changed = 0
    for issue in live:
        target = want.get(issue["title"])
        if target is None:
            log.warning("no draft entry for issue #%d %r", issue["number"], issue["title"])
            continue
        have = {l["name"] for l in issue["labels"] if l["name"].startswith("phase-")}
        if have == target:
            continue
        add, remove = target - have, have - target
        log.info("#%d %s  +%s -%s", issue["number"], issue["title"],
                 ",".join(sorted(add)) or "-", ",".join(sorted(remove)) or "-")
        if args.dry_run:
            changed += 1
            continue
        cmd = ["issue", "edit", str(issue["number"])]
        for l in sorted(add):
            cmd += ["--add-label", l]
        for l in sorted(remove):
            cmd += ["--remove-label", l]
        gh(*cmd)
        changed += 1

    log.info("done: %d issue(s) relabelled%s", changed,
             " (dry run)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
