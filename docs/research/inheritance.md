# Inheritance: flattening versus traits

Research for issue #41 (`T-R4`, `blocked-decision`). Deliverable is this
document; no code was changed.

The issue exists to attack a decision already implemented. This document tried
to break it and reports what it found, including the parts that survived.

---

## Verdict, up front

**The decision survives, but its stated reason does not, and it is incomplete.**

Three separate claims are tangled together in the current rule text. They have
to be separated before any of them can be judged:

| claim | verdict |
|---|---|
| **A.** Base *fields* are copied into the derived type's `State` | **Correct, and forced.** Rust has no field inheritance and never will; the RFC that would have added it died in 2018. Every serious translator does this. |
| **B.** Base *method bodies* become free fns over `(bank, st)` | **Correct, but not because of inheritance.** It is forced by the D2 callback signature, which has no `self` to offer. The inheritance rule takes credit for a decision D2 already made. |
| **C.** Therefore no trait is emitted at all | **Wrong, and the expensive part.** Nothing about A or B prevents an object-safe dispatch trait. Without one there is no vtable, and D1 and the sysbus both need one. |

The stated justification — *"a trait cannot carry the base's FIELDS, which is
what derived code actually reaches for"* — is a true statement that argues only
for **A**. It is used to justify **C**, which does not follow. A trait does not
need to carry fields to carry *methods*, and methods are what polymorphic
dispatch needs.

