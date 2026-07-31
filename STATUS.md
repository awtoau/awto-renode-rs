# renode-rs — scorecard

Generated 2026-07-31T13:19:59+10:00 from `68acd37` by `scripts/scorecard.py`. **Do not edit by hand.**

Leading with the metrics that detect drift, not the ones that flatter it —
"files translated" is exactly what looked healthy in `linux-rs` while its rules
averaged 1.87 validation instances each.

## Health metrics

| metric | value | target | status |
|---|---:|---:|---|
| **instances per rule** | — | ≥ 3 | no rules yet |
| patches outstanding | — | 0 | no translations yet |

## Corpus

| | count | % of corpus |
|---|---:|---:|
| methods ingested | 1,102 | — |
| operation nodes | 65,775 | — |
| pattern clusters | 11,279 | — |
| stubbed | 0 | 0.0% |
| translated | 0 | 0.0% |
| verified | 0 | 0.0% |
| **rules committed** | 0 | — |

## Gates

Genuine stop points. A failed gate means stop, not retry.

| gate | status | evidence |
|---|---|---|
| **P1** — is the Rust MMIO path faster? | PASS | [docs/perf-spike.md](docs/perf-spike.md) |
| **R3** — does the corpus collapse into clusters? | done | [docs/census.md](docs/census.md) |
| **10** — do one peripheral's rules cover an unseen second? | — | blocked on R6 |

## Oracle tiers

| tier | what it proves | status |
|---|---|---|
| 1 — compiles | the crate builds | built |
| 2 — trace replay | per-peripheral register behaviour | built |
| 3 — instruction lockstep | full machine state vs C# | not built (#23) |
| 4 — boot equivalence | firmware reaches the prompt | **C# reference pinned** |
| 5 — CLI suite | commands behave identically | not built (#25) |

## Tests

Not built — no `docs/status/tests.json`.

Per-method tests are generated from tier-2 trace fixtures once the
harness exists (#34 R5). Until then a stub fails its test by construction,
which is the intended starting state: **0% passing over 100% of the corpus**
is a truthful scoreboard, an empty table is not.

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

37 total.

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
| unphased | 3 | 0 |

