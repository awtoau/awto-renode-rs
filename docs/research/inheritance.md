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
| **A.** Base *fields* are copied into the derived type's `State` | **Correct, and forced.** Rust has no field inheritance; the RFC that would have added it was postponed in 2018 and its follow-up repo has been silent since 2017. Every surveyed translator does the equivalent. One refinement: QEMU and Servo keep the parent as a *named first field* rather than splatting its members, which is the same layout and retains the information we are currently throwing away. |
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

Cost: roughly **60–90 lines** of new emitter code in a new module, plus two
small correctness fixes (~27 lines changed) in `emit.py`. The dispatch trait
itself changes no existing generated line — it appends a block. See
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

### Hierarchy depth: the "1" is an artifact, the truth is up to 5

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

Five production systems that had to solve exactly this, plus the Rust sources
that settle the language question. Every one of them **separates the field
decision from the dispatch decision**. Not one of them drops dispatch.

A finding worth stating first, because it shapes how much of this is
transferable: **there is no general C#-to-Rust transpiler in public.** Searches
of GitHub for `"c# to rust"`, `"csharp rust transpiler"`, `"dotnet to rust"`,
`"IL to Rust"` and `cs2rust` return nothing with traction, against a crowded
C-to-Rust field (c2rust ~4.8k stars, corrode ~2.2k, plus crust, sactor, crown,
concrat, simcrat, decy). There is no off-the-shelf answer to copy, and the
nearest analogues are all one hop away: C# to C++ (IL2CPP), C to Rust (c2rust),
IDL to Rust (Servo), and C to Rust *by hand for an emulator's device models*
(QEMU) — which turns out to be the closest of all.

### 3.1 IL2CPP — Unity's C#-to-C++ AOT compiler

The closest analogue available: same source language, and a target with *more*
OO than Rust has.

**Fields → real C++ single inheritance.** From "IL2CPP Internals: A Tour of
Generated Code" (Josh Peterson, 2015-05-13; original URL is 404, archived at
`web.archive.org/web/20210515152602/https://blogs.unity3d.com/2015/05/13/il2cpp-internals-a-tour-of-generated-code/`):

```cpp
struct Important_t1  : public Object_t
{
// System.Int32 HelloWorld/Important::InstanceIdentifier
int32_t ___InstanceIdentifier_1;
};
struct Important_t1_StaticFields
{
// System.Int32 HelloWorld/Important::ClassIdentifier
int32_t ___ClassIdentifier_0;
};
```

Base subobject at offset zero. Instance fields inline; statics hoisted to a
separate struct reached through the type metadata. Physically identical to
flattening.

**Methods → free functions, instance as first argument.** From "IL2CPP
Internals: Method Calls" (2015-06-03, archived at
`web.archive.org/web/20210422110620/…/il2cpp-internals-method-calls/`), verbatim:

> "The last line is the actual method call. Note that it does nothing special,
> just calls a free function defined in the C++ code. Recall from the earlier
> post about generated code, that il2cpp.exe generates all methods as C++ free
> functions. **The IL2CPP scripting backend does not use C++ member functions or
> virtual functions for any generated code.**"

```cpp
Important_Method_m1(L_1, (String_t*) &_stringLiteral1,
                    /*hidden argument*/&Important_Method_m1_MethodInfo);
```

This is `fn method(st: &mut State, …)` with a different syntax. **The current
design's calling convention is IL2CPP's calling convention.**

**Virtual dispatch → an explicit, generated invoker over a generated vtable.**
IL2CPP had C++ `virtual` available and *declined to use it*, generating its own
dispatch instead:

```cpp
template <typename R, typename T1>
struct VirtFuncInvoker1
{
typedef R (*Func)(void*, T1, MethodInfo*);

static inline R Invoke (MethodInfo* method, void* obj, T1 p1)
{
VirtualInvokeData data = il2cpp::vm::Runtime::GetVirtualInvokeData (method, obj);
return ((Func)data.methodInfo->method)(data.target, p1, data.methodInfo);
}
};
```

