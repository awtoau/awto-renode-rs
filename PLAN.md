# renode-rs — pattern-learning C#→Rust translation of Renode, ARM/STM32F427 first

Plan drafted 2026-07-31. Method deliberately modelled on `linux-rs` (a sibling
project doing the same for C→Rust on the Linux kernel): faithful line-by-line
translation first, optimisation as a separate later pass, and every manual fix
generalised into a rule rather than landed as a one-off patch.

## End goal

A Rust emulator that boots a real **STM32F427VGT6 (Cortex-M4F, hard-float)
firmware** to an interactive shell and drives its CLI test suite — i.e.
reproduces what an existing C# Renode setup already achieves, but in Rust, with
a differential oracle against the C# original at every step.

That target is chosen because it is **already proven and already instrumented**.
The reference setup documents a full boot matching hardware in order (clock →
CAN → RTC/LSI → shell UART → OTP identity → FreeRTOS → banner → `system_boot OK`
→ prompt), a `help` command driven through CPU hooks, and an `otp` command
driven end-to-end over CAN ISO-TP. We are not chasing an unproven target; we are
re-implementing a known-good one with a byte-exact reference to diff against.

Scope is **ARM Cortex-M / STM32F427 only**. Every other architecture, board and
peripheral in Renode is out of corpus.

## Thesis

Renode is not 486k lines of unique logic. Measured on the current tree (v1.16.1,
`dc52b24c`, 1,968 `.cs` files, 485,893 lines), the F427-reachable subset is
**~13k lines of peripheral code over ~22 types**, and most of that is
*declarative register description* expressed through one fluent DSL with a
**20-method surface**.

So the leverage is not "translate 13k lines". It is:

1. **Translate the DSL once.** `PeripheralRegisterExtensions` exposes exactly 20
   `With*` combinators (`WithFlag`, `WithValueField`, `WithEnumField`,
   `WithTaggedFlag`, `WithReservedBits`, `WithReadCallback`, `WithWriteCallback`,
   `WithChangeCallback`, the `*Many`/`*s` plural forms, and the
   `ConditionallyWritable` variants). Get those right in Rust and a large
   fraction of every peripheral file translates by rule, not by hand.
2. **Learn rules, not files.** A solved construct becomes a general pattern→Rust
   rule validated against *all* structurally equivalent occurrences in the corpus.
3. **The rule DB is the product.** The F427 emulator is the proof it works.

### The measurement that makes this credible

DSL density across the F427 peripheral set — `With*` call count against file
length:

| Peripheral | Lines | `With*` calls | Character |
|---|---:|---:|---|
| `STM32F4_RCC` | 404 | 240 | almost purely declarative |
| `STM32F4_RTC` | 1188 | 153 | declarative + timekeeping logic |
| `STM32_Timer` | 1013 | 125 | declarative + counter logic |
| `STM32_ADC` | 338 | 86 | declarative |
| `STM32SPI` | 366 | 61 | declarative |
| `STM32DMA` | 425 | 63 | declarative + transfer engine |
| `STM32_UART` | 295 | 56 | declarative + FIFO/IRQ logic |
| `STM32_GPIOPort` | 376 | 48 | declarative |
| **`STMCAN`** | **1957** | **1** | **legacy hand-written, switch-on-offset** |

The corpus splits into two populations, and the split is the plan:

- **DSL-style peripherals** — high rule leverage, translate near-mechanically.
- **Legacy hand-written peripherals** — `STMCAN` is the outlier, 1957 lines with
  a single DSL call. It is also, not coincidentally, where two of the four
  defects below live. Low leverage, high care, human review.

## The case for doing this at all

Four Renode defects blocked the target firmware's boot outright, each traced to
an exact file and line during the C# Renode bring-up:

| Defect | Class |
|---|---|
| `STM32_CRC.UpdateCRC` throws `NullReferenceException` on first `CRC_DR` write — `reverseInputData` is assigned only when `ReversibleIO` is true, which F4 is not; dereferenced unguarded at line 156 while its siblings use `?.` | **Null-handling. Eliminated by construction in Rust** — `Option<T>` cannot be silently `.Value`'d. |
| `STMCAN` fabricates a bus error whenever `FrameSent == null` (no hub attached), and drives SCE as a level rather than latching through `MSR.ERRI` — interrupt storm, no task ever runs | **Null-as-sentinel + state-machine error.** The null half is a typestate problem Rust's `Option`/enum modelling makes explicit. |
| `STMCAN` never sets `MSR.INAK` — the model requires `InitRequest && !SleepRequest`, real silicon gives INRQ priority | Logic error. Translates as-is; found by comparison against silicon, not by the port. |
| `STM32F4_FlashController` cannot address bank 2 — sector table stops at 11, `SNB` defined 4 bits where F42x/43x is 5 | Wrong constant. Translates as-is. |

