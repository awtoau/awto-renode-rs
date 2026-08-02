# `Gc<T>` versus `Rc<RefCell<T>>` at the use site

Issue #57, phase 1. This is the document the decision rests on.

> **So the phase-1 API matters more than the collector.** If using `Gc<T>` is
> harder than using `Rc<RefCell<T>>`, the porting argument evaporates.

So the API was designed backwards from the use sites, and the use sites are
written out here before any conclusion is drawn. Every C# fragment below is
real, from the cut, quoted rather than paraphrased. Both Rust columns are what
the translator would have to emit for that fragment — not idiomatic Rust anyone
would write by hand.

## The shape being compared

One file carries every case at once, so it is the worked example throughout:
`src/Infrastructure/src/Emulator/Peripherals/Peripherals/DMA/STM32DMA.cs`.
A parent holding an array of children, each child holding a back-reference, and
a call chain that re-enters the parent while the parent is still on the stack.

```csharp
public sealed class STM32DMA : BasicDoubleWordPeripheral, IKnownSize, IGPIOReceiver
{
    public STM32DMA(IMachine machine) : base(machine)
    {
        streams = Enumerable.Range(0, NrOfStreams)
                            .Select(id => new Stream(this, id))
                            .ToArray();
        engine = new DmaEngine(machine.GetSystemBus(this));
        ...
    }

    public void OnGPIO(int number, bool value)
    {
        if(number < 0 || number >= streams.Length) { ...; return; }
        streams[number].OnGPIO(value);
    }

    private void UpdateInterrupts()
    {
        for(var streamId = 0; streamId < NrOfStreams; streamId++)
        {
            var stream = streams[streamId];
            var irqValue = stream.TransferCompleteIrqEnable
                        && transferCompleteIrqStatus[streamId].Value;
            stream.IRQ.Set(irqValue);
        }
    }

    private readonly Stream[] streams;

    private class Stream
    {
        public Stream(STM32DMA parent, int id) { this.parent = parent; this.id = id; ... }

        private void PerformTransfer()
        {
            if(CreateRequest() is Request request)
            {
                nrOfData.Value -= (ulong)nrOfDataUnits;
                dataOffset += (ulong)request.Size;
                parent.engine.IssueCopy(request);
                if(nrOfData.Value == 0)
                {
                    parent.transferCompleteIrqStatus[id].Value = true;
                    dataOffset = 0;
                    parent.UpdateInterrupts();
                }
            }
        }

        private readonly STM32DMA parent;
    }
}
```

This is not an unusual file. The same parent/child/back-reference shape appears
in `STM32F4_RTC` (`AlarmConfig.parent`, `TimerConfig.parent`), `STM32_Timer`
(`CaptureCompareChannel.parent`), `STM32_GPIOPort`
(`GPIOAlternateFunction.port`), `STM32_SYSCFG` (`InternalReceiver.parent`),
`NVIC` (`SysTick.parent`, and `NVIC.cpu` ↔ `CortexM.nvic`), `MappedMemory`
(`MappedSegment.parent`) and `STMCAN` (`master`, a self-edge). Those are seven
of the seven 2-cycles the prescan found in the cut.

---

## 1. A parent holding children

```csharp
private readonly Stream[] streams;
streams = Enumerable.Range(0, NrOfStreams).Select(id => new Stream(this, id)).ToArray();
```

**`Rc<RefCell<T>>`**

```rust
struct Stm32Dma {
    streams: Vec<Rc<RefCell<Stream>>>,
}

fn new(machine: Rc<RefCell<Machine>>) -> Rc<RefCell<Self>> {
    // `this` must exist before the children can point at it, so the field
    // cannot be initialised in the struct literal.
    let this = Rc::new(RefCell::new(Stm32Dma { streams: Vec::new(), .. }));
    let streams = (0..NR_OF_STREAMS)
        .map(|id| Rc::new(RefCell::new(Stream::new(Rc::downgrade(&this), id))))
        .collect();
    this.borrow_mut().streams = streams;      // two-phase construction
    this
}
```

