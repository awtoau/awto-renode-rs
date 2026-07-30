# GitHub issue drafts

## Scope, in one box

**In: Renode's ARM-only C# subset.** Nothing else.

| | |
|---|---|
| **Peripherals** | ~22 types, ~13k lines of C# — the F427 set |
| **ARM core bindings** | `NVIC` 2292 + `CortexM` 1385 lines of **C#** |
| **Core infrastructure** | register DSL, sysbus, GPIO, time framework — ~12–15k lines after cuts |
| **Custom peripherals** | ~1.6k lines, the test harness |
| **tlib (the CPU)** | **C. Untouched. Behind FFI. Not translated, not replaced.** |
| **Everything else in Renode** | Out. No `.repl` parsing, no monitor, no plugins, no GUI, no save/restore, no non-ARM cores |

Total Rust target ~25–30k lines. Issues tagged `deferred` are research logged so
the evidence is not lost — **not work, and not scheduled.**

---

Draft only — nothing filed yet. Reviewed and approved text becomes the issue
bodies verbatim. Ordering is the intended dependency order; `blocked by` is
noted where it is not simply the previous issue.

Labels used: `phase-0` … `phase-5`, `oracle`, `rules`, `decision`, `frontend`,
`peripheral`, `gate`, `epic`.

---

## E1 — [epic] Boot the target STM32F427 firmware on a Rust Renode

`epic`

Tracking issue for the whole project. See [PLAN.md](../PLAN.md).

**Goal.** A Rust emulator that boots a real STM32F427VGT6 (Cortex-M4F) firmware
to an interactive shell and drives its CLI test suite, reproducing a known-good
C# Renode setup with a differential oracle against it at every step.

**Method.** Faithful line-by-line translation first; optimisation is a separate,
gated pass. Every manual fix generalises into a rule rather than landing as a
one-off patch. The rule DB is the product; the emulator is the proof.

**Key scoping facts** (measured, Renode v1.16.1 `dc52b24c`):
- F427-reachable peripheral corpus is ~13k lines over ~22 types, out of 486k
  lines / 1,968 files total.
- The register DSL has exactly a 20-combinator surface. Translating it once is
  the highest-leverage single task in the project.
- tlib (the CPU) is 227k lines of **C**, not C#. We FFI to it unchanged — that
  is also what makes the lockstep oracle exact.

**Phase gates.** #8 (does rule leverage exist?) and #11 (does the census support
the thesis at corpus scale?) are genuine stop points, not milestones.

---

# Phase 0 — environment and decisions

Exit: D1–D4 settled with written verdicts, oracle tier 2 exists, tlib FFI proven.

## 1 — Reproduce and pin the C# Renode baseline boot

`phase-0` `oracle`

Nothing proceeds until the reference is reproducible on demand. The existing C#
setup boots to an interactive shell and drives `help` and `otp`; that needs to
be a one-command, repeatable operation producing an archived log.

**Tasks**
- Script the baseline boot end to end (`scripts/baseline_boot.py`), reading tree
  locations from `.env` per the repo rules.
- Archive the boot log with a commit-pinned Renode revision and firmware ELF
  hash, so "the reference" is a specific artifact, not "whatever it did today".
- Record wall-clock and simulated-time so the ~0.3× real-time figure — currently
  a single measurement from one boot — becomes a real baseline.
- Document the known launch traps: never combine `--console` with redirected
  stdio; `-P -1` turns a C# compile error into a silent hang.

**Exit** — `python3 scripts/baseline_boot.py` produces an archived, hash-pinned
boot log reaching the shell prompt, twice, identically.

## P1 — GATE: performance spike, before the design is locked

`phase-0` `gate` `perf`

**A genuine stop point, and the first real work after #1.**

