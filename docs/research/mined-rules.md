# Mined Rust-emission rules

Lessons taken from other source-to-source translators. Every one is about
**emitting Rust**, so it transfers regardless of the source language — which is
the whole reason a Python→Rust project is worth reading.

Sources and licences, checked once:

| project | pair | licence | rules tagged |
|---|---|---|---|
| [paiml/depyler](https://github.com/paiml/depyler) | Python→Rust | MIT | ~120 `DEPYLER-nnnn` across 14 files |
| [c2rust](https://github.com/immunant/c2rust) | C→Rust | BSD-3 | `known_fn.rs`, ~1000 lines of library models |
| [Bun](https://github.com/oven-sh/bun) | Zig→Rust | MIT | `docs/PORTING.md`, `docs/LIFETIMES.tsv` |
| NullAway | Java checker | MIT | `DefaultLibraryModels` |

**Status** column: `applied` is live in our rules; `pending` means we do not yet
emit the construct, and this is here so it is not re-learned the hard way.

## Applied

| lesson | source | what it replaced |
|---|---|---|
| Emit collection types **fully qualified** (`std::collections::VecDeque`) rather than tracking `use` lines | depyler DEPYLER-0623 | a hand-written conditional scanning emitted text for the substring `VecDeque`, which would silently miss any type added later |

## Pending — do not re-learn these

| lesson | source | bites when |
|---|---|---|
| **String literals are already `&str` — do not add `&`** | depyler `DEPYLER-E0277-FIX` | any rule emitting a borrow around a literal argument |
| `HashMap<String, V>::get_mut` takes `&Q where String: Borrow<Q>` — pass `"key"` directly, not `&"key".to_string()` | depyler | dictionary access, i.e. issue #49 |
| Reference iterators need **`.cloned()` before `.collect()`** | depyler DEPYLER-1001 | LINQ, i.e. issue #47 |
| `vec![]` for list literals, never `[T; N]` — array literals do not coerce to `&Vec<T>` parameters | depyler DEPYLER-0780 | array/collection literals |
| Heterogeneous collections need a **wrapper enum**; there is no other encoding | depyler DEPYLER-1166 | C# `Dictionary<string, object>` and `object`-typed fields, which we have no answer for |
| **Do not use `std::collections::HashMap`** where iteration order is observable — SipHash gives a different order and thus behavioural diffs | Bun `PORTING.md` | any translated iteration over a dictionary |
| A GC/refcount handle stored in a heap struct is a **use-after-free**; roots must be stack-scanned or explicitly registered | Bun | if D1's object graph is ever revisited |
| `Weak<T>` assumes an `Rc`/`Arc` allocation header — do **not** map an intrusive back-reference to it | Bun | back-references between peripherals |
| Library models belong in **data**, not the compiler | c2rust, NullAway, j2objc, Bun | already our design; four independent confirmations |

## Two disciplines worth adopting

**Rule provenance.** depyler tags every rule with the ticket that caused it
(`DEPYLER-0780`). That distinguishes a rule written from first principles from
one written after something broke — and the second kind is much harder to
rediscover. Our rules carry a `note` explaining reasoning but nothing links to
the failure.

**Two marker classes.** Bun separates `TODO(port)` — "could not translate
confidently" — from `PERF(port)` — "works, but slow". Two different debts,
separately greppable, separately burned down. Our scorecard has one bucket.

## What did NOT transfer, and why

depyler's `expr_methods.rs` is largely Python stdlib mapping — `re`, `hashlib`,
`json`, `colorsys`, `base64`. That half is source-specific and worthless to us.

The split is reliable: **anything phrased as "Python X becomes Rust Y" is
source-side; anything phrased as "Rust rejects Z, emit W instead" is
target-side and transfers.** The second kind is where the compiler-shaped
bruises are, and it is the half worth mining from any translator targeting
Rust, in any language pair.