**Recommendation:** keep A and B unchanged; add C's missing piece as a
*generated, additive* dispatch trait plus one impl per implementing type. This
regenerates nothing, changes no emitted body, and is proven below to compile
with `Rc<RefCell<dyn …>>` over heterogeneous flattened peripherals. Its failure
mode is named in [Recommendation](#recommendation-and-its-failure-mode).

Cost: roughly **60–90 lines** of new emitter code in a new module, ~25 lines
moved, and no change to any existing generated line. See
[Cost](#cost-what-would-actually-change).

---

## 1. What is implemented today

`scripts/emit.py`:

- `base_chain(type_name)` (line 873) walks `type.base_type_id` and returns the
  ancestors **that are inside the corpus cut**, nearest first, *by name*.
- `state_fields()` (line 919) selects members of `[type] + base_chain(type)`
  into one `State` struct. Base fields and derived fields become siblings.
- `emit_file()` (line 728–752) emits every base method with a body as a free
  fn. When the derived type declares a method of the same **name**, the base
  copy is renamed using `inheritance.qualified_call` = `{base}_{name}`.
- `emit_peripheral_method()` (line 1057) always emits
  `fn {name}(bank: &Bank<State>, st: &mut State, …)`. There is no `self`.

`rulesdb/rules/register_dsl.json` → `inheritance`:

> "Rust has no inheritance, so a peripheral's base class is FLATTENED into it:
> base fields join State, base methods are emitted as free fns over the same
> (bank, st). This is the object-model deviation D1 applied to peripherals —
> recorded here because the alternative, a trait, cannot carry the base's
> FIELDS, which is what the derived code actually reaches for."

Observed output (`src/renode-stm32/src/uart_registers.rs`):

```rust
fn basic_double_word_peripheral_reset(bank: &Bank<State>, st: &mut State) -> () {
    bank.reset();
}
```

That is `BasicDoubleWordPeripheral.Reset()` — the base's body — living inside
the UART's generated module under a name qualified by its declaring type. The
mechanism works.

### The real reason for free functions is D2, not inheritance

`register_dsl.json` → `peripheral_methods.note` states it plainly:

> "EVERY peripheral method becomes a free fn over (bank, state) … Inside a DSL
> callback you hold `&Bank<S>` and `&mut S`, which is the peripheral taken
> apart, so a method reached from a callback cannot have a `self`."

`renode_regs::ValueProvider<S> = fn(&Bank<S>, &mut S, usize, u64) -> u64` — a
bare `fn` pointer over the split peripheral. The split is real and it is D2's,
not inheritance's. Any inheritance model has to live with it. This matters
because it means **the free-function convention is not evidence for
flattening**; it would be true under a trait model too.

---

## 2. Corpus evidence

Run against `rulesdb/patterns.db`, `corpus_run.config = 'f427'`, Renode
`dc52b24c118a`. 45 files, 187 types, 1,423 methods, 69,741 operation nodes.

### The headline numbers the issue asked for

```
SELECT COUNT(*) FROM type WHERE base_type_id IS NOT NULL;          -->  10
SELECT COUNT(*) FROM method WHERE is_virtual=1 OR is_override=1;   -->  72
```

Of those 72: **9 `virtual`, 63 `override`, plus 145 `abstract`** (mostly
interface members). The cut's C# contains 17 `base.` references, of which 9 are
method invocations the corpus resolves to a named base type (the rest are
`base.Width` property reads and calls into out-of-cut bases).

### Hierarchy depth: the "1" is an artifact, the truth is up to 6

The recursive query over `base_type_id` says maximum depth **1**:

```
depth  types
0      92
1      10      STM32_UART -> BasicDoubleWordPeripheral, etc.
```

That number is wrong about the world. It is measuring the *cut*, not the
hierarchy, and `frontend/RenodeIngest/CorpusCut.cs` is a hand-listed set of 45
file paths that is **not closed under `BaseType`**. Reading the declarations in
the Renode tree directly:

| in-cut type | real chain | real depth |
|---|---|---|
| `CortexM` | → `Arm` → `TranslationCPU` → `BaseCPU` → `CPUCore` → `IdentifiableObject` | **5** |
| `STM32F4_FlashController` | → `STM32_FlashController` → `BasicDoubleWordPeripheral` | **2** |
| `STM32F1_I2C` | → `SimpleContainer<T>` → `SimpleContainerBase<T>` | **2** |
| `STM32_UART`, `STM32_ADC`, `STM32DMA`, `STM32F4_EXTI`, `STM32_PWR`, `STM32_IndependentWatchdog` | → `BasicDoubleWordPeripheral` | 1 |
| `STM32_GPIOPort` | → `BaseGPIOPort` | 1 |
| `STM32SPI` | → `NullRegistrationPointPeripheralContainer<T>` | 1 |
| `STM32_Timer` | → `LimitTimer` | 1 |

**Four of the eighteen peripherals in the cut (22%) have a base class the
emitter cannot see at all**, and so does `CortexM`. `base_chain()` returns `[]`
for `STM32F4_FlashController`, `STM32F1_I2C`, `STM32SPI`, `STM32_Timer` and
`CortexM`, and they are emitted as if they had no base:

```
STM32F4_FlashController:
  Reset:           withheld, body still contains a gap marker (/* GAP: base-class call */)
  WriteDoubleWord: withheld, body still contains a gap marker (/* GAP: base-class call */)
STM32F1_I2C:
  Reset: withheld, reaches state this peripheral does not have: st.address, st.child
```

Note the second one: `child` is `SimpleContainerBase<T>`'s protected field. The
gap says *"this peripheral does not have that state"* when the truth is *"its
base class is not in the corpus"*. Flattening degrades the diagnostic as well as
the output.

This is a **corpus-cut finding, not an inheritance finding** — a trait model
would need the base's bodies too — but flattening is what makes the failure
silent-ish rather than structural. Under a trait model the missing base is one
unimplemented trait; under flattening it is an unknown number of missing fields
and methods scattered through the derived type.

### Duplication: 3.2% today, and it scales with derived count

Running the emitter over all 11 register-defining types that emit:

```
7x  fn read_double_word(bank: &Bank<State>, st: &mut State, offset: i64)
7x  fn write_double_word(bank: &Bank<State>, st: &mut State, offset: i64, value: u32)
5x  fn basic_double_word_peripheral_reset(bank: &Bank<State>, st: &mut State)
5x  fn size(bank: &Bank<State>, st: &mut State) -> i64

duplicated lines (copies beyond the first): 99 = 3.2% of emitted output
```

Small, and honestly not an argument by itself — `rustc` will fold identical
bodies and 99 lines is nothing. The number that matters is the *shape*: cost is
`O(base_size × derived_count)`. `BasicDoubleWordPeripheral` is 35 lines of class
body and has **6 derived types in the cut**; a plain grep of the Renode tree
finds 314 classes implementing `IDoubleWordPeripheral`. (Cited as scale only —
per CLAUDE.md, tree-wide data is a health check and must not generate work
items.) In a corpus with a real framework base — an abstract `Device` with 400
lines and 300 subclasses — flattening emits those 400 lines 300 times.

### Duplication in the *gap report* is the concrete harm today

Same run, counting gap lines emitted across all types:

```
total gap lines: 240   distinct: 160   duplicated: 80  (33%)

  8x  state field `machine`: no Rust mapping for `Antmicro.Renode.Core.IMachine`
  8x  OffsetToString: withheld, reaches state this peripheral does not have: st.mapper
  6x  state field `sysbus`: no Rust mapping for `Antmicro.Renode.Peripherals.Bus.IBusController`
  2x  state field `Connections`: no Rust mapping for `IReadOnlyDictionary<int, IGPIO>`
```

`machine`, `sysbus` and `mapper` are `BasicDoubleWordPeripheral`'s three
protected fields. One unmapped base type produces **eight** gap lines, one per
derived peripheral. **A third of the reported gaps are the same handful of base
defects counted repeatedly.**

That directly damages the project's own instrumentation. `docs/census.md` and
`scripts/gap_census.py` exist to rank what to work on next; CLAUDE.md makes
patches-outstanding a CI-gated metric that must trend to zero. Under flattening
the ranking over-weights base classes by their fan-out, and closing one mapping
silently closes eight lines. A trait model reports each base defect **once**,
against the base.

### Interface diamonds are real, and Rust handles them better than flattening

`STM32SPI : NullRegistrationPointPeripheralContainer<ISPIPeripheral>,
IWordPeripheral, IDoubleWordPeripheral, IBytePeripheral, IKnownSize` — and
`IWordPeripheral`, `IDoubleWordPeripheral` and `IBytePeripheral` all extend
`IBusPeripheral : IPeripheral : IAnalyzable : IEmulationElement`.

`IPeripheral.Reset()` reaches `STM32SPI` by three inheritance paths. This is the
classic diamond, and **Rust's supertrait DAG resolves it exactly as C# does** —
one `Reset`, three contracts satisfied, no ambiguity, no code. Flattening
resolves it by collapsing everything to one bare snake-case name and losing the
fact that three contracts were satisfied.

`BaseGPIOPort` shows the other half of the same problem. It declares **four**
methods named `Register` and **two** named `Unregister`, one pair per interface
instantiation it implements. The emitter keys `emitted[…]` by `self.fn_name()`
= `snake(name)`, so all four collapse to `register` and the last one written
wins. It does not misbehave today only because all four gap out on
`IGPIOSender`/`IGPIOReceiver` parameter types. There are **70 `(type, method
name)` groups in the cut with more than one body-bearing overload** — `Logger`
has 10 `Log`, `BitHelper` has 5 `ClearBits`. Flattening merges the base's and
derived's name spaces into one, which makes this pre-existing name-keying bug
strictly worse.

### The emitted entry point is not stable across peripherals

`inheritance.qualified_call` fires when the derived type *declares* a method of
the same name — regardless of whether that derived method actually emits.
`STM32_ADC` overrides `Reset`, so the base copy is renamed
`basic_double_word_peripheral_reset`; the derived `Reset` is then withheld
(`reaches state … st.channels`). The module therefore exports **no `reset` at
all**. `STM32_PWR` does not override `Reset`, so the base copy keeps the plain
name and the module exports `reset`.

Same C# interface method, two different emitted names, decided by an unrelated
property of the derived class. Nothing generic can call "reset on any
peripheral" over that. This is exactly the "per-file rename table" that CLAUDE.md
already condemns for the hand-written files, arrived at from the other
direction.

---

## 3. What other translators actually do

<!-- SURVEY -->

---

## 4. Where flattening breaks

Ordered by how soon this project hits it.

### 4.1 It has no vtable, so there is no polymorphic entry point (now)

Covered above and in §5. This is the binding constraint.

### 4.2 `base.X()` needs the qualified name — and so does a trait model

Worth stating because it is the one place flattening does *not* lose. Rust has
no `super`. A trait's provided (default) method **cannot** be called from an
impl that overrides it — `Trait::method(self)` re-dispatches to the override.
Verified:

```rust
trait Base { fn reset(&mut self) { println!("base reset"); } }
impl Base for Derived {
    fn reset(&mut self) { println!("derived reset"); Base::reset(self); }
}
```

```
warning: function cannot return without recursing
  = note: `#[warn(unconditional_recursion)]` on by default
--- running ---
derived reset
derived reset
derived reset
...
```

This is precisely bug #1 in `docs/agents/transpiler-work-protocol.md` ("`base.Reset()`
emitted as a self-call | unbounded recursion; rustc accepts it"). The fix under
a trait model is *the same* `{base}_{name}` split the emitter already performs:
put the base body in a distinctly-named method and have the provided method
delegate to it. **The `qualified_call` rule is not wasted work — it is required
under every model considered here.** That is a genuine point in the current
design's favour.

Aside worth recording: `rustc` *does* diagnose that specific bug, as
`unconditional_recursion`, at warning level. `#![deny(unconditional_recursion)]`
in the generated crates would have turned the protocol doc's first "it compiled
and was wrong" case into a build failure.

### 4.3 Deep hierarchies multiply, and the corpus is not closed over them

§2: real depth reaches 5 (`CortexM`), and 28% of in-cut peripherals have an
out-of-cut base. Flattening needs the *entire* ancestor chain present. A trait
model needs the same bodies but degrades better: the missing base is one
unimplemented trait, named once.

### 4.4 Method hiding (`new`) is indistinguishable from an ordinary method

`RegisterField.cs:214` in the cut:

```csharp
public new int Width => base.Width;
```

`member`/`method` records `is_virtual=0, is_override=0` for `get_Width` — identical
to any non-virtual method. Under flattening, hiding and overriding produce the
same output. The two differ **only when called through a base reference**, which
is the case flattening cannot express anyway, so this is latent rather than live
— but it becomes live the moment §5's dispatch exists.

### 4.5 Name-keyed lookup merges same-named types

`base_chain()` returns type **names**, and `state_fields()` filters
`WHERE t.name IN (…)`. The corpus contains 7 duplicated type names, two of them
in a base/derived relationship:

```
PeripheralRegister  ->  PeripheralRegister<T> | PeripheralRegister
RegisterField       ->  RegisterField<T>      | RegisterField
```

Confirmed by running the emitter's own methods:

```
base_chain('PeripheralRegister') == ['PeripheralRegister']     # its own base
state_fields('PeripheralRegister') merges the members of BOTH types
```

This is the same bug `nested_enums()` was already fixed for, with the reason
recorded in the code: *"Keyed on the type's ID, never its name: the corpus holds
many types called `Registers` … and matching by name merged all of them."* The
fix did not reach `base_chain`. There is also a determinism exposure: line 880
is `SELECT … WHERE name=?` with `fetchone()` and no `ORDER BY`, so which of two
same-named types is chosen is unspecified — against CLAUDE.md's byte-identical
output requirement.

### 4.6 Heterogeneous collections need `dyn` or a closed enum

Flattening gives each peripheral a *distinct* `State` type, so `Bank<State>` is
a distinct type per peripheral and no uniform storage exists. Options are
`dyn Trait` (needs the trait §5 adds) or an enum over implementers.

The enum is more viable here than it looks. `docs/status/platform.json`, derived
from the `.repl`, has **65 instances of 24 distinct peripheral types**, and
PLAN.md already puts `.repl`/reflection loading in the "stays hand-written
forever" bucket — so the world is closed at compile time *for this project*.
A 24-variant enum is tractable.

It is disqualified anyway, for two reasons:

1. **It is not general.** The deliverable is a transpiler that "must work on any
   corpus". Closed-world is a property of this project's platform-loading
   decision, not of C#. Any corpus with a plugin registry breaks it. Emitting an
   enum would be baking a corpus fact into the language layer, which
   `scripts/check_layering.py` exists to prevent.
2. **It gets the semantics wrong.** A C# interface is an open set. An enum is a
   closed one. `peripheral is INumberedGPIOOutput` — which `IPeripheralExtensions`
   actually performs — is a downcast over an open world.

**What enum dispatch gets wrong, stated plainly:** it converts an open-world
contract into a closed-world one, it makes adding a peripheral a change to a
shared file (destroying the "many small crates, no shared edit" parallelism
constraint), and every call site becomes an `O(variants)` `match` that must be
regenerated when any implementer is added.

---

## 5. Does flattening survive polymorphic dispatch through `IPeripheral`?

**Not as it stands, and this is the part that must change.**

Renode's `SystemBus` stores `IBusPeripheral` and calls `ReadDoubleWord` /
`WriteDoubleWord` / `Reset` through the interface at every MMIO access. That
dispatch is not incidental — it is the hot path (~409 ns/access, per
`docs/perf-spike.md`). The generated code currently offers nothing to dispatch
*to*: free fns with per-peripheral `State` types, under names that are not even
stable (§2).

It does **not** force an enum. It forces one small generated trait.

### The additive fix, verified

The key fact is in the existing hand-written `src/renode-stm32/src/uart.rs`:

```rust
pub struct Stm32Uart {
    bank: Bank<State>,
    f: Fields,
    st: State,
    ...
}
```

`bank` and `st` are **separate fields**, so `&self.bank` and `&mut self.st` are
disjoint borrows and a `&mut self` method may call the generated free fns
directly. The dispatch trait is therefore pure addition — no generated body
changes:

```rust
pub trait IDoubleWordPeripheral {              // GENERATED, new
    fn reset(&mut self);
    fn read_double_word(&mut self, o: i64) -> u32;
}

impl IDoubleWordPeripheral for Uart {          // GENERATED, new, 2 lines/method
    fn reset(&mut self) { uart_registers::reset(&self.bank, &mut self.st) }
    fn read_double_word(&mut self, o: i64) -> u32 {
        uart_registers::read_double_word(&self.bank, &mut self.st, o)
    }
}
```

Compiled and run, with two peripherals whose `State` types differ, over D1's
object graph:

```rust
let bus: Vec<Rc<RefCell<dyn IDoubleWordPeripheral>>> = vec![
    Rc::new(RefCell::new(Uart{ .. })),
    Rc::new(RefCell::new(Pwr { .. })),
];
for p in &bus { p.borrow_mut().reset(); p.borrow_mut().read_double_word(0); }
```

This compiles and runs. Heterogeneous collection, virtual dispatch through the
base interface, `Rc<RefCell<dyn _>>`, flattened fields, unchanged free-fn
bodies — all four at once.

### The object-safety trap, and why it is benign

A trait that mentions `Self` in a signature is not `dyn`-compatible. A base trait
with a `fn bank(&self) -> &Bank<Self>` accessor hits it:

```
error[E0038]: the trait `Base` is not dyn compatible
  |           ^^^^^^^^ ...because method `bank` references the `Self` type in its return type
  = help: consider moving `bank` to another trait
```

So the model needs **two** traits: an object-safe *dispatch* trait (one per C#
interface, `Self`-free) and, if base bodies are ever hoisted, a non-object-safe
*base-behaviour* trait. Getting it wrong is a `rustc` error with the fix in the
diagnostic — a loud failure, not one of the four silent ones in the protocol doc.

---

## 6. What the choice does to D1

**PLAN.md already decided this, and the implementation quietly reversed it.**

PLAN.md, "The remaining C#→Rust mappings":

| C# construct | Rust, literal-first |
|---|---|
| `class` instance | `Rc<RefCell<T>>` (D1) |
| Inheritance (`BasicDoubleWordPeripheral`) | **Composition: base as a struct field + trait with default methods.** Measured trivial — the base is 49 lines and provides `RegistersCollection` plus three forwarding methods, not real polymorphism |
| `virtual`/`abstract` | **Trait objects (`Rc<RefCell<dyn Peripheral>>`)** |

CLAUDE.md: *"The four declared deviations (D1–D4) are whole-program decisions;
do not make a per-file choice that contradicts one, and do not silently revisit
one — reopen the decision issue."*

Flattening-with-no-trait contradicts both rows. `Rc<RefCell<dyn Peripheral>>`
requires a `Peripheral` trait; the emitter declines to produce one. There is no
`Rc<RefCell<_>>` anywhere in generated output today. This issue **is** the
reopening, which is the correct process — but the deviation should be recorded
as such rather than left looking like a faithful mapping.

Two smaller D1 interactions:

- PLAN.md's "not real polymorphism" is **understated**. All four
  `BasicDoubleWordPeripheral` methods are `virtual`, six in-cut types override
  `Reset`, and `ReadDoubleWord`/`WriteDoubleWord` are dispatched by the sysbus
  on every MMIO access. Its *recommendation* was right; its justification was
  not.
- D2 already pulls the other way. PLAN.md notes "D1's `Rc` blocks `Send` while
  D2's arena permits it". The dispatch trait in §5 is neutral on this: `dyn Trait`
  works equally in `Rc<RefCell<_>>` and in an arena with index handles, so
  adding it does not spend any of the Stage-3 lift's freedom.

---

## Recommendation and its failure mode

**Keep field flattening. Keep free-fn bodies. Add a generated dispatch trait.**

1. **Field flattening stays.** Forced by Rust; universal in the survey above.
2. **Free-fn bodies stay.** Forced by D2's `fn(&Bank<S>, &mut S, …)` callbacks,
   not by inheritance. Changing it is a D2 conversation, not this one.
3. **Emit one object-safe trait per C# interface a peripheral implements, and
   one impl per implementing type**, each method a two-line forward to the
   existing free fn. Additive; regenerates nothing.
4. **Rewrite the rule's stated reason.** It currently justifies "no trait" with
   an argument that only supports "flatten the fields".
5. **Derive the qualified name from `operation.symbol`, not by name-matching the
   base chain.** The corpus already records the exact declaring type — the
   ingest sets `IInvocationOperation.IsVirtual`, which is `false` precisely for
   `base.X()` calls, and `symbol` is fully qualified:

   ```
   STM32_UART.Reset -> Antmicro.Renode.Peripherals.BasicDoubleWordPeripheral.Reset()
                       {"virtual":false}
   ```

   Nine such sites resolve exactly today with no re-ingest. This removes §4.5's
   name-merging and §2's unstable entry point in one change.

   It also strictly dominates the current approach on the hardest case.
   `STM32F4_FlashController.Reset` calls `base.Reset()`; its immediate base
   `STM32_FlashController` is **not** in the cut, so `base_chain()` returns `[]`
   and the call is withheld. But Roslyn already resolved the call past the
   missing intermediate — `symbol` is
   `Antmicro.Renode.Peripherals.BasicDoubleWordPeripheral.Reset()`, a type that
   **is** in the cut. Reading the symbol emits correctly where walking the chain
   by name cannot.
6. **Move the rule to the language layer.** `inheritance` currently lives in
   `rulesdb/rules/register_dsl.json` (project idioms) and its note is written in
   terms of peripherals. Inheritance is generic C#; per CLAUDE.md's three-layer
   table it belongs in the language layer, and `csharp_core.json` has no
   inheritance section at all. `scripts/check_layering.py` cannot catch this —
   it checks the *language* layer for corpus words, never the *project* layer for
   generic constructs. That asymmetry is worth a follow-up issue on its own.

### Its failure mode — stated, because an option list without one is not research

**The trait set is derived from `type_implements`, which records only *directly
declared* interfaces.** `IPeripheral` appears there just twice across 187 types,
because everything else reaches it transitively through
`IDoubleWordPeripheral : IBusPeripheral : IPeripheral`. An emitter that reads
that table naively will generate a trait hierarchy that is *missing its own
supertraits*, and the symptom is `rustc` complaining that a trait bound is not
satisfied at the sysbus — far from the cause, and only once the sysbus exists
(Phase 2). The transitive closure must be computed, and the corpus does not
currently record enough to do it: `type_implements.interface_id` is `NULL` for
every interface outside the cut, and `IBusPeripheral` is one of them.

Second failure mode: a blanket `impl<T: BaseTrait> DispatchTrait for T` is the
tempting way to write step 3 with less code, and it **breaks on the second base
class** with coherence error E0119, because two base traits both blanket-impl
the same dispatch trait. Emit concrete per-type impls, and record that as a
negative in the rule (`rule_negative`) so the shortcut is not rediscovered.

### What to do about the corpus cut

Not this issue, but it blocks the measurement: `CorpusCut.cs` should be closed
under `BaseType`. Five in-cut types currently have an invisible base. Per
`docs/agents/transpiler-work-protocol.md` that is a **master-run request**, not
an agent change, and is filed as a finding rather than acted on here.

---

## Cost: what would actually change

Measured against `scripts/emit.py` (1,131 lines) and
`scripts/emitter/` (724 lines).

| change | where | lines | regenerates output? |
|---|---|---:|---|
| Dispatch trait + per-type impl emission | new `scripts/emitter/lang/inheritance.py` | ~60–90 new | **adds** a block; changes no existing line |
| Its rules | new `rulesdb/rules/lang/inheritance.json` | ~40 JSON | — |
| Move `inheritance` out of `register_dsl.json` | rules | ~6 moved | no |
| Qualified name from `operation.symbol` | `emit.py` 728–752 | ~15 changed | renames base copies in ≤5 files |
| `base_chain` keyed on type id | `emit.py` 873–892, 919–946 | ~12 changed | no (no live collision today) |
| Transitive interface closure | ingest (`type_implements`) | master run | no |

**Nothing in `emit_peripheral_method`, `rewrite_this`, the callback signatures,
`state_fields`, `renode_regs::Bank`, or any emitted body changes.** That is the
whole reason to recommend the additive version over a rewrite: the change is
confined to a new module plus two small correctness fixes, and the byte-identical
`check_generated.py` gate stays green for every existing file except the ≤5
whose base copies get a more precisely derived name.

For contrast, the rejected alternative — hoisting base bodies into trait provided
methods, i.e. *not* flattening — would rewrite `emit_peripheral_method`'s
signature template, `rewrite_this`'s `st.` rewriting, every callback signature in
`callback_signatures`, and `Bank<State>`'s type parameter, and would regenerate
every line of every file. It buys deduplication worth 3.2% and costs the D2
callback model. Not worth it.

---

## Findings to file separately

Reported, not fixed — each is outside this issue's module per
`docs/agents/transpiler-work-protocol.md`.

**Transpiler bugs**

1. `base_chain()`/`state_fields()` key on type **name**; two base/derived pairs
   in the cut share a name (`PeripheralRegister`, `RegisterField`) and their
   members are merged. Same class as the already-fixed `nested_enums` bug.
2. `emit.py:880` — `SELECT … WHERE name=?` + `fetchone()` with no `ORDER BY`;
   unspecified row choice where names collide, against the byte-identical
   output requirement.
3. `emitted[]` is keyed by snake-cased method name, so C# **overloads collide
   and the last one wins**. 70 `(type, name)` groups in the cut have more than
   one body-bearing overload; `BaseGPIOPort` has 4 × `Register`.
4. `inheritance.skip_when_external` names `BaseGPIOPort` as the example of an
   out-of-cut base. `BaseGPIOPort` is **in** the cut. The real examples are
   `STM32_FlashController`, `SimpleContainer<T>`,
   `NullRegistrationPointPeripheralContainer<T>`, `LimitTimer`, `Arm`.

**Ingest gaps** (each a property Roslyn exposes that is not being read)

5. `IMethodSymbol.OverriddenMethod` — would give the exact base method a
   `override` refines, removing the name-matching in §4.5.
6. `IMethodSymbol.IsSealed` — `sealed override` forbids further override and
   permits devirtualisation; not recorded.
7. `IMethodSymbol.ExplicitInterfaceImplementations` — C# resolves same-name
   members of two interfaces this way; neither the schema nor the emitter can
   represent it.
8. **Method hiding (`new`)** is not distinguishable from an ordinary method.
   `RegisterField.cs:214` has one in the cut. Detectable by looking for a
   same-signature member on a base type while `IsOverride` is false.
9. `type_implements` records only directly-declared interfaces and leaves
   `interface_id` `NULL` for anything outside the cut, so the interface
   supertrait closure cannot be computed. This blocks the recommendation.

**Corpus cut**

10. `CorpusCut.cs` is not closed under `BaseType`; 4 of the 18 in-cut
    peripherals plus `CortexM` have an invisible base class. Master-run request.

**Process**

11. `scripts/check_layering.py` checks the language layer for corpus leakage but
    not the project layer for generic constructs, so a generic C# rule sitting in
    a project rules file (as `inheritance` does) passes silently.

---

## Sources

<!-- SOURCES -->
