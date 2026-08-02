# Define a build target: the floor that runs

**Taken 2026-08-03.** The build target is **a CPU-free machine assembled from
the translated peripherals that already compile and are already drivable,
addressed from the `.repl`, behind a hand-written bus, driven over Renode's own
Robot XML-RPC keyword server.** The first acceptance test is a named Renode
test, not one of ours:

> `tests/unit-tests/stm32f4-erase.robot`, test case **`Should Perform Mass
> Erase`** — in the Renode tree, unmodified.

## Why this is a decision at all

[remove-the-cut.md](remove-the-cut.md) answered **ingest scope**: read
everything. That was right and it stands. It did not answer **build scope**,
and the two are different questions. With no answer to the second, the
converter's output has an audience of exactly one — `cargo check` — and the
scoreboard reads *N modules compile*, which is not a system.

`compile_baseline.json` is the state that made this urgent, and it is a
truthful one: a module count and an error count, with **nothing ever executed**
except register-trace replay on the peripherals that have recorded traces
(`python3 scripts/oracle_coverage.py`).

Every number below comes from a file under `docs/status/`, produced by a
committed script. None is retyped.

| file | produced by |
|---|---|
| `docs/status/floor.json` | `python3 scripts/floor_census.py` |
| `docs/status/compile_baseline.json` | `python3 scripts/compile_check.py --ratchet` |
| `docs/status/dispatch.json` | `python3 scripts/dispatch_spike.py` |
| `docs/status/platform.json` | `python3 scripts/parse_repl.py` |

---

## 1. The floor

`scripts/floor_census.py` asks the question `compile_check.py` does not: a
module that compiles is not a peripheral. A peripheral is something a bus can
hand an address to. So it intersects three properties —

1. **compiles** (reuses `compile_check`'s scratch crate, so there is one
   emitter run and one answer, not two);
2. **drivable** — exposes the `read_double_word` / `write_double_word` pair a
   generic caller dispatches through;
3. **addressed** — `docs/status/platform.json`, derived from the `.repl`, puts
   it somewhere.

`floor.json` reports `modules_emitted`, `modules_clean`, `modules_drivable`,
`modules_clean_and_drivable`, and then the intersection with the platform as
`platform_floor`, with every member named under `floor`.

**Drivable is the property that was never counted, and it is not implied by
clean.** `modules_drivable` exceeds `modules_clean`, and their intersection is
well under either — a module can compile and be unreachable, or be reachable
and not compile. Neither number alone describes anything that could run.

### What each member of the floor is for

The floor is not a curated list. It is whatever survives the three filters, and
today it is three shapes:

| shape | why it is in | what it is for |
|---|---|---|
| the UART family | `read_double_word`/`write_double_word` emitted, `reset` emitted under its own name | the only floor members whose `reset` contract is complete, and the peripheral with the largest recorded trace behind it |
| the `BasicDoubleWordPeripheral` subclasses | the base supplies the read/write pair | breadth: they prove the bus is generic over more than one type, which one peripheral cannot |
| the GPIO ports and `syscfg` | drivable, but `reset` is **absent** | they are in the floor and they name its first hole — see below |

### The piece that already exists, and was believed not to

[target-one-peripheral-end-to-end.md](target-one-peripheral-end-to-end.md)
recorded that *"nothing assembles a module into a peripheral that can be
instantiated and driven"*. That is no longer true, and the thing that changed
it is **generated**, not hand-written: `src/renode-stm32/src/dispatch.rs` emits
a trait, a struct per implementor holding `(Bank<State>, State)`, a `new()`
that calls `define_registers`, and the `impl`. That is a `dyn`-able MMIO
peripheral produced by the converter.

So the floor does not need a new mechanism. It needs the mechanism pointed at
an address.

### The first hole, and it is already measured

`dispatch.json` records that `reset` arrives under more than one name and is
missing from some modules; `floor.json` re-measures it across the floor
specifically, as `reset_names_across_floor`, and the count is **greater than
one**. A generic caller needs one name per contract. Until that is one name,
`Reset Emulation` — which the Robot harness calls before **every** test case,
unconditionally — cannot be implemented against the floor without a per-module
table, and a per-module table is a patch wearing a dispatch table's name.