> "The call into libil2cpp `GetVirtualInvokeData` looks up a virtual method in
> the vtable struct generated based on the managed code, then it makes a call to
> that method."

Interfaces get a parallel mechanism, `InterfaceFuncInvoker`, because the
interface must be passed too:

> "The vtable for each type is stored so that interface methods are written at a
> specific offset. Therefore, il2cpp.exe needs to provide the interface in order
> to determine which method to call. The bottom line here is that calling a
> virtual method and calling a method via an interface have effectively the same
> overhead in IL2CPP."

**What it gets wrong.** Code bloat is severe and acknowledged — a hello-world
project produced "4625 header files and 89 C++ source code files", and every
build re-converts `mscorlib.dll` because byte-code stripping makes the result
input-dependent ("We are researching better ways to do incremental builds, but
we don't have any good solutions yet"). Injected runtime checks (`NullCheck`,
`IL2CPP_ARRAY_BOUNDS_CHECK`, `ArrayElementTypeCheck`) cost measurably: "in a few
specific cases though, we are seeing these checks lead to degraded performance,
especially in tight loops". And the dispatch cost was enough of a problem that
Unity published follow-ups titled *IL2CPP Optimizations: Devirtualization*
(2016-07-26) and *IL2CPP Optimizations: Faster Virtual Method Calls* (2016-08-04).

**Bearing on this decision:** IL2CPP endorses A and B and refutes C. It kept an
explicit dispatch mechanism even though free functions were its calling
convention, because free functions and dispatch are orthogonal.

### 3.2 Servo — WebIDL to Rust, generated

The most directly applicable prior art: a large shipped Rust codebase that
generates Rust from an interface definition language describing a deep
single-inheritance hierarchy. `components/script/dom/mod.rs`, verbatim:

> "**Inheritance**
> Rust does not support struct inheritance, as would be used for the
> object-oriented DOM APIs. To work around this issue, Servo stores an instance
> of the superclass in the first field of its subclasses. (Note that it is
> stored by value, rather than in a smart pointer such as `Dom<T>`.)
> This implies that a pointer to an object can safely be cast to a pointer to
> all its classes.
> **This invariant is enforced by the lint in `plugins::lints::inheritance_integrity`.**"

Fields: composition by value at offset 0 — the same physical layout as
flattening, with the parent kept as a named sub-struct instead of splatted.

Dispatch: a **generated trait**, plus a **generated enum** for `match`
discrimination — both, not either:

> "Interfaces which either derive from or are derived by other interfaces
> implement the `Castable` trait, which provides three methods `is::<T>()`,
> `downcast::<T>()` and `upcast::<T>()` to cast across the type hierarchy and
> check whether a given instance is of a given type.
> Furthermore, when discriminating a given instance against multiple interface
> types, **code generation provides a convenient TypeId enum** which can be used
> to write `match` expressions instead of multiple calls to `Castable::is::<T>`."

**What it gets wrong**, and it is not small. The casts are `unsafe`
(`components/script_bindings/inheritance.rs`):

```rust
fn upcast<T>(&self) -> &T where T: Castable, Self: DerivedFrom<T> {
    unsafe { mem::transmute::<&Self, &T>(self) }
}
```

Soundness rests on a layout invariant the type system does not check, so Servo
had to write a **custom compiler lint** to enforce it — see servo/servo#5927,
"Ensure DOM types have their base type as the first field". The type identity is
carried at runtime by a `proto_id` range check (`id >= T::PROTO_FIRST && id <=
T::PROTO_LAST`), i.e. a hand-maintained numbering of the hierarchy. That is a
lot of machinery to buy C++-style downcasting.

**Bearing on this decision:** Servo needed downcasting because the DOM API
demands it. Renode's sysbus does not — it calls `ReadDoubleWord` through the
interface and never asks what concrete peripheral it holds. So we get Servo's
field layout for free and can skip its `unsafe` entirely by using ordinary
`dyn Trait` dispatch. Servo is evidence for the split, and a warning about the
version of it we do *not* need.

### 3.3 QEMU's Rust device model — the closest precedent that exists

