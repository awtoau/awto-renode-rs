# renode-rs — scorecard

Generated 2026-08-06T00:23:17+10:00 from `c050e6e` by `scripts/scorecard.py`. **Do not edit by hand.**

Leading with the metrics that detect drift, not the ones that flatter it —
"files translated" is exactly what looked healthy in `linux-rs` while its rules
averaged 1.87 validation instances each.

## Health metrics

| metric | value | target | status |
|---|---:|---:|---|
| **compile-clean modules (the gate)** | 283 | ratchet, may only grow | PASS |
| platform floor (peripherals reachable end-to-end) | 27 / 65 | 65 | 42% |
| modules clean *and* drivable | 173 / 599 | — | 29% |
| oracle trace replay: peripherals at 0 divergence | 3 / 8 | 8 | partial |

> **The `rule` / `rule_instance` / `pattern_cluster` / `translation` SQL tables are
> 0 rows by design, not by defect.** The tree-matcher/cluster-mining pipeline those
> tables were built for (see `docs/rulesdb-design.md`) was superseded by
> hand-authored JSON rule files read directly by `scripts/core/emit.py` — see
> [docs/rule-engine-readiness.md](docs/rule-engine-readiness.md) and
> [docs/decisions/remove-the-cut.md](docs/decisions/remove-the-cut.md). A scorecard
> that reported `instances per rule` and `patches outstanding` from those tables
> read "0 rules committed, nothing translated" while 283 modules compiled clean —
> the metric measured the abandoned pipeline, not the one in use.

## Corpus

| | count |
|---|---:|
| methods ingested | 26,159 |
| operation nodes | 1,590,724 |
| types ingested | 4,832 |

**Emission floor** (`docs/status/floor.json`, see [docs/decisions/the-floor-that-runs.md](docs/decisions/the-floor-that-runs.md)):

| | count |
|---|---:|
| modules emitted | 599 |
| modules clean (0 rustc errors) | 283 |
| modules drivable | 340 |
| modules clean and drivable | 173 |
| platform peripherals in scope | 65 |
| platform peripherals emitted | 50 |
| platform floor | 27 |

**Hand-authored rule files** actually read by the emitter (not the SQL `rule` table — see the note above):

| file | size |
|---|---:|
| `rulesdb/rules/csharp_core.json` | 70,310 bytes |
| `rulesdb/rules/register_dsl.json` | 64,253 bytes |
| `rulesdb/rules/bug_rules.json` | 25,985 bytes |
| `rulesdb/rules/offset_switch.json` | 13,460 bytes |
| `rulesdb/rules/constructor.json` | 8,226 bytes |
| `rulesdb/rules/object_graph.json` | 7,310 bytes |

**What the converter cannot yet emit** (27,673 gaps over 601 types, 601 emitted, 0 converter crash(es) — not a correctness claim, see [docs/rule-engine-readiness.md](docs/rule-engine-readiness.md); regenerate with `python3 scripts/analysis/gap_census.py`):

| gap category | count | share |
|---|---:|---:|
| missing state (cascade) | 5,108 | 18.5% |
| constructor: statement not an initialiser | 3,674 | 13.3% |
| other | 3,468 | 12.5% |
| unmapped return type | 1,877 | 6.8% |
| unhandled expression kind | 1,817 | 6.6% |
| unmapped parameter type | 1,663 | 6.0% |
| missing peer method (cascade) | 1,547 | 5.6% |
| withheld dependency (cascade) | 1,372 | 5.0% |
| object graph: target not emitted | 1,048 | 3.8% |
| exceptions | 743 | 2.7% |
| callback with no rule | 688 | 2.5% |
| unmapped state field type | 669 | 2.4% |
| non-constant field placement | 549 | 2.0% |
| withheld: gap marker in body | 489 | 1.8% |
| constructor: nothing to initialise | 466 | 1.7% |

Top root causes (cascades excluded):

| root cause | gaps blocked |
|---|---:|
| type  DoubleWordRegister | 526 |
| construct  StaticInvocation | 461 |
| construct  Throw | 449 |
| construct  DefaultValue | 398 |
| construct  DeclarationExpression | 379 |
| type  decimal | 298 |
| construct  ArrayCreation | 293 |
| type  object | 205 |
| construct  Using | 201 |
| type  Response | 184 |

