# Inheritance: merge, embed, or a trait

Issue #56. **Open.** This document produces the evidence and a recommendation;
the choice is the maintainer's, and PLAN.md line 437 is deliberately left
unreconciled until it is made.

Every number below comes from a file under `docs/status/`, produced by a
committed script. None of them is retyped from a previous document, and the
two that contradict what the previous document assumed are marked.

| file | produced by |
|---|---|
| `docs/status/inheritance.json` | `python3 scripts/inheritance_census.py` |
| `docs/status/inheritance-breadth.json` | the same, `--db tmp/breadth.db --cut-db rulesdb/patterns.db` |
| `docs/status/dispatch.json` | `python3 scripts/dispatch_spike.py` |

---

## Why this is being decided again

PLAN.md line 437 says inheritance becomes *"composition: base as a struct field
+ trait with default methods"*, and line 438 says `virtual`/`abstract` become
trait objects. The implementation **merges** base members into the derived
`State`, emits base bodies as free functions, and emits **no trait**. That
reversal was argued as a fresh decision. It was not one; CLAUDE.md forbids
revisiting a declared deviation silently, and this is the reopening.

Research (#41, `docs/research/inheritance.md`) separated three claims that had
been bundled:

- flattening the base's **fields** is forced by Rust — RFC 1546 postponed 2018,
  dead repository since 2017;
- base **method bodies** as free functions is forced by **D2**, whose callback
  type has no `self`, not by inheritance;
- *"therefore no trait"* does **not** follow, and no surveyed system omits
  dispatch.

What that research did not do is compare **merging** against **embedding**.
IL2CPP puts the base subobject at offset 0; Servo stores the superclass by
value in the first field; QEMU wraps it in `ParentField<T>`; c2rust emits
`#[repr(C)]` parent-first. All four keep the base *identifiable*. Merging
splats its members into the derived type's own field list and forgets that they
were the base's. That difference had never been measured here.

---

## The measurement

Two corpora, kept apart because CLAUDE.md requires it. The cut is the
deliverable and the only tier the trace oracle can reach. Breadth is the whole
Renode tree, admissible for **discovery** — "does this shape exist in real C#"
— and never for correctness. The cut alone would have answered the central
question wrongly, which is the case for running both.

| | **cut** (F427) | **breadth** (whole tree) |
|---|---:|---:|
| classes | 104 | 2,017 |
| classes with a base | 29 | 946 |
| **chains truncated by the corpus** | **20 (69%)** | 246 (26%) |
| max in-cut chain depth | 1 | 6 |
| `virtual` / `override` / `abstract` methods | 17 / 66 / 214 | 429 / 1,908 / 880 |

### 1. Collisions — the question that separates the two models

A member name declared at two levels of one chain. Merging puts both in one
struct; embedding cannot collide, because the base's members sit behind a
field.

| | cut | breadth |
|---|---:|---:|
| colliding storage members | **0** | **77**, across 50 types |
| …same C# name | 0 | 69 |
| …only after `snake_case` | 0 | 8 |
| colliding method names | 17 | 1,585 |

**On the cut alone, embedding's headline advantage has zero instances.** That
is a real finding and it points at merge. It is also an artefact of the cut
being small (9 untruncated chains) — and the next row is why that matters.

### 2. What the emitter actually does with a collision

Not argued: `scripts/inheritance_census.py` calls the real `state_fields()` on
every colliding type and records the result.

**11 types emit a `State` struct that declares the same field twice** — 15
duplicate names. That is rustc E0124: the type does not compile at all.

Two of the colliding types **are in the F427 cut**:

| type | collision | why it is invisible today |
|---|---|---|
| `STM32_Timer` | `initialLimit`, declared by both `STM32_Timer` and `LimitTimer` | `LimitTimer` is outside the cut, so `base_chain()` returns `[]` and nothing is merged |
| `CortexM` | `Clustered`, `Clusters`, declared by both `TranslationCPU` and `BaseCPU` | both ancestors are outside the cut |

So the cut's zero is not evidence that merging is safe here. It is evidence
that **69% of the cut's base chains are truncated**, and the collisions are
hiding in the part the corpus cannot see. Close `CorpusCut.cs` under `BaseType`
— which `docs/research/inheritance.md` already recommends, and which the
deliverable needs anyway — and merging stops compiling on two of this project's
own peripherals.

This is the measurement that changed the answer, and it is the opposite of what
the cut alone said.

### 3. `base.X()` and every other reach into the base

Counted as one class of site: `base.X()`, an inherited call through `this`, and
a read or write of a protected base field all cost the same under each model.

| | cut | breadth |
|---|---:|---:|
| sites reaching an ancestor member | 136 | 5,829 |
| …invocations / property reads / field reads | 52 / 71 / 13 | 2,362 / 1,773 / 1,694 |
| **…whose base is outside the corpus** | **107 (79%)** | 727 (12%) |
| **merge** — sites needing the invented `{base}_{name}` | 10 | 645 |
| merge — sites reachable under the plain name | 126 | 5,184 |
| **embed** — sites needing `self.parent.` | 136 | 5,829 |
| embed — sites needing an invented name | **0** | **0** |

Read that table honestly: **embedding costs more edits, not fewer.** Every one
of 5,829 sites grows a parent hop, against 645 that merging has to rename. What
embedding buys is that none of its edits is a *name it made up*.

### 4. Duplication

Merging copies a base's members into every derived type, so the cost is
`O(base members x derived count)`.

| | cut | breadth |
|---|---:|---:|
| distinct base storage members | 22 | 1,228 |
| member copies under merge | 42 | **10,218** |
| ratio | 1.9x | **8.3x** |

The worst cases are not marginal: `TranslationCPU` has 136 storage members and
25 in-corpus subclasses (3,400 copies); `BasicDoubleWordPeripheral` has 4
members and **189** subclasses. The cut's 1.9x is small enough to ignore. The
shape is not, and the deliverable already contains `CortexM`, whose chain is
`Arm → TranslationCPU → BaseCPU → CPUCore → IdentifiableObject`.

Duplication is also what damages this project's own instrumentation: one
unmapped base field (`machine`, `sysbus`, `mapper`) is reported as a separate
gap in every derived peripheral, so the census over-weights base classes by
their fan-out and closing one mapping silently closes several gap lines.

---

## The dispatch trait: built, compiled, and what stopped it

`scripts/dispatch_spike.py` generates a dispatch trait, a receiver type per
peripheral and the impls **from the corpus**, writes a scratch crate under
`tmp/dispatch_spike/`, and compiles it. Nothing under `src/` is touched;
`scripts/check_refactor.py` reports all nine artefacts byte-identical.

**The language claim holds.** The generated trait is object-safe, four
peripherals with four different `State` types live in one
`Vec<Rc<RefCell<dyn _>>>`, dispatch works, and the flattened `State` and the
free-fn bodies are untouched. 115 generated lines, `cargo test` green.

**The generated-output claim does not.** Three blockers, all measured:

### (a) The interface dispatch actually goes through is not in the corpus

`type_implements` records 126 interface declarations across the cut. **12
resolve to an ingested interface; 114 do not** — `interface_id` is NULL, so
their members are unknown. `IDoubleWordPeripheral`, which is what Renode's
system bus calls `ReadDoubleWord` through, is one of the 114. A trait declared
with hand-chosen methods would be a hand-written file wearing a rule's name.

The spike works around it with a rule that is general and needs no interface:
**an in-cut base class with virtual members defines a dispatch contract.**
Three such bases exist in the cut (`BasicDoubleWordPeripheral` with 6 derived
types, `BaseGPIOPort`, `RegisterField`). That is a legitimate rule for any C#
corpus, and it is not the same thing as translating the interface.

### (b) The forwarding target is private, so the trait is not additive

Every emitted method is `fn`, not `pub fn` — private to its module, callable
from no sibling. And no *generated* type owns the bank and the state together;
the receiver in the original hand-checked sketch was `Stm32Uart` from the
**hand-written** `uart.rs`, which exists for two of the seven modules.

Making them public is a one-token, behaviour-free edit that moves **39
committed lines** across the seven generated files. Real, small, and *not
additive*: `check_refactor.py` would go red. The spike patches the declaration
template in memory and does not commit it.

### (c) A withheld override silently becomes a call to the base

The sharpest result, and it is not an argument about traits. The obvious
resolver forwards a trait method to the plain name and falls back to
`{base}_{name}`. Run that way it produced an impl for all four peripherals —
and **three of them forwarded `reset` to `basic_double_word_peripheral_reset`,
the base's body**, because `STM32DMA`, `STM32F4_EXTI` and `STM32_ADC` all
override `Reset` and all three overrides are withheld. Virtual dispatch would
have called the wrong method, in code that compiles and passes its trace. That
is failure #1 in `docs/agents/transpiler-work-protocol.md` arriving by a new
route.

The correct rule falls out of how the emitter names things: the base copy takes
the plain name *unless* the derived type declares that name, in which case it
is qualified and the plain name belongs to the override. So the plain name is
always the dispatch target, and **`{base}_{name}` is exactly the set of bodies
that must never be dispatched to** — it is what `base.X()` calls, not what the
vtable calls.

With that rule the spike withholds `reset` from the trait entirely (3 of 4
implementors cannot supply it) and `offset_to_string` (no implementor emits it;
it reads the unmapped base field `mapper`). The trait that survives is
`read_double_word` + `write_double_word`, implemented by all four.

**One untranslatable base member shrinks the contract for every peripheral at
once.** That is a cost of the trait model that nobody had priced.

---

## The `{base}_{name}` convention

**Required under every model considered, including a trait model.** Rust has no
`super`; a trait's provided method cannot be called from an impl that overrides
it, because `Trait::method(self)` re-dispatches — verified in
`docs/research/inheritance.md`, and it warns as `unconditional_recursion` while
compiling happily. The base body has to live under a distinct name whatever the
layout is.

Under **embed** the same need is met without inventing anything:
`self.parent.reset()` names the base's body by its position rather than by a
manufactured identifier. That is the whole of embedding's advantage on this
axis, and the count is 645 invented names against 0 (breadth), 10 against 0
(cut).

Recommendation regardless of which option wins: `#![deny(unconditional_recursion)]`
in the generated crates. It turns the protocol doc's first "it compiled and was
wrong" case into a build failure.

---

## The options

### Option 1 — Reconcile PLAN.md to the implementation: merge, no trait

**Costs.** Gives up dispatch, which the system bus needs at every MMIO access
and which nothing in generated output can currently provide. Keeps a layout
that E0124s on 11 corpus types and on 2 of the cut's own peripherals as soon as
the cut is closed under `BaseType`. Keeps the invented `{base}_{name}` name.
Keeps gap-census fan-out.

**Buys.** Nothing changes. Zero regeneration.

### Option 2 — Reconcile the implementation to PLAN.md: keep merge, add a trait

**Costs.** 39 committed lines to `pub fn`, so not additive. Blocked on the
interface closure for the *real* dispatch trait, or accepts the base-class rule
instead. Inherits the shrinking-contract cost in (c). Leaves the collision
problem entirely untouched.

**Buys.** Dispatch, verified to compile. Nothing else moves.

### Option 3 — Embed the base, and add the trait

`struct DerivedState { parent: BaseState, ... }`, matching IL2CPP, Servo, QEMU
and c2rust.

**Costs.** Regenerates every line of every generated file. 5,829 sites grow a
parent hop. And a structural problem specific to **D2** that must be settled
first: the bank is typed `Bank<S>` on the *derived* `State`, so a base method
emitted as `fn reset(bank: &Bank<BaseState>, st: &mut BaseState)` cannot be
called with a `&Bank<DerivedState>`. Either base fns become generic over a
trait with field accessors — the RFC 1546 problem again, solved with methods —
or they are monomorphised per derived type, which is what merging already does.
**Embedding does not save the duplication under D2.** That was not obvious and
it is the strongest argument against option 3.

**Buys.** Collisions become unrepresentable rather than unlucky. The base stays
identifiable, so a gap can be attributed to it once instead of once per
derived type. `base.X()` stops needing an invented name.

### Option 4 — Merge now, embed only where the corpus forces it

Keep merging; **detect** a collision and refuse to emit, naming it. The census
already computes the set. Revisit embedding when the count stops being zero in
the cut.

**Costs.** Two layouts eventually, and the second one arrives under deadline.

**Buys.** The E0124 becomes a reported gap instead of a compile error, which is
this project's stated failure discipline, and it costs no regeneration.

---

## Recommendation

**Option 2 for dispatch, plus the collision guard from option 4. Not option 3,
for now.**

Reasoning, and the order matters:

1. **Dispatch is not optional and is nearly free.** It compiles, it changes no
   emitted body, and its only blocker is one keyword on 39 lines. Ship it as a
   deliberate, one-time regeneration of those 39 lines rather than pretending
   it is additive — the honest framing is that it is the *smallest possible*
   non-additive change, not that it is none.

2. **Embedding's advantage is real but its cost under D2 is worse than
   expected.** It buys collision-safety and base identity; it does not buy
   deduplication, because `Bank<S>` forces the base body to be monomorphised
   per derived type anyway. Paying a full regeneration and 5,829 edited sites
   for one property, when a guard delivers the same safety for a few lines, is
   not the trade this project should make while the cut has zero collisions.

3. **But the zero is fragile, and it should be guarded now.** Two of the cut's
   own peripherals collide already; they are hidden only by the truncated cut.
   The guard costs a comparison and turns a compile error into a named gap.

4. **Close `CorpusCut.cs` under `BaseType` before re-measuring anything.** 69%
   of the cut's chains are truncated and 79% of its base-access sites reach a
   base the corpus cannot see. Every number in this document about the cut is a
   lower bound, and the choice between merge and embed should be re-run once it
   is not. That is a master-run request, not an agent change.

**Where the evidence went against expectation, plainly:** I expected the
collision count to argue for embedding and it did the opposite on the cut —
zero instances — and it took a breadth run plus executing the emitter to find
that the zero was an artefact of the truncated corpus rather than a fact about
the code. And I expected embedding to reduce duplication; under D2's
`Bank<S>` it does not, which is the reason the recommendation stops short of
option 3.

**Failure mode of this recommendation.** The base-class dispatch rule in (a) is
not the C# interface. It produces a trait named after a class, and any code
that needs `peripheral is INumberedGPIOOutput` — which `IPeripheralExtensions`
performs — is not served by it. If the interface closure is never fixed in the
ingest, this becomes a permanent approximation that looks like a translation.
It should be recorded as a deviation on the rule, and the ingest gap
(`type_implements.interface_id` NULL for out-of-cut interfaces) filed against
the frontend rather than worked around again.

---

## Not done here, on purpose

- **PLAN.md is not edited.** Reconciling it is the maintainer's act once the
  option is chosen.
- **#57 (`Gc<T>`) is still open**, and the maintainer's note on #56 says it
  interacts: if reference-typed fields become `Gc<T>`, the field-layout half of
  this question changes shape. Nothing here commits a field layout, which is
  the half #57 would move; the dispatch half is neutral to it, since `dyn
  Trait` works the same behind `Rc<RefCell<_>>`, an arena index, or a `Gc<T>`.
- **No committed generated artefact was added.** The spike lives in `tmp/`
  because landing a trait that cannot yet name the right interface would be a
  plausible stub, and this project has already paid for one of those.
