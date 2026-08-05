# Review: the database-first transpiler platform proposal

Reviewed 2026-08-05/06. This is the **second** analysis of that document. The
first one was wrong in places, and the corrections are the interesting part, so
both verdicts are recorded rather than only the surviving one.

The proposal describes a database-first, multi-pass C#→Rust transpiler platform:
ingest before transpiling, explicit named passes, non-blocking progress, partial
compilable output, an annotated intermediate representation, a marker and
diagnostic system, PostgreSQL, a centralised data-access layer, and the official
Microsoft C# tests as a first external corpus.

## Why it was written

Not as an architecture exercise. It came from asking **why the migration is
taking so long**, with the hypothesis that Renode's complexity has been slowing
the transpiler down because C# problems and Renode problems had become the same
problem.

That hypothesis is correct, it is now measured, and it changes the review.

## The measurement that changed the verdict

`scripts/analysis/classify_gaps.py`, over the gap census. Of the 4,714 gaps with
a named root cause:

| | gaps | share |
|---|---:|---:|
| plain C# — the language and base class library | 3,273 | **69%** |
| Renode's own types and base classes | 1,441 | 31% |

See [docs/decisions/csharp-and-renode-are-two-problems.md](decisions/csharp-and-renode-are-two-problems.md).

## The finding this review turns on

The rules are already layered, and the layering is enforced at commit time by
`scripts/validation/check_layering.py`: the generic C# layer
(`scripts/emitter/lang/**`, `rulesdb/rules/csharp_core.json`) may not name a
Renode construct, and the commit fails if it does.

But that boundary is enforced **textually and not behaviourally**.

> `csharp_core.json` is policed for what it may *say*. It is validated only by
> whether Renode peripherals still compile.

A language rule can be changed however one likes, and the only thing that will
object is Renode. So 69 KB of generic language mappings are governed by the
corpus they are supposed to be independent of — and there is no way to tell a
C# regression from a Renode regression, because there is only one signal.

That is the mechanism behind the original complaint, and it is a *validation*
defect, not a rules-organisation defect.

## Second verdict, item by item

Changed since the first pass:

| item | first verdict | now | why it moved |
|---|---|---|---|
| Microsoft C# tests as an external corpus | scope expansion, defer | **adopt — highest-value item in the document** | It is the missing oracle for the language layer, which has none. The document proposed it for breadth; its real value is correctness. |
| Ownership / lifetime / GC-requirement inference passes | rejected — relitigates settled whole-program decisions | **withdrawn** | Those decisions are recorded as reversible defaults, and the object-graph successor is already named as later work. Rejecting the idea on authority was wrong. |
| Marker namespace (`C2R-*`) | rejected — churn | **still rejected, but on weaker grounds** | Existing markers carry a distinction the proposal's do not (withheld vs emitted-and-wrong). Naming preference, not a principle. |

Unchanged:

| item | verdict |
|---|---|
| Database-first ingestion | already done, and stricter here — no code path may read a `.cs` file |
| Non-blocking progress, partial output | already done as the gap system: 26,084 gaps, 0 converter crashes |
| Incremental rebuilds, caching, parallelism | already required, plus a constraint the proposal lacks: byte-identical output at 1 and 32 workers |
| PostgreSQL | not justified by a measured problem; the workload is read-heavy fan-out over an immutable snapshot |
| Migrating the database (its §6) | **category error** — the database regenerates from source in about a minute. There is nothing to migrate; the rebuild is the migration |
| Annotated intermediate C# as a stored artifact | mostly redundant — the corpus database already is the annotated representation, and queryable. Viable only as a regenerated read-only view that no pass reads back |
| Acceptance criteria | **the document's central flaw, unchanged** — sixteen criteria about documenting, ingesting, caching, timing and compiling, and not one about behaving the same as the C# |

## On that last point, with numbers

283 modules compile clean. Outside the 8 peripherals with recorded traces,
**none of them has ever been executed**. Compiling is not running, and running is
not matching.

Judged by the proposal's acceptance criteria this project is nearly finished.
Judged by behaviour it is 3 of 8 peripherals at zero divergence and one file
actually produced by the converter. An invented `.with_reserved(9, 23)` once
survived a 33,164-access trace and mutation testing because behaviourally inert
wrong code is invisible to every check of that kind.

## What is adopted

1. **A conformance harness for the language layer, independent of Renode.**
   `dotnet/runtime` `src/tests` are self-contained programs whose verdict is an
   `int` — `[Fact] static int TestEntryPoint()` returning 100 for pass, 101 for
   fail. Call it on both sides and compare two integers: no `Console`, no
   `string`, no xunit runner, no firmware, no traces. The C# runtime is the
   reference, so no expectations are written by hand.

2. **A ratchet on that harness.** Changing `csharp_core.json` or
   `scripts/emitter/lang/**` re-runs the suite, and the number of tests agreeing
   may only grow — the same shape as the existing compile-clean ratchet. This is
   what makes the layer boundary mean something.

3. **Corpus separation.** A second corpus needs its own database and an explicit
   selection. Today `scripts/core/csharp_emitter.py` picks its corpus with
   `SELECT id FROM corpus_run LIMIT 1`, correct only because exactly one row
   exists.

4. **A batch-compile ingest mode.** The current ingest opens one hardcoded
   project through `MSBuildWorkspace`. A corpus of thousands of single-file test
   projects needs `CSharpCompilation.Create` directly — which the design already
   called for, pending a measurement.

5. **Report the two gap classes separately** so it is visible which problem is
   moving.

## What is not adopted

PostgreSQL, the database migration package, the stored annotated-C# artifact,
the marker rename, and the 24-pass framework as a prerequisite. None addresses
the measured bottleneck, and the pass framework in particular retires none of
the top root causes.

## The one-line summary

The document diagnosed the right problem and prescribed the wrong remedy. The
problem is not that this lacks a platform architecture. It is that the layer
which accounts for 69% of the blockage has no test of its own, and the fix is a
test loop, not a rebuild.
