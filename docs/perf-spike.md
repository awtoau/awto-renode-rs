# P1 — performance spike (issue #3)

Measured 2026-07-31. Renode v1.16.1 `dc52b24c`, firmware `awto-htc.elf`
`4eccbaee`, host i9-14900K.

**Verdict: PASS** — but for different reasons than PLAN.md assumed, and two of
its stated arguments were wrong.

## Summary

| Claim in PLAN.md | Measured |
|---|---|
| Cache-resident register fields are a major win | **Wrong.** The layout choice is 0.08% of the per-access budget |
| `Rc<RefCell>`-per-field is slow because of cache misses | **Wrong mechanism.** It is the borrow-flag read-modify-write; the cache-exceeding case showed the *smallest* gap |
| Time-sync machinery is a major cost | **Partly.** Locking is 11.1%, but it is not the largest item |
| Managed boundary is the top cost | **No.** P/Invoke frames are ~2% |
| — | **`SystemBus::TryGetTag` is 12.78% — the single hottest function** |
| tlib translation might be worth doing (#P2) | **No.** tlib does not appear in the top 30 |

## 1. The D2 field-layout question

`debris/code/field-layout-spike` — pinned to a P-core, 240 fields (RCC-sized), 20M reads.

| workload | `Rc<RefCell>` | `Cell` arena | speedup |
|---|---:|---:|---:|
| `poll_one` (the LSI pattern) | 2054 M/s | 2939 M/s | **1.43×** |
| `poll_one` via `Rc<Cell>` | — | 2511 M/s | 1.22× |
| `scan_all` | 556 | 632 | 1.14× |
| `poll_with_writes` | 798 | 1378 | 1.73× |
| `whole_system` (1980 fields) | 418 | 468 | 1.12× |

**The cache argument is wrong.** If locality drove this, `whole_system` — whose
working set exceeds L1 for the `Rc` variant — would show the largest gap. It
shows the smallest. The third variant isolates it: `Rc<Cell>` (scattered
allocation, no borrow flag) recovers 1.22× of the 1.43×, so the borrow-flag
read-modify-write is roughly half the win and contiguity the rest.

**The magnitude makes it moot.** Renode performs ~65M MMIO reads in 26.57 s of
wall time — **~409 ns per access**. A `Cell` field read is **0.34 ns**. The
layout is **0.08%** of the budget.

> **Conclusion: keep the `Cell` arena, but not for performance.** Decide D2 on
> correctness — `Cell` cannot panic on re-entrant borrow, and it permits `Send`.
> The performance framing in PLAN.md should be removed.

## 2. Where the time actually goes

`perf record -e cpu_core/cycles/u -F 1999`, pinned to P-cores,
`DOTNET_PerfMapEnabled=1 DOTNET_EnableWriteXorExecute=0`, `RunFor 8.0`.

| Symbol | Share | Category |
|---|---:|---|
| `SystemBus::TryGetTag` | **12.78%** | Renode — unmapped-access path |
| `JIT_MonReliableEnter_Portable` | 6.46% | runtime — locking |
| `PeripheralRegister::ReadInner` | 4.90% | Renode — real work |
| `Misc::IndexOf` | 4.79% | Renode — linear search |
| `JIT_MonExit_Portable` | 4.66% | runtime — locking |
| `JIT_NewS_MP_FastPortable` | 4.55% | runtime — allocation |
| `JIT_ByRefWriteBarrier` | 3.47% | runtime — GC |
| `JIT_WriteBarrier` | 2.45% | runtime — GC |
| `_dl_tlsdesc_return` | 2.20% | runtime — TLS |
| `SystemBus::ReadDoubleWord` | 1.78% | Renode — real work |
| `JIT_VirtualFunctionPointer` | 1.74% | runtime — dispatch |
| `BaseClockSource::Update` | 1.32% | Renode — time |
| `TranslationCPU::ReadDoubleWordFromBus` | 1.03% | Renode — real work |
| `BitHelper::AssertMaskParameters` | 0.68% | Renode — assertion in release |
| **tlib** | **absent from top 30** | the CPU itself |

Aggregated:

| Category | Share | Eliminated by the port? |
|---|---:|---|
| .NET locking | **11.1%** | **Yes** — D3 single-threaded pays zero |
| .NET allocation + GC | **12.4%** | **Yes** — no allocation on the access path |
| TLS, dispatch, casts, thread-id | ~5% | Mostly |
| P/Invoke frames | ~2% | Yes |
| Renode's own hot path | remainder | Reducible, not free |
| **CPU emulation (tlib)** | **~1.5%** | Unchanged — kept via FFI |

**~30% is .NET runtime overhead that Rust does not pay at all**, before any
improvement to the translated logic.

## 3. The biggest single finding

```csharp
private bool TryGetTag(ulong address, out TagEntry? foundTag)
{
    foreach(var tag in tags.Where(x => x.Key.Contains(address)).Select(x => x.Value))
```

A **LINQ linear scan allocating two iterators, on every bus access that misses a
peripheral.** It is the hottest function in the emulator at 12.78%, and it
explains much of the neighbouring `Misc::IndexOf` (4.79%), `JIT_NewS` (4.55%)
and the GC write barriers.

It is provoked here by a **modelling gap**: the repl maps `adc1` at
`<0x40012000, +0x100>`, so ADC_CCR at `0x40012304` falls outside every window.
16,827 accesses in one boot take that path.

**This contaminates the baseline.** The measured 0.16× real time is not
Renode's inherent speed — a large fraction is its error-reporting path,
triggered by one missing register window. Any C#-vs-Rust comparison must
control for it.

*Attempted control, discarded:* mapping `MappedMemory` over `0x40012300`
removed the warnings but took 292 s and produced no firmware output — ADC_CCR
carries `TSVREFE`, so reading back zero changes behaviour. A valid control needs
a real ADC-common model, not RAM.

## 4. This also answers #P2 (replace tlib)

**tlib does not appear in the top 30 symbols.** Instruction dispatch is not on
the critical path — the cost is entirely the peripheral/bus/runtime path.

So the question "is the 2008-vintage JIT worth replacing for speed?" is answered
**no**. If tlib is ever replaced it must be justified on *testability* (one test
file in 227k lines of C), never on throughput. This also confirms keeping tlib
behind FFI, which is what makes the tier-3 lockstep oracle exact.

## 5. Methodology notes, all learned the hard way

1. **Pin benchmarks.** Unpinned, run-to-run variance was ~50% on this hybrid
   CPU (8 P-cores + 16 E-cores); the process migrates between core types.
   Pinned: ±2%.
2. **A ns/read threshold is the wrong hoisting detector.** An L1-resident
   indexed load genuinely retires in ~2 cycles, so "too fast" is not evidence.
   Use **linearity**: double the iterations, expect double the time. The first
   version of this benchmark reported a 2.02× speedup from a fully hoisted loop.
3. **`perf` needs `DOTNET_EnableWriteXorExecute=0`** or every managed frame
   resolves to a raw address in `memfd:doublemapper`. The perf map is written
   for a different alias than the samples land in.
4. **Specify the PMU on a hybrid CPU.** A default `perf record` sampled
   `cpu_atom` only and collected 1K samples.
5. **Log volume is not the cost.** 38,195 warnings vs 13: 74.98 s vs 75.13 s.
   Worth testing before assuming, and it eliminated a confound.

## 6. What this changes

- **PLAN.md**: drop the cache argument for D2; keep D2 on correctness grounds.
- **D3 (single-threaded)**: strengthened. 11.1% in lock enter/exit on a
  single-CPU emulation is pure waste.
- **#P2 (tlib)**: answered on the performance axis — not the bottleneck.
- **Baseline**: `0.16×` must be reported with the caveat that it includes the
  unmapped-ADC_CCR error path.
- **New**: the port must not reproduce `TryGetTag`'s shape. Address decode
  should be a flat table or compiled match, and tag lookup should not exist on
  the hot path at all.
