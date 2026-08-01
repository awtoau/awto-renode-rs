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

### No second source of truth

Enforced by `python3 scripts/check_derived.py` (pre-commit, hard failure).

Platform configuration lives in the `.repl`. `scripts/parse_repl.py` derives
`docs/status/platform.json` and the generated `src/renode-stm32/src/platform.rs`
from it; everything else **reads** those. Retyping a reset value or a peripheral
list into a test creates a copy that drifts silently — change the platform and
the test keeps asserting the old value *while passing*.

This is a different failure class from absolute paths, and the path check does
not catch it. It went unnoticed until review.

Not everything that looks like configuration is: the UART's 8 MHz is the C#
constructor default and the `.repl` never overrides it, so it belongs to the
source. It is named `DEFAULT_FREQUENCY` with that reasoning recorded, rather
than wrongly derived.

### No private-work references

No names of private repos, products, customers, or hardware programs. The
firmware under test is "the target STM32F427 firmware". Keep it generic; the
technical content stands on its own without the provenance.

## Three layers, and where a fix belongs

Getting this wrong is how the converter ends up with the corpus baked into it.

| what | where it lives | why |
|---|---|---|
| **Extraction** — reading what Roslyn exposes | transpiler SOURCE (`Walker.cs`) | Mechanism, not knowledge. A bug here is a transpiler bug: fix it once at source and every corpus benefits. This is the c2rust model — generic C-to-Rust bugs are fixed in c2rust, not worked around per project. |
| **Language mapping** — `ConditionalOr` → `\|\|`, overflow semantics | DATA, `rulesdb/rules/csharp_core.json` | Knowledge, but generic to C# and Rust. Belongs in data so it is reviewable and changeable without touching code, and reusable on any corpus. |
| **Project idioms** — the register DSL, peripheral shapes | DATA, `rulesdb/rules/*.json` | Knowledge, Renode-only. |

**A generic bug is fixed at source.** Six ingest gaps so far were properties
Roslyn already exposed and the walker did not read — `OperatorKind`,
`IArgumentOperation.Parameter`, `PartialImplementationPart`,
`OriginalDefinition`, and two more. **None were Roslyn limitations.** Each fix
belongs in `Walker.cs`, and each is recorded in `csharp_core.json` under
`known_transpiler_bugs_fixed` so the class of mistake is visible.

**Nothing project-specific may reach the source.** `csharp_core.json` must not
mention Renode, a peripheral or a register; if a mapping needs project
knowledge it is a project rule. That boundary is what keeps the transpiler
reusable and the project rules small.

Run `dotnet run -- --audit` in `frontend/RenodeIngest` to list what Roslyn
exposes per operation kind, so gaps are enumerable rather than discovered by
tripping over them.

## The one rule that matters

**BUILD THE CONVERTER. DO NOT WRITE THE OUTPUT BY HAND.**

The deliverable is a general C#-to-Rust converter driven by the corpus database.
It must work on any corpus. It is never a per-peripheral special case, and a
"rule" that only ever matches one site is a hand-written file wearing a rule's
name.

When asked to "translate `<peripheral>`", the task is **to make the converter
able to produce it**, not to produce it. If the converter cannot yet emit some
construct, the correct output is a gap the converter reports — never a
hand-written stand-in that looks finished.

### Why this is stated this bluntly

It has already gone wrong here, and quietly. Both peripherals were hand-written,
described as translations in three commit messages, and passed their traces and
mutation testing. Regenerating and diffing then found:

- `.with_reserved(9, 23)` in `uart.rs` that **the C# does not contain** —
  invented, and behaviourally inert, so no test could see it
- a dummy `ValueId::default()` handle where the C# has a computed field with no
  storage — the generated version is *more faithful* than the hand-written one
- four renamed fields, making the file unreproducible without a per-file rename
  table

PLAN.md already said "recreatable from the C# source plus committed rules and
scripts alone". Saying it was not enough, so it is now checked.

### Enforced

- `scripts/check_generated.py` (pre-commit, hard failure): a file listed as
  generated must be byte-identical to converter output. Hand-editing one fails
  the commit.
- `scripts/verify_emit.py`: diffs a hand-written peripheral against what the
  converter produces, and names every difference as either an emitter gap or a
  hand edit that should not exist.
- Anything not yet reproducible is recorded as a **patch** and counted on the
  scorecard. The target is zero.

## Conversion rules

These are hard rules for the conversion pipeline. Full rationale and schema:
[docs/rulesdb-design.md](docs/rulesdb-design.md).

### Breadth discovers; only the cut validates

*Amended. The original rule said breadth "must never produce rules, clusters,
coverage numbers, or work items" — written when the deliverable was ~16k lines
of F427 code. The deliverable is now a general C#-to-Rust transpiler, and that
changes what breadth is for. Reasoning recorded on the decision issue; do not
re-litigate it here.*

`--all` runs the ingest over the whole Renode tree (~448k lines, ~57s, 308 MB).
It answers two questions now.

**1. Does the tooling crash or lose data silently?** A breadth failure is a
**bug in our tooling**, not a fact about Renode. It found one on its first run:
5,123 methods (24.7%) claimed a body while emitting no operations, with zero
exceptions thrown, because `partial void Foo();` is neither abstract nor extern.

**2. What C# exists that the cut cannot show us?** The tree is 22x the code but
only 1.3x the operation kinds (71 → 90) — and those 19 extra kinds are
`SwitchExpression`, `RelationalPattern`, `Await`, `Tuple`,
`DeconstructionAssignment` and friends. Modern C# that any real transpiler must
handle and that the cut would never reveal. The BCL surface is 4.6x larger
(531 → 2,420 members). For **discovery**, and for **negative examples** showing
where a rule over-matches, breadth is the best source we have.

**What breadth still may not do: claim correctness.**

> Breadth can prove a rule EMITS. It can never prove the output is RIGHT.

The oracle is trace replay, and traces exist only for the cut. A rule matched a
thousand times across the tree has produced *plausible* output a thousand times
— which is exactly how the invented `.with_reserved(9, 23)` survived a
33,000-access trace: behaviourally inert wrong code is invisible.

So the rule DB has **two validated tiers**, enforced by triggers in
`rulesdb/schema.sql`, not by review:

| tier | threshold | guarantee |
|---|---|---|
| `general` | ≥3 instances **anywhere**, breadth included | emits on real code; correctness unknown |
| `committed` | ≥3 instances **in the cut**, each oracle-backed | the output is right |

`rule_commit_threshold` counts only instances whose `corpus_run.config <>
'breadth'`, so breadth cannot manufacture confidence it has no way to supply.

**Metrics report the tiers separately.** Coverage and instances-per-rule mean
"validated", never "emitted". Blur the two and the headline metric quietly
becomes a measure of how much we produced rather than how much works — which is
the failure the original rule was guarding against, and the part of it that
still stands.

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
