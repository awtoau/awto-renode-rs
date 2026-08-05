# C# and Renode are two problems, and mixing them is why this is slow

Status: proposed, 2026-08-05. Supersedes nothing; reframes how the work is
measured and where a fix gets checked.

## The complaint

Migration is taking longer than it should, and the suspicion was that Renode's
complexity is the cause — not because Renode is hard to translate, but because
**C# problems and Renode problems have become the same problem**. Every time
the converter fails, the failure arrives wearing a peripheral's name.

## The measurement

`scripts/analysis/classify_gaps.py` splits the gap census by what is actually
blocking the converter. Of the 4,714 gaps that have a named root cause:

| | gaps | share |
|---|---:|---:|
| plain C# — the language and the base class library | 3,273 | **69.4%** |
| Renode's own types and base classes | 1,441 | 30.6% |

The C# side is ordinary language surface, nothing exotic:

    604  static method calls          293  array creation
    446  throw                        205  object
    398  default values               201  using
    348  declaration expressions      108  delegate creation
    298  decimal                       83  ?? coalescing

The Renode side is what you would expect: `DoubleWordRegister`, `BaseCPU`,
`UARTBase`, `IPeripheral`, `IUART`, `UARTFrame`.

**Seven gaps in ten are the C# language.** The converter is not mainly stuck on
Renode. It is stuck on C#, inside Renode.

## Why that costs time

The two classes have completely different economics, and right now both are
paying the expensive one.

A C# gap — `throw`, `using`, static calls — is generic. One fix serves every
corpus forever. It could be reproduced by a five-line standalone program, fixed
in minutes, and checked by running that program.

A Renode gap needs Renode knowledge and can only be judged by a peripheral
behaving correctly.

But **today there is only one way to discover either, and only one way to
confirm either is fixed**: a peripheral fails to emit, and later emits again.
So the cheap class is being debugged through the expensive loop. A `throw`
mapping bug surfaces as "the flash controller won't emit", is diagnosed by
reading flash controller code, and is confirmed by re-emitting the flash
controller — when the actual defect had nothing to do with flash, registers, or
Renode.

This also explains a second symptom. There is no signal anywhere that
distinguishes "the C# layer is wrong" from "the Renode layer is wrong", so
neither can be worked on independently, and progress on one is invisible in the
metrics of the other.

## Where the split already exists, and where it doesn't

The **rules** are already layered, and correctly:

| layer | lives in | size |
|---|---|---:|
| C# language and BCL | `rulesdb/rules/csharp_core.json` | 70,310 B |
| Renode idioms | `register_dsl` + `bug_rules` + `offset_switch` + `constructor` + `object_graph` | 119,234 B |

The **validation** is not layered at all. Every check the project has —
compile-clean counts, the peripherals-that-run floor, trace replay on eight
peripherals, mutation testing — is Renode-shaped. So 70 KB of C# language
mappings have exactly one form of evidence behind them: *some Renode peripheral
compiled*.

That is the gap. Not in the rules. In how they are checked.

## What follows

1. **The C# layer needs its own test loop, independent of Renode.** Run a
   self-contained C# program under `dotnet`, run its translated Rust, and
   compare exit code and output. The C# runtime is the reference, so any C#
   program becomes a test case without anyone writing expectations. No Renode,
   no firmware, no recorded traces, no F427.

   This is also the first execution-level check the project would have outside
   eight peripherals: 283 modules compile clean today and **not one has ever
   been run**.

2. **Report the two separately.** A single "gaps" number hides which problem is
   moving. `docs/status/gap_split.json` is the start; the scorecard should lead
   with both.

3. **Fix the C# class first, by weight.** The top C# causes are worth ~3,273
   gaps between them and are the smallest, most general fixes available. They
   are also the prerequisites for point 1 — nothing can print a result until
   static calls work.

## What this does not claim

Not that Renode is simple, and not that the Renode-specific 30% is easy. It
claims only that the majority of what is blocking the converter today is not
Renode-specific, that this was invisible because nothing measured it, and that
the fix for it is being routed through the slowest available feedback loop.
