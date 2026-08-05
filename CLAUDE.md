# renode-rs project rules

Load chain: this file → the global awto agent rules → embedded rules.

Read [PLAN.md](PLAN.md) before touching anything. Four decisions are made once
for the whole program — shared objects are reference-counted and never freed; a
peripheral's register bits live in one flat array; one thread per emulator;
recoverable errors become return values. Do not make a per-file choice that
contradicts one, and do not silently revisit one — reopen the decision.

**Write in plain words.** The letter-codes this project started with (D1–D4, P1,
P2, R3, R6) went opaque within weeks, including to the person who wrote them. A
code is not a name. Say what a thing does; if an old label must appear, put it in
brackets as a redirect and never as the primary reference.

**These rules are provisional.** They are what the project thought it needed at
the start, and several describe machinery that no longer runs. Argue from
evidence — a measurement, or an incident this project actually had — not from
this file. Where a rule below is backed by something that happened, the incident
is stated with it; where it is an inherited assumption, it says so.

## Canonical development entry point

All supported operations go through `python3 scripts/dev.py`. Read
[README.md](README.md) for command examples or run
`python3 scripts/dev.py describe` for the machine-readable registry. Raw scripts
under `scripts/` are implementation details, not separate workflows.

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

**A generic bug is fixed at source.** **Ten** ingest gaps so far were properties
Roslyn already exposed and the walker did not read — `OperatorKind`,
`IArgumentOperation.Parameter`, `PartialImplementationPart`,
`OriginalDefinition`, `IFieldInitializerOperation`,
`IParameterSymbol.ExplicitDefaultValue`, and four more. **None was a Roslyn
limitation.** Each fix belongs in `Walker.cs`, and each is recorded in
`csharp_core.json` under `known_transpiler_bugs_fixed` — count them there rather
than trusting this sentence, which has been stale twice.

Two of the ten are worth knowing as a class: a field initialiser was absent
entirely, so `private bool x = true;` was indistinguishable from
`private bool x;` — silently inverting the value. And the last attempt to fix
it appeared to fail, because the re-ingest ran `--no-build` and measured the old
binary. **When an ingest change seems not to reproduce, check the build first.**

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

### Emitting is not validating; the oracle is the only judge

**The corpus is the whole Renode tree.** ~448k lines, ~1,708 files, ~55s to
re-ingest, 308 MB. There is no file list to maintain.

**A wider corpus is a discovery instrument, not a confidence one.**

> A rule that EMITS a thousand times has been shown to produce plausible output
> a thousand times. It has never been shown to produce right output.

That is exactly how the invented `.with_reserved(9, 23)` survived a
33,000-access trace: behaviourally inert wrong code is invisible to tests. The
oracle is trace replay, and it reaches the peripherals that have recorded
traces — 8 of them — not the corpus.

**And nothing else has ever been run.** 283 modules compile clean; outside those
8 peripherals, not one has been executed and compared against anything. Compiling
is not running, and running is not matching.

> **The tier machinery described below does not run.** `rule`, `rule_instance`,
> `rule_match`, `rule_negative`, `pattern_cluster` and `translation` are all **0
> rows**. Hand-authored JSON rule files read directly by `scripts/core/csharp_emitter.py`
> replaced that pipeline. The triggers in `rulesdb/schema.sql` are real code that
> currently guards nothing, and the two-tier guarantee is not in force. Kept here
> as a design worth reviving or deleting on purpose — not as a description of
> today.

The design was **two validated tiers**, enforced by triggers rather than review:
`general` at ≥3 instances anywhere in the corpus (emits on real code, correctness
unknown), `committed` at ≥3 instances a trace actually checked.

The idea that survives regardless of the mechanism: **never report "emitted" as
if it meant "validated"**. Blur those and the headline number becomes a measure
of how much was produced rather than how much works.

**A bigger corpus means more gaps, and that is correct.** The converter always
could not emit those constructs; it was simply never asked. Do not "fix" a gap
count by emitting something plausible.

**`--all` declares a run's PURPOSE, not its scope** — every run reads every
file. It marks a tooling health check (`scripts/check_breadth.py`) whose output
goes to a scratch database tagged `config = 'breadth'` and is refused by every
rule/cluster consumer. That check earns its place: it found 5,123 methods
(24.7%) claiming a body while emitting no operations, with zero exceptions
thrown, because `partial void Foo();` is neither abstract nor extern.

### Corpus before translation

- **The translator reads only from the corpus database.** No code path may read a
  `.cs` file directly. An unpopulated database therefore translates nothing —
  skipping ingestion is impossible, not merely discouraged.
- **Ingest the whole tree, never a hand-picked subset.** Cherry-picking is exactly
  what makes the leverage measurement unavailable — and the hand-picked subset
  that used to be permitted is the one this rule now forbids.

### Hand edits destroy the ability to regenerate

This one is not inherited — it is the point of the whole exercise.

Rules are the source code and the Rust is a build artifact. A hand-edited file is
one that **will not regenerate**, so at 5% hand-edited a rule-set A/B moves only
95% of the codebase and the comparison is quietly contaminated. Hand edits are
not process debt, they are holes in the main asset. A landed translation must be
recreatable from the C# source plus committed rules and scripts alone.

A rule should also record the shapes it must *not* match. A rule that
over-matches is worse than one that under-matches, because nothing may catch it.

### Inherited from linux-rs, and not currently measured

Recorded so they are revisited deliberately rather than half-followed:

- **Three validated instances before a rule counts.** The threshold was borrowed,
  never tested here, and the table it was enforced in has 0 rows.
- **Instances-per-rule as the headline metric.** `linux-rs` reached 1.87 while
  "38 TUs translated" still looked healthy, which is a real warning — but with no
  rule rows the number does not exist here, and the scorecard says so.
- **The LLM is invoked once per unmatched cluster, never per function.** This was
  the entire cost argument, and it depended on the clustering that was abandoned.
  Whatever replaces it needs its own cost argument.

### What is actually blocking the converter is mostly C#, not Renode

Of the 4,714 gaps with a named root cause, **69% are the plain C# language and
base class library** — static calls, `throw`, default values, `using`, `decimal`
— and 31% are Renode's own types. Measured by
`scripts/analysis/classify_gaps.py`.

Both are found the same way, by a peripheral failing to emit, and both are
confirmed fixed the same way, by that peripheral emitting again. So the cheap,
generic class is being debugged through the slowest loop available. See
[docs/decisions/csharp-and-renode-are-two-problems.md](docs/decisions/csharp-and-renode-are-two-problems.md).

### Parallelism is a design constraint

- **Every parallel stage uses at least 32 workers, or carries a written reason why not.**
  Conversion is re-run constantly; its wall-clock is the iteration speed.
- **Output must be byte-identical at `-j1` and `-j32`.** CI enforces this by
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