**`Gc<T>`**

```rust
struct Stm32Dma {
    streams: Vec<Gc<Stream>>,
}

fn new(h: &mut Heap, machine: Gc<Machine>) -> Gc<Stm32Dma> {
    let this = h.alloc(Stm32Dma { streams: Vec::new(), .. });
    for id in 0..NR_OF_STREAMS {
        let s = h.alloc(Stream::new(this, id));
        h[this].streams.push(s);
    }
    this
}
```

Both need two phases, because the C# does too — `new Stream(this, id)` reads
`this` before the field assignment completes. The difference is that the `Rc`
version had to decide, here, that the *parent → child* direction is the strong
one and the child's back-edge is `Weak`. Nothing in the source says that.

## 2. A child holding a back-reference

```csharp
private readonly STM32DMA parent;
```

| | |
|---|---|
| `Rc<RefCell<T>>` | `parent: Weak<RefCell<Stm32Dma>>` — **a decision**, made per field, from whole-graph knowledge the translator does not have |
| `Gc<T>` | `parent: Gc<Stm32Dma>` — the same mapping as every other reference field |

This row is the argument. There are 52 object-reference edges in the cut and
1,278 across the tree; `Rc` needs a direction for each one. Get it wrong in the
`Rc` direction and it leaks; get it wrong in the `Weak` direction and the
object is dropped while still referenced, and `.upgrade()` starts returning
`None` on a path that used to work. **Neither failure is visible to the
differential oracle** — a leak changes nothing observable, and a `None` shows up
as a panic in a completely different file.

## 3. A field read

```csharp
parent.transferCompleteIrqStatus[id]      // one hop
parent.ticker.Value                       // two hops, from STM32F4_RTC.AlarmConfig
```

**`Rc<RefCell<T>>`**

```rust
let parent = self.parent.upgrade().expect("parent dropped");
let f = parent.borrow().transfer_complete_irq_status[self.id];

// two hops: the intermediate borrow must outlive the expression
let p = parent.borrow();
let v = p.ticker.borrow().value();
```

**`Gc<T>`**

```rust
let f = h[h[this].parent].transfer_complete_irq_status[h[this].id];
let v = h[h[h[this].parent].ticker].value();
```

Neither is pretty. The `Rc` version is longer and has two failure modes the
`Gc` version does not: `upgrade()` returns `Option`, and holding `p` across the
next call is how you get a panic. The `Gc` version's ugliness is uniform and
mechanical — `h[..]` around every hop, no temporaries, no lifetimes to place.

## 4. A field write

```csharp
dataOffset = 0;
parent.transferCompleteIrqStatus[id].Value = true;
```

**`Rc<RefCell<T>>`**

```rust
self.data_offset = 0;                                   // needs &mut self
parent.borrow_mut().transfer_complete_irq_status[self.id].set(true, ...);
```

**`Gc<T>`**

```rust
h[this].data_offset.set(0);                             // Cell field, &Heap
h[h[this].parent].transfer_complete_irq_status[h[this].id].set(true, ...);
```

The `Gc` version puts scalar fields in `Cell`, so a write needs only a shared
borrow of the arena. That is not a new idea in this project: it is exactly
**decision D2**, which chose `Cell` over `RefCell` for register fields because
`Cell` has no borrow flag and therefore cannot panic on re-entrant access. This
applies the same reasoning one level up, to the object graph. The cost is
`.set(v)` instead of `= v`, which the emitter writes and nobody reads.

## 5. A method call through the reference — where they separate

```csharp
// STM32DMA.OnGPIO
streams[number].OnGPIO(value);
// ... which reaches Stream.PerformTransfer, which does:
parent.UpdateInterrupts();
// ... which reads back into every child:
var stream = streams[streamId];
var irqValue = stream.TransferCompleteIrqEnable && ...;
```

So the live call chain is **parent → child → parent → every child**.

