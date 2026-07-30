# renode-rs project rules

Load chain: this file → the global awto agent rules → embedded rules.

Read [PLAN.md](PLAN.md) before touching anything. The four declared deviations
(D1–D4) are whole-program decisions; do not make a per-file choice that
contradicts one, and do not silently revisit one — reopen the decision issue.

## This repo is PUBLIC

Two rules follow from that, and they are hard errors, not preferences.

### No absolute paths in tracked files

Enforced by `python3 scripts/check_paths.py` (exit 1 on violation, log to
`tmp/logs/check_paths.log`). Run it before every commit.

- **Docs** — reference repos by name (`awtoau/c2rust`) and files by
  *repo-relative* path (`src/Infrastructure/.../STM32_UART.cs`). Never an
  absolute path of any form — no mount roots, no home directories, no
  drive letters.
- **Scripts** — resolve this workspace with `git rev-parse --show-toplevel` or
  `Path(__file__).parents[N]`. Never hardcode a root.
- **External trees** — Renode, the firmware — come from environment variables
  documented in the tracked `.env.example` and set in a gitignored `.env`.

Note for VSCode: `${workspaceFolder}` is *variable substitution*, resolved only
in `tasks.json` / `launch.json` / `settings.json`. It is not an environment
variable and does not exist in the terminal. Injecting it via
`terminal.integrated.env.linux` works but breaks under ssh, CI and cron — so
scripts use git, not the editor.

### No private-work references

No names of private repos, products, customers, or hardware programs. The
firmware under test is "the target STM32F427 firmware". Keep it generic; the
technical content stands on its own without the provenance.

## Translation discipline

Faithful first, optimisation later — see PLAN.md. Specifically:

- The oracle certifies **equivalence, never improvement**. A "better" translation
  that diverges from C# Renode is a failed translation.
- Deviations are never silent. If Rust forces a difference, record it against the
  rule with a justification.
- **Every manual fix lands as a rule, not a file patch.** Re-deriving the same
  investigation per file is the failure mode the rule DB exists to prevent.
- Reproduce known Renode defects faithfully first (so the oracle passes), then
  fix them as recorded, justified deviations. Do not silently "improve" them
  during translation.

## Tooling

- Scripts → `scripts/<name>.py`, committed. No shell scripts.
- Logs → `tmp/logs/<name>.log`, stdout+stderr. `tmp/` is untracked.
- Renode must be run from a **source build**: the packaged binary swallows C#
  compilation errors, and `-P -1` turns a compile error into a silent hang.