Performance is a primary motivation (see PLAN.md, "Performance is a first-class
goal"), and the plan currently *assumes* Rust wins on the MMIO path. That
assumption must be tested before the architecture is committed, because a
negative result changes what this project is.

**The case to profile.** The firmware's LSI measurement spins on `TIM5->SR` up to
500,000 times per edge across 130 edges — order 65M MMIO reads, ~30 ms on
hardware, **~27 s under C# Renode**. Traced through the source, each poll goes:

```
STM32_Timer.cs:198  → cpu.SyncTime()
TranslationCPU.cs   → TlibGetExecutedInstructions()   [P/Invoke, managed↔native]
                    → ReportProgress(...)             [multithreaded TimeHandle
                                                       state machine]
```

The sync is semantically required — the counter depends on elapsed virtual time,
which only advances when the CPU reports progress. The question is entirely how
much the *implementation* costs.

**Tasks**
- Profile C# Renode over the LSI boot (`perf` and/or `dotnet-trace`). Produce the
  split: tlib execution vs managed boundary vs time framework vs address decode
  vs register dispatch vs GC. **This number does not currently exist and every
  performance claim in PLAN.md depends on it.**
- Build a throwaway Rust prototype of just the MMIO path: tlib → Rust callback →
  one peripheral → one register field. No DSL, no rules, no correctness — just
  the hot path.
- Microbenchmark both: N million reads of one timer register. Report
  accesses/sec.
- Compare the two D2 candidate layouts head to head in the prototype:
  `Rc<RefCell<_>>` per field versus `Cell` in a contiguous arena. Measure, do not
  assume — the claimed difference is cache behaviour and it should show up as one.
- Establish the tracked metrics: MMIO accesses/sec, instructions/sec, and the
  MMIO:instruction ratio.

**Exit** — `docs/perf-spike.md` with the C# profile breakdown, the Rust
prototype numbers, the D2 layout comparison, and a verdict.

- **Pass** — the Rust MMIO path is materially faster and the profile identifies
  where. Proceed; the numbers become the Phase-4 baseline.
- **Fail** — the win is marginal. The performance motivation evaporates and this
  becomes a safety-only project (still defensible on the two null-handling
  defects, but a much weaker case). **That verdict must be allowed to stand.**

## P2 — [deferred research] Replacing tlib: 2008-vintage QEMU with no tests

`deferred` `research`

> **Not scheduled. Does not block any phase. Nobody works on this during
> Phases 0–4.** Logged so the evidence is not lost and the decision is not made
> by default. The scoped project is Renode's **ARM-only C# subset**; tlib is C,
> stays behind FFI, and is not in scope.

Phase 1 FFIs to tlib unchanged, deliberately —
keeping the CPU identical on both sides is what makes the tier-3 lockstep oracle
exact. This issue exists because the long-term answer is probably different, and
the decision should be evidence-led rather than inherited.

### The evidence

| | |
|---|---|
| Lineage | ARM translator carries Fabrice Bellard (2003, 2008), CodeSourcery (2005–2007) and OpenedHand (2007) copyrights — the QEMU 0.9/1.0-era TCG |
| Size | 19,157 lines of ARM translation; 227,771 lines of C in tlib overall |
| Tests | **One test file in the entire tree** — `hash-table-store-test.c`, which tests a hash table. There is no instruction-level test infrastructure at all |

The structure is the problem, not just the age. TCG is a JIT: instruction
semantics are expressed as code that *emits* host code. You cannot unit-test
"does `UMLAL` set the flags correctly" without running generated machine code, so
in practice nobody does, and the model's correctness rests on it having been
exercised by real guests rather than on any test.

### The decisive question, and it depends on #P1

**Is instruction dispatch even on the critical path?**

If #P1 shows the cost is dominated by the MMIO path — managed boundary, time
sync, register dispatch — and not by instruction execution, then the JIT is
buying very little and costing a great deal in opacity. Renode currently manages
~50 MIPS *with* a JIT. A straightforward Thumb-2 interpreter in Rust is
plausibly in the same range on a modern host for this ISA, because Cortex-M is
small and regular.

If that holds, the trade is: **give up JIT throughput that is not the bottleneck,
and buy per-instruction testability** — one pure function per instruction, each
directly unit-testable, which is the thing tlib structurally cannot offer.

### Tasks

- Take the instruction-dispatch share of the profile from #P1. If it is small,
  say so plainly — that single number decides most of this.
- Quantify the divergence from upstream QEMU: what has Renode's fork changed,
  and what upstream TCG fixes since ~2010 has it never received? (Relevant to
  correctness, not just tidiness.)
- Survey the options, honestly and without assuming the answer:
  - A hand-written Rust Thumb-2/Cortex-M interpreter — most testable, unknown
    throughput, moderate build.
  - Existing Rust ARM emulation crates — establish what actually exists and is
    maintained rather than assuming.
  - Unicorn Engine — note it is itself QEMU-derived, so it inherits the same
    structural testability problem.
  - **Generated from a formal spec** — ARM publishes a machine-readable
    architecture specification (ASL), and Sail has been used to derive executable
    ARM models from it. A generated model is testable *against the vendor's own
    definition* rather than against someone's reading of the manual. Highest
    ceiling, highest unknown; worth costing rather than dismissing.
  - Rebasing onto modern upstream TCG — cheapest, fixes the age, fixes nothing
    about testability.
- **Design the validation strategy, which is unusually strong here.** We have the
  physical STM32F427 and existing SWD tooling. Random-instruction differential
  testing against real silicon — generate sequences, run on hardware, run on the
  model, diff registers and flags — is the gold-standard CPU validation method,
  and it is available to this project in a way it is not to most. This is worth
  specifying **regardless of which CPU option wins**, including if the answer is
  "keep tlib": it would be the first real test coverage tlib has ever had.

### Exit

`docs/cpu-options.md` with the #P1 dispatch share, the divergence assessment, a
costed option comparison, and a recommendation. A recommendation of "keep tlib,
but build the hardware-differential test harness" is a legitimate and possibly
the correct outcome.

## P3 — [deferred research] Running tlib through the linux-rs C→Rust pipeline

`deferred` `research`

> **Not scheduled. Does not block any phase.** Same status as #P2 — and note
> this is C→Rust work, which does not reduce the C# surface and therefore does
> not serve this project's stated motivation.

Logged because the idea is sound and the reuse is real: `linux-rs` already has a
working C→Rust pipeline and a hardened `awtoau/c2rust` fork, tlib is 227k lines
of **C** (c2rust's actual domain, unlike the C# side), and translating it would
remove the FFI boundary entirely.

**Recommendation: not as the first target.** Reasoning below; the issue exists so
the decision is recorded rather than assumed, and so the stepping-stone variant
does not get lost.

### Prior art (searched 2026-07-31, needs a fuller dig)

- **`zevorn/tcg-rs`** — "Rust for QEMU TCG", Rust, 31★, active (updated
  2026-07-22).
- **`qemu-rs/qemu-rs`** — "QEMU for Rust, and Rust for QEMU", 103★, active
  (2026-07-23).
- **QEMU upstream has official Rust support** — `wiki.qemu.org/RustInQemu`,
  `qemu.org/docs/master/devel/rust.html`. Hand-written Rust *device models*, not
  translation: the exact Rust-for-Linux analogue, and the same "no translation by
  policy" shape.
- **No c2rust-on-QEMU work found** — `gh search repos "c2rust qemu"` returns
  empty.

So: partially done, actively moving, and the specific thing proposed here
(mechanical translation) is unclaimed. **The fuller survey is a task below, not a
settled result — 31 stars is not an assessment.**

### Why not first

1. **c2rust hits its hardest cases in TCG.** Computed goto for the dispatch loop,
   `setjmp`/`longjmp` for `cpu_loop_exit` unwinding, inline asm, function-pointer
   tables, and runtime host-code generation. `setjmp`/`longjmp` in particular has
   no clean Rust equivalent and is a known c2rust weak point.
2. **You would get a JIT, in Rust.** The generated-code path is irreducibly
   `unsafe` — it emits bytes and jumps to them — so there is no safety win there,
   and it stays untestable per-instruction. **That is precisely the complaint that
   motivated #P2.** Translating the JIT preserves the defect.
3. **It does not serve either stated motivation.** The C# maintenance burden is
   unaffected — tlib is C, not C#. And if #P1 shows the CPU is not the
   bottleneck, translating it buys nothing on performance either.
4. **It does not test the project's central risk**, which is whether the rule
   thesis holds for C#. Months spent here and a failed C# gate leaves a Rust QEMU
   fork and no answer.

### The variant that *is* attractive

**c2rust tlib as a stepping stone to deleting it.** Translate faithfully → the
build is now one language → then replace the JIT with a testable interpreter
incrementally, function by function, using the c2rust output as the differential
baseline. That is exactly the linux-rs method applied here, and it is coherent in
a way "translate and stop" is not.

This merges with #P2: they are the same decision. #P2 asks "what should the CPU
be"; this asks "how do we get there". If the answer to #P2 is "a testable
interpreter", this is one credible route to it.

### Tasks

- Do the proper prior-art dig: `zevorn/tcg-rs` (what does it actually cover —
  the TCG IR, a backend, a whole emulator?), `qemu-rs`, QEMU's upstream Rust
  effort, and search beyond GitHub (GitLab, Codeberg, sr.ht, grep.app).
- Assess c2rust's actual behaviour on tlib's hard constructs — take `arch/arm`
  and *try it*, using the `awtoau/c2rust` fork. A one-day experiment beats
  argument, and any failures are useful upstream to `linux-rs` regardless.
- Cost the stepping-stone variant against a from-scratch interpreter (#P2).
- Feed any c2rust gaps found back to `awtoau/c2rust` as evidence-based issues —
  that is the fork's stated purpose and the benefit compounds for `linux-rs`.

### Exit

Merged into `docs/cpu-options.md` (#P2) as a costed route, or recorded as
rejected with reasons.

## 2 — Oracle tier 2: register access trace capture

`phase-0` `oracle`

The workhorse tier, and the thing that converts "port a peripheral" from a
research task into a test-driven one with exact pass/fail.

Add a Renode-side hook that records, per peripheral, every
`(offset, value, width, direction)` access plus every IRQ line transition during
a boot. The resulting trace is replayed against a Rust peripheral in isolation —
no CPU, no bus, no timing — asserting identical read results and identical IRQ
edges.

**Tasks**
- C# hook in the source Renode build; output a stable, diffable trace format.
- Capture a full boot trace for each of the ~22 in-corpus peripherals.
- Rust-side replay harness (`oracle/trace_replay`).
- Commit the traces as test fixtures (they are the reference, and they are small).

**Exit** — traces captured for every in-corpus peripheral; replay harness runs
and fails informatively against a deliberately-wrong stub.

## 3 — Rust workspace and tlib FFI proof

`phase-0`

Prove the riskiest structural assumption early: that Rust can drive tlib as
cleanly as C# does through P/Invoke.

**Tasks**
- Cargo workspace per the PLAN.md layout.
- `bindgen` over tlib's exported headers; hand-audit the generated surface.
- Link and run a "do-nothing" machine: init a Cortex-M4 core, map a RAM region,
  execute a handful of instructions, read back registers.
- Confirm the hard-float `cortex-m4f` configuration is reachable (the firmware
  faults on the first VFP instruction otherwise).

**Exit** — a Rust binary steps a Cortex-M4F through instructions in tlib and
reads back correct register state.

## 4 — DECISION D1/D2: object graph and register field representation

`phase-0` `decision`

Written verdict required. See PLAN.md "The four declared deviations".

Blocked by #P1 — this decision is made against the profile, not ahead of it.

**D1 (coarse object graph)** — proposal is `Rc<RefCell<T>>` with cycles leaked
(correct: the machine is built once and the process exits). One indirection and
one borrow check per MMIO access, not per field. Keeps the translation literal.
Cost: it makes a machine `!Send`, so N-instance test parallelism needs processes
rather than threads.

**D2 (register fields)** — proposal is **`Cell` in a contiguous arena with typed
index handles**, *not* `Rc<RefCell<_>>` per field. Register fields are all `Copy`
scalars (`ulong`, `bool`, small enums), which is exactly `Cell`'s use case. RCC
alone defines ~240 fields; one heap allocation each, with 16 B of refcounts and
an 8 B borrow flag apiece scattered across the heap, is the difference between a
polling loop living in L1 and one missing cache on every read.

This costs nothing in faithfulness — the DSL is the abstraction boundary, so
translated peripheral code reads identically either way — and it removes the
borrow-panic hazard entirely for the most numerous object in the system.

**The remaining real work is the borrow discipline for D1.** `RefCell` panics on
re-entrant borrow; the exposure is peripheral → sysbus → peripheral (DMA reading
memory through the bus while the DMA peripheral is itself borrowed). A panic
there is not necessarily a C# bug — it may be legitimate re-entrancy C# tolerates.

**Tasks**
- Take the D2 layout verdict from #P1's head-to-head measurement.
- Enumerate the re-entrant paths in the F427 corpus by inspection: which
  peripherals call back into the bus, and from where.
- Propose and write down the discipline (candidate: never hold a borrow across a
  bus call; bus calls take `&self` and re-borrow internally).
- Record the D1 arena lift (`PeripheralId` indices, machine becomes `Send`) as
  the named Stage-3 successor, #23 — deferred, not rejected.

**Exit** — `docs/decision-d1-d2.md` committed with the verdict, the enumerated
re-entrant paths, and the discipline.

## 5 — DECISION D3: threading model

`phase-0` `decision`

**The decision most worth challenging.** Written verdict required.

Blocked by #P1.

Renode is multithreaded: ~2k of the 6,277-line time framework is thread
coordination (`TimeSourceBase` 1041, `TimeHandle` 935, plus the master/slave
sources) — and that machinery sits **on the hot path**, since `SyncTime` →
`ReportProgress` walks it on every timer register poll.

The proposal is **single-threaded within one machine**, and the argument is now
performance-led rather than simplicity-led:

1. **Intra-instance parallelism does not pay for a single-core MCU.** There is
   one CPU. Peripherals could tick on other threads, but every interaction point
   needs synchronisation and a polling loop drives that rate through the roof.
   QEMU's MTTCG parallelises *guest cores*, not guest peripherals, for exactly
   this reason — and here there is one guest core.
2. **Removing the thread coordination is itself an optimisation.**
   Single-threaded, `ReportProgress` collapses to `virtual_time += delta` plus a
   deadline comparison.
3. Determinism is the product and is easier to guarantee without threads.

**The parallelism that pays is N independent instances** — the CLI test suite
across 16 cores. That needs the machine `Send` (which D1's `Rc` blocks and D2's
arena permits) or process isolation. Processes work today; note the tension and
do not close it off.

**Tasks**
- Take the time-framework share of the profile from #P1. If it is small, this
  decision matters less than assumed and should say so.
- Establish what, if anything, in the F427 boot path depends on genuinely
  concurrent execution rather than interleaving the time framework already
  serialises.
- Check whether tlib's execution model imposes a threading requirement of its own.
- Decide the N-instance story: threads (needs `Send`, implies the D1 arena) or
  processes (works now).
- Write the verdict, including what evidence would reverse it.

**Exit** — `docs/decision-d3.md` committed.

## 6 — DECISION D4: error model

`phase-0` `decision`

Smaller and less contentious than D1–D3, but still global. `RecoverableException`
/ `ConstructionException` → `Result<T, RenodeError>` threaded with `?`; what C#
treats as fatal becomes a panic.

Worth noting in the verdict: the `STM32_CRC` defect *is* a fatal C# exception
that aborts the emulator process, and the Rust construct it maps to does not
compile. That is the clearest single illustration of why the port is worth doing.

**Exit** — `docs/decision-d4.md` committed, with the error enum sketched.

## 7 — Prior-art sweep

`phase-0`

Cheap, and it can change the framing. Two questions:

1. Has anyone published a C#→Rust translator beyond toy scale? (The PLAN.md
   position is no — the closest things are Roslyn-based DIY emitters. Verify.)
2. Is there a Rust deterministic-emulator framework worth building *on* rather
   than porting onto?

Search GitHub **plus** GitLab, Codeberg, sr.ht, Bitbucket and code-search
engines — GitHub alone misses a lot.

**Exit** — `docs/prior-art.md` with a written verdict per question.

---

# Phase 1 — the register DSL and one peripheral by hand

Exit: the rule thesis is tested on a second, unseen peripheral.

## 8 — Implement the register DSL in Rust

`phase-1` `rules`

The single highest-leverage translation in the project: 2,538 lines of C#
(`PeripheralRegister` 836, `PeripheralRegisterExtensions` 580,
`RegisterCollection` 547, `RegisterField` 314, `RegisterSelector` 104, plus the
field interfaces) implementing a 20-combinator fluent DSL.

The combinators: `WithFlag`, `WithValueField`, `WithEnumField`, `WithPacketField`
(+ the `*s` plural forms), `WithTag`, `WithTaggedFlag` (+ plurals),
`WithReservedBits`, `WithIgnoredBits`, `WithReadCallback`, `WithWriteCallback`,
`WithChangeCallback`, and `WithConditionallyWritable{Flag,ValueField,EnumField}`.

**The design problem.** C# `out` parameters in a fluent chain
(`.WithFlag(2, out receiverEnabled, name: "RE")`) hand the peripheral a shared
handle into storage the collection also owns. Rust has no `out` params and a
consuming builder cannot hand back a borrow. Resolve per D2 (#4): the builder
returns the field handle, the peripheral binds it.

**Tasks**
- Port `FieldMode` semantics exactly, including `WriteZeroToClear`,
  `WriteOneToClear`, `Toggle`, and read/write-callback ordering.
- Port reset semantics including `softResettable`.
- Port the `DefineMany` / `DefineManyConditional` register-array forms.
- Unit-test each combinator against behaviour extracted from the C# source.

**Exit** — DSL compiles, every combinator has a test, `FieldMode` semantics match
the C# implementation.

## 9 — Hand-translate `STM32_UART` as the calibration file

`phase-1` `peripheral` `rules`

295 lines, 56 DSL calls. Representative: declarative register block plus real
logic (receive FIFO, IRQ aggregation in `Update()`, an idle-line timeout
scheduled on the machine's time source, a DMA request GPIO).

Every decision made here becomes a rule — that is the point of the file, not the
UART itself.

**Tasks**
- Translate faithfully. Do not fix anything, including the fact that Renode has
  no baud-rate model at all (`BaudRate` is computed and used for exactly one
  thing: the idle-line timeout).
- Record each translation decision as a rule in `rulesdb/`.
- Pass oracle tier 2 against the captured UART trace from #2.

**Exit** — tier-2 clean; rules committed with the instances they were derived from.

## 10 — GATE: does rule leverage exist?

`phase-1` `gate`

**A genuine stop point.** Translate `STM32_GPIOPort` (376 lines, 48 DSL calls) —
a second, unseen peripheral — using only the DSL from #8 and the rules from #9.

Measure: what fraction is covered by existing rules, and how much new hand work
is needed?

- **Pass** — most of it falls out mechanically; new rules are few and general.
  Proceed to Phase 2 and build the frontend.
- **Fail** — file two costs about what file one cost. The rule thesis is wrong
  for this corpus. **Stop**, having spent one peripheral. Write up why; a
  hand-port of ~22 peripherals may still be worth doing, but not with a
  rule-learning pipeline behind it.

**Exit** — `docs/phase1-gate.md` with the measured coverage number and the
go/no-go verdict.

---

# Phase 2 — the Roslyn frontend and the census

Exit: DSL-style peripherals translate automatically.

## 11 — Roslyn `IOperation` frontend

`phase-2` `frontend`

Blocked by #10.

Build the C# host that walks Renode's source with `Microsoft.CodeAnalysis` and
emits our serialised IR.

**Why `IOperation` specifically.** It is a lowered, language-agnostic tree with
`foreach`, `using`, `lock`, LINQ query syntax, object initialisers and pattern
matching already desugared, carrying full type resolution and nullability
annotations. It is already the typed IR c2rust had to hand-build — which is the
core reason forking c2rust for C# would be wasted effort (its `TypedAstContext`
models C integer promotion, bitfields, unions, `goto` and `va_arg`, and knows
nothing of classes, generics, virtual dispatch, properties, events, exceptions
or LINQ).

**Tasks**
- Load Renode's solution; restrict to the F427 corpus.
- Walk `IOperation`; emit JSON/CBOR (c2rust's two-process split, same rationale:
  the good AST library lives in a foreign runtime).
- Adopt c2rust's `WithStmts<T>` design for expressions needing hoisted statements
  — C# hits this with side-effecting property getters, `??=`, and `out` params in
  expression position.
- Adopt a scope-aware name manager for reserved-word collisions.

**Exit** — IR emitted for the whole F427 corpus; round-trip sanity checks pass.

## 12 — GATE: pattern census of the F427 corpus

`phase-2` `gate` `rules`

Blocked by #11.

The linux-rs Phase-1 analogue: read-only, no Rust emitted. Fingerprint every
method in the corpus, normalise, cluster.

**Deliverable** — *the F427 corpus by pattern*: how many idiom families cover
50% / 80% / 95% of methods; the size and shape of the unmatched tail; the split
between the DSL-style population and the legacy hand-written one.

The expectation from the density measurement (RCC 240 `With*` calls in 404 lines
versus STMCAN 1 in 1957) is a sharp bimodal split. If the census does not show
one, the plan's central assumption is wrong.

**Exit** — `docs/census.md` published with the coverage curve.

## 13 — Automate translation of the DSL-style population

`phase-2` `rules`

Blocked by #12.

Wire the miss path: unmatched subtree → cluster → propose a general rule →
validate against **all** matching occurrences → human gate for semantics-bearing
categories → commit.

Target set: RCC, Timer, RTC, ADC, SPI, DMA, GPIO, UART. Every manual fix lands as
a rule, never a file patch — a landed peripheral must be recreatable from the C#
source plus committed rules and scripts alone.

**Exit** — the DSL-style peripherals translate from source with no file-specific
hand edits, and pass oracle tier 2.

---

# Phase 3 — boot

Exit: the firmware reaches its shell prompt under renode-rs.

## 14 — Port machine, sysbus and GPIO routing

`phase-3`

The core plumbing: address decoding, peripheral registration, access-width
translation (`AllowedTranslations` — the UART alone needs word- and
byte-to-doubleword), and GPIO connection routing.

Out of scope by design: `.repl`/`.resc` parsing (the platform is compiled in),
SVD parsing, symbol lookup, the monitor. That is ~2.9k lines of `Peripherals/Bus`
dropped as debug-only.

## 15 — Port NVIC and the CortexM binding

`phase-3`

`NVIC` 2292 lines + `CortexM` 1385. Interrupt priority, masking, SysTick, and the
binding between tlib's exception model and the NVIC.

Note from the reference setup: `systickFrequency` must match the real 168 MHz
SYSCLK or every delay in the firmware is wrong by the ratio.

## 16 — Port the time framework

`phase-3`

Blocked by #5 (D3).

6,277 lines of C#, less ~2k of thread coordination if D3 lands single-threaded.
Clock sources, time intervals, scheduled actions, and the sink/handle model.

**Human review mandatory** regardless of oracle tier — timing and IRQ delivery
ordering are exactly where an automated tier will pass a wrong translation.

## 17 — Port `STMCAN`

`phase-3` `peripheral`

The legacy outlier: 1957 lines, one DSL call, switch-on-offset throughout. Low
rule leverage, hand-translated, human review.

**Reproduce both known defects faithfully first** so the oracle passes:
- `MSR.INAK` never set — the model requires `InitRequest && !SleepRequest`; real
  silicon gives INRQ priority.
- A fabricated bus error on every transmit when no hub is attached
  (`FrameSent == null`), plus SCE driven as a level from `ESR.LEC` rather than
  latched through `MSR.ERRI` — an interrupt storm at interrupt priority.

Then fix both as **recorded, justified deviations** with the oracle re-baselined.
Do not silently improve them during translation.

Both are worth reporting upstream to Antmicro independently of this port.

## 18 — Port the project's custom peripherals

`phase-3` `peripheral`

~1,600 lines: a dual-bank F427 flash controller (the in-tree one stops at sector
11 with a 4-bit `SNB` where F42x/43x is 5), an F4 CRC unit (~30 lines — the F4
unit is fixed-everything, which is why the in-tree model's `REV_IN`/`REV_OUT`
handling has no business dereferencing anything), a shell-I/O hook peripheral, a
UART peer model and a CAN peer model.

These are the test harness — without them there is nothing to drive.

## 19 — Oracle tier 3: instruction-lockstep state diff

`phase-3` `oracle`

Run both emulators to instruction count N on the same ELF; diff CPU registers,
RAM and peripheral state; bisect any divergence to the first differing
instruction.

Exact, because tlib is shared between both sides — so every divergence is a
peripheral bug, not a CPU bug. This is also the tool that will find D1 `RefCell`
re-entrancy panics at an exact instruction rather than as a mystery.

## 20 — Oracle tier 4: boot-log equivalence

`phase-3` `oracle`

The documented boot sequence, in order: clock config → CAN init → RTC/LSI →
shell UART → OTP identity → FreeRTOS started → banner → shell commands ready →
SPI/IMU bring-up → CAN tunnel → OTA slot → `system_boot OK` → prompt.

**Exit — the headline milestone: the firmware reaches an interactive prompt
under renode-rs.**

---

# Phase 4 — drive the tests

## 21 — Oracle tier 5: drive the CLI test suite

`phase-4` `oracle`

`help`, `otp`, `info`, the auto-discovered command smoke sweep, and the CAN
ISO-TP path — all already proven under C# Renode, including a 512-byte `otp`
reply reassembled over 74 ISO-TP frames.

**Exit** — the CLI test suite runs against renode-rs with results matching C#
Renode.

## 22 — Performance baseline

`phase-4`

Compare wall-clock against C# Renode's ~0.3× real time (from #1, now a real
benchmark rather than a single measurement).

Beating it is expected but is **not** a goal here — equivalence is. This issue
exists to produce the number that Phase 5 optimises against, and to identify
whether tight MMIO polling loops remain pathologically slow (the LSI measurement
spins on a timer register up to 500,000 times per edge across 130 edges, and
dominated boot at ~27 s wall under C# Renode).

---

# Phase 5 — the optimisation pass

Only against a clean differential record.

## 23 — Stage-3 lift: `Rc<RefCell<T>>` → arena + typed index handles

`phase-5`

D1's named successor. Start with register fields (D2), which are the most
numerous and the most uniform. Representation change only — no algorithm change
— with the `Rc<RefCell>` version as the differential baseline.

## 25 — Scope out "the rest of Renode"

`phase-5`

Blocked by #12 (census) and #21 (tests passing). Not a commitment — a costing,
written once the method is either proven or dead.

The measured shape of what remains after F427, across the full 854-file
peripheral tree (DSL-style = ≥5 `With*` per 100 lines):

| Population | Files | Lines |
|---|---:|---:|
| DSL-style peripherals | 419 | 208,580 |
| Legacy hand-written peripherals | 370 | 105,707 |
| Reflection-dependent infrastructure | — | ~33,000 |

**Two-thirds of the peripheral tree by line count is declarative**, sharing the
same 20 combinators the F427 work already implements. That population should be
mostly pipeline throughput rather than new design.

The residue that translates by no rule, and is therefore hand-written whenever it
happens: Migrant state save/restore (15,278 — optional, drop it and the residue
nearly halves), monitor/`UserInterface` (8,253 — reflection-based command binding,
needs a compile-time registry), `PlatformDescription` for `.repl`/`.resc`
(5,188 — dynamic instantiation by reflection, replaceable with build-time codegen
from the same files), and the Xwt `UI` (4,040 — drop entirely).

**Tasks**
- Cost each population against the actual Phase-2/3 throughput, not against
  estimates.
- Decide whether `.repl` parsing is worth building at all, or whether build-time
  codegen from `.repl` files into compiled platforms is strictly better. (It
  probably is: it keeps the reflection out and the platform data in.)
- Decide whether save/restore is wanted. It is the single largest piece of the
  non-scaling residue.

**Exit** — `docs/beyond-f427.md` with a costed scope, or a recorded decision not
to pursue it.

## 24 — Revisit D3, and the tlib question

`phase-5` `decision`

Two deferred decisions, reopened only if Phase 4 data justifies it:

- **D3** — does profiling justify reintroducing threading?
- **tlib** — translate the CPU via `awtoau/c2rust`? The PLAN.md position is
  probably not: TCG is a JIT, so c2rust-ing it yields a Rust program that still
  JITs through the same machinery, with none of the safety benefit and all of the
  review cost — and it would destroy the exactness of the tier-3 oracle by making
  the CPU differ between the two sides.