**`Rc<RefCell<T>>`**

```rust
dma.borrow_mut().on_gpio(3, true);
//  ^-- (1) parent borrowed mutably

fn on_gpio(&mut self, number: i32, value: bool) {
    let s = self.streams[number as usize].clone();
    s.borrow_mut().on_gpio(value);
    //  ^-- (2) child borrowed mutably
}

fn perform_transfer(&mut self) {
    let parent = self.parent.upgrade().unwrap();
    parent.borrow_mut().update_interrupts();
    //     ^-- (3) PANIC: "already mutably borrowed" -- (1) is still live
}

fn update_interrupts(&mut self) {
    for id in 0..NR_OF_STREAMS {
        let stream = self.streams[id].borrow();
        //           ^-- (4) PANIC again for id == 3 -- (2) is still live
    }
}
```

Two panics, on a path the `dma1` and `dma2` traces exercise. Both are run-time,
both are `RefCell`'s, and neither is visible to any type check. PLAN.md already
names this: *"`RefCell` panics on re-entrant borrow ... this is the highest-risk
item in the plan"*, with the mitigation left as a borrow discipline to be
decided later. The discipline that actually works is "never hold a borrow across
a call", and following it means every field is individually `Cell`/`RefCell` and
methods take `&self` — at which point the outer `RefCell` is doing nothing but
adding a panic, and you have arrived at the `Gc` design by a longer route.

**`Gc<T>`**

```rust
fn on_gpio(h: &Heap, this: Gc<Stm32Dma>, number: i32, value: bool) {
    stream::on_gpio(h, h[this].streams[number as usize], value);
}

fn perform_transfer(h: &Heap, this: Gc<Stream>) {
    h[this].data_offset.set(0);
    update_interrupts(h, h[this].parent);          // re-entrant, and fine
}

fn update_interrupts(h: &Heap, this: Gc<Stm32Dma>) {
    for id in 0..NR_OF_STREAMS {
        let s = h[this].streams[id];               // Copy, no borrow held
        let irq = h[s].transfer_complete_irq_enable.get() && ...;
    }
}
```

`&Heap` is a *shared* borrow, and shared borrows nest without limit. There is
nothing to panic. This is tested rather than asserted:
`gc::tests::parent_child_parent_reentrancy_does_not_panic` builds exactly this
graph and drives exactly this chain.

## 6. Construction order and cycles

```csharp
nvic.AttachCPU(cortexM);   // NVIC.cpu  <-> CortexM.nvic
```

| | |
|---|---|
| `Rc<RefCell<T>>` | one side must be `Weak`. Whichever is chosen, the other side's `.upgrade()` can fail, and the choice is invisible in the source |
| `Gc<T>` | `h[nvic].cpu.set(cortex_m); h[cortex_m].nvic.set(nvic);` — symmetric, because it is symmetric in C# |

## 7. Where `Gc<T>` is genuinely worse

Stated plainly, because a comparison that finds no cost is not a comparison.

1. **Every method grows a parameter.** `fn f(&mut self, ..)` becomes
   `fn f(h: &Heap, this: Gc<Self>, ..)`. In isolation that is a real ergonomic
   loss. In context it is close to free: the emitter *already* threads a field
   bank and a state struct through every translated method — every generated
   function in `src/renode-stm32/src/*_registers.rs` is
   `fn name(bank: &Bank<State>, st: &mut State, ..)`. One more parameter joins
   two that are already there, and threading it is mechanical.
2. **`h[..]` at every hop.** Noisier to read than `.`, and a two-hop read nests.
   No re-fetch is *required* (the handle is `Copy` and stays valid), so it is
   verbosity, not work.
3. **A `Trace` impl per type.** `Rc` needs none. It is derivable from the field
   list with no judgement — one `t.edge(f)` per handle field — so it must be
   generated; a hand-written one that misses an edge collects a live object.
