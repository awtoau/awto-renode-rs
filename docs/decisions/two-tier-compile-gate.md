# Parallel emission, and a two-tier compile gate

**Taken 2026-08-03.** Emission runs on every core; the everyday compile gate is
scoped to a declared working set and ratchets **per module over the clean set**
instead of on the error total.

This is the case `docs/decisions/remove-the-cut.md` listed under *"what would
overturn it"* — *"evidence that the whole-tree ingest is slow enough to stop
being run every iteration"* — arriving one level down the pipeline. The ingest
stayed fast (~55s). The **tooling over the corpus** did not.

## The defect

Removing the cut took the corpus from 21,620 lines to 448,375 and the emitted
modules from 24 to 569. Both census scripts emitted all 569 **serially**, one
`Emitter` at a time:

| script | before |
|---|---|
| `gap_census.py` | 8m 51s |
| `compile_check.py` | 10m 08s |
| `check_refactor.py` (runs both) | ~22 min |

`compile_check --ratchet` was in the pre-commit hook. So the last several
commits were made with `RENODE_RS_SKIP_HOOK=1` and the checks run by hand.

**That is not slowness, it is a gate that does not run.** This repo has already
found three checks reporting success while verifying nothing — a refactor
oracle that recorded a crash as a baseline, a concurrency harness that had
never failed, and a compile gate that reported a clean build when cargo never
started. A skipped hook is the same outcome by a different route, and it is
harder to see, because nothing about the commit records that the gate was
absent.

## What was done, and what each part fixed

### 1. Emission is parallel (`scripts/emit_pool.py`)

Processes, not threads, even though this interpreter is a free-threading build
with the GIL off: `Emitter` carries mutable per-instance state and has never
been audited for thread safety, and a process pool still parallelises on a
GIL-enabled interpreter. Each worker builds its own `Emitter` with its own
read-only SQLite connection, so nothing mutable is shared.

Work-stealing, not static partitioning — one shared queue at `chunksize=1`, so
a fast P-core simply takes more types than a slow E-core. Tasks are issued
longest-first, because the corpus is wildly uneven.

| stage | before (-j1) | after (-j31) |
|---|---|---|
| `gap_census.py` | 534.7s | **92.9s** (5.6x) |
| `compile_check.py` | 573.8s | **97.2s** (5.5x) |
| — sub-block probe | 11.4s | 2.0s |
| — emit | 584.3s | 114.6s |
| — `cargo check` | 12.4s | 12.3s (unchanged; it was never the cost) |
| `check_refactor.py` | ~22 min | **192.6s** |
| `check_generated.py` | 25.0s | 10.0s |
| `compile_check --working-set` | — | **48.2s** |

**Why 5.8x and not 31x, and why that is the ceiling.** The single longest type,
`WindowIOMMU`, takes 61.0s to emit on its own. No worker count goes below that.
Total emit CPU is 584s, so the theoretical floor is `max(584/31, 61) = 61s` and
the measured 92-115s is within ~1.6x of it. The remaining lever is caching, not
threads — see below.

### 2. The everyday tier is scoped, and says what it did not check

Parallelism alone left the hook at ~2 min, which is still enough to get
skipped. So the gate is now two commands:

    python3 scripts/gates.py            fast  -- every commit
    python3 scripts/gates.py --full     whole corpus -- before a push

The fast tier compiles the **declared clean set** plus every corpus type named
in the working diff: 212 modules, 58s.

A gate over a subset cannot catch a regression outside the subset, and that is
exactly how the corpus cut hid four platform peripherals for weeks while every
headline number over it looked healthy. So:

1. The working set is **declared data** (`docs/status/compile_clean_set.json`),
   not "whatever was fast". It may only grow; `min_modules` is a floor, so
   shrinking it takes two edits and shows up in review.
2. The fast tier **prints what it did not check**, every run —
   *"NOT CHECKED: 355 of 567 module(s)"*, with the command that does.
3. The full tier is one command and gates a push.

### 3. The ratchet is per module over the clean set, not the error total

The total had already stopped being a gate, and
`docs/status/compile_baseline.json` said so itself under
`why_this_ratchet_is_now_weaker`: with 2,880 errors across 348 modules, 50 new
errors is a 1.7% rise and passes.

**212 of 560 modules compile with zero errors. That set is the signal.** A
module leaving it is unambiguous, attributable to one file, and is precisely
what a total can never tell you.

## The hook is faster and is STILL NOT FAST ENOUGH

Measured end to end: **316.7s**, down from over 15 minutes. That is a real
improvement and it is not the finish line, and saying otherwise would repeat
the mistake this whole document is about.

    check_rule_negatives                     118.5s
    check_postconditions                     117.0s
    compile_check --working-set --ratchet      48.2s
    check_generated                            8.0s
    check_inheritance                          7.4s
    everything else                           <2s each