This is a converter work item, not a floor work item. It is the reason `reset`
is stated here rather than shimmed.

### What the floor does *not* contain, and why that is two different facts

`floor.json` lists every platform peripheral with no emitted module under
`platform_not_emitted`, each with a `why_not_emitted`. There are three reasons
and they are not interchangeable:

- **`no register-defining member at all`** — the memories, the bit-band
  windows. Structurally outside a converter that emits register maps. These are
  infrastructure and are dealt with in §3.
- **`not a type in the corpus`** — a `.repl` entry that names another
  peripheral rather than a class. A parser artefact, not a gap.
- **`HAS registers but defines them OUTSIDE a matching method`** — and this one
  is a finding. `compile_check.emit_all` selects types by a **name heuristic**:
  a member matching `%Register%` or `%DefineReg%` that has a body. A peripheral
  that defines its registers inline in its constructor never reaches the
  emitter at all. `platform_not_emitted` carries this reason for several of the
  platform's peripherals, **including the one PLAN.md names as the densest
  declarative peripheral in the whole corpus**.

  **"Not emitted" and "cannot be emitted" have been reported as the same
  state.** They are not, and the module and error totals in
  `compile_baseline.json` are therefore over a work list, not over the corpus.
  Recorded here; the fix belongs in the work-list query, not in this decision.

---

## 2. The first Robot test

### What the interface actually is

It is not a CLI. `tests/renode-keywords.robot` imports
`Remote  http://127.0.0.1:<port>/`, so the surface is the **Robot Framework
Remote Library protocol**: XML-RPC over HTTP, three methods —
`get_keyword_names`, `run_keyword(name, args)`, `stop_remote_server` — served
by `src/Renode/RobotFrameworkEngine/XmlRpcServer.cs`. `run_keyword` returns a
struct with `status` = `PASS`/`FAIL`, an optional `return`, and `error` +
`traceback` on failure.

One non-obvious hard requirement: the harness discovers the port by polling for
a **`robot_port` file** under a per-pid temporary directory
(`tests/robot_tests_provider.py`). A server that binds the port and does not
write that file is never connected to, and the failure is a 180-second timeout
with no diagnostic.

The harness also invokes keywords no test body mentions, on every suite:
`Set Default Uart Timeout`, `Enable Logging To Cache`, `Reset Emulation`
(suite setup, every test setup, every test teardown), `Clear Cached Log`, and
`Save Cached Log` on failure. Teardown is by SIGINT, not by
`stop_remote_server`, under the standard runner.

### Why `Should Perform Mass Erase`

The cheapest test in the tree is **not** the right first test, and the
distinction is the whole point of choosing one.

`tests/unit-tests/sysbus-tag.robot` is the cheapest: one keyword
(`Execute Command`), no CPU, no download, no `.repl` file, one peripheral. It
is also **worthless as an oracle for this project**, because everything it
asserts on — `sysbus Tag` semantics and `Memory.ArrayMemory` — is
infrastructure we would hand-write. Passing it would be evidence about the
shim.

> A Robot test earns its place here only if its verdict is decided by converter
> output. Otherwise it measures the scaffolding.

By that criterion `tests/unit-tests/stm32f4-erase.robot` is the cheapest
qualifying test in the tree:

- its verdict is decided by `STM32F4_FlashController`, which the converter
  emits;
- it never starts the CPU, so tlib, the time framework, the NVIC and `CortexM`
  are all out of the first milestone;
- it downloads no ELF and creates no terminal tester.

And **`Should Perform Mass Erase` specifically**, not the whole file: it is the
one case of the three that needs no `Create Log Tester` / `Wait For Log Entry`,
which drops the entire logging subsystem and its log-tester backend from the
first milestone. The other two cases are the second and third milestones, in
that order.

### Exactly what it needs

`floor_census.py` reads this out of the test file rather than taking anyone's
word for it — `floor.json` → `robot_surface`. It reports
`keywords_server_side` against `keywords_served_by_renode_total` (itself
derived, by scanning `[RobotFrameworkKeyword]` in
`src/Renode/RobotFrameworkEngine/`), the keywords the test defines for itself,
and `monitor_command_heads`.

The shape of the answer is the point: **`robot_keywords_required` is a
single-digit fraction of `robot_keywords_renode_serves`, and
`monitor_commands_required` is single-digit too.** `Should Perform Mass Erase`
alone needs fewer still — the log-tester pair belongs to the file's first case,
not to this one.

