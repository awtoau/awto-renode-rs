# Prior art: has anyone built a C#-to-Rust transpiler?

Answers issue #43 (T-R6). Research note, no code.

**Verdict: the claim holds. No C#-to-Rust source translator exists** — not on
GitHub, not on any other forge, not in the academic literature, not as a
commercial product. What exists is one alpha-quality *F#*-to-Rust compiler
(Fable), a family of C#-to-*other-language* translators, and a large number of
LLM snippet converters.

The negative result is not the interesting part. The interesting part is that a
dozen unrelated teams — commercial, open source, and lone developers over
eight-year stretches — each attacked "C# source to a language without a garbage
collector", and most left a written record of exactly which part defeated them.
It is the same part every time, and it is not the syntax.

### If you read five things

1. **§12.6 — the graveyard has one cause of death**, and it is the standard
   library, not the language. IL2CPP survived by refusing to translate it. This
   project's scope is on the right side of that line, and PLAN.md should say so.
2. **§6 and §12.5 — patching output is what kills these projects**, with two
   independent receipts: CodePorting abandoned it under release pressure, and
   NGit measured it at **62 KB of source patches versus 358 KB of output
   patches** before being archived.
3. **§10 — the issue's IL2CPP premise is wrong.** IL2CPP ships a garbage
   collector. So do four of the other five C#-to-native pipelines. Nobody has
   automatically converted C# object lifetime to statically-checked ownership,
   and the load-bearing question for this project is what the *corpus* does with
   object lifetime.