## Gates

Genuine stop points. A failed gate means stop, not retry.

### Current

| gate | status | evidence |
|---|---|---|
| **two-tier compile gate** — modules with 0 rustc errors | 283 (ratchet, may only grow) | [docs/decisions/two-tier-compile-gate.md](docs/decisions/two-tier-compile-gate.md) |
| **the floor that runs** — peripherals reachable end-to-end | 27 / 65 | [docs/decisions/the-floor-that-runs.md](docs/decisions/the-floor-that-runs.md) |

### Historical (Phase 0/1)

| gate | doc's own verdict | evidence |
|---|---|---|
| **P1** — is the Rust MMIO path faster? | PASS | [docs/perf-spike.md](docs/perf-spike.md) |
| **R3** — does the corpus collapse into clusters? | FAIL | [docs/census.md](docs/census.md) — coverage metric itself disputed by open issue #37 ("R3b — bare leaves are not rule failures") |
| **10** — do one peripheral's rules cover an unseen second? | PASS | [docs/phase1-gate.md](docs/phase1-gate.md) |

## Oracle tiers

| tier | what it proves | status |
|---|---|---|
| 1 — compiles | the crate builds | built |
| 2 — trace replay | per-peripheral register behaviour | built — 8 peripherals, 24 traces captured |
| 2.5 — interleaving | a critical section is not observed part-way through | built (#52) |
| 3 — instruction lockstep | full machine state vs C# | not built (#23) |
| 4 — boot equivalence | firmware reaches the prompt | **C# reference pinned** |
| 5 — CLI suite | commands behave identically | not built (#25) |

**Tier-2 replay, per peripheral** (from `generated_replay!()` in `src/renode-stm32/tests/generated_trace.rs`):

| module | trace | divergences | status |
|---|---|---:|---|
| `renode_stm32::syscfg_registers` | `syscfg` | 0 | PASS |
| `renode_stm32::exti_registers` | `exti` | 0 | PASS |
| `renode_stm32::adc_registers` | `adc1` | 1192 | diverges |
| `renode_stm32::dma_registers` | `dma1` | 7 | diverges |
| `renode_stm32::dma_registers` | `dma2` | 616 | diverges |
| `renode_stm32::can_registers` | `can1` | 28 | diverges |
| `renode_stm32::gpio_registers` | `gpioPortA` | 3 | diverges |
| `renode_stm32::uart_registers` | `usart1` | 0 | PASS |

> **Threading is UNCERTIFIED.** Tier-2 replay is single-threaded, so a threading difference cannot appear in it by construction. The tier-2.5 harness can observe interleaving and is proven to fail when a lock is deleted (`scripts/check_sync_harness.py`) — but it has been pointed at no translated peripheral: 56 lock site(s) in the corpus, 0 in emitted Rust. Nothing here is evidence for or against D3.

## Severity — translated, but the semantics differ

| marker | sites in emitted Rust | what differs |
|---|---:|---|
| `WARN(condwrite)` | 5 | the source performs this access only under a guard; here it is UNCONDITIONAL. The guard reads state this declaration cannot see. |
| `WARN(eager)` | 6 | a lazy sequence became an owned collection: it is evaluated EAGERLY, so enumeration side effects and their order differ. |
| `SYNC(measure)` | 0 | C# `lock`. Structure preserved; TIMING IS NOT. |
| `WARN(multicast)` | 7 | a multicast event collapsed to ONE subscribe: there is no unsubscribe, and a second subscriber replaces the first. |
| `WARN(narrowed)` | 15 | a value outside the declared set has no variant here: the source keeps the number, this falls back to the default. |
| `WARN(orderby)` | 0 | ordering is a PASS-THROUGH: the key selector is discarded and the sequence keeps its source order. |
| **total** | **33** | |

A **gap** withholds the member, so it can never read as a translation. A **warning** emitted and is wrong in a stated way — the number is the count of sites carrying the marker, not the count of deviations declared, so a deviation that is declared and never marked reads as zero rather than as done.

> **2 declared deviation(s) mark nothing yet** — `measure`, `orderby`. Each has sites in the corpus and none of those sites reaches emitted Rust today: the members carrying them are withheld for unrelated reasons. The zero is a fact about how little is emitted, not evidence that the deviation is gone.

## Tests

Not built — no `docs/status/tests.json`.

Per-method tests are generated from tier-2 trace fixtures once the
harness exists (#34 R5). Until then a stub fails its test by construction,
which is the intended starting state: **0% passing over 100% of the corpus**
is a truthful scoreboard, an empty table is not.

## Converter

**The deliverable is the converter, not its output.** A hand-written
peripheral is not a translation, however well it passes its tests — both
current ones did, and one contained a `.with_reserved(9, 23)` call the C#
does not have.

| | |
|---|---|
| files produced by the converter | 1 (`uart_registers.rs`) |
| peripherals still hand-written | uart behaviour, gpio layout + behaviour |
| enforcement | none |

The UART's register layout is now generated and enforced byte-for-byte.
Deleting the hand-written version removed three edits that had survived
both the 33,164-access trace and mutation testing — including a
`.with_reserved(9, 23)` call the C# does not contain.

## Mutation score

What the tests can actually *see*. A passing trace replay means
"indistinguishable on this trace" — nothing about a green tick separates a
thorough trace from a useless one. Mutation testing is the only signal that does.

| target | mode | caught | viable | score | equivalent | survivors |
|---|---|---:|---:|---:|---:|---:|
| gpio | all | 8 | 8 | 100.0% | 4 | 0 |
| uart | all | 30 | 37 | 81.1% | 0 | 7 **7** |

**Unresolved survivors** — each names a behaviour nothing checks:

- `uart` rw->read line 229: `.with_value(0, 9, &mut ValueId::default(), FieldMode::READ_W`
- `uart` rw->read line 255: `.with_flag(15, &mut f.oversampling_mode, FieldMode::READ_WRI`
- `uart` rw->read line 268: `.with_value(12, 2, &mut f.stop_bits, FieldMode::READ_WRITE)`
- `uart` read->rw line 220: `FieldMode::READ | FieldMode::WRITE_ZERO_TO_CLEAR,`
- `uart` and->or line 126: `if !self.bank.flag(self.f.usart_enabled) && !self.bank.flag(`
- `uart` and->or line 182: `&& !self.bank.flag(self.f.transmitter_enabled)`

## Benchmarks

Not built — no `docs/status/benchmarks.json`.

Tracked once there is a Rust emulator to measure (#26). The metrics are
fixed now so the series is comparable from its first point:

| metric | why |
|---|---|
| MMIO accesses/sec | the dominant cost; ~409 ns/access in C# today |
| instructions/sec | CPU throughput; ~50 MIPS in C# today |
| MMIO:instruction ratio | polling-heavy firmware lives or dies on this |
| wall : simulated ratio | the user-visible number (0.16× in C# today) |
| boot wall-clock | end-to-end, the one that matters in CI |

**Benchmarks must be pinned to a P-core.** Unpinned variance on this
hybrid host was ~50% from core migration; pinned it is ±2%.

## C# reference baseline

| | |
|---|---|
| Renode commit | `dc52b24c118a` |
| firmware ELF | `awto-htc.elf` `4eccbaee25d7` |
| markers in order | 8 / 8 |
| init steps | 19 (2 expected failures) |
| `system_boot OK` | 291 ms simulated |
| first output | host 26.57s / virt 7.16s (LSI-measurement cost) |
| real-time ratio | 0.16× |

> The real-time ratio is **contaminated**: `SystemBus::TryGetTag` is 12.78% of
> profile, driven by 16,827 accesses per boot to unmapped ADC_CCR
> (`0x40012304`). It measures Renode's error path as much as its speed.
> See [docs/perf-spike.md](docs/perf-spike.md).

## Issues

65 open, 9 closed, 74 total. Full list: [github.com/awtoau/awto-renode-rs/issues](https://github.com/awtoau/awto-renode-rs/issues).

| phase | open | closed |
|---|---:|---:|
| phase-0 | 8 | 0 |
| phase-1 | 7 | 0 |
| phase-2 | 2 | 0 |
| phase-3 | 4 | 0 |
| phase-4 | 1 | 0 |
| phase-5 | 7 | 0 |
| phase-6 | 2 | 0 |
| phase-7 | 3 | 0 |
| unphased | 31 | 9 |

**By label** (an issue may carry more than one; counts are not additive to the total above):

| label | issues |
|---|---:|
| `P0` | 1 — [#61](https://github.com/awtoau/awto-renode-rs/issues/61) |
| `blocked-decision` | 3 — [#38](https://github.com/awtoau/awto-renode-rs/issues/38), [#39](https://github.com/awtoau/awto-renode-rs/issues/39), [#41](https://github.com/awtoau/awto-renode-rs/issues/41) |
| `blocked-on-split` | 5 — [#46](https://github.com/awtoau/awto-renode-rs/issues/46), [#47](https://github.com/awtoau/awto-renode-rs/issues/47), [#48](https://github.com/awtoau/awto-renode-rs/issues/48), [#49](https://github.com/awtoau/awto-renode-rs/issues/49), [#50](https://github.com/awtoau/awto-renode-rs/issues/50) |
| `bug` | 2 — [#64](https://github.com/awtoau/awto-renode-rs/issues/64), [#69](https://github.com/awtoau/awto-renode-rs/issues/69) |
| `code` | 8 — [#46](https://github.com/awtoau/awto-renode-rs/issues/46), [#47](https://github.com/awtoau/awto-renode-rs/issues/47), [#48](https://github.com/awtoau/awto-renode-rs/issues/48), [#49](https://github.com/awtoau/awto-renode-rs/issues/49), [#50](https://github.com/awtoau/awto-renode-rs/issues/50), [#54](https://github.com/awtoau/awto-renode-rs/issues/54), [#55](https://github.com/awtoau/awto-renode-rs/issues/55), [#63](https://github.com/awtoau/awto-renode-rs/issues/63) |
| `decision` | 11 — [#8](https://github.com/awtoau/awto-renode-rs/issues/8), [#9](https://github.com/awtoau/awto-renode-rs/issues/9), [#10](https://github.com/awtoau/awto-renode-rs/issues/10), [#29](https://github.com/awtoau/awto-renode-rs/issues/29), [#50](https://github.com/awtoau/awto-renode-rs/issues/50), [#51](https://github.com/awtoau/awto-renode-rs/issues/51), [#52](https://github.com/awtoau/awto-renode-rs/issues/52), [#56](https://github.com/awtoau/awto-renode-rs/issues/56), [#57](https://github.com/awtoau/awto-renode-rs/issues/57), [#60](https://github.com/awtoau/awto-renode-rs/issues/60), [#74](https://github.com/awtoau/awto-renode-rs/issues/74) |
| `deferred` | 2 — [#4](https://github.com/awtoau/awto-renode-rs/issues/4), [#5](https://github.com/awtoau/awto-renode-rs/issues/5) |
| `epic` | 1 — [#1](https://github.com/awtoau/awto-renode-rs/issues/1) |
| `frontend` | 4 — [#15](https://github.com/awtoau/awto-renode-rs/issues/15), [#30](https://github.com/awtoau/awto-renode-rs/issues/30), [#33](https://github.com/awtoau/awto-renode-rs/issues/33), [#70](https://github.com/awtoau/awto-renode-rs/issues/70) |
| `gate` | 8 — [#3](https://github.com/awtoau/awto-renode-rs/issues/3), [#14](https://github.com/awtoau/awto-renode-rs/issues/14), [#16](https://github.com/awtoau/awto-renode-rs/issues/16), [#32](https://github.com/awtoau/awto-renode-rs/issues/32), [#37](https://github.com/awtoau/awto-renode-rs/issues/37), [#53](https://github.com/awtoau/awto-renode-rs/issues/53), [#72](https://github.com/awtoau/awto-renode-rs/issues/72), [#73](https://github.com/awtoau/awto-renode-rs/issues/73) |
| `oracle` | 10 — [#2](https://github.com/awtoau/awto-renode-rs/issues/2), [#6](https://github.com/awtoau/awto-renode-rs/issues/6), [#23](https://github.com/awtoau/awto-renode-rs/issues/23), [#24](https://github.com/awtoau/awto-renode-rs/issues/24), [#25](https://github.com/awtoau/awto-renode-rs/issues/25), [#34](https://github.com/awtoau/awto-renode-rs/issues/34), [#44](https://github.com/awtoau/awto-renode-rs/issues/44), [#45](https://github.com/awtoau/awto-renode-rs/issues/45), [#52](https://github.com/awtoau/awto-renode-rs/issues/52), [#72](https://github.com/awtoau/awto-renode-rs/issues/72) |
| `perf` | 3 — [#3](https://github.com/awtoau/awto-renode-rs/issues/3), [#33](https://github.com/awtoau/awto-renode-rs/issues/33), [#36](https://github.com/awtoau/awto-renode-rs/issues/36) |
| `peripheral` | 3 — [#13](https://github.com/awtoau/awto-renode-rs/issues/13), [#21](https://github.com/awtoau/awto-renode-rs/issues/21), [#22](https://github.com/awtoau/awto-renode-rs/issues/22) |
| `phase-0` | 8 — [#2](https://github.com/awtoau/awto-renode-rs/issues/2), [#3](https://github.com/awtoau/awto-renode-rs/issues/3), [#6](https://github.com/awtoau/awto-renode-rs/issues/6), [#7](https://github.com/awtoau/awto-renode-rs/issues/7), [#8](https://github.com/awtoau/awto-renode-rs/issues/8), [#9](https://github.com/awtoau/awto-renode-rs/issues/9), [#10](https://github.com/awtoau/awto-renode-rs/issues/10), [#11](https://github.com/awtoau/awto-renode-rs/issues/11) |
| `phase-1` | 7 — [#15](https://github.com/awtoau/awto-renode-rs/issues/15), [#16](https://github.com/awtoau/awto-renode-rs/issues/16), [#30](https://github.com/awtoau/awto-renode-rs/issues/30), [#31](https://github.com/awtoau/awto-renode-rs/issues/31), [#32](https://github.com/awtoau/awto-renode-rs/issues/32), [#36](https://github.com/awtoau/awto-renode-rs/issues/36), [#37](https://github.com/awtoau/awto-renode-rs/issues/37) |
| `phase-2` | 2 — [#33](https://github.com/awtoau/awto-renode-rs/issues/33), [#34](https://github.com/awtoau/awto-renode-rs/issues/34) |
| `phase-3` | 4 — [#12](https://github.com/awtoau/awto-renode-rs/issues/12), [#13](https://github.com/awtoau/awto-renode-rs/issues/13), [#14](https://github.com/awtoau/awto-renode-rs/issues/14), [#35](https://github.com/awtoau/awto-renode-rs/issues/35) |
| `phase-4` | 1 — [#17](https://github.com/awtoau/awto-renode-rs/issues/17) |
| `phase-5` | 7 — [#18](https://github.com/awtoau/awto-renode-rs/issues/18), [#19](https://github.com/awtoau/awto-renode-rs/issues/19), [#20](https://github.com/awtoau/awto-renode-rs/issues/20), [#21](https://github.com/awtoau/awto-renode-rs/issues/21), [#22](https://github.com/awtoau/awto-renode-rs/issues/22), [#23](https://github.com/awtoau/awto-renode-rs/issues/23), [#24](https://github.com/awtoau/awto-renode-rs/issues/24) |
| `phase-6` | 2 — [#25](https://github.com/awtoau/awto-renode-rs/issues/25), [#26](https://github.com/awtoau/awto-renode-rs/issues/26) |
| `phase-7` | 3 — [#27](https://github.com/awtoau/awto-renode-rs/issues/27), [#28](https://github.com/awtoau/awto-renode-rs/issues/28), [#29](https://github.com/awtoau/awto-renode-rs/issues/29) |
| `research` | 12 — [#4](https://github.com/awtoau/awto-renode-rs/issues/4), [#5](https://github.com/awtoau/awto-renode-rs/issues/5), [#38](https://github.com/awtoau/awto-renode-rs/issues/38), [#39](https://github.com/awtoau/awto-renode-rs/issues/39), [#40](https://github.com/awtoau/awto-renode-rs/issues/40), [#41](https://github.com/awtoau/awto-renode-rs/issues/41), [#42](https://github.com/awtoau/awto-renode-rs/issues/42), [#43](https://github.com/awtoau/awto-renode-rs/issues/43), [#44](https://github.com/awtoau/awto-renode-rs/issues/44), [#45](https://github.com/awtoau/awto-renode-rs/issues/45), [#59](https://github.com/awtoau/awto-renode-rs/issues/59), [#74](https://github.com/awtoau/awto-renode-rs/issues/74) |
| `rules` | 13 — [#12](https://github.com/awtoau/awto-renode-rs/issues/12), [#13](https://github.com/awtoau/awto-renode-rs/issues/13), [#16](https://github.com/awtoau/awto-renode-rs/issues/16), [#17](https://github.com/awtoau/awto-renode-rs/issues/17), [#30](https://github.com/awtoau/awto-renode-rs/issues/30), [#31](https://github.com/awtoau/awto-renode-rs/issues/31), [#32](https://github.com/awtoau/awto-renode-rs/issues/32), [#35](https://github.com/awtoau/awto-renode-rs/issues/35), [#36](https://github.com/awtoau/awto-renode-rs/issues/36), [#37](https://github.com/awtoau/awto-renode-rs/issues/37), [#51](https://github.com/awtoau/awto-renode-rs/issues/51), [#71](https://github.com/awtoau/awto-renode-rs/issues/71), +1 more |
| `tooling` | 3 — [#61](https://github.com/awtoau/awto-renode-rs/issues/61), [#69](https://github.com/awtoau/awto-renode-rs/issues/69), [#71](https://github.com/awtoau/awto-renode-rs/issues/71) |
| `transpiler` | 30 — [#38](https://github.com/awtoau/awto-renode-rs/issues/38), [#39](https://github.com/awtoau/awto-renode-rs/issues/39), [#40](https://github.com/awtoau/awto-renode-rs/issues/40), [#41](https://github.com/awtoau/awto-renode-rs/issues/41), [#42](https://github.com/awtoau/awto-renode-rs/issues/42), [#43](https://github.com/awtoau/awto-renode-rs/issues/43), [#44](https://github.com/awtoau/awto-renode-rs/issues/44), [#45](https://github.com/awtoau/awto-renode-rs/issues/45), [#46](https://github.com/awtoau/awto-renode-rs/issues/46), [#47](https://github.com/awtoau/awto-renode-rs/issues/47), [#48](https://github.com/awtoau/awto-renode-rs/issues/48), [#49](https://github.com/awtoau/awto-renode-rs/issues/49), +18 more |

**Gate-labeled**:

- [#3](https://github.com/awtoau/awto-renode-rs/issues/3) (OPEN): P1 — GATE: performance spike, before the design is locked
- [#14](https://github.com/awtoau/awto-renode-rs/issues/14) (OPEN): 10 — GATE: does rule leverage exist?
- [#16](https://github.com/awtoau/awto-renode-rs/issues/16) (OPEN): 12 — GATE: pattern census of the F427 corpus
- [#32](https://github.com/awtoau/awto-renode-rs/issues/32) (OPEN): R3 — Fingerprint, cluster, and GATE the collapse
- [#37](https://github.com/awtoau/awto-renode-rs/issues/37) (OPEN): R3b — Revisit the coverage metric: bare leaves are not rule failures
- [#53](https://github.com/awtoau/awto-renode-rs/issues/53) (OPEN): Instrumentation: a path that emits nothing must say why -- six silent failures in one session
- [#72](https://github.com/awtoau/awto-renode-rs/issues/72) (OPEN): Conformance harness: run the C# tests and the translated Rust, compare
- [#73](https://github.com/awtoau/awto-renode-rs/issues/73) (OPEN): Ratchet: changing a language rule must re-run the conformance suite