Two of four are null-handling defects that the Rust type system forecloses.
That is a concrete, evidenced argument — not a theoretical one — and it is the
accurate headline: the port does not fix logic bugs, it fixes a *class* of bug.

## Performance is a first-class goal, not a Phase-5 afterthought

The second motivation, and on current evidence the stronger one: **C# Renode is
slow on exactly the workload this target generates, and the cause is
architectural rather than incidental.**

### The measured case

The firmware's LSI-measurement routine spins on `TIM5->SR` up to 500,000 times
per edge across 130 edges — order 65 million MMIO reads. On hardware it takes
~30 ms. Under C# Renode it took **~27 seconds of wall time**, dominating boot and
completing only because the firmware is defensively coded with guard counters.
Steady-state the simulator runs at ~0.3× real time, ~50 MIPS against a 168 MHz
Cortex-M4.

### Why, traced through the source

`STM32_Timer` calls `cpu.SyncTime()` in its counter path
(`STM32_Timer.cs:198`, `:331`). `TranslationCPU.SyncTime()` is:

```
TlibGetExecutedInstructions()   → P/Invoke across the managed boundary into tlib
ReportProgress(...)             → the multithreaded TimeHandle state machine
```

So a single register poll costs a managed↔native transition plus a walk through
quantum negotiation and handle bookkeeping. That is not a bug — the timer's value
genuinely depends on elapsed virtual time, and virtual time only advances when
the CPU reports progress, so the sync is semantically required. **The cost is in
how it is implemented, and every part of that implementation is something the
port removes.**

### Where the Rust wins come from, in expected order of size

1. **No managed boundary.** tlib→Rust is a direct C ABI call; the instruction
   counter can be a shared memory location Rust reads with a plain load, making
   it *no call at all*. C# pays P/Invoke marshalling and a GC transition per
   access.
2. **Time sync collapses under D3.** Single-threaded, the handle state machine
   becomes `virtual_time += delta` and one deadline comparison.
3. **Cache-resident peripheral state (D2).** A whole peripheral's register fields
   in ~5 contiguous cache lines means a polling loop runs entirely out of L1. The
   naive `Rc<RefCell<_>>`-per-field design would scatter ~240 allocations across
   the heap for RCC alone and touch 2–3 lines per field read.
4. **Lazy evaluation as a design rule** (below).
5. **No GC**, and no allocation on the access path.

### Design rule: peripherals are pure functions of virtual time

A timer's counter is `f(virtual_time, start, frequency, limit, mode)` — pure
arithmetic. Nothing needs to be "ticked" per cycle; values are computed on demand
and the only scheduled work is the *next deadline*. Renode's `BaseClockSource`
already does this in principle, but wraps it in machinery that costs more than
the computation it protects.

This rule is stated up front because it constrains the translation: where the C#
computes a value through clock-source indirection, the Rust computes it directly,
and that is a **declared deviation** to be recorded, not a silent improvement.

### The measurement obligation

None of the above is proven, and the plan must not assume it. **Phase 0 carries a
performance spike (#P1) that is a genuine gate**: profile C# Renode on the LSI
case to get the real split between tlib execution, the managed boundary, the time
framework, address decode and register dispatch; then microbenchmark the same
MMIO path in a throwaway Rust prototype.

If the Rust MMIO path is not dramatically faster in that spike, the performance
motivation evaporates and this becomes a safety-only project — which materially
changes whether it is worth doing. Better to learn that in week one.

**Scaling metrics tracked from Phase 0 onward:** MMIO accesses/sec,
instructions/sec, and the MMIO:instruction ratio — polling-heavy firmware has a
high ratio, and that ratio is what this target's performance actually depends on.

## Prior art, and the c2rust question answered

**Can we use c2rust as a framework and swap the backend?**

Short answer: **no for the C#, yes for tlib — and tlib is the bigger surprise.**

### c2rust is not reusable for C#

c2rust's pipeline is `c2rust-ast-exporter` (C++ linked against libclang, walks
the clang AST → CBOR) → `c2rust-transpile` (CBOR → `TypedAstContext` → translator
→ Rust AST) → `c2rust-ast-printer`.

The middle stage is the whole value, and it is **C-shaped to the bone**.
`CDeclKind` / `CExprKind` / `CTypeKind` model C integer promotion, bitfields,
unions, designated initialisers, `goto`/labels, `va_arg`. They have no concept
of classes, interfaces, generics, virtual dispatch, properties, events,
delegates, exceptions, GC, LINQ, `async`, or closures with captured state. You
would delete ~95% of it, and the surviving 5% (Rust AST construction and
printing) is better served today by `syn` + `quote` + `prettyplease` off
crates.io.

