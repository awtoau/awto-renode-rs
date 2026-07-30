# GitHub issue drafts

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

The proposal is `Rc<RefCell<T>>` for the object graph with cycles leaked
(correct: the machine is built once and the process exits), and one
`Rc<RefCell<_>>` **per register field** rather than borrowing through the
collection.

**The real work here is the borrow discipline.** `RefCell` panics on re-entrant
borrow, and the exposure is peripheral → sysbus → peripheral (DMA reading memory
through the bus while the DMA peripheral is itself borrowed). A panic there is
not necessarily a C# bug — it may be legitimate re-entrancy C# tolerates.

**Tasks**
- Enumerate the re-entrant paths in the F427 corpus by inspection: which
  peripherals call back into the bus, and from where.
- Propose and write down the discipline (candidate: never hold a borrow across a
  bus call; bus calls take `&self` and re-borrow internally).
- Record the rejected alternative (arena + index handles) as the named Stage-3
  lift, #21.

**Exit** — `docs/decision-d1-d2.md` committed with the verdict, the enumerated
re-entrant paths, and the discipline.

## 5 — DECISION D3: threading model

`phase-0` `decision`

**The decision most worth challenging.** Written verdict required.

Renode is multithreaded: ~2k of the 6,277-line time framework is thread
coordination (`TimeSourceBase` 1041, `TimeHandle` 935, plus the master/slave
sources). The proposal is to port it **single-threaded**, on the grounds that
(a) Renode's determinism contract already serialises it logically so it is
unobservable in the emulated machine, (b) `Rc<RefCell<T>>` is not `Send` so D1
and threading are incompatible, and (c) determinism is the actual product and is
easier to guarantee without threads.

This is the one place the plan knowingly departs from "faithful". Reversal cost
is an `Rc`→`Arc`/`Mutex` mechanical sweep — painful but bounded.

**Tasks**
- Establish what, if anything, in the F427 boot path actually depends on
  concurrent execution rather than on interleaving the time framework already
  serialises.
- Check whether tlib's execution model imposes a threading requirement of its own.
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

## 24 — Revisit D3, and the tlib question

`phase-5` `decision`

Two deferred decisions, reopened only if Phase 4 data justifies it:

- **D3** — does profiling justify reintroducing threading?
- **tlib** — translate the CPU via `awtoau/c2rust`? The PLAN.md position is
  probably not: TCG is a JIT, so c2rust-ing it yields a Rust program that still
  JITs through the same machinery, with none of the safety benefit and all of the
  review cost — and it would destroy the exactness of the tier-3 oracle by making
  the CPU differ between the two sides.