This is the one to read if only one is read. QEMU is porting device models to
*safe* Rust one at a time, from a C codebase whose object system (QOM) is
struct-embedding plus class structs of function pointers — structurally the same
problem as Renode's `IPeripheral` hierarchy, in the same domain, at the same
scale. The reference device is **a UART with a chip-specific derived variant**.

`rust/qom/src/qom.rs`, module documentation, verbatim:

> "The QEMU Object Model (QOM) provides inheritance and dynamic typing for QEMU
> devices. This module makes QOM's features available in Rust through three main
> mechanisms:
> * Automatic creation and registration of `TypeInfo` for classes that are
>   written in Rust, as well as mapping between Rust traits and QOM vtables.
> * Type-safe casting between parent and child classes, through the [`IsA`]
>   trait …
> * **Automatic delegation of parent class methods to child classes. When a
>   trait uses [`IsA`] as a bound, its contents become available to all child
>   classes through blanket implementations.**"

And its decomposition of a class — read this as a specification for what a C#
class becomes in Rust:

> "If a class has subclasses, it will also provide a struct for instance data …
> but it also needs additional components to support virtual methods:
> * a struct for class data, for example `DeviceClass`. This corresponds to the
>   C "class struct" and holds the vtable that is used by instances of the class
>   and its subclasses. **It must start with its parent's class struct.**
> * a trait for virtual method implementations, for example `DeviceImpl`. Child
>   classes implement this trait to provide their own behavior for virtual
>   methods. …
> * a trait for instance methods, for example `DeviceMethods`. This trait is
>   automatically implemented for any reference or smart pointer to a device
>   instance. It calls into the vtable …"

**Base fields: the parent is the first field, by value, in a marker newtype.**

```rust
#[repr(C)]
#[derive(qom::Object, hwcore::Device)]
pub struct PL011State {
    pub parent_obj: ParentField<SysBusDevice>,
    pub iomem: MemoryRegion,
    pub char_frontend: CharFrontend,
    pub regs: BqlRefCell<PL011Registers>,
    pub interrupts: [InterruptSource; IRQMASK.len()],
    pub clock: Owned<Clock>,
    pub migrate_clock: bool,
}
qom_isa!(PL011State : SysBusDevice, DeviceState, Object);
```

`ParentField<T>` is `#[repr(transparent)]` over `ManuallyDrop<T>` with `Deref`
and `DerefMut` to `T` — so the base's members are reachable without naming them,
while the base stays one identifiable field.

**The subtype relation is an `unsafe` marker trait** with the layout invariant
as its safety condition:

```rust
/// # Safety
///
/// The struct `Self` must be `#[repr(C)]` and must begin, directly or
/// indirectly, with a field of type `P`.  This ensures that invalid casts,
/// which rely on `IsA<>` for static checking, are rejected at compile time.
pub unsafe trait IsA<P: ObjectType>: ObjectType {}
```

**The vtable is an explicit `#[repr(C)]` class struct** whose first field is the
parent's class struct, and chain-up is an explicit call at the end of
`class_init`:

```rust
#[repr(C)]
pub struct PL011Class {
    parent_class: <SysBusDevice as ObjectType>::Class,
    device_id: DeviceId,
}
impl PL011Class {
    fn class_init<T: PL011Impl>(&mut self) {
        self.device_id = T::DEVICE_ID;
        self.parent_class.class_init::<T>();     // this is `base.ClassInit()`
    }
}
```

**Virtual overrides are associated consts holding function pointers** — an
override *populates a slot*, it does not shadow a default:

```rust
impl DeviceImpl for PL011State {
    const VMSTATE: Option<VMStateDescription<Self>> = Some(VMSTATE_PL011);
    const REALIZE: Option<fn(&Self) -> util::Result<()>> = Some(Self::realize);
}
impl ResettablePhasesImpl for PL011State {
    const HOLD: Option<fn(&Self, ResetType)> = Some(Self::reset_hold);
}
impl SysBusDeviceImpl for PL011State {}
```

**And the derived variant** — the exact shape of a Renode chip-specific
subclass, overriding one value and re-affirming the rest:

