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

## Conversion rules

These are hard rules for the conversion pipeline. Full rationale and schema:
[docs/rulesdb-design.md](docs/rulesdb-design.md).

### Breadth is a health check, never a source of work

`--all` / `scripts/check_breadth.py` runs the ingest over the whole Renode tree
(~448k lines, ~50s). It exists to answer one question: **does the tooling crash
or lose data silently?** It is cheap enough to run routinely only because Renode
is small; the kernel corpus this method came from is 70x larger.

**It must never produce rules, clusters, coverage numbers, or work items.** The
deliverable is ~16k lines of F427 code. Breadth data would generate hundreds of
clusters from EFR32xG2, Xtensa and RISC-V peripherals that will never be
translated — polluting the rule DB, inflating coverage, and spending LLM budget
on patterns that are not the deliverable.

Enforced structurally: `--all` refuses to write `rulesdb/patterns.db` and tags
`corpus_run.config = 'breadth'`. The rule engine must reject any run so tagged.

A breadth failure is a **bug in our tooling**, not a fact about Renode. It found
one on its first run: 5,123 methods (24.7%) claimed a body while emitting no
operations, with zero exceptions thrown, because `partial void Foo();` is
neither abstract nor extern.

### Corpus before translation

- **The translator reads only from the corpus database.** No code path may read a
  `.cs` file directly. An unpopulated database therefore translates nothing —
  skipping ingestion is impossible, not merely discouraged.
- **Ingest the whole cut, never a hand-picked subset.** Cherry-picking is exactly
  what makes the leverage measurement unavailable.

### A rule is not a rule until it has three validated instances

- `rule.status` cannot reach `committed` while
  `COUNT(rule_instance) < min_instances_required` (default 3). Enforced in the
  tool, not in review.
- Below the threshold it is recorded as a **`patch`**. Patches are a
  CI-gated metric that must trend to zero. A file-specific hand edit is evidence
  the generic process is incomplete — record it as such, do not launder it.
- **Why zero patches actually matters**: rules are the source code, and the Rust
  is a build artifact. A hand-edited file is one that **will not regenerate** —
  so with 5% patched, a rule-set A/B moves only 95% of the codebase and the
  comparison is quietly contaminated. Patches are not process debt, they are
  holes in the ability to regenerate, and that ability is the main asset. A
  landed translation must be recreatable from the C# source plus committed rules
  and scripts alone.
- **The LLM is invoked once per unmatched *cluster*, never per function.** A
  per-function invocation path must not exist in the tool. This is the entire
  cost argument.
- Every rule carries `rule_negative` entries — shapes it must *not* match. A rule
  that over-matches is worse than one that under-matches, because the oracle may
  not catch it.

### The headline metric is instances-per-rule

Not files translated. A fall toward 1 means the process has drifted into
per-file work, and it must be visible the week it starts. `linux-rs` reached
1.87 while "38 TUs translated" still looked healthy.

### Parallelism is a design constraint

- **Every stage saturates all 31 threads, or carries a written reason why not.**
  Conversion is re-run constantly; its wall-clock is the iteration speed.
- **Output must be byte-identical at `-j1` and `-j31`.** CI enforces this by
  running both and diffing. Without it, every diff against the C# reference is
  noise and the oracle is worthless. So: no timestamps or paths in generated
  code, content-derived stable IDs, sort before writing, never depend on hash-map
  iteration order.
- **Emit a workspace of many small crates**, not one large crate — rustc
  parallelises across crates, barely within one.
- **Cache content-addressed** on `(subtree hash, rule-set hash)` so a rule change
  recomputes only what changed.
- The machine is heterogeneous (8 P-cores + 16 E-cores). Use work-stealing, not
  static partitioning.
- Forking Roslyn is a last resort and needs a recorded measurement first. Try
  bypassing `MSBuildWorkspace` (`CSharpCompilation.Create` directly) and caching
  the compilation before considering it.

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
