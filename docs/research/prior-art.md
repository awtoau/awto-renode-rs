# Prior art: has anyone built a C#-to-Rust transpiler?

Answers issue #43 (T-R6). Research note, no code.

**Verdict: the claim holds. No C#-to-Rust source translator exists** — not on
GitHub, not on any other forge, not in the academic literature, not as a
commercial product. What exists is one alpha-quality *F#*-to-Rust compiler
(Fable), a family of C#-to-*other-language* translators, and a large number of
LLM snippet converters.

The negative result is not the interesting part. The interesting part is that
three unrelated teams — one commercial, one open source, one a lone developer
over eight years — each attacked "C# source to a language without a garbage
collector" and each left a written record of exactly which part defeated them.
It is the same part in all three cases, and it is not the syntax.

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
| `topic:transpiler csharp` | search API | 47 — the main seam, see §5 |
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
SearchCode, crates.io, NuGet) and the academic literature were surveyed
separately; see §7 and §8.

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
(0 stars, created and last pushed 2026-06-28 — one day of work, 47 KB).

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

**What to note as a warning**: Fable has had a Rust backend since 2022 and it
is still Alpha, with 259 KB of emitter for a language far simpler than C# — no
inheritance, no mutable-by-default fields, no `unsafe`, no `partial`. Emitter
size is not the risk; the long tail of semantics is.

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
| [AlexAlbala/Alter-Native](https://github.com/AlexAlbala/Alter-Native) | C++ | ILSpy/NRefactory | 162★, dead since 2020 |
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
