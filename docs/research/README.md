# Research index

Each report below is long. This page is the part you need.

Format: **decision — why — how it fails**. If you read nothing else, read the
failure column; it is the part that gets forgotten.

| # | question | decision | fails when |
|---|---|---|---|
| [#38](nullability.md) | `?.` and nullable refs | Assume non-null; demote to `Option<T>` only where the corpus assigns/compares null or uses `?.`/`??`. **4.0%** of members, not 100%. | Null evidence is sparse — 12 of 17 `?.` receivers have `?.` as their *only* evidence. Lose one and the type goes non-nullable and diverges **with no compile error**. |
| [#39](exceptions.md) | exceptions | Typed unwinding **panic**, not `Result`. **Reopens D4.** | `panic = "abort"` in a profile silently turns every `catch` into a process abort, and no current test would see it. |
| [#41](inheritance.md) | inheritance | Keep flattened fields + free fns; **add** a dispatch trait. **Contradicts PLAN.md line 437, which is unreconciled.** | Blocked: `type_implements` records only directly-declared interfaces, so the supertrait closure cannot be computed. |
| [#43](prior-art.md) | does a C#→Rust transpiler exist? | **No.** Nor Java→Rust nor Go→Rust. All published translate-to-Rust work is C→Rust. | A search-derived negative is only valid if a control query returned non-zero in the same run — see the arXiv HTTP 301 incident in that doc. |

## Things that were measured, not argued

- **Roslyn's `NullableFlowState` is unusable here.** Context off → everything
  reports "not analyzed". Forced on → all 22 `?.` receivers report `NotNull`,
  none report `MaybeNull`. The one construct we need it for, it gets wrong
  every time.
- **Blanket `Option<T>` is counterproductive**, not merely ugly: eager
  insertion measured **+49%** and **+181%** more errors (FSE 2023).
- **28.7%** of bodied methods transitively reach a `throw` — the surface
  `Result` colouring would have to cover.
- **c2rust emits output >99.99% of the time; only 72.64% of it runs.**
  Calibration for our own "151,548 lines emitted, zero crashes".

## Corrections to things this project had asserted

- **IL2CPP does not solve C# without a GC.** It ships Boehm `libgc`; so do
  CS2X, bflat and AlterNative. Five of seven C#-to-native pipelines kept a GC.
  Microsoft's own IL→C++ backend in CoreRT was deleted.
- **`?.` is not the biggest blocker.** It is joint 4th at 7 gaps. Type mapping
  is 37–53% of all gaps. The claim came from an issue framing, not the census.
- **"A trait cannot carry the base's fields"** argues for flattening *fields*.
  It says nothing about *methods*, and methods are what dispatch needs.

## Converged findings — four reports, independently

1. **Boundary knowledge is data, everywhere.** c2rust's def-lists, NullAway's
   library models, j2objc's `.jaif`, Bun's `LIFETIMES.tsv`. Nobody puts it in
   the compiler. That is the `rulesdb` boundary, arrived at four times.
2. **Ownership is a per-site classification with recorded evidence**, never a
   global policy — and `UNKNOWN` must be a legal outcome.
3. **Arrays are the universal hole.** `new Widget[10]` is ten nulls with no
   syntactic tell. NullAway, the Checker Framework and C# NRT all document it.
   A peripheral corpus is array-intensive.
4. **The repair loop beats better inference.** Kotlin's J2K survives an
   admittedly-wrong analysis by recompiling and patching diagnostics.

## Ideas worth stealing, with where they came from

| idea | source | why |
|---|---|---|
| **WASM as an oracle** | VERT | Compile C#→WASM, lift WASM→Rust: a correct-by-construction reference that is neither the C# nor our output. C# has a WASM compiler today. Nobody has done this for C#. |
| Ownership ledger with `evidence` + legal `UNKNOWN` | Bun | Global analysis, precomputed, consumed locally. "Trust it over local guessing." |
| Two marker classes, `TODO` vs `PERF` | Bun | Two different debts. Our scorecard has one bucket. |
| Rule provenance (ticket ID per rule) | depyler | Distinguishes a rule written from first principles from one written after something broke. |
| Declining-LLM-usage metric | depyler | Measures whether the process is *learning*. 200+ → <5 calls per 1000 files. |
| A "don't translate" ban list | Bun | Different from `rule_negative`: targets the emitter must not reach for. |
| Feature reduction | Reboot | Translate skeleton → validate → add callbacks → validate. Beat multi-agent-alone by 6–20 points. |
| Differential fuzzing | FLOURINE | Register pokes are a small structured input space. More tractable for us than for general C. |
| Compiler-shim with fallback | Corrode | Drop the converter in where the compiler goes, fall back on failure, hash-dedupe errors. Free coverage metric. |

## The two receipts for zero-patches

- **CodePorting** (ships millions of LOC monthly): *"prioritize framework
  fixing over resulting code fixing, thus fixing each translation error only
  once."*
- **Sharpen/NGit priced it**: 62 KB of source patches vs **358 KB** of output
  patches. Project archived.

## The one warning to keep

Corrode's author, after two months and 6.4% of his corpus:

> "I've spent an entire afternoon comparing the generated Rust to the original
> C without spotting any differences, and yet the Rust version doesn't pass the
> test suite."

Eyeball-diffing against the source is not an oracle.
