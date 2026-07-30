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
Rust reaches it through `extern "C"`, which is strictly simpler. tlib translation
is a separate, later, optional project.

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

### D2 — Register fields: `Rc<RefCell<Field>>`, one per field, not one per collection

`out IFlagRegisterField receiverEnabled` in a fluent chain gives the peripheral a
handle into storage the register collection also owns. Modelling each *field* as
its own `Rc<RefCell<_>>` — rather than borrowing through the collection — is both
the faithful mapping and the one that avoids D1's re-entrancy trap, since a
write callback that touches another field never needs the collection borrowed.

This is the highest-value single rule in the DB: it covers every `out` parameter
in every `With*` call across the entire corpus.

### D3 — Threading: single-threaded

Renode is multithreaded — `TimeSourceBase` (1041 lines), `TimeHandle` (935),
`SlaveTimeSource`, `MasterTimeSource`; roughly 2k lines of the 6,277-line time
framework is thread-coordination machinery.

**Recommendation: port the time framework single-threaded.** Justification:
(a) Renode's determinism contract already means the threading is logically
serialised, so it is unobservable in the emulated machine's behaviour;
(b) `Rc<RefCell<T>>` is not `Send`, so D1 and multithreading are incompatible —
choosing threads means `Arc<Mutex<T>>` everywhere, which is both slower and
further from the source; (c) determinism is *easier* to guarantee, and
determinism is the actual product.

This is the one place the plan knowingly departs from "faithful", and it is
recorded as such. **It is also the decision most worth challenging before Phase 2
starts.**

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

### Phase 0 — environment and decisions (exit: D1–D4 settled, oracle tier 2 exists)

- Reproduce the known-good C# baseline boot to a prompt. This is the reference;
  nothing proceeds until it is reproducible on demand.
- Build the tier-2 trace capture hook in C# Renode; record a boot trace per
  peripheral.
- Stand up the Rust workspace, tlib FFI binding, and prove a "do-nothing" machine
  links and runs against tlib.
- **Settle D1–D4 with a written verdict each**, especially D3 (threading) and the
  D1 borrow discipline.
- Prior-art sweep: C#→Rust translators beyond toy scale; existing Rust
  deterministic-emulator frameworks worth building on.

### Phase 1 — the register DSL and one peripheral by hand (exit: thesis tested)

- Implement the 20-combinator register DSL in Rust, plus `PeripheralRegister` /
  `RegisterCollection` / `RegisterField` semantics (2,538 lines of C# — the
  single highest-leverage translation in the project).
- Hand-translate **`STM32_UART`** (295 lines, 56 DSL calls) as the calibration
  file. Every decision made here becomes a rule.
- Pass oracle tier 2 against the recorded UART trace.
- **Go/no-go gate:** does the DSL implementation plus the rules derived from one
  peripheral mechanically cover most of a *second, unseen* peripheral
  (`STM32_GPIOPort`, 376 lines / 48 DSL calls)? If translating file two is as
  expensive as file one, the rule thesis has failed and we stop, having spent one
  peripheral.

### Phase 2 — the Roslyn frontend and the census (exit: automated translation of DSL-style peripherals)

- Build the Roslyn `IOperation` walker and the serialised IR.
- Run the census over the F427 corpus: fingerprint every method, cluster,
  measure how many rules cover what fraction. Publish the number.
- Automate translation for the **DSL-style population** (RCC, Timer, RTC, ADC,
  SPI, DMA, GPIO, UART).
- Every manual fix lands as a rule, never a file patch.

### Phase 3 — boot (exit: firmware reaches the shell prompt in Rust)

- Port the machine, sysbus, GPIO routing, NVIC, time framework (D3), and
  `MappedMemory`.
- Port the project's custom peripherals (flash controller, CRC, shell I/O, UART
  peer, CAN peer).
- Port `STMCAN` — the legacy outlier, hand-translated with human review, and the
  place to *not* replicate the two defects above (recorded as deliberate,
  justified deviations rather than silent fixes).
- Oracle tiers 3 and 4: instruction-lockstep, then boot-log equivalence.

### Phase 4 — drive the tests (exit: the CLI test suite runs against renode-rs)

- Oracle tier 5: `help`, `otp`, `info`, the command smoke sweep, CAN ISO-TP.
- Compare wall-clock against C# Renode's measured ~0.3× real time. Beating it is
  expected but is **not** a Phase-4 goal — equivalence is.

### Phase 5 — the optimisation pass (exit criteria set from Phase 4 data)

Only now, and only against a clean differential record:

- **Stage-3 lift**: `Rc<RefCell<T>>` → arena + typed index handles (D1's named
  successor), starting with register fields (D2).
- Remove `RefCell` borrow-check overhead on hot paths.
- Consider whether a TIM5 input-capture stub — which would remove a documented
  ~27 s LSI-measurement boot cost — belongs here or earlier.
- Revisit D3 if profiling justifies it.
- Only *then* consider tlib translation via `awtoau/c2rust`, if at all.

## Risk register

| Risk | Mitigation |
|---|---|
| **`RefCell` re-entrancy panics** (highest risk) | Phase-0 borrow discipline: never hold a borrow across a sysbus call. Tier-3 lockstep finds these immediately, at an exact instruction |
| D3 (single-threaded) proves wrong | Decided explicitly in Phase 0 with a written verdict; reversal cost is an `Rc`→`Arc` mechanical sweep, painful but bounded |
| Rule thesis false for C# | Phase-1 gate on peripheral two, before any frontend is built |
| Roslyn frontend is a bigger build than expected | Phase 1 hand-translates without it; the frontend is only justified once the DSL and rules exist |
| tlib FFI proves awkward from Rust | It is a plain C ABI already called by P/Invoke; if it fails, that is Phase-0 knowledge, not Phase-3 |
| Scope creep toward "a Rust Renode" | Non-goal, stated: no `.repl` parsing, no monitor, no plugins, no GUI, one platform compiled in |
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
