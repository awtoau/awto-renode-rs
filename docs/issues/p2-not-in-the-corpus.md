TITLE: P2 — constructs deferred only because the corpus had no instance

Each of these was reached, reasoned about, and **not built for one reason
only: too few instances to justify a rule**. That reason is now weaker and in
some cases gone — the corpus is the whole Renode tree since the cut was
removed, so a count that was zero may not be.

Recorded together so the next reader sees a **decision** rather than an
oversight. Every one has its reasoning already written; none needs re-research.

**Re-count every number here against the current corpus before starting.** They
were taken against the 21,620-line cut; the corpus is now 448,375 lines.

## Deferred purely on instance count

| construct | cut count | tree count | where the reasoning is |
|---|---:|---:|---|
| `linq.Max/1`, `Min/1` — `.unwrap()` where C# throws | **0** | ? | `csharp_core.json` `unwrap_still_here_why`. Same error mode as `First`, which DID become a runtime function. A runtime function with no caller is the hand-written-peripheral mistake with the layers swapped — so it waits for an instance, not for an argument. |
| indexers | 2 | 33 | below the ≥3 threshold, so correctly a patch. Wants a `no_rust_form` note either way. |
| `params` | 19 | 72 | not handled, no rule, small. |
| optional / default arguments | 508 | 2,698 | ingested and **unconsumed**. Named arguments *are* handled; defaults are not. Blocked on the ingest gap below. |
| lifted operators (`Nullable<T>` operands) | 11 | ? | excluded deliberately — needs the D4 form before an arithmetic mapping means anything. |
| `IDisposable` / `using` | 3 | 215 | `Drop`, with two documented divergences. The existing `no_rust_form` refusal covers the TYPE, not the statement. **215 tree-wide is no longer a rounding error.** |
| `yield return` / `yield break` | 8 / 1 | 82 / 3 | Rust `gen` blocks are **still unstable** (rust-lang#117078), so the only stable option is an explicit state machine — which is what the C# compiler itself emits. Note it lowers BELOW `IOperation`, so it is a whole-method rewrite, not a rule. |
| `async` / `await` | **0** | 15 | correctly deferred. **No prior art exists** on translating a language's async to Rust's, and no published rejection either. Picking an executor is a whole-program decision of D1–D4 weight. |
| exception filters (`catch … when`) | **0** | **5** | the tree count was never re-taken and is not 0. The ingest now records filter presence on all 268 catch clauses, so the five are visible instead of silently translatable as an `if` at the top of the handler. Still not built — but now it can refuse rather than guess. |
| `dynamic` | 3 | 90 | no handler and, worse, **no refusal note**. Every surveyed AOT C# compiler refuses `dynamic`; we have the precedent and never wrote it down. |
| operator overloading | 11 | ~76 | `op_Implicit`/`op_Explicit` dominate tree-wide (30/15) — user-defined conversions, the dangerous half. Unmeasured. |
| extension methods, general case | 220 | 567 | only LINQ is handled, via a marker match. |
| mutable statics | 6 | 34,886 raw | Reclassified by #58: 34,600 const-valued, 222 `static readonly`, **29** written outside `.cctor`, 2 `.cctor`-only, and 33 with no recorded write. A general guard now refuses mutable-static methods until runtime `OnceLock`/lock storage exists; see `0-status-58.md`. |

## Justified as runtime, deliberately not built

**Multicast delegates and events.** 206 `Invoke` + 8 `EventAssignment` + 14
`EventReference`. Meets all three tells of `docs/decisions/runtime-is-the-fourth-layer.md`:
the list is state, a null invoke throws, and the template spells the operation
out rather than naming it. Not built because changing the field representation
reaches `emit.py`'s constructor path and `object_graph.py`.

A D library already replicates C# multicast combine/remove semantics — an
existence proof that this is a **component**, not a rule.

**`Queue.Dequeue` / `.Peek`.** The panic is faithful; only the *message*
differs. Recorded to move together with `First` when D4 lands.

## Blocked on an ingest gap, not on instance count — CLOSED

All four were properties Roslyn exposes that `Walker.cs` did not read. Same
class as the nine already recorded in `csharp_core.json` under
`known_transpiler_bugs_fixed`, **none of which was a Roslyn limitation**, and
these four were not either. Each is now recorded there, and each has a count in
`scripts/check_ingest.py` so losing it again moves a number.

| gap | Roslyn property | corpus before | after |
|---|---|---:|---:|
| field / property / event initialisers | `GetOperation(EqualsValueClauseSyntax)` | 0 | 1,414 initialisers, 30,719 operation nodes |
| parameter default VALUES | `IParameterSymbol.ExplicitDefaultValue` | flag only | 1,741 of 2,698 carry a value |
| unary checked-ness | `IUnaryOperation.IsChecked` | 0 of 4,360 | 4,360 of 4,360 |
| exception filter presence | `ICatchClauseOperation.Filter` | 0 of 268 | 268 of 268, five of them true |

Consuming them is separate work and is not done: optional arguments, folding a
constructor into `Default`, routing unary minus to the runtime, and refusing a
`when` filter are all still unbuilt. The corpus can now answer the questions
they ask, which it could not before.

**The first attempt at the initialisers was reverted for not reproducing, and
the walker was not the reason.** The measuring run went through
`dotnet run --no-build`, which executes whatever is in `bin/` — so it walked
with the previous binary and honestly reported zero. That branch's `Walker.cs`,
rebuilt from source, produces 30,139 field-attached operations. Both halves are
now closed: `check_determinism.py` and `check_breadth.py` build first, and
`Ingest.cs` counts and names every row the write discards instead of
`continue`-ing past it.

## Latent, found and not fixed

- **`format_strings.specs` has no default-deny.** An unknown spec passes
  through and produces an **invalid Rust format string** — a compile error, not
  a wrong value. Every spec in the cut is `X`/`x`, so it is unreachable today.
- **`sub_blocks`**: does not detect a register-bearing child in a `List<>` or
  `Dictionary<>` and emits **no gap** when it declines; `const_under` returns
  the first constant ignoring the operator above it, so `Range(0, N/2)` would
  silently yield `N`; a non-zero `Range` start is discarded.

## Acceptance

- Every count above re-taken against the current corpus, and the table updated
- Anything now above the ≥3 threshold either implemented or given a recorded
  refusal with a reason
- The four ingest gaps filed against the frontend rather than worked around
- Nothing here left in the state that prompted this issue: reasoned about,
  correct, and invisible