4. **Allocation needs `&mut Heap`.** A method that allocates cannot be called
   while a `&Heap` is outstanding. That is a **compile error**, not a run-time
   surprise, and in this corpus allocation is overwhelmingly constructor-time.
   But it is a genuine constraint and a method that both allocates and is
   re-entered would need hoisting.
5. **Speed.** `safe-gc`'s author says plainly that a safe arena collector "is
   not a particularly high-performance garbage collector", and this one is no
   different: an access is a `BTreeMap` lookup by `TypeId`, a downcast, a bounds
   check and a generation compare. Against the measured ~409 ns per bus access
   budget that is noise, but it is noise *for this corpus*, and it is slower
   than `Rc`'s pointer chase in isolation.
6. **A stale handle panics.** If an object is collected while a handle to it
   lives in a local, the next use panics on the generation check. `Rc` cannot
   have this problem. It is mitigated by collection being explicit — nothing
   collects behind your back — and the failure is loud rather than a silent read
   of a recycled slot.

## Verdict

**`Gc<T>` is not worse at the use site, and is better in the one place that
matters.**

| | `Rc<RefCell<T>>` | `Gc<T>` |
|---|---|---|
| ownership decision per reference field | **yes — 52 in the cut, 1,278 tree-wide** | none |
| back-reference | `Weak<RefCell<T>>` | `Gc<T>`, unchanged |
| read | `.upgrade().unwrap().borrow().f` | `h[g].f` |
| write | `.borrow_mut().f = v` | `h[g].f.set(v)` |
| call re-entering an object on the stack | **runtime panic** | compiles, cannot panic |
| cycles | leaked | collectable |
| getting the direction wrong | leak, or dangle — oracle-invisible | not representable |
| extra parameter per method | no | yes (joins two already there) |
| `Trace` impl per type | no | yes, generated |
| raw speed | faster | slower, ~0.08%-scale against the real budget |

The rows that decide it are the first and the fifth. The first is the porting
argument: `Rc` requires 1,278 judgements the source does not contain, made by a
translator that cannot see the whole graph, with failures the oracle cannot
catch. The fifth is a correctness argument that stands on its own: the
re-entrant call is real, it is on a traced path, and under `Rc<RefCell<T>>` it
panics.

**This is not a recommendation to adopt it.** D1 remains as written and PLAN.md
is unchanged; what phase 1 lands is the option, the evidence, and the rule that
would carry it. The measurement that should settle it is phase 2's tracer, which
needs running peripherals that do not exist yet.

## What phase 2 needs from this API

The tracer's job is to turn `docs/status/ownership-tree.tsv`'s `static` evidence
column into a measured one — which objects were *actually* shared, *actually*
cyclic, *actually* long-lived — so a field the tracer never saw shared can be
demoted to a plain owned value. What that needs, and what already exists:

| needed | status |
|---|---|
| reachability from roots | `Heap::collect` already walks it; the mark phase is the answer |
| per-object liveness counts | `Heap::live`, `Heap::live_of::<T>()`, `Collected { freed, live }` |
| a stable per-object identity to key evidence on | `Gc<T>` is `Copy + Eq + Hash`; `GcRaw` is `Ord` and type-tagged |
| **share count per object** — how many distinct fields point at it | **not built.** The mark phase discards it: it visits an already-marked slot and stops. Recording an in-degree means counting the second visit instead of ignoring it |
| **which field** an edge came from | **not built.** `Tracer::edge` takes only the handle. A field name or index would have to be added to the call, which means the generated `Trace` impl carries it |
| **cycle membership per object** | derivable from the same walk, not currently recorded |
| coverage — which paths were exercised | belongs to the harness, not here; the caveat on the issue applies (a field never shared *in the traces we ran* is not a field that is never shared) |

The two "not built" rows are the real API question for phase 2, and they point
the same way: `Tracer::edge` needs to carry the edge's *source field*, and the
mark phase needs to count revisits rather than discard them. Both are additive
and neither changes the emitted mapping — which is why phase 1 does not guess at
them now.