```rust
#[repr(C)]
#[derive(qom::Object, hwcore::Device)]
pub struct PL011Luminary {
    parent_obj: ParentField<PL011State>,
}
qom_isa!(PL011Luminary : PL011State, SysBusDevice, DeviceState, Object);
unsafe impl ObjectType for PL011Luminary {
    type Class = <PL011State as ObjectType>::Class;   // adds no virtual methods
    const TYPE_NAME: &'static CStr = crate::TYPE_PL011_LUMINARY;
}
impl PL011Impl for PL011Luminary {
    const DEVICE_ID: DeviceId = DeviceId(&[0x11, 0x00, 0x18, 0x01, 0x0d, 0xf0, 0x05, 0xb1]);
}
impl DeviceImpl for PL011Luminary {}
impl ResettablePhasesImpl for PL011Luminary {}
impl SysBusDeviceImpl for PL011Luminary {}
```

**What it gets wrong**, in QEMU's own words. The `IsA` relation is asserted, not
checked:

> "This macro is a thin wrapper around the [`IsA`] trait and performs **no
> checking whatsoever** of what is declared. It is the caller's responsibility
> to have $struct begin, directly or indirectly, with a field of type
> `$parent`."

The class-struct design duplicates code deliberately, and says why:

> "These `class_init` functions are methods on the class rather than a trait,
> because the bound on `T` … will change for every class struct … **This design
> incurs a small amount of code duplication but, by not using traits, it allows
> the flexibility of implementing bindings in any crate, without incurring into
> violations of orphan rules for traits.**"

That last sentence is a direct warning about the blanket-impl shortcut named in
this document's failure-mode section: QEMU hit the orphan/coherence wall and
paid duplication to avoid it.

**Bearing on this decision:** QEMU is a working existence proof at our exact
problem shape, and it does *not* flatten. It keeps the parent as a named first
field, emits an explicit vtable struct, and models overrides as slot values.
Field-flattening (splatting the base's members into the derived struct's own
field list) is a *lossier* variant of the same layout — it discards the ability
to say "these fields are the base's", which is what `ParentField` and `IsA`
exist to preserve, and which our gap-report duplication (§2) is the symptom of
having lost.

### 3.4 c2rust — C to Rust

C has no inheritance, so c2rust has nothing to translate here. It matters for a
different reason: it is the project CLAUDE.md names as the model, and it states
the faithful-first principle we are working under. From `immunant/c2rust`'s
README:

> "The transpiler, `c2rust transpile`, produces unsafe Rust code that closely
> mirrors the input C code. **The primary goal of the transpiler is to preserve
> functionality;** test suites should continue to pass after translation.
> The output of `c2rust transpile` is unsafe and unidiomatic; **it is merely the
> first step in a longer migration process.** Generating safe and idiomatic Rust
> code from C ultimately requires additional work."

Its pipeline is `transpile → refactor → postprocess → human`, and it ships a
`cross-checks` facility to compare translated against original — structurally
the same as this project's oracle.