### What *is* worth taking from c2rust

Four things, all design rather than code:

1. **The two-process split with a serialised IR.** c2rust uses C++/clang → CBOR
   → Rust because the only good AST library for the source language lives in a
   foreign runtime. Exactly our situation: Roslyn is .NET, our emitter is Rust.
   Copy the shape: `Roslyn (C#) → JSON/CBOR → Rust emitter`.
2. **`WithStmts<T>`** — c2rust's abstraction for "this source expression needs
   hoisted statements before it can be a Rust expression". C# has the same
   problem (property getters with side effects, `??=`, ternaries containing
   statement-shaped work, `out` parameters in expression position). The design
   transfers directly and is the single most reusable idea in the codebase.
3. **The name manager** — scope-aware renaming, reserved-word collision handling.
4. **Per-TU → crate/module structuring logic.**

### Roslyn is a better frontend than c2rust ever had

The decisive point: **Roslyn's `IOperation` API is already the `TypedAstContext`
that c2rust had to hand-build.** It is a lowered, language-agnostic tree with
`foreach`, `using`, `lock`, LINQ query syntax, object initialisers and pattern
matching already desugared, with full type resolution and nullability
annotations attached. c2rust's authors built their IR because clang gave them
nothing equivalent. We do not have to.

So the frontend is `Microsoft.CodeAnalysis` walking `IOperation`, emitting our
own serialised IR. That is a build, not a fork.

### tlib is C — and that is the real c2rust opportunity

Renode does **not** interpret ARM itself. The CPU is `tlib`, a C fork of QEMU's
TCG, vendored under `src/Infrastructure/src/Emulator/Cores/tlib`: **227,771 lines
of C** total, of which the ARM-relevant slice is `arch/arm` (31,727) + core
(5,827) + `tcg` (14,440) ≈ **52k lines**.

This is the single most important scoping fact in the plan, and it cuts two ways:

