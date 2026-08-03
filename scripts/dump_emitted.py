#!/usr/bin/env python3
"""Write every module the converter can emit to tmp/out/, for reading by eye.

The structural checks parse the emitted text; this dumps the same text so a
human can compare a module against the C# it came from. Nothing here is a
check -- it never exits non-zero on the content.

Run:  python3 scripts/dump_emitted.py
Log:  ./tmp/logs/dump_emitted.log
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))

from emitted_modules import emit_all, repo_root, setup_log  # noqa: E402


def main() -> int:
    log = setup_log("dump_emitted")
    root = repo_root()
    db = root / "rulesdb" / "patterns.db"
    if not db.exists():
        log.error("no corpus at rulesdb/patterns.db -- it is gitignored, so a "
                  "fresh worktree does not have one. Copy it in or re-ingest.")
        return 1
    out = root / "tmp" / "out"
    out.mkdir(parents=True, exist_ok=True)
    for mod in emit_all(db, log):
        (out / f"{mod.mod_name}.rs").write_text(mod.text)
        log.info("%-28s -> tmp/out/%s.rs", mod.type_name, mod.mod_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
