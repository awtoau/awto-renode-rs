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
| exception filters (`catch … when`) | **0** | 0 | correctly not built. But the ingest should RECORD filter presence so a future corpus fails loudly — it does not. |
| `dynamic` | 3 | 90 | no handler and, worse, **no refusal note**. Every surveyed AOT C# compiler refuses `dynamic`; we have the precedent and never wrote it down. |
| operator overloading | 11 | ~76 | `op_Implicit`/`op_Explicit` dominate tree-wide (30/15) — user-defined conversions, the dangerous half. Unmeasured. |
| extension methods, general case | 220 | 567 | only LINQ is handled, via a marker match. |
| mutable statics | 6 | 34,886 raw | 741 of 769 were const-valued; six need `OnceLock`. |

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

## Blocked on an ingest gap, not on instance count

These are properties Roslyn exposes that `Walker.cs` does not read. Same class
as the nine already recorded in `csharp_core.json` under
`known_transpiler_bugs_fixed`, **none of which was a Roslyn limitation**.

1. **Parameter default VALUES.** `parameter.has_default` is a flag; the value is
   absent. `IParameterSymbol.ExplicitDefaultValue`. Blocks folding any
   constructor into `Default`, and blocks optional arguments entirely.
2. **Field initialisers.** Absent from the corpus completely — verified twice,
   independently. `private bool x = true;` is **indistinguishable from**
   `private bool x;`, which silently inverts the initial value.
   `IFieldInitializerOperation`. This is what still blocks
   `CortexM.pcNotInitialized`.
3. **`IUnaryOperation` has no `checked` flag.** Every Unary row's `detail` is
   empty where every Binary row carries one, so `operators.unary.Minus` cannot
   be routed to the runtime the way `Subtract` was — routing on an assumed
   context is a guess dressed as a mapping.
4. **Exception filter presence** — see above.

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