The compile census is no longer the problem; it is now the third-largest cost.
**The two rule-semantics gates are 74% of the hook**, and they have the same
defect shape one level down: each walks **33,531 combinator sites** in a serial
`for` loop against one shared `Emitter`. Take those two out and the hook is
~81s, which is a hook nobody has a reason to skip.

They are NOT parallelised here, deliberately. They call fine-grained emitter
internals — `bind`, `out_field`, `select_rule` — rather than the whole-file
`emit_file` entry point, so whether a fresh `Emitter` per chunk gives the same
answer as one shared emitter walking every site in order is a question about
emitter state that this change is not in a position to answer. Getting it wrong
produces a gate that validates a different arm than the converter picks, which
is exactly the failure `check_rule_negatives` exists to catch — and the comment
at `scripts/check_rule_negatives.py:125` records that a hand-written copy of
the arm selection already caused it once.

**So this is a reported finding, not a fixed one.** The fix is the same shape as
`scripts/emit_pool.py` plus a determinism harness for those two scripts, and it
belongs to whoever owns the emitter.

## What this deliberately does NOT cover

**A module that already fails can get worse and nothing will notice.** 348
modules have at least one error; their counts are recorded for trend and are
not gated. This is stated rather than papered over — a ratchet over a
mostly-broken population carries no signal, and pretending the total covered it
is how the weak ratchet survived.

**The fast tier says nothing about the 355 modules outside the working set.**
It prints that, every run.

**Emission crashes on 7 types** (`list index out of range`). They are named,
and counted in the "not checked" total rather than quietly dropped.

## What is NOT changed

- **Output is byte-identical at every `-j`.** Enforced by
  `scripts/check_emit_determinism.py`, the emit-side counterpart to
  `scripts/check_determinism.py` for the ingest. Results are collected in
  **task order**, never completion order — aggregating in completion order
  gives the same totals with different `Counter.most_common` tie-breaks and a
  different "first example per category": valid output, different bytes, and no
  test that would see it.

  Measured, 8 comparisons, all MATCH:

  | | `-j1` vs `-j31` | 3 runs at `-j31` | lpt vs `--no-lpt` |
  |---|---|---|---|
  | `gap_census` | MATCH `a00c555a78d049cb` | MATCH | MATCH |
  | `compile_check` | MATCH `4224a06d5a6826c9` | MATCH | MATCH |

  The `--no-lpt` column is the one that would catch a regression nobody would
  think to look for: the scheduler hands out expensive types first, so if any
  aggregation ever started depending on arrival order, that is what would move.

- **Emitting a subset gives the same bytes as emitting everything.** Checked by
  diffing the 212 modules the working-set run produced against the same 212
  from the full run: byte-identical, the only differences being the 348 modules
  the subset does not emit and a `lib.rs` that correctly lists fewer.

- **The new ratchet can actually reject.** A check that has never rejected
  anything reports exactly what a check doing nothing reports, so both refusal
  paths were exercised: declaring a module clean that has 101 errors exits 1
  and names it; shrinking the declared list without lowering `min_modules`
  exits 1 before compiling anything.
- **The traces.** All 8 replay with the same divergence counts, asserted
  exactly in `src/renode-stm32/tests/generated_trace.rs` — usart1 0, exti 0,
  syscfg 0, gpioPortA 3, dma1 7, dma2 616, adc1 1192, can1 99. The three zeros
  are the sharp signal; the whole suite is 0.09s, so all 8 are kept.
- **No emitter change.** Nothing under `scripts/emit.py`, `scripts/emitter/` or
  `rulesdb/rules/` was touched. Before and after, over the whole corpus:
  **2,880 errors across 348 modules, 212 of 560 clean, 164,700 lines** — and
  the gap census stdout is byte-identical to the serial baseline recorded
  before any of this landed.

## The next lever, with the measurement that justifies it

Caching, which CLAUDE.md already asks for: *"cache content-addressed on
(subtree hash, rule-set hash) so a rule change recomputes only what changed"*.

The fast tier's 58s is 55s of emission for 212 types that mostly did not
change. A content-addressed cache would take a docs-only or script-only commit
to near zero and a single-rule change to whatever that rule touches.

It is not built here, deliberately: a stale cache entry is silently wrong
output, which is the failure class this project keeps paying for, so it needs
its own proof rather than being bolted onto a speed change.

## What would overturn this

- The fast tier missing a regression the full tier then finds. That is a signal
  the working set is too narrow, and the answer is to grow the declared set,
  not to widen the tier by feel.
- The clean set shrinking for reasons nobody can attribute — which would mean
  per-module is still too coarse and the gate wants to be per error code.