- **c2rust is exactly the right tool for tlib** — it is C, and there is already a
  hardened fork at [`awtoau/c2rust`](https://github.com/awtoau/c2rust).
- **But we should not translate tlib in Phase 1 anyway.** TCG is a JIT;
  c2rust-ing a JIT yields a Rust program that still JITs through the same
  machinery, with none of the safety benefit and all of the review cost. More
  importantly, *keeping tlib byte-identical is what makes the differential oracle
  exact* — if the CPU is the same code on both sides, every state divergence is a
  peripheral bug, not a CPU bug.

**Phase 1 decision: FFI to tlib, unchanged.** Renode reaches it through P/Invoke;
Rust reaches it through `extern "C"`, which is strictly simpler.

**But tlib is not a good long-term answer, and that is tracked separately (#P2).**
Its ARM translator carries Fabrice Bellard (2003, 2008), CodeSourcery (2005–2007)
and OpenedHand (2007) copyrights — QEMU 0.9/1.0-era TCG — and the entire 227k-line
tree contains **one test file**, which tests a hash table. There is no
instruction-level test infrastructure at all, and TCG's structure is why: it is a
JIT, so instruction semantics are code that *emits* host code, and you cannot
unit-test an instruction without running generated machine code.

The decisive question is whether instruction dispatch is even on the critical
path. If the #P1 profile says the cost is the MMIO path rather than execution,
then the JIT buys little and costs a great deal in opacity — and a plain Rust
Thumb-2 interpreter, one testable pure function per instruction, becomes the
better trade. Cortex-M is a small, regular ISA and Renode manages only ~50 MIPS
with a JIT today.

Also worth stating because it applies whichever way #P2 lands: we have the
physical STM32F427 and SWD tooling, so **random-instruction differential testing
against real silicon** is available to this project. That is the gold-standard
way to validate a CPU model, and it would be the first real test coverage tlib
has ever had.

### Other prior art

| Project | Relevance |
|---|---|
| **c2rust** (Immunant) | Architecture and `WithStmts`; the transpiler itself is for tlib only, not C# |
| **`awtoau/c2rust`** | Existing hardened fork — reusable for tlib if that phase ever runs |
| **Roslyn** | The frontend. `IOperation` is the IR we would otherwise have to build |
| **`syn` / `quote` / `prettyplease`** | Rust AST construction and emission; replaces `c2rust-ast-printer` |
| **linux-rs** | The method: faithful-first, rule-learning, layered oracle, mixed system that works at every step |
| **QEMU / tlib** | The CPU, kept as-is via FFI |

Prior-art check still owed (Phase 0): whether anyone has published a C#→Rust
translator beyond toy scale, and whether any Rust deterministic-emulator
framework is worth building on rather than porting onto.

## Translation discipline: faithful, not clever

- **The oracle certifies equivalence, never improvement.** Every tier compares
  Rust against C# Renode running the same firmware.
- **Optimisation is a separate pass**, gated on a clean differential record.
- **Deviations are never silent.** Where Rust forces a difference it is recorded
  with justification. The declared deviations are listed below — there are four,
  and they are decided once, globally, not per file.
- **Not literally line-by-line**: structure maps (properties become methods,
  `foreach` becomes iterators, LINQ becomes iterator chains) but semantics,
  side-effect order and error behaviour must not change.

## The four declared deviations

These are the whole-program decisions that cannot be made per-file. Deciding
them wrong is the main way this project fails, so they are made explicitly, up
front, with the reasoning recorded.

### D1 — Object graph: `Rc<RefCell<T>>`, cycles leaked

Every C# reference-typed field becomes `Rc<RefCell<T>>` (or
`Option<Rc<RefCell<T>>>` where C# permits null). Renode's graph is cyclic by
construction — the machine owns peripherals, peripherals hold `IMachine`
back-references, GPIO cross-links both ways — so reference cycles are
unavoidable and **leaking them is correct**: the machine is built once and lives
for the process, which then exits.

*Rejected alternative:* arena + index handles. Better in every way except
faithfulness, and it is a whole-program refactor. It is the **named Stage-3
lift**, run after the differential record is clean, not before.

*Known risk:* `RefCell` panics on re-entrant borrow. The real exposure is
peripheral → sysbus → peripheral (e.g. DMA reading memory through the bus while
the DMA peripheral is itself borrowed). A `RefCell` panic here is not
necessarily a C# bug — it can be legitimate re-entrancy that C# tolerates. This
needs a borrow discipline decided in Phase 0 (likely: never hold a borrow across
a bus call), and it is the highest-risk item in the plan.

### D2 — Register fields: `Cell` in a contiguous arena, handle is a typed index

`out IFlagRegisterField receiverEnabled` in a fluent chain gives the peripheral a
handle into storage the register collection also owns. The obvious literal
mapping is one `Rc<RefCell<_>>` per field — and it is **the wrong choice, for
performance reasons that dominate this project** (see "Performance is a
first-class goal" above).

Register fields are *all* `Copy` scalars: `IValueRegisterField` is a `ulong`,
`IFlagRegisterField` a `bool`, `IEnumRegisterField<T>` a small enum. That is
exactly what `Cell` exists for.

**Storage:** one contiguous `Vec<Cell<u64>>` (or a fixed inline array) per
peripheral. **Handle:** a typed index — `FlagFieldId(u16)`, `ValueFieldId(u16)` —
stored in the peripheral struct.

Why this rather than `Rc<RefCell<_>>` per field:

| | `Rc<RefCell<Field>>` per field | `Cell` arena + index |
|---|---|---|
| Allocation | one heap allocation *per field* — RCC defines ~240 | one, per peripheral |
| Per-field overhead | 16 B refcounts + 8 B borrow flag + payload, scattered | 8 B payload, contiguous |
| Read cost | pointer chase → borrow-flag check (branch + write) → load | one indexed load |
| Cache behaviour | a poll touches 2–3 lines, likely missing | a whole peripheral's fields fit in ~5 lines; a polling loop stays in L1 |
| Borrow panics | possible | **impossible** — `Cell` has no borrow flag |
| `Send` | blocks it | permits it |

**This costs nothing in faithfulness.** The DSL is the abstraction boundary —
peripherals never touch storage directly, they go through field handles — so the
translated peripheral code reads the same either way. Same semantics, better
layout, and it removes D1's re-entrancy hazard from the single most numerous
object in the system.

This is the highest-value single rule in the DB: it covers every `out` parameter
in every `With*` call across the entire corpus.

### D3 — Threading: single-threaded *within* an instance, parallel *across* instances

Renode is multithreaded — `TimeSourceBase` (1041 lines), `TimeHandle` (935),
`SlaveTimeSource`, `MasterTimeSource`; roughly 2k lines of the 6,277-line time
framework is thread-coordination machinery, and that machinery is on the hot
path (`SyncTime` → `ReportProgress` → the handle state machine).

**Recommendation: single-threaded within one machine.** The reasoning is
performance-led, not just simplicity-led:

1. **Intra-instance parallelism does not pay for a single-core MCU.** There is
   one CPU. Peripherals could in principle tick on other threads, but every
   interaction point needs synchronisation, and a polling loop drives the
   interaction rate through the roof. This is the standard result in emulator
   design — QEMU's MTTCG parallelises *guest cores*, not guest peripherals, for
   exactly this reason. With one guest core there is nothing to parallelise.
2. **The thread-coordination machinery is itself a major cost.** Single-threaded,
   `ReportProgress` collapses from a blocking quantum negotiation to
   `virtual_time += delta` plus a comparison against the nearest deadline.
   Removing threads is a *performance optimisation here*, not a compromise.
3. **Determinism is the product**, and it is easier to guarantee without threads.

**The parallelism that does pay is N independent instances** — the CLI test suite
running 16 emulators on 16 cores. Embarrassingly parallel, no shared state, and a
far bigger win for test wall-clock than anything intra-instance. That needs the
machine to be either `Send` (movable to a worker thread) or process-isolated;
processes work today and are the fallback, but note that D1's `Rc` blocks `Send`
while D2's arena permits it — a further reason the arena direction matters.

This is the one place the plan knowingly departs from "faithful", and it is
recorded as such. It should be **re-validated against the Phase-0 profile**
(#P1) rather than assumed.

### D4 — Exceptions → `Result`, panics for the fatal

Renode's `RecoverableException` / `ConstructionException` become
`Result<T, RenodeError>` threaded with `?`. What C# treats as fatal
(`NullReferenceException` and friends) becomes a panic. Note that the
`STM32_CRC` defect above *is* a fatal C# exception that aborts the emulator
process — in Rust that construct does not compile, which is the point.

## The remaining C#→Rust mappings

Mechanical once D1–D4 are fixed. These become the initial rule DB:

| C# construct | Rust, literal-first |
|---|---|
| `class` instance | `Rc<RefCell<T>>` (D1) |
| Inheritance (`BasicDoubleWordPeripheral`) | Composition: base as a struct field + trait with default methods. Measured trivial — the base is 49 lines and provides `RegistersCollection` plus three forwarding methods, not real polymorphism |
| `virtual`/`abstract` | Trait objects (`Rc<RefCell<dyn Peripheral>>`) |
| Properties | Getter/setter methods |
| `event` / `Action<T>` | `Vec<Box<dyn FnMut(T)>>`; `Option<Box<dyn Fn>>` for single-subscriber |
| `null` | `Option<T>` |
| LINQ | Iterator chains (`.Where`→`.filter`, `.Select`→`.map`, `.Any`→`.any`, `.ToList()`→`.collect()`) — deferred-execution semantics match |
| Generics + constraints | Rust generics + trait bounds; `where T : new()` → `Default` |
| `lock(obj)` | Removed under D3; `Mutex` if D3 is reversed |
| `enum : long` register offsets | `const` or `#[repr(u64)] enum` |
| Reflection (`RegisterMapper(this.GetType())`, `.repl` loading, monitor binding) | **Not translated.** Hand-written compile-time registry — the class-1 "stays hand-written forever" bucket |
| `[Transient]` / Migrant serialisation | Dropped in Phase 1; save/restore is out of scope |

## Corpus census (measured, not estimated)

Renode v1.16.1, commit `dc52b24c`.

**In corpus — peripherals (~13k lines):**

`STMCAN` 1957, `STM32F4_RTC` 1188, `STM32_Timer` 1013, `STM32F1_I2C` 606,
`STM32DMA` 425, `STM32F4_RCC` 404, `STM32_GPIOPort` 376, `STM32SPI` 366,
`STM32_ADC` 338, `STM32_CRC` 317, `STM32_UART` 295, `STM32F4_FlashController` 275,
`STM32_SYSCFG` 196, `STM32_IndependentWatchdog` 171, `STM32_RNG` 137,
`STM32_PWR` 125, `STM32F4_EXTI` 123, `BitBanding` 113, plus `NVIC` 2292,
`CortexM` 1385, `MappedMemory` 882, `CombinedInput` 46.

**In corpus — core infrastructure (~12–15k lines after cuts):**

Register DSL 2,538 · `GPIO` 154 · base peripheral classes ~560 · time framework
6,277 (less ~2k thread machinery under D3) · `Peripherals/Bus` 9,832 (less
`SVDParser`, `SymbolLookup`, `Symbol` — all debug-only, ~2.9k) · selected
machine plumbing from `Main/Core`.

**Out of corpus:** every non-ARM core (`Cores/RiscV` 11,125 lines of C#,
`arch/arm64` 63,891 lines of tlib C, etc.), monitor/CLI, `.repl`/`.resc` parsing
(the platform is compiled in), Xwt GUI, plugins, Migrant serialisation,
`Main/Tests` 12,597, `Main/Utilities` 21,179 except what is actually called, and
all non-F427 peripherals (854 peripheral files exist; we need ~22).

**Also in corpus — the project's custom peripherals (~1,600 lines):** a dual-bank
F427 flash controller, an F4 CRC unit, a shell-I/O hook peripheral, a UART peer
model and a CAN peer model. These must port too — they are the test harness.

**Total Rust target: ~25–30k lines.** Tractable in months, not years.

## Architecture

```
Renode C# (F427 subset)          target firmware ELF
        │                                 │
        ▼                                 │
Roslyn IOperation walk                    │
  (C# host, Microsoft.CodeAnalysis)       │
        │  serialised IR (JSON/CBOR)      │
        ▼                                 │
rule DB match (SQLite)                    │
   ├─ hit  → apply rule → emit Rust ──┐   │
   └─ miss → cluster                  │   │
             → agent proposes a       │   │
               GENERAL rule           │   │
             → validated against ALL  │   │
               matching occurrences   │   │
             → human gate → commit ───┘   │
        ▼                                 │
  syn/quote/prettyplease → Rust crate     │
        │                                 │
        ▼                                 ▼
  renode-rs binary ◄──── FFI ──── tlib (C, unchanged)
        │
        ▼
differential oracle vs C# Renode ── same ELF, same platform
```

## Validation oracle

Layered, cheapest first. **This is stronger than a typical translation project
gets**, because the reference implementation is a deterministic emulator we can
run in lockstep.

1. **Compiles** — `cargo build`, clippy clean.
2. **Register-level unit differential** — for each peripheral, replay a recorded
   trace of `(offset, value, width)` accesses captured from a C# Renode boot and
   assert identical read results and identical IRQ line transitions. Cheap,
   per-peripheral, no CPU needed. *This is the workhorse tier and it should be
   built first.*
3. **Instruction-lockstep state diff** — run both emulators to instruction count
   N on the same ELF; diff CPU registers, RAM, and peripheral state. Exact,
   because tlib is shared. Bisect divergence to the first differing instruction.
4. **Boot-log equivalence** — the documented boot sequence, in order, to
   `system_boot OK` and the shell prompt.
5. **CLI test drive** — `help`, `otp`, `info`, the auto-discovered command smoke
   sweep, and the CAN ISO-TP path, all already proven under C# Renode.
6. **Human review** — mandatory for anything touching the time framework, IRQ
   delivery ordering, or the D1/D3 borrow-and-threading decisions, regardless of
   tiers 1–5.

Tier 2 deserves emphasis: capturing an access trace from C# Renode is a small
Renode-side hook, and it converts "port a peripheral" from a research task into
a test-driven one with an exact pass/fail.

## Phases

### Phase 0 — environment, decisions, and the performance gate

Exit: D1–D4 settled, oracle tier 2 exists, tlib FFI proven, **and the
performance premise validated or killed**.

- Reproduce the known-good C# baseline boot to a prompt. This is the reference;
  nothing proceeds until it is reproducible on demand.
- **Performance spike (gate).** Profile C# Renode on the LSI polling case;
  microbenchmark the MMIO path against a throwaway Rust prototype. Establish the
  scaling metrics. A negative result here changes the project's justification and
  must be allowed to.
- Build the tier-2 trace capture hook in C# Renode; record a boot trace per
  peripheral.
- Stand up the Rust workspace, tlib FFI binding, and prove a "do-nothing" machine
  links and runs against tlib.
- **Settle D1–D4 with a written verdict each**, especially D3 (threading) and the
  D1 borrow discipline.
- Prior-art sweep: C#→Rust translators beyond toy scale; existing Rust
  deterministic-emulator frameworks worth building on.

### Phase 1 — the corpus database (exit: whole corpus queryable, clustered, ordered)

**Tooling before translation. This ordering is not negotiable**, and the reason
is evidenced: `linux-rs` skipped its own census gate, and its rule track reached
31 rules across 58 validation instances — **1.87 instances per rule** — with
`functions` and `statement_families` both at **0 rows**. Its *other* track, which
did build corpus-scale tooling (897,814 decl outcomes ingested), worked exactly
as designed. With no corpus in the database, "validate this rule against all
occurrences" is not a runnable operation, so every rule collapses into a patch
and per-file review becomes the only remaining quality mechanism.

Full schema and process defences: **[docs/rulesdb-design.md](docs/rulesdb-design.md)**.

- Build the Roslyn `IOperation` ingest tool and the schema.
- **Ingest the entire F427 corpus** — files, types, members, methods, parameters,
  locals, and the full operation tree, one row per node.
- Derive: metrics, purity fixpoint, call graph, field-access graph.
- Fingerprint and cluster every method. *The census is now a query, not a
  project.*
- Emit the topological work queue: leaves first, simplest first within each level.

### Phase 2 — stubs and the harness (exit: the crate builds, CI is real)

- Emit a `todo!()` stub for **every** method in the corpus. The crate compiles on
  day one, rustc validates the whole type mapping before a single body is
  written, and every call site is pre-wired.
- Wire the tier-2 trace fixtures into generated per-method tests.
- Stand up the progress dashboard. The headline metric is
  **instances-per-rule**, not files translated — a fall toward 1 means the
  process has drifted, and it must be visible the week it happens.

### Phase 3 — the register DSL and rule-driven translation (exit: thesis tested)

- Implement the 20-combinator register DSL in Rust, plus `PeripheralRegister` /
  `RegisterCollection` / `RegisterField` semantics (2,538 lines of C# — the
  single highest-leverage translation in the project).
- Build the **rule engine**: match against the operation tree → emit → query
  *all* matches in the corpus → validate each → commit only at ≥3 validated
  instances. Below that threshold it is recorded honestly as a `patch`, and
  patches are a tracked metric that must trend to zero.
- **Work the queue bottom-up** — leaves first, simplest first. Simple methods
  produce general rules; starting from a 300-node method produces over-specific
  ones, which is how a rule DB ends up at 1.87 instances per rule.
- The LLM is invoked **once per unmatched cluster**, never per function. That is
  the entire cost argument: ~200–400 invocations for the corpus rather than
  ~2,000, and the rules carry forward to the other 419 DSL-style peripheral
  files at no further cost.
- **Go/no-go gate:** on a *second, unseen* peripheral (`STM32_GPIOPort`, 376
  lines / 48 DSL calls), what fraction is covered by rules already committed from
  the first? If file two costs what file one cost, the thesis has failed and we
  stop.

### Phase 4 — corpus-wide rule application (exit: DSL-style population translated)

- Run the queue to completion over the DSL-style population (RCC, Timer, RTC,
  ADC, SPI, DMA, GPIO, UART).
- Every manual fix lands as a rule, never a file patch. A landed translation must
  be recreatable from the C# source plus committed rules and scripts alone —
  file-specific hand edits are evidence the generic process is incomplete, and
  are counted as such.

### Phase 5 — boot (exit: firmware reaches the shell prompt in Rust)

- Port the machine, sysbus, GPIO routing, NVIC, time framework (D3), and
  `MappedMemory`.
- Port the project's custom peripherals (flash controller, CRC, shell I/O, UART
  peer, CAN peer).
- Port `STMCAN` — the legacy outlier, hand-translated with human review, and the
  place to *not* replicate the two defects above (recorded as deliberate,
  justified deviations rather than silent fixes).
- Oracle tiers 3 and 4: instruction-lockstep, then boot-log equivalence.

### Phase 6 — drive the tests (exit: the CLI test suite runs against renode-rs)

- Oracle tier 5: `help`, `otp`, `info`, the command smoke sweep, CAN ISO-TP.
- Compare wall-clock against C# Renode's measured ~0.3× real time. Beating it is
  expected but is **not** a Phase-4 goal — equivalence is.

### Phase 7 — the optimisation pass (exit criteria set from Phase 6 data)

Only now, and only against a clean differential record. Note that D2 already
took the largest layout win up front, so this phase is about what the Phase-6
profile actually shows rather than a predetermined list:

- **Stage-3 lift for the coarse object graph**: `Rc<RefCell<T>>` → arena +
  `PeripheralId` indices (D1's named successor). This is the change that also
  makes a machine `Send`, enabling N-instance test parallelism on threads rather
  than processes.
- **Address decode**: flat page table indexed by `address >> 12`, or a compiled
  `match` over the fixed platform's ranges, replacing dictionary lookup.
- Push lazy evaluation further wherever the profile shows scheduled work that
  could be deadline-driven.
- Revisit D3 against real data.
- Only *then* consider tlib translation via `awtoau/c2rust`, if at all — and note
  it would destroy the tier-3 oracle's exactness by making the CPU differ between
  the two sides.

A deliberately *out-of-scope* optimisation: stubbing TIM5 input capture to skip
the LSI measurement entirely. That makes the benchmark faster by deleting the
work, which is precisely the kind of change the oracle is built to reject. It may
be worth doing as a *test-harness* convenience, but it must never be counted as a
performance result.

## Beyond F427 — what actually scales

F427 is the proving ground, not the ceiling. If the rule thesis holds, most of
Renode follows, and it is worth stating how much rather than vaguely calling
wider scope "creep".

Measured across the full peripheral tree (854 files), classifying a file as
DSL-style at ≥5 `With*` calls per 100 lines:

| Population | Files | Lines | After F427 |
|---|---:|---:|---|
| **DSL-style peripherals** | 419 | **208,580** | Mostly more of the same. Same 20 combinators, same rules. This is where the pipeline pays off |
| Legacy hand-written peripherals | 370 | 105,707 | Hand work, but the same *kind* of work as `STMCAN`, and rules from the DSL population still cover their logic bodies |
| Reflection-dependent infrastructure | — | ~33,000 | **Translates by no rule.** Hand-written, and bounded |

**Two-thirds of the peripheral tree by line count is declarative.** That is the
strongest argument that this generalises, and it is why "whole-Renode is a
non-goal" — borrowed from linux-rs's plan — is the wrong policy here. Linux is
34M lines with macro-obscured idioms; Renode is 486k with a 200k-line population
sharing one 20-method DSL. The ratio is about 70:1 and the idiom density is not
comparable. Copying that non-goal across was a mistake.

**The bounded residue that does not scale**, and what it costs:

| Subsystem | Lines | Note |
|---|---:|---|
| Migrant (state save/restore) | 15,278 | Deeply reflection-based. **Optional** — drop it and the residue nearly halves |
| Monitor / `UserInterface` | 8,253 | Command binding by reflection; needs a compile-time registry |
| `PlatformDescription` (`.repl`/`.resc`) | 5,188 | Dynamic peripheral instantiation by reflection; replaceable with build-time codegen from the same `.repl` files |
| `UI` | 4,040 | Xwt GUI — drop entirely |

So "a Rust Renode" is roughly: the rule pipeline over 314k lines of peripherals,
plus ~18k lines of hand-written infrastructure if save/restore is skipped. That
is a real project but a *knowable* one, and nothing about it is open-ended.

**What is genuinely deferred, and why it is a sequencing decision only:**
Phases 1–4 compile the platform in and skip the monitor entirely, because that is
the shortest path to a booting firmware and a working oracle. Building `.repl`
parsing first would feel necessary and would delay the only thing that validates
the method. Generalising comes after the proof, not before it.

## Risk register

| Risk | Mitigation |
|---|---|
| **The performance premise is wrong** — Rust's MMIO path is not materially faster | Phase-0 spike is a **gate**, run before the design is locked. A negative result reduces this to a safety-only project and that verdict must be allowed to stand |
| **`RefCell` re-entrancy panics** | Phase-0 borrow discipline: never hold a borrow across a sysbus call. D2's `Cell` arena removes the hazard entirely for register fields, which are the numerous case. Tier-3 lockstep finds the rest at an exact instruction |
| Cache-hostile data layout locks in early and is expensive to undo | D2 decided up front rather than deferred — the DSL is the abstraction boundary, so storage layout is changeable without touching peripheral code, but only if the boundary is respected from file one |
| D3 (single-threaded) proves wrong | Decided explicitly in Phase 0 against the profile, not assumed; reversal cost is an `Rc`→`Arc` mechanical sweep, painful but bounded |
| Rule thesis false for C# | Phase-1 gate on peripheral two, before any frontend is built |
| Roslyn frontend is a bigger build than expected | Phase 1 hand-translates without it; the frontend is only justified once the DSL and rules exist |
| tlib FFI proves awkward from Rust | It is a plain C ABI already called by P/Invoke; if it fails, that is Phase-0 knowledge, not Phase-3 |
| Building general Renode machinery (`.repl` parsing, monitor) *before* the method is proven | Sequencing rule, not a scope limit: Phase 1–4 compile the platform in and skip the monitor, because that reaches boot fastest. Generalising afterwards is the payoff, not creep — see "Beyond F427" |
| Legacy hand-written peripherals (STMCAN) resist rules | Expected. They are the human-review bucket by design, not a rule-DB failure |
| The four known Renode defects get faithfully reproduced | Deliberate: reproduce first (so the oracle passes), then fix as recorded, justified deviations |

## Repo layout (intended)

```
PLAN.md            this file
docs/              phase reports, census output, decision verdicts
scripts/           census/analysis tooling (Python; logs → ./tmp/logs/)
frontend/          Roslyn IOperation walker (C#) → serialised IR
rulesdb/           rule definitions + SQLite pattern DB
src/               the Rust emulator crate
oracle/            trace capture, lockstep harness, boot-log diff
tmp/               scratch + logs (untracked)
```

## Licensing note

Renode is MIT-licensed (Antmicro). Translated work derives from it and must
carry appropriate attribution. To be confirmed before any code is published.