**What it gets wrong**, from `docs/known-limitations.md`: it declines whole
categories rather than approximating them — `longjmp`/`setjmp` ("Likely won't
ever support"), jumps into and out of statement expressions, macros, `restrict`.
That is the *right* failure mode and matches this project's withhold-and-report
rule, but it means a c2rust output is not a finished port and never claims to be.

**Bearing on this decision:** it is the authority for "faithful first,
idiomatic later" — which argues for keeping the free-fn bodies exactly as they
are, and against a rewrite motivated by elegance. It does **not** license
omitting dispatch, because dispatch is not idiom, it is behaviour.

### 3.5 Three more, briefly

**J2ObjC** (Java → Objective-C, Google). Objective-C *has* single inheritance,
so classes map straight across; the interesting work is where Objective-C falls
short. A Java 8 **default method becomes a free function plus a generated shim
on every implementing class** — the generator's own header comment
(`translator/src/main/java/com/google/devtools/j2objc/translate/DefaultMethodShimGenerator.java`):

> "Generate shims for classes and enums that implement interfaces with default
> methods. Each shim calls the functionalized default method implementation
> defined in the interface."

Real output in the tree (`protobuf/runtime/src/com/google/protobuf/MapField.m`):

```objc
- (void)remove {
  // Default method impl.
  JavaUtilIterator_remove(self);
}
```

Two things there matter to us. First, this is the *same* answer as our
`{base}_{name}` split — hoist the body to a free function, then generate a
per-implementor forwarder. Second, `super` genuinely breaks in one case, and the
fix is a hand-built vtable slot
(`.../translate/SuperMethodInvocationRewriter.java`):

> "Some super method invocations cannot be translated directly as an ObjC super
> invocation. This occurs when the invocation is qualified by an outer type or
> when the containing method has been functionized. **To resolve these
> invocations we declare a static function pointer and look up the
> implementation during static initialization.**"

*Functionized* is exactly what our emitter does to every method. **What it gets
wrong:** overloads have no target equivalent and are mangled into the selector
(`[someList addWithInt:0 withId:object]`) — the docs concede "This is a bit
ugly"; and J2ObjC ships a **per-symbol rename table** as an official escape
hatch (`@ObjectiveCName(...)` plus a `--mapping` properties file). Worth naming
here, since CLAUDE.md treats a per-file rename table as evidence of failure:
a mature translator shipped one and it is a documented maintenance burden, not a
solution.

**Scala.js (WasmGC backend)**. Fields are **re-declared in every subclass,
qualified by declaring class**, because Wasm struct subtyping does not imply
field inheritance — from the backend's README, "As required in Wasm structs, all
fields are always repeated in substructs. Declaring a parent struct type does
not imply inheritance of the fields." Dispatch is a vtable struct whose
subtyping mirrors the class hierarchy, plus a **bridge forwarder per virtual
method** because the receiver has to be erased to `(ref any)` for the vtable
structs to remain subtypes. **What it gets wrong:** ~2× the code size of the JS
backend; and the thesis behind it records that lowering *static overloading*
into runtime dispatch naively "will cause an infinite recursion when called with
an instance of `CharSequence`" — a name-based collapse of overloads producing
silent non-termination, which is the same hazard as §4.5 here.

**TeaVM** (Java bytecode → JS/Wasm). One data point, from
`teavm.org/docs/intro/overview.html`:

> "**Devirtualization** turns virtual calls into static function calls, which
> makes code faster."

The same optimisation IL2CPP published two follow-up posts about. The pattern
across both: emit the dispatch mechanism, then let a whole-program pass remove
it where the call site is monomorphic. **Nobody omits the mechanism up front.**
**What it gets wrong:** TeaVM is explicit that it is not a general translator —
"It's not for taking your large existing codebase in Java or Kotlin and
producing JavaScript … TeaVM restricts usage of these APIs [reflection,
resources, class loaders, JNI]." Whole-program devirtualisation is what buys the
speed and what forbids reflection: a closed-world assumption paid for with a
language-feature restriction.

### 3.6 The Rust position, from the sources that settle it

**The language will not grow field inheritance in any relevant timeframe.**
RFC 1546, "Allow fields in traits that map to lvalues in impl'ing type"
(rust-lang/rfcs#1546), opened 2016-03-16, **closed unmerged 2018-02-14**
(`"merged": false`, confirmed via the GitHub API). Its motivation is the exact
claim the current rule makes:

> "Fields serve as a better alternative to accessor functions in traits. They
> are more compatible with Rust's safety checks than accessors, but also more
> efficient when using trait objects."

It was **postponed for bandwidth, not rejected on design** — nikomatsakis,
2018-01-26: "after some discussion in the @rust-lang/lang meeting, it seemed
clear that while we are still interested in a change like this, we don't have
the bandwidth to push this through right now, so we're going to postpone the
change." It moved to a dedicated repository (`nikomatsakis/fields-in-traits-rfc`)
that has had **no commit since 2017-05-25**. The broader tracking issue,
rust-lang/rfcs#349 "Efficient code reuse", has been open since 2014, and three
earlier attempts (#245, #250, #254) all closed unmerged.

**So the rule's stated premise is literally true and, for our purposes,
permanent: a trait cannot carry fields.** Flattening the fields is not a
workaround, it is the answer. That half of the decision is correct and should
not be revisited.

**But the language separates the two reasons for inheritance, and answers them
differently.** The Rust Book, ch. 18, "Characteristics of Object-Oriented
Languages" (`doc.rust-lang.org/book/ch18-01-what-is-oo.html`):

> "**There is no way to define a struct that inherits the parent struct's fields
> and method implementations without using a macro.**
> … You would choose inheritance for two main reasons. One is for reuse of code
> … You can do this in a limited way in Rust code using **default trait method
> implementations** …
> The other reason to use inheritance relates to the type system: to enable a
> child type to be used in the same places as the parent type. This is also
> called *polymorphism* …
> For these reasons, Rust takes the different approach of using **trait objects**
> instead of inheritance to achieve polymorphism at runtime."

Two reasons, two mechanisms. The current design implements the first and skips
the second.

**And the shortcut to avoid.** *Rust Design Patterns*, anti-patterns,
"Deref polymorphism" (`rust-unofficial.github.io/patterns/anti_patterns/deref.html`)
— `impl Deref for Bar { type Target = Foo; … }` to inherit the base's methods
through the dot operator:

> "Most importantly this is a surprising idiom … we are misusing the `Deref`
> trait rather than using it as intended … **This pattern does not introduce
> subtyping between `Foo` and `Bar`** like inheritance in Java or C++ does.
> Furthermore, traits implemented by `Foo` are not automatically implemented for
> `Bar`, so this pattern interacts badly with bounds checking and thus generic
> programming.
> Using this pattern gives subtly different semantics from most OO languages
> with regards to `self`. Usually it remains a reference to the sub-class, with
> this pattern it will be the 'class' where the method is defined.
> Finally, this pattern only supports single inheritance, and has no notion of
> interfaces …"

Its recommended alternative is exactly the recommendation of this document:

> "There is no one good alternative. Depending on the exact circumstances it
> might be better to **re-implement using traits or to write out the facade
> methods to dispatch to `Foo` manually**."

### 3.7 Summary of the survey

| system | base FIELDS | base/own METHODS | virtual + interface DISPATCH | documented cost |
|---|---|---|---|---|
| IL2CPP | C++ inheritance, base subobject at offset 0 | **free functions, instance as first arg** | generated vtable + `VirtFuncInvoker`/`InterfaceFuncInvoker` | code bloat (4,625 headers for hello-world), injected null/bounds checks, no incremental builds |
| Servo | superclass by value in the first field | inherent `impl` methods | generated `Castable` trait **and** generated `TypeId` enum | `unsafe` transmutes; soundness held up by a bespoke compiler lint |
| **QEMU (Rust)** | **parent as first field, `ParentField<T>` + `unsafe trait IsA`** | trait methods on `*Impl` traits | **explicit `#[repr(C)]` class struct; overrides are associated `const fn` pointers; chain-up is an explicit call** | `qom_isa!` "performs no checking whatsoever"; deliberate duplication to dodge orphan rules |
| c2rust | `#[repr(C)]`, parent first — relation recorded **nowhere** | free functions | `Option<extern "C" fn>` in a class struct, `.expect()` at each call | unsafe/unidiomatic by design; independently measured at 72.6% of outputs executing successfully |
| J2ObjC | ObjC ivars | default methods → free fn + per-class shim | `@protocol` | overloads mangled into selectors; ships a per-symbol rename table |
| Scala.js (WasmGC) | re-declared per subclass, qualified by declaring class | — | vtable structs + bridge forwarders; bucketed itables | ~2× code size; naive overload lowering causes infinite recursion |
| TeaVM | JS object properties | JS methods | virtual, then whole-program devirtualisation | closed-world; forbids reflection/JNI |
| **this project, today** | **flattened into `State`, relation recorded nowhere** | **free fns over `(bank, st)`** | **none** | **the subject of this document** |

Two things fall out of the table.

**No surveyed system relies on flattening alone.** Every one pairs a physical
field layout with a *separate*, explicit dispatch mechanism, and the two are
never conflated. The one row that comes closest to the current design is
**c2rust** — parent first, relation recorded nowhere, dispatch left as raw
function pointers — and c2rust is explicitly a first step whose output "is
unsafe and unidiomatic", independently measured at a 72.6% success rate.

**Our free-function calling convention is IL2CPP's, and that is good company.**
The row that differs is the dispatch column, where we are alone in having none.

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

§2: real depth reaches 5 (`CortexM`), and 4 of the 18 in-cut peripherals have an
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

The enum is also genuinely faster, and the margin is not small. The
`enum_dispatch` crate publishes a benchmark over 1,024 mixed-type objects in a
`Vec`:

```
test benches::boxdyn_homogeneous_vec       ... bench: 5,900,191 ns/iter
test benches::refdyn_homogeneous_vec       ... bench: 5,658,461 ns/iter
test benches::enumdispatch_homogeneous_vec ... bench:   479,630 ns/iter
```

> "Since a `Vec` of enum_dispatch objects is actually a `Vec` of enums rather
> than addresses, accessing an element takes half the indirection of the other
> techniques."

Roughly 12×. Note the scale before this decides anything: PLAN.md measures the
MMIO budget at ~409 ns per access, and a `dyn` call is single-digit nanoseconds.
This is the same shape of argument D2 already resolved — "**Decide this on
correctness, not speed.** The measured advantage is real … but irrelevant in
context." The same reasoning applies here, and it points the other way from the
benchmark.

It is disqualified for two reasons:

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
7. **Secondary, and separable — record which fields came from which base.**
   Splatting the base's members into `State` loses the fact that they *are* the
   base's, and §2 measures the cost: `machine`, `sysbus` and `mapper` are one
   base-class problem reported eight times, and a third of all gap lines are
   duplicates of this kind. QEMU keeps the parent as `ParentField<T>` and Servo
   as a by-value first field precisely to retain that information. The cheapest
   version here does not change the struct at all — attribute each gap to its
   *declaring* type and deduplicate the census, so one base defect counts once.
   That is a `gap_census.py` change, not an emitter change, and it should be a
   separate issue.

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

**Second failure mode:** a blanket `impl<T: BaseTrait> DispatchTrait for T` is
the tempting way to write step 3 with less code, and it **breaks on the second
base class** with coherence error E0119, because two base traits both
blanket-impl the same dispatch trait. Emit concrete per-type impls, and record
that as a negative in the rule (`rule_negative`) so the shortcut is not
rediscovered. QEMU hit this exact wall and documented paying duplication to
avoid it: "by not using traits, it allows the flexibility of implementing
bindings in any crate, without incurring into violations of orphan rules for
traits."

**Third failure mode, and the one that bounds how far this can go:** not every
C# virtual method is expressible as a `dyn` method. The Rust Reference's
dyn-compatibility rules require a dispatchable method to have no type
parameters and to not use `Self` except as the receiver. So:

- a C# **generic virtual method** (`virtual T Foo<T>(…)`) has no `dyn` encoding
  and must be withheld as a gap, not approximated;
- a **covariant return override** likewise;
- upcasting a `dyn Derived` to a `dyn Base` only became possible in **Rust 1.86
  (2025-04-03)**; before that it needed an explicit `fn as_base(&self) -> &dyn
  Base` in the trait. This is now available, but it pins a minimum toolchain
  version that should be recorded rather than discovered.

None of these appear in the F427 cut: **no `virtual` or `override` in the cut
declares its own type parameters.** 17 of the 72 have `<` in their signature,
but in every case that is the *containing* type being generic
(`PeripheralRegister<T>.CallChangeHandlers(ulong, ulong)`), which is a different
thing — a `dyn` over a generic base just needs the type argument fixed, and the
register DSL fixes it four ways already (`ByteRegister`, `WordRegister`,
`DoubleWordRegister`, `QuadWordRegister`). So this bounds the *general* claim,
not this corpus. It should be recorded as a rule deviation so a future corpus
trips a gap rather than silently getting something else.

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

Every quotation above was fetched and read; where the original URL is dead the
archived snapshot actually used is given. Claims that could not be verified
first-hand were dropped rather than repeated.

**Translators and generated code**

- IL2CPP — "IL2CPP Internals: A Tour of Generated Code", Josh Peterson,
  2015-05-13. Original `blogs.unity3d.com` URL is dead (the `unity.com`
  successor returns 404/403); read via
  `web.archive.org/web/20210515152602/https://blogs.unity3d.com/2015/05/13/il2cpp-internals-a-tour-of-generated-code/`
- IL2CPP — "IL2CPP Internals: Method Calls", 2015-06-03, via
  `web.archive.org/web/20210422110620/https://blogs.unity3d.com/2015/06/03/il2cpp-internals-method-calls/`
- Servo — `github.com/servo/servo`, `components/script/dom/mod.rs` (module
  documentation, "Inheritance") and
  `components/script_bindings/inheritance.rs` (`Castable`, `HasParent`);
  issue servo/servo#5927 "Ensure DOM types have their base type as the first
  field"
- QEMU — `github.com/qemu/qemu`, `rust/qom/src/qom.rs` (`IsA`, `qom_isa!`,
  `ParentField`, "Structure of a class") and
  `rust/hw/char/pl011/src/device.rs` (`PL011State`, `PL011Class`,
  `PL011Luminary`); `docs/devel/rust.rst`
- c2rust — `github.com/immunant/c2rust`, `README.md` and
  `docs/known-limitations.md`
- Corrode — `github.com/jameysharp/corrode` (last commit 2017-04-12)
- J2ObjC — `github.com/google/j2objc`,
  `translator/src/main/java/com/google/devtools/j2objc/translate/DefaultMethodShimGenerator.java`
  and `.../SuperMethodInvocationRewriter.java`;
  `protobuf/runtime/src/com/google/protobuf/MapField.m`. Note that the
  `developers.google.com/j2objc` guides are now 404 and are not archived.
- Scala.js — `github.com/scala-js/scala-js`,
  `linker/shared/src/main/scala/org/scalajs/linker/backend/wasmemitter/README.md`;
  Sébastien Doeraene's thesis, `chara.epfl.ch/~doeraene/thesis/`
- TeaVM — `teavm.org/docs/intro/overview.html`
- Cheerp — `cheerp.io/docs/reference/sections/genericjs/memory-model`

**Rust language**

- The Rust Programming Language, ch. 18 —
  `doc.rust-lang.org/book/ch18-01-what-is-oo.html` and
  `.../ch18-02-trait-objects.html`
- RFC 1546, "Allow fields in traits that map to lvalues in impl'ing type" —
  `github.com/rust-lang/rfcs/pull/1546` (state confirmed via the GitHub API:
  closed 2018-02-14, `merged: false`); follow-up repository
  `github.com/nikomatsakis/fields-in-traits-rfc` (no commit since 2017-05-25);
  tracking issue `github.com/rust-lang/rfcs/issues/349`
- Rust Design Patterns, anti-patterns, "Deref polymorphism" —
  `rust-unofficial.github.io/patterns/anti_patterns/deref.html`
- The Rust Reference, "Traits" (dyn compatibility) —
  `doc.rust-lang.org/reference/items/traits.html`; type layout —
  `doc.rust-lang.org/reference/type-layout.html`
- Trait upcasting stabilised in Rust 1.86 —
  `blog.rust-lang.org/2025/04/03/Rust-1.86.0/`
- `enum_dispatch` benchmarks — `docs.rs/enum_dispatch/`

**Measurements taken for this document**

- Corpus queries against `rulesdb/patterns.db` (`corpus_run.config = 'f427'`,
  Renode `dc52b24c118a`) and the emitter run over all register-defining types.
- Four Rust programs compiled and run to check the claims made here: the
  trait-default `super` recursion (`unconditional_recursion` fires; the program
  loops), the object-safety error for a `Bank<Self>` accessor (E0038, with
  rustc's own "consider moving `bank` to another trait"), and the additive
  dispatch trait over `Rc<RefCell<dyn _>>` with two peripherals whose `State`
  types differ (compiles and dispatches).