Read results are string-compared by the test, so the formatting is part of the
contract.

Behaviour: the flash controller's KEYR unlock sequence, `CR.MER`, and the mass
erase writing the erase pattern through a **reference to another peripheral**
(`flash: flash` in the `.repl`) — which is an object-graph edge (D1), not a
register write.

### What blocks it today, named by the converter itself

Running the emitter on `STM32F4_FlashController` produces the layout and
withholds every method the test depends on — `PerformMassErase`,
`PerformSectorErase`, `Erase`, `WriteDoubleWord`, `Reset` — each with its
reason in the module header. The reasons reduce to four:

1. state fields the emitted struct does not have (`sectors`, `erasePattern`);
2. `flash` maps to a handle on `MappedMemory`, which **has no emitted Rust
   type**, so there is nothing to point at;
3. the same for `LockRegister`;
4. `IMachine` / `IBusController` as traits (#41).

None of those is "the converter got it wrong". Each is a gap it reported
rather than guessing, which is the intended behaviour. They are the work items,
and they are shared with every other peripheral that references a memory.

### The one thing in the test's platform that is not behaviour

`platforms/cpus/stm32f4.repl` ends with a `sysbus: init:` block containing an
`ApplySVD` of a gzipped SVD **fetched over the network**, and three `Tag`
directives. `ApplySVD` supplies register names for log messages and nothing
else; `Tag` does change reads.

The rule taken here, because "ignore it" is exactly how an oracle stops being
one: **the loader refuses an unimplemented `init:` directive and names it**,
and a refused directive whose address range intersects any address the test
touches is a hard failure, not a warning. For this test neither tagged range is
touched, so the refusal is recordable as a deviation rather than a blocker —
and that is a checkable claim, not a judgement call.

---

## 3. Between "modules compile" and "one Robot test passes"

`floor_census.py` now probes the infrastructure the floor needs and the
converter has never been asked for, because "the converter cannot do the bus"
was an assumption and is now a measurement under `floor.json` →
`infrastructure`. Each entry carries the C# file, its length, its member count,
and what the emitter actually produced.

The result is unambiguous and it is the finding that shapes everything below:
**for the bus, the memories and the machine, the converter emits an empty
`define_registers` and, at most, a handful of trivial getters.** Not a low
fraction of their members — effectively none. They are not partially
translated; they are untranslated, and the emitter says so at length in the gap
headers.

| component | verdict | why |
|---|---|---|
| **CPU** | **already exists, as FFI** | `src/renode-tlib/` binds tlib by `dlopen`. Its header records why it is deliberately not translated: instruction dispatch is not the bottleneck, and a byte-identical CPU on both sides is what makes the lockstep oracle exact. Bring-up is incomplete — the bus read/write callbacks that carry MMIO are among those unattached — but **the first test never starts the CPU**, so this is out of the first milestone entirely. |
| **time framework** | **not needed** | nothing advances virtual time when `Start Emulation` is never called. The C# constructs a time source regardless; the floor does not have to, because it is not restoring serialised state. |
| **NVIC, `CortexM`** | **not needed** | same reason. They are constructed by the `.repl` in C#; the floor instantiates only what a translated module exists for and reports the rest as gaps — the withholding discipline applied to instantiation. |
| **system bus** | **translate the semantics, hand-write the container** | see the boundary below. Address decode, and what happens on an unmapped access, are behaviour the oracle must certify. |
| **memory** | **hand-written infrastructure** | the C# is dominated by host page mapping for the CPU translator and by serialisation. With no CPU, the semantics are a byte vector. |
| **machine** | **hand-written infrastructure** | a name→peripheral map and an address map. Renode's is dominated by registration, hooks and serialisation, none of which the floor has. |
| **`.repl` loading** | **build time, not run time** | already true: `scripts/parse_repl.py` derives `platform.json`. PLAN.md already decided the platform is compiled in. `parse()` is generic over any `.repl`; only its `main()` names one, so pointing it at a Renode-shipped platform is a parameterisation. Multi-region registration and peripheral-reference parameters are new parser work. |
| **monitor command binding** | **generated dispatch, not a shim** | see §3.1. |
| **Robot XML-RPC server + keyword table** | **shim** | a wire protocol and a harness contract. There is no Renode semantics in it. |

### 3.1 Reflection is not translated. It is resolved at generation time.

A first pass of this estimate counted Renode's reflection plumbing — the
Monitor's reflective binder, `TypeManager`, the `.repl` `CreationDriver`,
`SystemBus`'s access-method construction — as a translation cost, on the
grounds that it "has no analogue in Rust".

**That is a category error and it inflates the floor with work nobody has to
do.** C# uses reflection to defer to run time what a transpiler already knows
statically: which peripherals exist, which method a command word reaches, which
type implements a contract. We hold all of it — in the corpus and in the
platform description — before the binary exists. A generated dispatch table is
not an approximation of reflection; for a fixed platform it is strictly better
and strictly smaller. This is what every surveyed AOT C# pipeline does, IL2CPP
included (`docs/research/prior-art-2026-08-02.md`).

So the cost is not the reflection engine. It is the table, and `floor.json` →
`static_resolution` measures both sides:

| closed at generation time | source |
|---|---|
| `monitor_target_names` — every name the monitor must resolve | `platform.json`, derived from the `.repl` |
| `peripheral_dispatch_entries` — every (peripheral, contract method) pair | the emitted modules' contract; **`src/renode-stm32/src/dispatch.rs` already generates exactly this**, from the corpus |
| `monitor_commands_required` — the verbs this test uses | the `.robot` file |
| `robot_keywords_required` — of `robot_keywords_renode_serves` | the `.robot` file, against `[RobotFrameworkKeyword]` |

Against that, `genuinely_dynamic` lists what survives, and it is short:

1. the command **string** arrives from the Robot client, so it must be
   tokenised at run time — but every name it can resolve to is in the closed
   sets above;
2. scalar argument coercion, because a token's type is not known until parsed;
3. how many machines exist, if a suite creates more than one.

That is a tokeniser and a `match`, not a binder. **The three reflection hot
spots reduce to: `CreationDriver` → the generator that already produces
`platform.rs`; `FillAccessMethodsWithDefaultMethods` → `dispatch.rs`, already
generated; `MonitorCommands` + `TypeManager` → a generated table whose size is
`peripheral_dispatch_entries`.** None of them is hand-written volume, and two
of the three exist.

The residue that genuinely cannot be resolved statically is Renode features
this floor does not have: `LoadPlatformDescriptionFromString` (a platform
authored at run time), ad-hoc C# compilation, and the Python engine. Each is a
capability the floor declines, not a cost it pays — and each would reopen this,
because a platform that does not exist at generation time cannot be dispatched
from a generated table.

---

## 4. The shim boundary

The failure mode is a shim that grows into a reimplementation. The boundary is
therefore stated as an admission rule with a tripwire, not as a list.

There are now **three** dispositions, not two, and keeping them apart is what
stops the floor being over-costed:

> **GENERATE** where the C# reflects over something the corpus or the platform
> already fixes. Not a shim and not a translation — the table reflection would
> have computed, emitted ahead of time. §3.1.
>
> **SHIM** only where the C# is a wire protocol or a harness contract with no
> Renode semantics in it, or where a real implementation already sits behind an
> FFI.
>
> **TRANSLATE** everything whose value a Robot assertion can observe, because
> that is the only thing the test is evidence about.

Applied:

- peripheral dispatch, the monitor's target table, platform construction —
  **generate.** Two of the three already are.
- the XML-RPC server, the port file, the keyword table, the log cache —
  **shim.** No assertion observes them; they only carry values.
- address decode, unmapped-access behaviour, byte/word access to a doubleword
  peripheral, register semantics, erase behaviour — **translate.** A Robot
  assertion reads exactly these.
- memory contents — **hand-written, and admitted as the one place the rule
  bends.** `Should Perform Mass Erase` asserts on bytes in a memory. The bend is
  bounded by being a byte vector with no behaviour of its own beyond
  read/write/fill, and it is named here rather than discovered later.

**The tripwire, so this is enforceable rather than aspirational:** a shim that
acquires a *branch on a peripheral's identity or state* has stopped being
plumbing. `if peripheral_is_flash_controller { ... }` inside the bus is the
exact shape of a reimplementation starting, and it is the thing to fail a
review on. The bus may branch on an **address**; it may not branch on a
**peripheral**.

Second tripwire, from this project's own history: a shim must not be the thing
that makes a test pass. If `Should Perform Mass Erase` goes green while
`STM32F4_FlashController`'s `PerformMassErase` is still withheld, the shim has
implemented the peripheral. `scripts/check_generated.py` cannot see that, and
neither can the test. The check is that the withheld-method list for the type
under test must be **empty** before its Robot test counts.

---

## What this costs

- **A hand-written bus, machine and memory that the converter did not produce.**
  They are infrastructure by PLAN.md's own taxonomy, but they are lines nothing
  regenerates, and they must be counted where hand-written lines are counted.
  These, not the reflection plumbing, are the floor's real hand-written cost.
- **A generator extension**, not a runtime engine: `parse_repl.py` today emits
  peripheral names and GPIO reset values, and the floor needs it to emit the
  address table and the construction order too. That is derivation from the
  `.repl` it already reads, so it adds no second source of truth — but it is
  work, and it is where the reflection cost actually lands.
- **A `.repl` parser that handles more than the target platform** — multi-region
  registration, peripheral-reference parameters, and refusal-with-a-name for
  `init:` directives.
- **The `reset` contract has to be unified in the converter first.** That is a
  blocking dependency the floor cannot route around without a per-module table.
- **The first milestone proves nothing about the CPU, time, or interrupts.**
  Deliberately. It is a floor, not a boot.

## What was rejected

- **`tests/unit-tests/sysbus-tag.robot` as the first test.** Cheapest by a
  distance and rejected on the criterion above: its verdict is decided entirely
  by code we would hand-write. It is kept as the **harness smoke test** — the
  thing that proves the XML-RPC server, the port file and the keyword table
  work — and it must never be reported as an oracle result.
- **The whole of `stm32f4-erase.robot` as the first milestone.** Its first case
  needs the log tester and an exact log string; splitting the file makes the
  logging subsystem a second milestone instead of a prerequisite.
- **Making more modules compile first.** That is a ceiling, not a floor. The
  intersection in `floor.json` shows that clean and drivable move
  independently, so raising `modules_clean` need not raise `platform_floor` at
  all.
- **Booting the firmware first.** Rejected for the reason
  [target-one-peripheral-end-to-end.md](target-one-peripheral-end-to-end.md)
  already gave: a long stall with no signal, and on failure no way to tell
  which of a dozen missing things caused it.
- **Translating the bus, the memories and the machine.** The measurement under
  `floor.json` → `infrastructure` says the converter emits effectively none of
  them today, and they are the parts PLAN.md already assigns to the
  hand-written bucket. Attempting them now would be the largest possible detour
  from a floor that runs.
- **Counting Renode's reflection plumbing as a translation cost.** Rejected on
  the measurement in §3.1, and recorded because the first pass of this
  document did exactly that. The test is never "does Rust have this feature" —
  it is "is the set this resolves over closed at generation time". For the
  monitor binder, the platform loader and the bus's access-method
  construction, it is.

## What would overturn it

- **The `reset` contract turning out not to be unifiable in the converter** —
  if `reset` can only be reached per-module, the generic machine is unavailable
  and the floor needs a different assembly story.
- **A Robot test being found whose verdict is decided by converter output and
  which needs strictly less than this one.** The survey covered
  `tests/unit-tests/` and `tests/peripherals/`; the other suites were not swept,
  and that is a gap in the search, not a claim about it.
- **The shim boundary being crossed to make the first test pass.** If
  `Should Perform Mass Erase` can only be made green by putting peripheral
  behaviour into the bus or the machine, the floor is in the wrong place and
  the decision fails on its own tripwire rather than on argument.
- **`ApplySVD` or `Tag` turning out to affect an address the test touches** —
  that would make the `.repl` `init:` block a blocker rather than a recorded
  deviation, and it is checkable rather than arguable.
- **A required capability whose target set is not closed at generation time.**
  §3.1 holds only while the platform is known before the binary exists.
  `LoadPlatformDescriptionFromString`, the ad-hoc compiler and the Python
  engine all break that, and any of them entering the acceptance set reopens
  the generate-versus-shim split — not just the estimate.