4. **§12.9 — [depyler](https://github.com/paiml/depyler) is the same
   architecture, three years ahead.** Read its docs before touching the rule
   engine.
5. **§11.6 — the failure literature**, especially *Aliasing Limits on
   Translating C to Safe Rust* (a group overturning its own prior conclusions)
   and *Does BLEU Score Work for Code Migration?* (a group showing its own
   field's headline metric does not measure what it claims).

---

## 1. Scope and definitions

Four categories, kept separate throughout. Conflating them is how the original
shallow check went wrong.

| | category | test |
|---|---|---|
| **(a)** | **True C#-to-Rust source translator** | Reads C# source, emits Rust source, mechanically, for arbitrary input |
| **(b)** | **Opposite direction** | Rust-as-a-.NET-language, or a C# compiler/toolchain *written in* Rust |
| **(c)** | **LLM snippet converter** | A prompt with a web form; no fidelity claim, no reproducibility |
| **(d)** | **Adjacent-target translator** | C# to something else, or something else to Rust — solves most of the same problem |

Category (a) is empty. Everything found is (b), (c) or (d).

---

## 2. What was searched

Reproducing the negative result matters more than trusting it, so every query
is listed. Run date: 2026-08-01.

### 2.1 GitHub

`gh search repos` and the `search/repositories` / `search/code` REST endpoints.

| query | endpoint | result |
|---|---|---|
| `c# to rust` | repos | 20 hits, all C/C++-to-Rust |
| `csharp to rust` | repos | 5 hits, all learning material or LLM demos |
| `cs2rust` | repos | 1 hit — a Counter-Strike 2 cheat, not a transpiler |
| `csharp2rust` | repos | 0 |
| `roslyn rust` | repos | 0 |
| `dotnet to rust` | repos | 2, both FFI binding generators |
| `C# transpiler rust` | repos | 0 |
| `"C# to Rust" in:name,description,readme` | search API | 1096, all awesome-lists and unrelated |
| `"csharp to rust" in:name,description,readme` | search API | 13, none a translator |
| `"C# to Rust" transpiler` | search API | 15, every one C-to-Rust |
| `rust transpiler language:C#` | search API | 2, both SQL-dialect transpilers |
| `topic:transpiler csharp` | search API | 47 — the main seam, see §5 and §8 |
| `"C# subset" transpiler` | search API | 2 (CS2X, and a KerboScript toy) |
| `"Roslyn" rust in:name,description` | search API | 6 — includes both previously-dismissed lookalikes |
| `transpile "to Rust" in:description` | search API | 27 — sources are C, Elm, Lua, QBasic, Ruby, F#. Not C# |
| `"Microsoft.CodeAnalysis" "rust" transpiler language:C#` | code | 22 files, 1 relevant (`protogen`) |
| `"CSharpSyntaxWalker" rust emit language:C#` | code | 7 files, 0 relevant |
| `"SyntaxKind" "fn " rust csharp language:C#` | code | 5 files, 0 relevant |
| `"IOperation" rust` | code | 0 |
| `renode rust peripheral` / `renode emulator rust` | repos | 0 relevant — nobody is porting Renode |

### 2.2 Curated cross-references

Two independent human-maintained indexes, checked because they cover obscure
language pairs that repository search misses.

- **[atErik/Transpiler.and.similar.List](https://github.com/atErik/Transpiler.and.similar.List)**
  ([rendered](https://aterik.github.io/Transpiler.and.similar.List/)) — the most
  complete transpiler cross-reference found. It lists **C# as a source language
  for**: C, C++, Nim, D, Go, Java, JavaScript, Python, ActionScript, Lua,
  WebAssembly, Swift, Fortran, VB.NET, PHP, Perl, Ruby, TypeScript. **Rust is
  not among them.** It lists **Rust as a target for**: C, C++, TinyCC, Python,
  Clojure, Ruby, CoffeeScript, Lua. **C# is not among them.** A list that
  bothers to record CoffeeScript-to-Rust and Clojure-to-Rust has no C#-to-Rust
  entry.
- **[Wikipedia, *Source-to-source compiler*](https://en.wikipedia.org/wiki/Source-to-source_compiler)** —
  Rust appears only as the target of C2Rust and as mrustc's bootstrap source.
  C# appears as a source for JS/Java/C++/Go/Python/Lua/PHP. No C#-to-Rust row.

### 2.3 Commercial and web tools

- `playwrong --search "\"C# to Rust\" converter tool commercial"` returns six
  results, **all six LLM snippet forms**: [CodeConvert AI](https://www.codeconvert.ai/csharp-to-rust-converter),
  [CodingFleet](https://codingfleet.com/code-converter/csharp/rust/),
  [codeconverter.com](https://codeconverter.com/convert-c-sharp-to-rust),
  [Syntha AI](https://syntha.ai/converters/csharp-to-rust),
  [CodePorting.AI](https://products.codeporting.ai/convert/csharp-to-rust/),
  [FavTutor](https://favtutor.com/csharp-to-rust-converter). Category (c).
- **CodePorting** — the one company on earth with a production C#-source
  translation business — ships [C# to C++](https://products.codeporting.com/translator/csharp-to-cpp),
  [C# to Java](https://products.codeporting.com/translator/csharp-to-java) and a
  [C# to Python wrapper](https://products.codeporting.com/wrapper/csharp-to-python).
  **No Rust translator.** Their blog carries a `Rust` tag; it contains a
  beginners' tutorial, nothing more.

### 2.4 Discussion archives

- Hacker News via `hn.algolia.com/api/v1/search`: `C# to Rust` (9390 hits, none
  an announcement), `csharp rust transpiler` (**3 hits, none relevant**),
  `port C# Rust` (1034 hits, none a tool).

Non-GitHub forges (GitLab, Codeberg, sr.ht, Bitbucket, SourceForge, grep.app,
SearchCode, crates.io, NuGet, Software Heritage) and the academic literature
were surveyed separately; see **§9** and **§11**.

---

## 3. Category (b) — the lookalikes, re-checked

Both previously-dismissed repositories were re-read. **Both dismissals were
correct**, and neither is close to a transpiler.

| repo | what it actually is | stars |
|---|---|---|
| [mistahoward/rustlyn](https://github.com/mistahoward/rustlyn) | "A rust shim for roslyn for unlicensed Microsoft forks (cursor, antigravity, etc) to allow for modern type checking within blazor / razor projects" — a language-server shim. Single commit, 2025-12-24. | 0 |
| [hanu-tayal/csharp-compiler-rust](https://github.com/hanu-tayal/csharp-compiler-rust) | "C# compiler written in Rust — lexer, recursive descent parser, semantic analysis, and IL code generation". Emits **IL**, not Rust. | 0 |

One more found that fits the pattern: [himoji/cs2rust](https://github.com/himoji/cs2rust) —
`cs2` is Counter-Strike 2. It is a game overlay written in Rust. Name collision only.

---

## 4. Category (c) — the LLM converters, and the one that matters

Web-form converters are listed in §2.3 and need no further treatment. One
GitHub project deserves a note because it is the closest anyone has come to
attacking the actual problem, and it demonstrates precisely the cost model this
project rejected:

**[arikdutta/CSharp-toRUST-Assistant](https://github.com/arikdutta/CSharp-toRUST-Assistant)**
(0 stars, 47 KB; created 2026-06-28T18:23Z and last pushed 2026-06-28T19:27Z —
about an hour of work, and untouched since).

> "Tree-sitter handles **structure** (splitting source into one translatable
> unit at a time); an LLM handles **meaning** (the actual translation, including
> ownership, LINQ, async); and `cargo check` **grades** the output, feeding
> compiler errors back into the model until the code compiles."

Architecture: `extractor.rs` (tree-sitter-c-sharp finds class/struct/enum/
interface boundaries) → `llm.rs` (one declaration per LLM call, carrying a
running symbol table of already-translated signatures) → `cargo_check.rs`
(re-prompts with compiler errors, up to `MAX_REPAIRS`).

Two things are worth taking, and one is worth refusing.

- **Take**: the *symbol table threaded across units* so a later translation
  sees earlier signatures. That is the cross-unit coherence problem, and
  carrying resolved signatures forward is the cheap answer.
- **Take**: `cargo check` as an automatic grader in the loop, not as a
  post-hoc human step.
- **Refuse**: one LLM call per declaration. This is exactly the per-function
  invocation path CLAUDE.md forbids, and the repository's own scale — one file,
  one day, no corpus — is what that approach produces. It also has no fidelity
  oracle at all: "it compiles" is the entire acceptance criterion, so a
  translation that compiles and behaves differently passes.

Note also its choice of **tree-sitter over Roslyn**. Tree-sitter gives a syntax
tree with no semantic model — no symbol resolution, no overload resolution, no
`IOperation` lowering — which is why the LLM has to do the semantics. Choosing
Roslyn's `IOperation` instead is the difference between the LLM guessing at
meaning and the frontend supplying it.

---

## 5. Category (d.1) — CS2X / IL2X: the closest structural precedent

**This is the most directly comparable project found**, and it is a
partially-abandoned one, which is what makes it valuable.

One developer (`zezba9000` / Reign Studios), 2018–2024, three repositories:

| repo | approach | commits | last substantive work |
|---|---|---|---|
| [zezba9000/CSharpTranspiler](https://github.com/zezba9000/CSharpTranspiler) | original experiments | — | superseded 2018 |
| [reignstudios/CS2X.Old](https://github.com/reignstudios/CS2X.Old) | **Roslyn, C# source → C89** | 241 | 2020-11-13 |
| [reignstudios/IL2X](https://github.com/reignstudios/IL2X) | **Cecil, .NET IL → C89** | 165 | 2024-02-07 |
| [reignstudios/CS2X](https://github.com/reignstudios/CS2X) | restart, Roslyn again | 1 | started 2026-06-19 |

### What it gets right, and what to take

- **The subset is enforced as a Roslyn analyzer, not discovered at emit time.**
  `CS2X.Analyzer` is a real `DiagnosticAnalyzer` shipped as a VSIX
  (`CS2X.Analyzer.Vsix`), so unsupported C# is a red squiggle in the editor with
  messages like `"CS2X ERROR: Runtime does not support boxing"`. Its `TODO.txt`
  reads like a subset specification: *"DllImport extern methods cannot use
  managed types"*, *"Disable nullable value types"*, *"String concat should make
  sure it only supports operator+ char and not object / boxing"*.

  **Worth stealing.** This project already withholds anything not yet
  emittable; publishing that same set as an analyzer would turn a silent
  emitter gap into a diagnostic at the source, and would make the supported
  subset a reviewable artifact rather than an emergent property of the emitter.

- **Emitter structure**: `Transpilers/Transpiler.cs` (target-agnostic base) +
  `Transpilers/C/{TypeWriters,StatementWriters,ExpressionWriters,NameResolution,Options}.cs`.
  Splitting name resolution out from the writers is the right seam — it is
  where the deterministic-output requirement lives.

### What defeated it — the finding

CS2X's README promised *"a micro deterministic GC/defragger that targets
embedded devices with 1kb or higher"*. Eight years later, `CS2X.Native/` contains:

- `CS2X.GC.Boehm.h` — delegate to the Boehm conservative collector
- `CS2X.GC.Dumby.h` — `malloc`, `memset`, **never free**
- `CS2X.GC.Micro.h` — in its entirety:
  ```c
  #pragma once
  void* GC_New(size_t size)
  {
      return 0;// TODO
  }
  ```

**The memory-management strategy is the part that was never written.** The
Roslyn frontend, the C emitter, the vtable binding, the analyzer, .NET 5
support — all landed. The thing the project existed to do did not.

The author also switched approach mid-stream and left the reasoning in an
issue thread ([CS2X.Old#5](https://github.com/reignstudios/CS2X.Old/issues/5),
2021-12-05):

> "CoreRT translates IL instructions while CS2X translates/compiles C# syntax
> to a target."

and ([CS2X.Old#4](https://github.com/reignstudios/CS2X.Old/issues/4), 2021-09-13):

> "I'm re-looking into some IL2X stuff to see if it offers features faster for
> CPU targets (not GPUs)"

He then spent 2021–2024 on the IL route and, on restarting in 2026, went back
to Roslyn source-level: the current READMEs read *"CS2X This will probably be
the only focused compiler"*. **A round trip from source-level to IL-level and
back, ending at source-level.** Recorded reasoning for preferring source is in
[CS2X.Old#3](https://github.com/reignstudios/CS2X.Old/issues/3):

> "C# transpilation/compilation into C89 is simplified because C# has Roslyn
> (aka compiler as a service). […] The only approach you should take with the
> Go lang is: Go-AST => semantic analyzes => transpilation/compilation logic =>
> C/C++ (with a custom runtime). With CS2X Roslyn takes care of the first two
> steps."

**Read across to this project**: the frontend is not the risk. Roslyn plus
`IOperation` is a solved, cheap step — CS2X got there in months. The risk is
concentrated entirely in the memory/ownership model and in having something
that forces it to be finished. This project's advantage is that its corpus
(peripheral models with `IValueRegisterField` handles and no object graphs) may
sidestep the very thing that killed CS2X — which is worth stating explicitly as
a scope boundary rather than assuming.

---

## 6. Category (d.2) — CodePorting Cs2Cpp: the only production-scale C# source translator

[CodePorting.Translator Cs2Cpp](https://products.codeporting.com/translator/csharp-to-cpp)
(formerly CodePorting.Native Cs2Cpp) is the machine Aspose uses to ship its
entire C++ product line, generated monthly from the C# sources. **Millions of
lines per library, released to paying customers.** This is the largest
real-world C#-to-unmanaged-language source translation that exists, and the
team wrote it up in detail.

Still shipping, verified on NuGet:
[`CodePorting.Translator.Cs2Cpp.Framework`](https://www.nuget.org/packages/CodePorting.Translator.Cs2Cpp.Framework/)
**v26.7.0, 314,888 downloads**, plus `Cs2Cpp.Control` and the legacy
`CodePorting.Native.Cs2Cpp.API` (440,487 downloads). **There is no
`Cs2Rust`** — a NuGet query for `Cs2` and for `CodePorting` returns no Rust
package, and `csharp to rust` on NuGet returns zero results. The organisation
with more C#-source-translation experience than anyone else has not attempted
Rust.

Primary sources:
[Part 1](https://www.codeporting.com/blog/from_csharp_to_cpp_how_we_have_automated_project_conversion_part1) ·
[Memory management models](https://www.codeporting.com/blog/memory-management-models-porting-csharp-to-cpp) ·
[Circular references and memory leaks](https://www.codeporting.com/blog/circular-references-memory-leaks-porting-csharp-to-cpp) ·
[SmartPtr implementation](https://www.codeporting.com/blog/smartptr-implementation-porting-csharp-to-cpp)

### The finding that most matters

They started by hand-patching translated output, and stopped:

> "Initially, manual fixing of translated Java code allowed to speed up the
> development and product releases. However, in the long run, this significantly
> raised the expenses needed to prepare each version for the release, as every
> translation error had to be fixed each time it appeared. […] it was decided to
> prioritize C++ framework fixing over resulting code fixing, **thus fixing each
> translation error only once**."

That is CLAUDE.md's "every manual fix lands as a rule, not a file patch" and
"patches trend to zero", arrived at independently by a commercial team under
monthly release pressure. They also record the intermediate compromise they
rejected — *feeding the output with patches computed as the diff between two
consecutive translator runs* — which is worth knowing about precisely because
it is the tempting middle road, and they judged it not worth it.

**Independent corroboration of the project's central rule. Cite it.**

### What else to take

- **A support library shaped like the source BCL, not a mapping to idiomatic
  target types.** "Because of the inability to map .NET types to STL ones, we
  decided to use custom Library types as substitutions." Fable made the same
  call independently (§7). Two of two production translators chose *ship a
  runtime that looks like `System.*`* over *rewrite call sites into target
  idiom*.
- **Translate the tests too.** "the tests that covered the original C# code are
  translated alongside it, ensuring the functionality of the resulting solution
  is monitored". A free second oracle tier, orthogonal to trace replay: Renode's
  own C# test suite is corpus that can be run against the Rust.
- **Why not reuse an existing runtime** (they considered and rejected Mono):
  "Our products do not require the full .NET implementation. However, if we had
  a full implementation, it would be hard to distinguish which methods and
  classes we need and which ones do not. We would spend much time fixing the
  features we never use." The same argument applies to pulling in a large Rust
  compatibility shim.

### What they found too hard — GC to reference counting

The Rust reading of this section is nearly one-to-one, because `SharedPtr` /
`WeakPtr` is `Rc` / `Weak`.

| problem | their statement | Rust equivalent |
|---|---|---|
| **Strong reference cycles** | GC handles isolation islands; refcounting leaks them. Requires a **`[CppWeakPtr]` attribute placed by a human on the C# field** | `Rc` cycles leak identically; needs `Weak` chosen per field |
| **Object deleted during construction** | A temporary `SharedPtr<T>` to a not-yet-fully-constructed object can hit zero and destruct it. Translator auto-inserts a `ThisProtector` guard | `Rc::new_cyclic` / two-phase init |
| **Double deletion when a constructor throws** | Stack unwinding destroys fields holding strong references back to the object being destroyed | Rust's `Drop`-during-panic |
| **Deleting long chains** | Recursive destruction of a linked list of a few thousand nodes **overflows the stack**; fixed by translating a C# finalizer into an iterative destructor | Exactly Rust's well-known recursive-`Drop` stack overflow |

And the concluding sentence, which is the honest headline of the whole
programme:

> "Despite the fundamental mismatch between the C# and C++ type systems, we
> managed to build a smart pointer system that allows the converted code to run
> with behavior close to the original. **At the same time, the task was not
> solved in a fully automatic mode.** We have created tools that significantly
> simplify the search for potential problems."

Those tools are worth knowing about: a debug-build **global object registry**
(populated in `System::Object`'s constructor), a translator-emitted virtual
`GetSharedMembers()` returning every smart pointer a given object holds, and
graph dumps rendered with graphviz showing live objects, strong-only cycles,
and isolation islands. **A leak oracle, generated by the translator, run after
every test.** If this project ever needs `Rc` in emitted code, that is the
shape of the tooling required, and it should be budgeted at the same time as
the emitter — not after.

One divergence to note: their weak-reference decisions are recorded as
**attributes in the C# source**. This project cannot edit its C# (it is
upstream Renode), so the equivalent has to live in the rules DB keyed by
symbol. That is a strictly harder version of the same problem, and it is the
kind of per-site knowledge that could quietly become a patch if not designed
for.

---

## 7. Category (d.3) — Fable: a .NET language *does* compile to Rust

The nearest miss, and the one the original check missed entirely.

**[Fable](https://github.com/fable-compiler/Fable)** (3,137 stars, active,
last push 2026-07-29) is "F# to JavaScript, TypeScript, Python, Rust, Erlang
and Dart Compiler". **The Rust backend is real and shipping**, at
[status *Alpha*](https://fable.io/docs/) — the only .NET-family language with a
working Rust target.

It is not C#, so it does not falsify the negative result. It is, however, the
single best-matched piece of engineering to read, because it answers "how does
a .NET frontend emit Rust" in production code rather than in principle.

### Architecture

| component | file | size |
|---|---|---|
| typed AST → Rust AST | `src/Fable.Transforms/Rust/Fable2Rust.fs` | 259 KB, 5,867 lines |
| BCL / library call mapping | `src/Fable.Transforms/Rust/Replacements.fs` | 180 KB |
| modelled Rust AST | `src/Fable.Transforms/Rust/AST/Rust.AST.Types.fs` | 53 KB |
| pretty printer | `AST/Other/Rust.AST.Printer.fs`, `Rust.AST.Pretty.fs` | — |
| runtime support crate | `src/fable-library-rust/` | Rust + F# |

Three structural decisions worth copying:

1. **Emit through a modelled Rust AST, then pretty-print** — `Rust.AST.Types.fs`
   is a transcription of rustc's own `ast` crate. Nothing is built by string
   concatenation. This is what makes byte-identical output at any parallelism
   achievable rather than aspirational.
2. **A separate `Replacements` layer** holding every `System.*` → Rust mapping,
   distinct from the code that walks the tree. That is the same split this
   project draws between `Walker.cs` (mechanism) and `csharp_core.json`
   (language mapping) — except Fable's is 180 KB of hand-written F# rather than
   reviewable data. **The place this project can beat Fable is exactly there**:
   Fable's mapping layer cannot be A/B tested, mined, or counted.
3. **A support crate shaped like the source library** (`fable_library_rust`),
   same call as CodePorting's. Two independent production translators, same
   answer.

### How Fable answers GC-to-ownership

It does not infer ownership. It **reference-counts everything**, behind an
alias:

- `Lrc<T>` / `LrcPtr<T>` — "local Rc", switched between `Rc<T>` and `Arc<T>` by
  a Cargo feature. `Fable2Rust.fs` carries the comment *"such as Rc\<T\> (or
  Arc\<T\> in a multithreaded context)"*.
- `makeClone` inserts `.clone()` at ownership boundaries — *"This guarantees a
  new owned Rc\<T\>"*.
- A `byref` path (`isByRefType`, `IsParamByRefPreferred`) for the cases where
  borrowing is provably fine, as an optimisation over the refcount default.

The `fable-library-rust` Cargo features are the design levers, and they are
directly relevant to an embedded target:

```toml
[features]
atomic = []            # Rc -> Arc
lrc_ptr = []
no_std = ["dep:hashbrown"]
threaded = ["atomic", "dep:futures", "dep:futures-timer"]
```

**`no_std` is a supported configuration.** Whatever this project decides about
allocation in emitted peripheral code, Fable has already walked that path from
a GC'd source language.

**What to take**: the `Lrc` default-plus-`byref`-optimisation shape is the
pragmatic answer to GC mapping — *always refcount, then narrow to borrows where
the frontend can prove it*, rather than attempting ownership inference up
front. It is also the answer that keeps the translation faithful, which is this
project's stated priority; ownership inference is where fidelity gets traded
for idiom.

**What to note as a warning**: the first commit to `Fable2Rust.fs` is
**2021-05-25** ("Fable2Rust WIP"), and that one file has since taken **384
commits**. Five years and 259 KB of emitter later the target is still *Alpha* —
for a source language far simpler than C#: no inheritance, no
mutable-by-default fields, no `unsafe`, no `partial`, no properties, no
overload resolution. Emitter size is not the risk; the long tail of semantics
is. A translator for *all* of C# is a multi-year project by this evidence, and
the only reason this one is tractable is that it is not translating all of C# —
it is translating one corpus, with a scorecard that makes the withheld
remainder visible.

### Related, smaller

- [lue-bird/elm-syntax-to-rust](https://github.com/lue-bird/elm-syntax-to-rust) —
  Elm (GC'd, functional) to Rust.
- [ppn-systems/protogen](https://github.com/ppn-systems/protogen) — the **only
  Roslyn-driven Rust emitter found on GitHub**. It reads C# packet definitions
  via `MSBuildWorkspace` and emits wire-compatible C and Rust structs. Not a
  translator (declarations only, no method bodies), but it independently
  invented a differential oracle: it "builds round-trip test suites
  (`packet_test.c` and `packet_tests.rs`) to prove serialization/deserialization
  logic is identical across target languages."
- [AdHoc-Protocol/AdHoc-protocol](https://github.com/AdHoc-Protocol/AdHoc-protocol) —
  same shape: C# used as the schema DSL, `CSharpSyntaxWalker` frontend,
  multi-language emit including Rust. Again declarations, not behaviour.

---

## 8. Category (d.4) — the other C# source translators

The `topic:transpiler csharp` seam, which is where all of this actually lives.
None target Rust; several are architecturally instructive.

| project | target | powered by | state |
|---|---|---|---|
| [ASDAlexander77/cs2cpp](https://github.com/ASDAlexander77/cs2cpp) | C++ | Roslyn | 298★, last push 2024-06 |
| [yanghuan/CSharp.lua](https://github.com/yanghuan/CSharp.lua) | Lua | Roslyn | 1,280★, **active** (2026-07) |
| [afrog33k/SharpNative](https://github.com/afrog33k/SharpNative) | D, C++11, Java, Swift | Roslyn | 67★, dead since 2015 |
| [AlexAlbala/Alter-Native](https://github.com/AlexAlbala/Alter-Native) | C++ | **ILSpy + Mono.Cecil — decompiled assembly, not source** | 162★, dead since 2020 |
| [rogeralsing/ProjectExodus](https://github.com/rogeralsing/ProjectExodus) | Kotlin | Roslyn | 79★ |
| [jindraivanek/cs2fs](https://github.com/jindraivanek/cs2fs) | F# | Roslyn | 64★ |
| [CoderNate/CSharpToPython](https://github.com/CoderNate/CSharpToPython) | Python | Roslyn | 53★ |
| [roblox-csharp/roblox-cs](https://github.com/roblox-csharp/roblox-cs) | Luau | Roslyn | 97★ |
| [cybercom684/CS2SX](https://github.com/cybercom684/CS2SX) | C (Nintendo Switch homebrew) | Roslyn | 14★, active |
| [kekyo/IL2C](https://github.com/kekyo/IL2C) | C | **IL, not source** | 448★ |
| [onelang/OneLang](https://github.com/onelang/OneLang) | many↔many | own AST | 1,142★, dead since 2023 |

Two observations from the table.

**Roslyn is the universal frontend choice.** Every source-level C# translator
on it uses Roslyn; the ones that went to IL (IL2C, CoreRT's CppCodeGen, IL2X)
are a separate, smaller family. Nobody built a C# parser. That is a settled
question and this project settled it the same way.

**AlterNative is the one with academic backing**, and it is worth a paragraph
because its stated assumptions are the exact opposite of this project's.
[Its site](https://alexalbala.github.io/Alter-Native/) records it as "a research
project […] with the collaboration of UPC - BarcelonaTech and AlterAid S.L.",
funded by the Spanish Ministry of Science and Innovation (CloudARM,
IPT-2011-1834-430000). Two design assumptions are stated up front:

> "**Translatable source code**: Theoretically any source code can be
> translated from one machine to another.
> **Readability and Usability**: The developer should be able to understand and
> modify the generated code, or even replace some parts."

The second is precisely the property `check_generated.py` forbids. Generated
code you are expected to hand-modify is generated code that will not
regenerate — which is why AlterNative is a dead 2020 repository and CodePorting,
which chose the opposite, is still shipping monthly. It also reads
**decompiled assemblies** via ILSpy and `Mono.Cecil` rather than C# source, and
its runtime library links **Boehm gc** (see §10).

**OneLang is the cautionary one.** Its README is unusually candid:

> "Some may call it a transpiler […] Those will have a hard time using it, as
> OneLang has its own rules and **does not respect** those of the input
> language, sometimes not even its syntax."

That is what a translator becomes when nothing enforces fidelity. It is the
failure mode the oracle exists to prevent, stated by an author who accepted it.
Worth noting that OneLang did put its library mappings in **YAML data files**
(`JsToCSharp.yaml`, `JsToPython.yaml`, …) while keeping the generators as
code — a partial precedent for rules-as-data, and it did not save the project.
Data-driven mappings are necessary but plainly not sufficient; the missing
piece there was any notion of an equivalence check.

### The emulator-specific comparison: QEMU

Worth recording because it is the same problem in the same domain, solved the
other way. QEMU is [moving device models to Rust](https://www.qemu.org/docs/master/devel/rust.html),
and does it **by hand**. `rust/hw/char/pl011` and `rust/hw/timer/hpet` are
described as "functional replacements for the `hw/char/pl011.c` and
`hw/timer/hpet.c` files", and the drift problem is managed by pinning:

> "The `pl011` crate is synchronized with `hw/char/pl011.c` as of commit
> `3e0f118f82`. The `hpet` crate is synchronized as of commit `1433e38cc8`.
> Both are lacking tracing functionality."

Two devices, hand-written, each pinned to a named upstream commit, each already
missing features. That is the alternative to building a converter, and it is
what the effort looks like at N=2. **The pinning convention itself is worth
copying** — recording the exact upstream C# commit each generated Rust file
corresponds to makes drift a checkable fact rather than a suspicion. This
project already pins the Renode reference commit in `STATUS.md`; doing it
per-file is the finer-grained version.

Nobody — not Antmicro, not anyone else — is porting Renode to Rust. Searches
for `renode rust peripheral`, `renode emulator rust` and a scan of Antmicro's
public repositories return only *firmware written in Rust and run under
Renode*, never the emulator itself.

---

## 9. Off-GitHub: forges, registries, archives, forums

Surveyed separately and in full. **Result: nothing, anywhere.**

| source | method | queries | result |
|---|---|---|---|
| **GitLab.com** | `/api/v4/projects?search=` | `csharp rust`, `cs2rust`, `csharp2rust`, `c# to rust`, `roslyn rust`, `dotnet rust transpiler`, `csharp transpiler`, `transpiler rust`, `c# transpiler` | Nothing. `csharp transpiler` returns only Java→C#, TS→C#, T-BASIC→C#, C#→C++ |
| **Codeberg** | Gitea `/api/v1/repos/search?q=` | `rust csharp`, `cs2rust`, `csharp2rust`, `csharp-to-rust`, `dotnet2rust`, `il2rust`, `cil2rust`, `roslyn`, `transpiler`, `transpile`, `c#`, `rust converter` | Nothing. ~24 hobby transpilers, best being `Rustfuck` (brainfuck→Rust) |
| **sr.ht** | `sr.ht/projects?search=` via browser | `transpiler`, `rust transpiler`, `rust c#` | Nothing |
| **SourceForge** | `/directory/?q=` | `c# to rust` (158 hits), `rust transpiler` (1 hit), `csharp rust` | Nothing. The single `rust transpiler` hit is py2many |
| **grep.app** | browser (`/search?q=`) | `cs2rust`, `csharp2rust`, `C# to Rust transpiler` | "No results found" for all three |
| **crates.io** | `/api/v1/crates?q=` | `csharp`, `c-sharp`, `dotnet`, `roslyn`, `transpiler csharp`, `transpiler` | ~150 crates reviewed. All FFI generators, .NET metadata parsers, or CLR hosts. **Zero translate C# source to Rust** |
| **NuGet** | `azuresearch-usnc.nuget.org/query?q=` | `rust`, `rust transpiler`, `convert to rust`, `csharp to rust`, `Fable`, `Fable.Rust`, `CodePorting`, `Cs2` | `csharp to rust` → **0 results**. No `Cs2Rust` package exists |
| **Software Heritage** | `/api/1/origin/search/` | `cs2rust`, `csharp2rust`, `csharp-to-rust`, `dotnet2rust`, `roslyn-rust`, `2rust`, `rust-transpiler`, `transpiler` | Nothing. Non-GitHub origins: cpp_to_rust, php-to-rust, dyon_to_rust, openapi-to-rust — no C# |
| **Hacker News** | Algolia API, stories + comments | 9 phrasings incl. `C# to Rust transpiler`, `transpile C#`, `automatically convert C# to Rust` | No announcement, no request, no abandonment |
| **users.rust-lang.org** | `/search.json?q=` | `C# to Rust transpiler`, `csharp transpiler`, `convert C# code to Rust`, `port C# project to Rust automatically` | **`csharp transpiler` → zero topics.** See below |
| **Reddit** | old.reddit + `/search/` via browser | `"C# to Rust" transpiler`, `port our C# codebase to Rust automated tool` | Nothing. All results are C/C++→Rust or language comparison |
| **Stack Overflow** | `api.stackexchange.com/2.3/search/advanced` | `C# to Rust transpiler`, `convert C# code to Rust` | **Zero questions** |
| **Lobsters** | `/search?q=` | `C# Rust`, `transpiler rust` | Nothing (54 hits, all C/Clojure/Bash) |

**Three sources could not be surveyed and the negative result is caveated
accordingly**: Bitbucket has retired anonymous global repository search (HTTP
401 / login wall); the Google Code Archive's search is a JavaScript shell with
no server-rendered results and its GCS bucket denies anonymous listing;
**searchcode.com no longer offers code search at all** — it has pivoted to an
LLM "code intelligence" product and the classic `/api/codesearch_I/` endpoint
returns 404. These are unlikely to hide an active project (Google Code has been
read-only since 2016) but the gap should be stated rather than papered over.

### The strongest negative datum

`users.rust-lang.org` has "does a translator exist" threads for **C** (2014,
2017), **Java** (2016), **Python** (2017, 2020 ×2), **C++** (2018), **D**
(2023), **Haskell** (2023), **WASM** (2020) and **Rust→C** (2023). Searching
that forum for `csharp transpiler` returns **zero topics**. Stack Overflow:
zero questions.

Nobody has built one, and nobody has publicly asked for one either. Given how
large the C# installed base is, that is worth sitting with. The most plausible
explanation available is second-hand, from a Rust-forum thread on RIIR tooling
([users.rust-lang.org/t/98345](https://users.rust-lang.org/t/easy-refactoring-to-rust-lang/98345)):

> "c2rust is a transpiler for converting C into Rust, but it's highly
> non-idiomatic and I doubt that using it on a project would ge[t you far]"

If the DARPA-funded effort on the *easy* source language is regarded as
producing unusable output, starting on a garbage-collected object-oriented one
looks unattractive. **This project's answer to that objection is its oracle**:
it does not need idiomatic output, it needs *equivalent* output, and it has a
way to prove it. That reframing is the actual reason this is tractable when the
general problem was judged not to be, and it belongs in PLAN.md's rationale.

### One genuinely relevant off-GitHub find

**[libldt/libldt3-transpiler](https://gitlab.com/libldt/libldt3-transpiler)** —
active (created 2025-07, ~108 commits). Reads **Java** with the **Spoon** model
library and emits **C# or Rust** through **FreeMarker templates**
(`TranspileCsharp#main()`, `TranspileRust#main()`): Java classes → Rust structs,
interfaces → traits, enums → enums, generated `mod.rs` hierarchy, `snake_case`
renaming directives.

Not C#-to-Rust, but the only *live, production, model-plus-template
OO-language-to-Rust translator* found on any forge. The template approach is
the road not taken here: templates make simple shapes trivial and make
anything context-dependent (ownership, borrow lifetimes, name collisions)
impossible, which is why it works for a schema library and would not work for
peripheral behaviour. Useful as a bound on what the cheap approach buys.

### Category (b) additions — Rust to .NET, the true opposite

Worth recording since the original check named only two lookalikes; there are
more, and one is substantial:

- **[rustc_codegen_clr](https://crates.io/crates/cilly)** (`cilly` crate) — a
  rustc backend emitting CIL. **Rust → .NET.**
- **[SourceGear.Rust.NET.Sdk](https://www.nuget.org/packages/SourceGear.Rust.NET.Sdk/)** —
  "MSBuild SDK for compiling **Rust to .NET assemblies**".
- **[elteammate/rust2sharp-translator](https://github.com/elteammate/rust2sharp-translator)** —
  "A translator from rust to C# **(useless)**", the author's own word.
- Rust crates that *read* .NET: `dotnetdll`, `dotscope`, `clrmeta`, `cilium`,
  `oak-msil`. Rust crates that *host* the CLR: `rustclr`, `clroxide`,
  `netcorehost`.

All opposite-direction. None emits Rust from C#.

### One useful artefact from the LLM-converter side

CodePorting's LLM snippet page for
[C# to Rust](https://products.codeporting.ai/convert/csharp-to-rust/) publishes
a self-scored **"Translation Challenges"** table — async 9/10, nullability
8/10, extension methods 8/10, properties 7/10, exceptions 7/10 (mapping
`try`/`catch` onto `std::panic::catch_unwind`). It is marketing, not
measurement, but it is one honest signal of where a C#-to-Rust mapping hurts,
from the company with the most C#-translation experience. Three of those five —
properties, extension methods, nullability — are already live in this project's
corpus. Async and exceptions are largely not, which is a point in favour of the
chosen corpus.

---

## 10. The IL2CPP premise, corrected

Issue #43 says IL2CPP is "especially relevant — it solves C# semantics on a
non-garbage-collected target, which is most of our problem."

**That premise is wrong, and the correction is the most useful thing in this
note.** IL2CPP targets an unmanaged *language*. It does not target a
*non-garbage-collected runtime*. From Unity's own
[IL2CPP internals](https://unity.com/blog/engine-platform/an-introduction-to-ilcpp-internals)
(Josh Peterson, 2015):

> "The technology that we refer to as IL2CPP has two distinct parts. An
> ahead-of-time (AOT) compiler [and] a runtime library to support the virtual
> machine. […] **One key part of the runtime is the garbage collector.** We're
> shipping Unity 5 with **libgc, the Boehm-Demers-Weiser garbage collector**."

IL2CPP compiles IL to C++ and then links `libil2cpp`, a static library
containing a GC, thread and file abstractions, and internal calls. C++ is the
*code generation* target; the memory model is unchanged.

Check that against everything else found:

| project | source → target | what happened to the GC |
|---|---|---|
| **IL2CPP** (Unity) | IL → C++ | **Kept.** Boehm `libgc`, linked into the player |
| **CS2X** (Roslyn, C89) | C# → C89 | **Kept**, or punted. Boehm binding, or `malloc`-and-never-free; the promised "micro deterministic GC" is `return 0;// TODO` |
| **bflat** (Roslyn + NativeAOT) | C# → native | **Kept.** CoreCLR GC in the binary. `--stdlib:zero` gives "not much more than primitive types" for UEFI — i.e. avoid allocating, not manage it |
| **CoreRT / NativeAOT** | IL → native | **Kept** |
| **AlterNative** (UPC BarcelonaTech) | .NET assembly → C++ | **Kept.** Its support library links **Boost + Boehm gc** |
| **CodePorting Cs2Cpp** | C# → C++ | **Replaced** with `SharedPtr`/`WeakPtr` refcounting — *"the task was not solved in a fully automatic mode"* |
| **Fable** | F# → Rust | **Replaced** with `Lrc`/`LrcPtr` (`Rc`/`Arc`) refcounting plus a `byref` fast path. Alpha after five years |

**Five of the seven kept a garbage collector or forbade allocation outright.
The two that replaced it both landed on reference counting, and both needed
manual help to make it correct.**

This is the finding. Nobody has automatically converted C# object lifetime into
statically-checked ownership, and the people best placed to do it chose not to
try. Rust has no third option: there is no "link a GC" escape hatch that keeps
the code idiomatic and safe.

**Therefore the load-bearing question for this project is not "can we translate
C# syntax" — that is settled, repeatedly, by Roslyn. It is "what does the
Renode peripheral corpus actually do with object lifetime?"** If the answer is
"peripherals hold `IValueRegisterField` handles, a reference to the machine, and
a few `Action` callbacks, with no cyclic ownership and no allocation in the
MMIO path", the project sidesteps the thing that defeated every predecessor and
should say so explicitly as a scope claim in PLAN.md. If the answer is anything
else, the `Rc`/`Weak` decision plus a leak oracle needs budgeting now, on
CodePorting's evidence, rather than discovered at emit time.

That question is answerable from data the corpus DB already holds, and it is
the single highest-value follow-up this survey produces.

---

## 11. The academic literature

### 11.1 Coverage, and its limits

| index | queries | note |
|---|---|---|
| **arXiv** API + web UI | 49 attempted, 3 completed via API (HTTP 429), remainder via browser | **arXiv's indexer strips `#`**, so the literal token `C#` cannot be queried there at all |
| **DBLP** | 21 queries, all completed | Title-word matching only |
| **Semantic Scholar** | Graph API 429 on every call; 2 queries via web UI | |
| **Google Scholar** | exact phrase `"C# to Rust" translation` | **2 results total** |

**Stated honestly**: ACM DL and IEEE Xplore full-text were not swept. The
negative rests principally on the Google Scholar and Semantic Scholar
exact-phrase results plus DBLP. Given the strength of the corroborating
evidence in §2 and §9 that is sufficient, but it is the softest leg of the
argument and is recorded as such.

### 11.2 (A) C# to Rust: confirmed absent

**No academic paper on C#-to-Rust translation exists.** Google Scholar's exact
phrase `"C# to Rust"` returns exactly two documents, neither a translation
method: an AMOS 2022 space-situational-awareness application paper that mentions
having **manually** ported a C# orbit propagator ("Porting from C# to Rust
requires many changes to the baseline"), and a 2024 URI thesis that uses a
C#↔Rust FFI callback.

The Rust-translation literature is roughly **95% C-sourced**, with small Go,
Java, Python and C++ tails. C# is absent as a *source* in the Rust literature
and Rust is absent as a *target* in the C# literature.

### 11.3 A second confirmed gap: emulator and peripheral-model translation

Nothing exists on translating peripheral models, device models or simulator
code between languages. The adjacent field is **peripheral-model inference** —
P2IM (USENIX Security 2020), [FirmGuide](https://dl.acm.org/doi/abs/10.1109/ASE51524.2021.9678653)
(ASE 2021), Fuzzware, Jetset, [*What Your Firmware Tells You Is Not How You
Should Emulate It*](https://arxiv.org/pdf/2208.07833) — which **synthesises**
peripheral behaviour from firmware traces rather than translating an existing
model. Those papers face the same "is this model faithful?" question the oracle
here answers, and are worth reading for that, but they are not prior art for
translation.

Renode itself has only a workshop paper (Speiser & Szalay, *Embedded System
Simulation Using Renode*) and a [thesis on Renode in CI](https://www.diva-portal.org/smash/record.jsf?pid=diva2:1900246).

### 11.4 The one closely-matched research line — and it used C#

**Tien N. Nguyen's group (Iowa State), 2010–2016**, mined translation rules
from a corpus, and used **Java↔C#** as that corpus precisely because paired
ports exist (db4o, Lucene, Spring/Spring.NET, Neodatis). This is the closest
methodological ancestor of the rulesdb design and it deserves citation in
`docs/rulesdb-design.md`.

| paper | year | why it matters here |
|---|---|---|
| [*Mining API mapping for language migration*](https://doi.org/10.1145/1806799.1806831) (MAM) | ICSE 2010 | The founding paper of corpus-mined mapping rules: align corresponding methods across a ported pair, extract rules from the alignment |
| [*StaMiner*](https://doi.org/10.1145/2642937.2643010) | ASE 2014 | Mines **many-to-many API usage-sequence mappings**, not 1:1 name pairs. Renode's register DSL is a many-to-many shape mapping, not a token substitution |
| [*mppSMT*](https://doi.org/10.1109/ASE.2015.74) | ASE 2015 | Decomposes migration into phases (syntax → type/API → literals). Essentially CLAUDE.md's three-layer extraction / language-mapping / project-idiom split |
| [*Hybrid API Migration*](https://doi.org/10.1145/3609437.3609466) | Internetware 2023 | Small mined mapping model + LLM for the residue — **precisely this project's architecture**, published |

Beyond that line, **C#-to-anything has essentially no academic literature**.
JSIL, Bridge.NET, Sharpen and CodePorting are industrial and unpublished; .NET
IL decompilation has no academic treatment either. The one exception is
**AlterNative** (§8), a UPC-BarcelonaTech research project on public funding —
and no venue publication for it surfaced in DBLP, Scholar or Semantic Scholar,
only the project site.

Worth knowing as the classical analogue: the **Eiffel** line — [*Automated
Translation of Java Source Code to Eiffel*](https://doi.org/10.1007/978-3-642-21952-8_4)
(TOOLS 2011) and [*Automatic Translation of C Source Code to
Eiffel*](http://arxiv.org/abs/1206.5648) — rule-based, faithful, whole-program,
with an explicit no-hand-edits discipline.

### 11.5 Rule mining: where `min_instances_required = 3` comes from

This project asserts a three-instance threshold without citation. **The
literature supplies one.**

- [**Sydit**](https://people.cs.vt.edu/nm8247/publications/Meng2011.pdf) (PLDI
  2011) generalises a program transformation from a **single** example — and
  over-matches.
- [**LASE**](https://www.cs.utexas.edu/~mckinley/papers/lase-icse2013.pdf)
  (ICSE 2013) is the same authors' fix: generalise an edit script from
  **multiple** examples by anti-unification, *specifically to avoid over-fitting
  to one site*, then find every other site it applies to.

That is the empirical basis for the threshold, and for `rule_negative`.
Two more worth reading:

- [**Getafix**](https://arxiv.org/abs/1902.06111) (OOPSLA 2019, Facebook) —
  hierarchical clustering of mined edit patterns plus a **ranking model for
  when several rules match one site**. That problem is coming and there is a
  published answer.
- [**Revisar**](https://dl.acm.org/doi/10.1145/3474624.3474650) — mines rewrite
  rules from commit histories and emits **human-readable** rules. Rule
  *presentation* is an unsolved-looking part of the rulesdb design.
- [**ADELT**](https://www.ijcai.org/) (IJCAI 2023) — decouples skeleton
  transpilation from API-keyword mapping and measures the gain (+16 pts
  pass@1). Experimental validation of the three-layer split.
- [**Building Code Transpilers for DSLs Using Program
  Synthesis**](https://doi.org/10.4230/LIPIcs.ECOOP.2023.38) (ECOOP 2023,
  experience paper) — synthesises *the transpiler* rather than the output.
  CLAUDE.md's "build the converter, do not write the output" as a research
  result, with a write-up of what went wrong.

### 11.6 Abandonment and failure reports — the highest-value findings

**1. [*Aliasing Limits on Translating C to Safe Rust*](https://dl.acm.org/doi/10.1145/3586046)
(OOPSLA 2023).** The same group auditing its own OOPSLA 2021 tool (Laertes) and
reporting a hard ceiling:

> "Our novel evaluation methodology enables our study to extend beyond prior
> studies, and to discover new information **contradicting the conclusions of
> prior studies**. We find that existing translation methods are **severely
> limited by a lack of precision in the Rust compiler's safety checker**,
> causing many safe pointer manipulations to be labeled as potentially unsafe."

Their best result moves translatable-to-safe-reference pointers **from 12% to
21%**. Two things transfer. First, the bottleneck was *the target language's
checker*, not the analysis — a failure mode available to any Rust-targeting
translator. Second, they had to build a **new evaluation methodology** because
the old one had let over-optimistic conclusions stand. That is the same
argument as `verify_emit.py` and regenerate-and-diff: the reason those exist is
that this project already had two peripherals pass their traces while being
hand-written.

**2. [*Does BLEU Score Work for Code Migration?*](https://arxiv.org/abs/1906.04903)
(ICPC 2019).** The Nguyen group publishing that **their own field's headline
metric does not measure what it claims** — BLEU correlates poorly with semantic
correctness of migrated code. This is the direct historical precedent for
"instances-per-rule, not files translated", and evidence that a wrong headline
metric let an entire research line drift unnoticed. **The strongest available
citation for the metric discipline in PLAN.md.**

**3. [Corrode](https://github.com/jameysharp/corrode)** — a hand-written
rule-based C→Rust transpiler in Haskell, 2,188 stars, **last commit 2019**,
superseded by C2Rust. The abandonment is documented only in the repository, not
in the literature. The **absence of a post-mortem is itself the finding**: the
most-starred rule-based Rust transpiler died without recording why.

**4. [IRENE](https://arxiv.org/abs/2508.06926) (ICSME 2025)** states the
standard criticism of rule-based translation:

> "Early approaches in code translation rely on static rule-based methods, but
> they suffer from **limited coverage due to dependence on predefined rule
> patterns**."

**This project's entire thesis is the reply to that sentence** — rules mined
from the corpus rather than predefined, with instances-per-rule proving the
coverage. Quote it in PLAN.md and answer it.

**5. [EvoC2Rust](https://arxiv.org/abs/2508.04295) (ICSE 2026 SEIP)** states the
trade-off as settled:

> "rule-based methods often struggle to satisfy code safety and idiomaticity
> requirements, while LLM-based methods frequently fail to generate semantically
> equivalent Rust code… **Recent studies have revealed that both solutions are
> limited to small-scale programs.**"

**6. [SafeTrans](https://arxiv.org/pdf/2505.10708) (2025)** — first-shot LLM
translation succeeds **54%** of the time, rising to **80%** only with iterative
compile/runtime repair. A hard number on how much of "translation" is actually
error repair, useful for sizing the LLM budget.

### 11.7 Three papers to read before the next design decision

- **[Reboot](https://arxiv.org/abs/2606.27122)** (2026), *Mostly Automatic
  Translation of Language Interpreters from C to Safe Rust*. **Read this
  first.** Interpreters have the same shape as peripheral models — big dispatch
  switches, state machines, mutable shared state, tight test coupling — and the
  scale matches (6k–23k LoC vs. this project's ~16k). Its method is **feature
  reduction**: decompose by program *feature* into a chain of milestones where
  each milestone is a complete, compilable, testable program, simplest first.
  Six interpreters, **1–11 human interventions each**, 100% of provided tests
  passing. Ablation shows feature reduction beats multi-agent orchestration
  alone by 6–20 points. This is a direct generalisation of "withhold anything
  not yet emittable" and it has measurements attached.
- **[VERT](https://arxiv.org/abs/2404.18852)** (2024) — the strongest oracle
  design in the field. Compile source → WASM → Rust to obtain a *known-correct
  reference*, then bounded-model-check an idiomatic LLM translation against it.
  If this project ever needs to certify "the idiomatic version ≡ the faithful
  version", that is the pattern.
- **[FLOURINE](https://arxiv.org/abs/2405.11514)** (2024) — differential
  fuzzing for I/O equivalence with counterexample feedback, across C, C++, Go
  and Python to Rust. The cleanest published statement of equivalence-checking
  as a feedback loop, and the nearest thing to what trace replay does here.

Also worth noting because it is the same idea arrived at independently:
**[Syzygy](https://arxiv.org/abs/2412.14234)** translates code *and its tests*
together, using dynamic-analysis execution traces as the alignment signal —
the same combination of CodePorting's "translate the tests" and this project's
trace oracle.

### 11.8 Where this project sits

Three things follow from the survey, and they are the honest positioning:

1. **C# as a source for Rust translation is unpublished territory.**
2. **Emulator/peripheral-model translation is unpublished territory.**
3. **Corpus-mined translation rules is a 2010–2016 research line — conducted on
   C#, no less — that the LLM wave interrupted rather than refuted.** IRENE
   (2025) and TRAVEL (2026) are rediscovering rules-as-guidance from the LLM
   side. **Nobody has gone back and applied modern mining to the rule side.**
   That is the gap this project is in.

Two corrections to the issue's framing while here: **LLIFT** is not a
translation paper (it is LLM-assisted static analysis for use-before-init bugs
in the Linux kernel), and **[IntelLabs/IDEAS](https://github.com/IntelLabs/IDEAS)**
has no accompanying publication.

---

## 12. Adjacent targets, in depth

§10 corrected the IL2CPP premise. This section covers what the adjacent
translators are actually worth, and it contains the two most useful finds in
the whole survey after CodePorting.

### 12.1 IL2CPP — what it is worth, once the GC claim is dropped

Sources: Unity's eight-part *IL2CPP Internals* series —
[introduction](https://unity.com/blog/engine-platform/an-introduction-to-ilcpp-internals),
[a tour of generated code](https://unity.com/blog/engine-platform/il2cpp-internals-a-tour-of-generated-code),
[method calls](https://unity.com/blog/engine-platform/il2cpp-internals-method-calls),
[generic sharing](https://unity.com/blog/engine-platform/il2cpp-internals-generic-sharing-implementation),
[GC integration](https://unity.com/blog/engine-platform/il2cpp-internals-garbage-collector-integration) —
plus the [scripting restrictions](https://docs.unity3d.com/6000.4/Documentation/Manual/scripting-restrictions.html).

Mechanically, IL2CPP declines to map C# concepts onto C++ concepts:

- **Every method is a free C++ function.** C++ inheritance is used for *types*
  (`struct AnyClass_t1 : public Object_t`) but **never for method overriding**.
  Two hidden parameters on every method: `this` (NULL for statics) and a
  `MethodInfo*`. Dispatch goes through explicit `VirtFuncInvoker` /
  `InterfaceFuncInvoker` and a vtable lookup, not C++ virtuals.
- **Static fields live in a separate struct** so the GC can be handed them as
  roots; the C++ `static` keyword is deliberately unused.
- **Null and bounds checks are injected**, not signalled, because WebGL has no
  signalling mechanism.
- **Generic sharing**: all reference-type instantiations collapse to one
  `Object_t*` body; **value types get one instantiation each**, because sizes
  differ. Unity's own description of how the shared body typechecks:

  > "IL2CPP is **lying to the C++ compiler** to avoid the C++ type system.
  > Since the C# compiler has already enforced that no code does anything
  > unreasonable with type T, then IL2CPP is safe to lie."

**That last sentence is why IL2CPP is a weaker model for this project than it
looks.** Its central trick is a cast-based escape hatch from the target
language's type system. Rust does not offer that safely. The same shape in Rust
is `unsafe` plus transmute, and this project's whole premise is that it does not
need to go there.

**The one thing to steal from IL2CPP is the scope decision**, and it is
stated plainly:

> "We did **not** attempt to re-write the C# standard library with IL2CPP, and
> we could not be happier that we ignored it… when we investigate a bug we can
> be fairly confident that the bug is in either the AOT compiler or the runtime
> library, and nowhere else."

Scope discipline as a fault-localisation strategy. See §12.6 — it is the single
strongest predictor in this entire dataset.

Also worth taking: flag-driven codegen (`--emit-null-checks`,
`--enable-stacktrace`, `--output-format=Compact`) so safety checks and name
compaction are switchable rather than baked in; and their test posture, that
with clear inputs and outputs *"the vast majority of the bugs we see are not
unexpected behavior, but rather unexpected cases."*

Documented refusals: `System.Reflection.Emit`, `dynamic`,
`System.Diagnostics.Process`, threads on Web, generic instantiations not
discoverable at build time (needs a user-supplied `--extra-types.file`
manifest), reflection-driven serialization — and **exception filters
observably reorder relative to Mono**, because C++ exceptions are used. On
incremental builds: *"we don't have any good solutions yet."*

### 12.2 The rest of the .NET AOT family, and one deleted backend

- **NativeAOT / ILC** —
  [architecture](https://github.com/dotnet/runtime/blob/main/docs/design/coreclr/botr/ilc-architecture.md).
  Compilation is driven by a **dependency-analysis graph**: seed with roots,
  expand transitively, and *the reachable set is the output*. An optional **IL
  scanning pre-pass** runs the whole graph with a null codegen backend to
  stabilise vtable slot assignment **before** real compilation. **Steal both**:
  a dependency graph is a better compilation driver than iterating files, and a
  scanning pre-pass is a principled way to make output order deterministic —
  directly relevant to the `-j1` == `-j31` byte-identity requirement.
- **CoreRT's C++ backend was deleted.** `ILCompiler.CppCodeGen` shipped as an
  explicit "reference prototype" warning that *"portability comes at certain
  costs"*, choked on generic virtual methods
  ([corert#6147](https://github.com/dotnet/corert/issues/6147)), and the
  current BotR records that it *"wasn't brought over from the now archived
  CoreRT repo."* Only RyuJIT and LLVM survived. **Microsoft tried IL-to-source
  and abandoned it.**
- **[bflat](https://github.com/bflattened/bflat)** (3,963★, **AGPL-3.0** — note
  the licence) and **[zerosharp](https://github.com/MichalStrehovsky/zerosharp)**.
  The `--stdlib:zero` split plus `--no-reflection`, `--no-stacktrace-data`,
  `--no-globalization`, `--no-exception-messages` is the closest published model
  for "C# semantics on a no_std-ish target", and the features **degrade
  visibly** rather than vanishing: with those flags on, `typeof(int)` prints
  `EETypeRva:0x00048BD0` and `"Вторник".ToUpper()` is a no-op. zerolib has **no
  GC and no exception handling at all**; the author's verdict on the
  `no-runtime` sample is *"you're so severely limited it's rather pointless."*

### 12.3 Unity Burst / HPC# — the licence to restrict

**The most relevant precedent for a deliberately-restricted C# subset**, and
the one to cite when declining a construct.
[HPC# overview](https://docs.unity3d.com/Packages/com.unity.burst@1.8/manual/csharp-hpc-overview.html) ·
[type support](https://docs.unity3d.com/Packages/com.unity.burst@1.8/manual/csharp-type-support.html).

Banned, verbatim: *"Catching exceptions `catch` in a `try`/`catch`. Storing to
static fields except via Shared Static. Any methods related to managed objects,
for example, string methods."* Also out: `char`, `decimal`, `string`, **classes
and reference types entirely**, multi-dimensional arrays, general managed
arrays, `Enum.HasFlag`.

The detail that matters most here: **interfaces are supported only as
constraints on generic struct parameters** — monomorphised, never dynamically
dispatched. That is exactly how a Rust emitter should handle C# interfaces on
an embedded target: trait bounds, no `dyn`. Burst is the precedent for making
that a rule rather than a case-by-case judgement.

### 12.4 The common refusal set

Every AOT or subset C# compiler surveyed refuses the *same* things. This is a
ready-made, precedented list of constructs this project may decline without
inventing a justification:

1. `System.Reflection.Emit`, runtime codegen, `dynamic`, the DLR — universally.
2. Dynamic assembly loading; dynamically-constructed generic instantiations.
3. Generic instantiations not statically discoverable (manifest, or failure).
4. **Generic virtual methods** — an "orthogonal mechanism" everywhere, and the
   thing that broke CoreRT's C++ backend outright.
5. Value-type generics cost one instantiation each, always.
6. Reflection-driven serialization.
7. Reverse P/Invoke callbacks must be static and pre-registered.

The stricter subsets (Burst, zerolib) additionally drop **all reference types,
GC allocation, `catch`, mutable statics, strings, boxing, and dynamic interface
dispatch.**

### 12.5 The measured price of patching output — Sharpen / NGit

The single most load-bearing number found. [mono/sharpen](https://github.com/mono/sharpen)
(archived) translated Java to C#; [mono/ngit](https://github.com/mono/ngit) is
JGit ported through it. NGit carries **two** patch files:

| file | patches against | size |
|---|---|---|
| `gen/java.patch` | the **source** | **62 KB** |
| `gen/cs.patch` | the **generated** C# | **358 KB** |

Both re-conflict on every upstream pull. NGit is archived.

**Patching the output cost roughly six times what patching the input cost, and
it is what killed the project.** That is the zero-patches rule with a price tag
attached, and it should be quoted in PLAN.md next to CodePorting's statement.

CodePorting reached the same conclusion and built **three input-side escape
hatches** rather than ever touching output: `[CppWeakPtr]` attributes; a no-op
C# *service method* the translator substitutes with a hand-written target
implementation; and `//CPPCODE:` comments lifted verbatim into the target. All
three are worth having as rule-DB constructs here, since the C# itself is
upstream and cannot be annotated.

### 12.6 Why the graveyard is a graveyard — one cause of death

Every failed C#-to-native project in this survey died in the same place, and it
is not the language:

| project | died on |
|---|---|
| [Blackmire](https://github.com/ActiveMesa/Blackmire) | its own README: *"Declarations are processed, but definitions (i.e., what's inside methods) will in most cases yield junk."* |
| [ASDAlexander77/cs2cpp](https://github.com/ASDAlexander77/cs2cpp) | translating CoreCLR's real `System.Private.CoreLib` |
| [SharpNative](https://github.com/afrog33k/SharpNative) | async / LINQ |
| [AlterNative](https://github.com/AlexAlbala/Alter-Native) | reflection, serialization, lambdas, string switch |
| [anydream/il2cpp](https://github.com/anydream/il2cpp) | repo title: *"已弃坑. C#是个好语言，然而.NET不是一个干净的平台"* — "Abandoned. C# is a good language, but .NET is not a clean platform" |
| DotNetAnywhere | dropped for Mono because the **standard library**, not the instruction set, was the hard part |
| **IL2CPP** | **survived — by refusing to translate the standard library at all** |

**~16k lines of peripheral logic against a small fixed runtime surface is on
the right side of that line.** This is the strongest single predictor in the
dataset and it should be stated explicitly in PLAN.md as the reason this project
is expected to finish when those did not.

### 12.7 Source-level vs IL-level: settled, with a documented reversal

| | **IL/bytecode-level** | **source-level** |
|---|---|---|
| language coverage | free — every C# version, plus VB and F# | you owe the front end |
| lowering | already done by the vendor compiler | you reimplement iterators, async, closures, `lock`, LINQ |
| information | **destroyed** — `bool`→`int`, `char`→`int`, enums→ints, properties→calls, `switch`→jump table, loops rotated | intact and semantically resolved |
| readability | JSIL's author: *"did not survive contact with reality"* | the point of the exercise |
| outcome | **every IL-level project promising readable source is dead** — JSIL archived, CoreRT `--cpp` deleted, DotNetAnywhere inactive. Survivors (Blazor, IKVM) emit **binaries** | the live ones are all source-level: Transpose, go2cs, c2rust, CodePorting, depyler |

[JSIL](https://github.com/sq/JSIL)'s transform list is the receipt for what
IL-level costs: `HandleBooleanAsInteger`, `IntroduceCharCasts`,
`IntroduceEnumCasts`, `DeoptimizeSwitchStatements`,
`ConvertPropertyAccessesToInvocations`, `IntroduceVariableDeclarations`,
`EmulateInt64`, `EmulateStructAssignment` — ~35 passes, every one rebuilding
information the C# compiler had and discarded. Its author,
[in InfoQ](https://www.infoq.com/articles/jsil/): *"generating good JavaScript
from IL not only requires decompiling the IL, but **reversing some
optimizations performed by the compiler**… my approach is still ultimately
ad-hoc and based on partial knowledge."*

The strongest evidence is a **documented reversal**. Bridge.NET → h5 →
[Transpose](https://github.com/curiosity-ai/transpose) used NRefactory plus a
Roslyn `SharpSixRewriter` that lowered C# into "the subset of the C# language
that is supported by the transpiler". Transpose threw it out:

> "built entirely on **Roslyn**… **The legacy Bridge/NRefactory pipeline has
> been removed**… The emitter walks Roslyn syntax trees **guided by the
> semantic model** and emits JavaScript directly — there is no NRefactory and
> no `SharpSixRewriter` lowering pass."

**That is this project's emitter contract, arrived at by a team that lived with
the alternative.** Corroborated by [go2cs](https://github.com/ritchiecarroll/go2cs)
abandoning an ANTLR grammar for Go's own `go/types` (*"conversion decisions are
**semantic, not syntactic**"*) and by c2rust linking the real clang front end
rather than reading LLVM IR.

Counter-note worth heeding: [SharpKit](https://github.com/SharpKit/SharpKit)'s
README has asked for help *"replacing NRefactory with Roslyn"* for a decade.
**A front-end choice is not retrofittable once the emitter is written against
it.** This project has made the right choice; it just cannot change its mind
later.

### 12.8 GC to ownership: the strategy table, with success rates

Nobody solves it automatically. The honest options, and who paid for each:

| strategy | cost | who |
|---|---|---|
| **Refuse** — emit raw pointers, tell the user | output as unsafe as input | Tangible (*"complete memory deallocation is not included in the conversion"*); c2rust by design |
| **Universal refcount + human-annotated weak edges** | cycles leak; needs a human who knows where | **CodePorting** — *"the developer typically does not know which specific reference should be weak, nor that a cycle even exists"* |
| **Ship a tracing GC** | sidesteps cycles; costs a runtime | IL2CPP, anydream, AlterNative, IL2C |
| **Refcount + cycle collector** | middle ground | [IL2CXX](https://github.com/shin1m/IL2CXX) — and it **published pause-distribution graphs against .NET 6's GC** rather than asserting the choice |
| **Static ownership inference** | **Laertes: ~11% of raw pointers.** `c2rust-analyze`: *"only apply to a **small subset** of unsafe Rust code"* | Laertes, Crown, c2rust-analyze — after ~8 years and DARPA funding |
| **LLM** | *"Less than 20% of C programs over 150 lines could be satisfactorily translated by an LLM-based method without manual intervention"* | C2SaferRust, Flourine, VERT |
| **Restrict the subset so aliasing cannot arise** | eliminates the problem | **Burst (no reference types at all)**, zerolib, py2many, CS2X |

**The last row is the one this project should be aiming at**, and §10 already
names the question that decides whether it can.

### 12.9 depyler — the closest architectural twin, and it is three years ahead

**[paiml/depyler](https://github.com/paiml/depyler)** (357★) is a Python-to-Rust
transpiler that has **independently arrived at nearly this project's entire
process discipline**. Its [architecture](https://github.com/paiml/depyler/blob/main/docs/architecture.md),
[annotation syntax](https://github.com/paiml/depyler/blob/main/docs/annotation-syntax.md)
and [80/20 single-shot-compile doc](https://github.com/paiml/depyler/blob/main/docs/80-20-rule-single-shot-compile.md)
should be read before the next line of the rule engine is written.

- **"Jidoka: build quality in" — *don't fix the same bug twice*.** It names the
  failure mode in the same terms CLAUDE.md does:
  *"WASTE (Muda): Error → Oracle → LLM Fix → Ship → (same error tomorrow) → LLM
  Fix again. Cost: O(n) per unique error… Permanent dependency on expensive LLM
  inference."* versus *"JIDOKA: Error → Oracle → LLM Fix → `rule_patch.json` →
  Hardcode into transpiler → NEVER see that error again. Cost: O(1) per unique
  error pattern."*
- **A structured `rule_patch.json`** with `error_pattern`, `python_pattern`
  (ast_type + context + operation), `rust_fix` (strategy + template),
  `confidence`, `test_cases`, `source: "llm_claude_sonnet"`, `human_verified` —
  and a CLI to ingest and verify them against a corpus.
- **LLM usage as a *declining* metric**: calls per 1000 files 200+ → <100 →
  <20 → **<5**; repeat error rate → **<1%**. Their rule: *"**If LLM usage is
  not declining, the feedback loop is broken.** Stop and fix it."*
  **This project's scorecard has no such metric and should.**
- **Poka-yoke hard rejections** — the transpiler *fails the build* rather than
  emitting low-quality Rust. The list includes **`Rc<RefCell<T>>` without
  justification → "Ownership inference failure. Indicates Python-in-Rust
  antipattern"**, plus `Box<dyn Any>`, >3 clones per function, any generated
  `unsafe`.
- Ownership annotations on the *input* (`# @depyler: ownership = "owned" |
  "borrowed" | "shared"`, `interior_mutability = "none" | "arc_mutex" |
  "ref_cell" | "cell"`) — **converging independently on CodePorting's
  `[CppWeakPtr]` answer, for the same stated reason: output edits do not
  survive regeneration.**

**Two things to take verbatim**: the declining-LLM-usage metric, and treating an
emitted `Rc<RefCell<T>>` as a **reported ownership-inference failure** rather
than as a solution.

### 12.10 go2cs — upgrade the patch count to a disclosure ledger

[go2cs](https://github.com/ritchiecarroll/go2cs) (396★, active) translates Go to
C#. Three lessons, all documented, all bought expensively:

- On milestone honesty:
  > "A transpiler whose output merely **compiles** has proven very little, and
  > I've been on the wrong side of that lesson inside this very repo: the first
  > 'full standard library conversion' in 2025 meant only that the converter
  > didn't crash."
- One commit wrote the full machine conversion **on top of** the hand-finished
  baseline library (+508k lines), *"stalled the test loop"*, and took
  **thirteen months** to unpick. Their rule now: hand-written runtime lives in a
  directory **the converter is forbidden to write**. This project's
  `check_generated.py` enforces the converse; the forbidden-directory half is
  worth adding.
- **The disclosure ledger.** `go2cs_test_disclosures.json` pins every accepted
  divergence by **exact failure signature**, *"so any other failure of that test
  is still a hard mismatch."* **This is strictly better than a patch count**: a
  count tells you how much debt exists; a signature ledger stops an accepted
  divergence from masking a new regression. Recommended as a change to how
  patches are recorded.

### 12.11 Make the negative space a build artifact

Four independent mechanisms for the same problem — "what can the converter not
do?" — in increasing strength:

1. **anydream/il2cpp** — a declared unsupported-features section in the README.
   Prose; drifts.
2. **Tangible Software's C# to C++ Converter**
   ([FAQ](https://www.tangiblesoftwaresolutions.com/faq/csharp-to-cplus-converter-faq.html))
   — emits the untranslated C# verbatim beside a machine-greppable marker
   (`//ORIGINAL LINE:`) under a three-severity taxonomy: `TODO TASK` (gave up),
   **`WARNING` (translated, but semantics differ)**, `NOTE`. **The middle tier
   is the valuable one**, because it flags silent behaviour change no compiler
   will catch. Their best real example: *"The 'Compare' parameter of `std::sort`
   produces a boolean value, while the .NET `Comparison` parameter produces a
   tri-state result."* Compiles clean, silently misbehaves. **A `WARNING` tier
   belongs in this project's emitter output and on the scorecard.**
3. **[kekyo/IL2C](https://github.com/kekyo/IL2C)** — *"Following lists are
   auto-generated by unit test: Supported IL opcodes list / Supported basic
   types / Supported runtime system features."* **The coverage matrix is a build
   artifact generated from the passing test suite. It cannot drift and it cannot
   overstate.** This is the best idea in the tier and it fits `scorecard.py`
   directly.
4. **CS2X's Roslyn analyzer** (§5) — converts "the emitter can't do this" into
   "the input can't contain this", at authoring time.

### 12.12 ILSpy — the best-documented multi-pass source-translation engine

[ILSpy](https://github.com/icsharpcode/ILSpy) (25,753★, active) now ships
[`doc/DecompilerArchitecture.html`](https://github.com/icsharpcode/ILSpy/blob/master/doc/DecompilerArchitecture.html)
(July 2026). Pipeline: metadata → `DecompilerTypeSystem` → `ILReader` +
`BlockBuilder` → **ILAst** → ~40 ordered IL transforms → expression/statement
builders → **C# AST** → 15 AST transforms → `CSharpOutputVisitor`.

Four design tenets, all directly applicable:

1. **Round-trip correctness** — it embeds a full C# resolver and *re-resolves
   its own output while generating it*; a cast or qualifier is emitted only when
   the resolver proves omitting it changes meaning. The Rust analogue is
   emitting parentheses, casts and turbofish only where required, decided by
   the emitter rather than by defensive habit.
2. **Progressive raising through many small transforms** — *"There is no single
   clever algorithm… Transforms are strict pattern matchers: they fire only on
   shapes the compiler is known to emit, and leave anything else untouched."*
   That is a rule DB, described in other words, and "leave anything else
   untouched" is `rule_negative`.
3. **Graceful degradation** — unverifiable input becomes `InvalidBranch` /
   `InvalidExpression` nodes with warnings; a failed state-machine analysis
   leaves the method in its lower-level form. *"A method that cannot be
   prettified is still decompiled — just with gotos."* **The Rust analogue is a
   faithful-but-ugly fallback emission rather than withholding the method
   entirely** — worth considering against the current withhold-on-gap policy.
4. **Trees with checked invariants** — `CheckInvariant` runs after **every
   single transform** in debug builds, so *"the common failure mode of a
   forty-pass pipeline — pass 12 corrupts, pass 31 crashes — largely
   disappears."*

Plus a `Stepper` that re-runs decompilation stopped after any transform (a
debugging affordance worth having), ~150 feature flags where a disabled
transform simply does nothing, and the rule that matters most:

> **"Tests as the real specification: a transform PR without a fixture is
> architecturally incomplete — the fixture is the pattern's definition."**

That is `min_instances_required` stated as a review rule.

### 12.13 `IOperation` — no ruts in this road, and Roslyn's own breadth check

`IOperation` is the language-agnostic semantic tree over C# and VB: ~150
operation kinds, each node carrying `Kind`, `Type`, `ConstantValue`,
`IsImplicit` (compiler-generated), `Syntax`, `SemanticModel`, `Parent`, and
`Descendants()` **in evaluation order**;
`Microsoft.CodeAnalysis.FlowAnalysis` adds a lowered `ControlFlowGraph`.

Two facts to know:

- **No existing transpiler is built on `IOperation`.** It is designed for
  analyzers. This project is on a road with no ruts — which is an advantage on
  fidelity (it is the compiler's own lowered semantics) and a risk on API
  stability: the docs say *"This interface is reserved for implementation by
  its associated APIs. We reserve the right to change it in the future."*
- **Roslyn runs the exact breadth check this project runs.** Its
  [IOperation Test Hook](https://github.com/dotnet/roslyn/blob/main/docs/compilers/IOperation%20Test%20Hook.md)
  enumerates every syntax node in every test compilation and *"verif[ies] that
  `GetOperation` does not crash, and returns information that matches up with
  the `SemanticModel`… We also fetch and verify the control flow graph for every
  member body and run the CFG verifier."*

  Roslyn's rule for what to do with a gap it finds is worth adopting verbatim:
  a new node either gets `IOperation` support **in the same PR**, or it goes
  into a catch-all with a `prototype` comment **that must be resolved before
  merging**. That is precisely the right framing for `--all`: a crash and
  data-loss check whose findings are tracked prototype markers, **never a work
  item generator** — which is what CLAUDE.md already says, now with the
  compiler team's own precedent behind it.

---

## 13. Verdict and what to take

### The claim

**"No C#-to-Rust transpiler exists" holds.** The original conclusion was
right; the reasoning behind it was not strong enough to rely on. It is now
supported by:

- GitHub repository and code search, 20 distinct queries
- thirteen non-GitHub sources — GitLab, Codeberg, sr.ht, SourceForge, grep.app,
  crates.io, NuGet, Software Heritage, HN, Reddit, users.rust-lang.org,
  Stack Overflow, Lobsters
- two independent human-curated transpiler cross-references, both of which
  record obscure pairs like Clojure-to-Rust and C#-to-Fortran and neither of
  which has a C#-to-Rust entry
- the commercial C#-translation market, where the incumbent ships C++, Java and
  Python and no Rust
- the academic literature — Google Scholar's exact phrase `"C# to Rust"`
  returns **two** documents, neither a translation method (§11)

Caveated: **Bitbucket** and the **Google Code Archive** are not anonymously
searchable, **searchcode.com** no longer does code search, arXiv's index
**cannot represent the token `C#`**, and ACM DL / IEEE Xplore full-text were
not swept. None of these plausibly hides an active project, but the gaps are
recorded rather than glossed.

The three original dismissals were all correct. `rustlyn` is a Roslyn
language-server shim, `csharp-compiler-rust` emits IL, and the web converters
are LLM prompts. Add `cs2rust` (a Counter-Strike 2 overlay) and
`rust2sharp-translator` (self-described "useless") to the lookalike pile.

### What is worth stealing, in priority order

1. **CodePorting's rule: fix the translator, never the output** — with
   **Sharpen/NGit's price tag attached** (§12.5). CodePorting derived it under
   commercial release pressure at millions of lines per month, after trying the
   alternative. NGit measured what the alternative costs: **62 KB of patches
   against the source versus 358 KB against the generated output**, both
   re-conflicting on every upstream pull, project now archived. Direct external
   validation of the zero-patches metric, twice, and it belongs as a citation in
   PLAN.md rather than as a house opinion.
2. **Use the tests as a second oracle — and here that is cheaper than
   CodePorting had it.** Their move was to translate the C# tests alongside the
   C# code. Checking the Renode tree, that maps badly and well at once:
   `tests/unit-tests/RenodeTests` is only 25 C# files and is mostly
   `PlatformDescription` parser tests, so there is little peripheral behaviour
   to translate. But `tests/` holds **265 Robot Framework `.robot` files**,
   including `tests/peripherals/*.robot` and per-platform suites, and those
   drive the emulator through its CLI — **they are already language-neutral and
   need no translation at all**. The work is CLI compatibility, not
   translation. That is oracle tier 5 in `STATUS.md` (issue #25), and this
   survey raises its priority: it is the cheapest large oracle available and
   the only one that exercises whole-platform behaviour a per-peripheral trace
   cannot.
3. **Emit through a modelled Rust AST, not strings** — Fable's
   `Rust.AST.Types.fs` is a transcription of rustc's `ast`. This is the
   mechanism that makes "byte-identical at `-j1` and `-j31`" a property rather
   than a hope.
4. **Publish the supported subset as a Roslyn `DiagnosticAnalyzer`** — CS2X's
   `CS2X.Analyzer`, shipped as a VSIX with messages like *"CS2X ERROR: Runtime
   does not support boxing"*. It turns the withheld-construct list from an
   emitter internal into a reviewable, testable artefact.
5. **Settle the object-lifetime question from the corpus before the emitter
   grows** (§10). Every predecessor that got this wrong got it wrong late.
6. **Pin generated files to the upstream commit they were derived from**, as
   QEMU does per Rust device. Drift becomes checkable.
7. **A support crate shaped like the source library, not idiomatic mappings** —
   the one call CodePorting and Fable made independently and identically.
8. **If `Rc` ever enters emitted code, budget the leak oracle at the same
   time**: debug-mode object registry, translator-emitted "what does this
   object hold" reflection, cycle and isolation-island dumps. CodePorting's
   verdict was that the mapping is not fully automatic and the tooling is what
   makes it survivable.
9. **Cite the literature the design is already asserting.** `min_instances_required = 3`
   has a published basis (Sydit's single-example over-matching → LASE's
   multiple-example anti-unification); the instances-per-rule metric has a
   published precedent (*Does BLEU Score Work for Code Migration?*); the
   three-layer split has an experimental validation (ADELT). Uncited house
   rules are the ones that get quietly dropped under schedule pressure.
10. **Read *Reboot*'s feature-reduction method before the next phase plan.**
   Interpreter-shaped code, matching scale, milestone-per-feature where each
   milestone is a complete compilable testable program, and measurements.

### Four concrete changes this survey recommends

Distinct from "read this" — these are edits to existing artefacts.

- **Add a declining-LLM-usage metric to `scorecard.py`.** depyler tracks LLM
  calls per 1000 files (200+ → <100 → <20 → **<5**) and repeat-error rate
  (→ **<1%**), with the rule *"if LLM usage is not declining, the feedback loop
  is broken. Stop and fix it."* This project's cost argument is
  once-per-cluster; nothing currently measures whether that holds over time.
  Instances-per-rule detects drift into per-file *rules*; it does not detect
  drift into per-file *LLM calls*.
- **Upgrade the patch count to go2cs's disclosure ledger** (§12.10). Pin every
  accepted divergence by **exact failure signature**, so any *other* failure of
  that test is still a hard mismatch. A count says how much debt exists; a
  signature ledger stops an accepted divergence masking a new regression.
- **Generate the supported-construct matrix from the passing test suite**, as
  IL2C does (§12.11). A hand-maintained "what we support" list drifts and
  overstates; one generated from green tests cannot.
- **Add a `WARNING` tier to emitter output** — Tangible's middle severity:
  *translated, but semantics differ*. `TODO` (gave up) is already covered by
  withholding. The dangerous class is the construct that emits, compiles, and
  behaves differently — and nothing in the current pipeline names it.

### What to refuse

- **One LLM call per declaration**, however good the repair loop
  (`CSharp-toRUST-Assistant`). It is the cost model this project exists to
  avoid, and "it compiles" is not an equivalence check.
- **Template-based emission** (`libldt3-transpiler`). Fine for schemas,
  hopeless for behaviour.
- **Translating without a fidelity oracle.** OneLang's author wrote down what
  that becomes: a tool that "does not respect" the rules of the input language.
  It has 1,142 stars and has been dead since 2023.

### The one prediction this survey makes

Every failed C#-to-native translator in §12.6 died in the same place: the
standard library and the long tail of language features it drags in. IL2CPP is
the survivor, and it survived by refusing to translate the BCL at all.

**~16k lines of peripheral logic against a small fixed runtime surface is on
the right side of that line.** That should be stated in PLAN.md as the reason
this project is expected to finish, because it is the strongest single
predictor in the dataset — and because if the scope ever creeps toward "and
also the rest of Renode", the prediction inverts.

### What is actually distinctive here

Not the oracle on its own. The research literature has stronger oracles than
this project's: VERT bounded-model-checks against a WASM-derived reference,
Heimdall proves 94.1% of translated eBPF programs equivalent with symbolic
execution and Z3, FLOURINE differential-fuzzes for I/O equivalence, RustAssure
does differential symbolic testing. Claiming novelty for trace replay would be
wrong.

What is distinctive is the **combination**, and specifically which half is
missing everywhere else:

- **The shipped tools have no oracle.** CS2X had none. Fable tests its own
  output against its own tests. CodePorting got closest — translating the C#
  tests — and still needed manual `[CppWeakPtr]` annotation. IL2CPP's check is
  "does the game run".
- **The research tools with strong oracles have no rule corpus.** They are
  LLM-per-function or analysis-per-program. None mines rules from a corpus and
  none measures instances-per-rule; the one line that did mine rules (Nguyen
  et al., on C#) was measured with BLEU, which its own authors then showed does
  not work.

**Mined rules plus a mechanical equivalence check plus a drift metric is the
cell in the table nobody has occupied.** That is also why the standard
objection — "transpiled Rust is unusable, look at c2rust" — does not land here.
Unusable output is a claim about idiom. This project is not selling idiom; it
is selling equivalence, and unlike every shipped translator surveyed, it can
prove it.

---

*Compiled 2026-08-01 for issue #43. All searches re-runnable from the queries
in §2, §9 and §11.*
