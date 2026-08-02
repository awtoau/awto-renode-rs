# Runtime is the fourth layer

**Taken 2026-08-02.** A semantic that Rust does not have becomes a **tested
function in `src/csharp-rt/`**, and the rule emits a *call* to it. It does not
become a string template that spells the semantic out at every site.

## The three layers, and what was missing

CLAUDE.md declares three:

| what | where |
|---|---|
| extraction — reading what Roslyn exposes | transpiler source |
| language mapping — `ConditionalOr` → `\|\|` | data, `csharp_core.json` |
| project idioms — the register DSL | data, `rulesdb/rules/*.json` |

All three assume a mapping can be *written down as a template*. Most can. Some
cannot, and for those a template is not a simplification — it is a wrong answer
that compiles.

**The fourth layer is RUNTIME**: C# semantics with no Rust equivalent, written
once as ordinary Rust, tested once, and called.

## The evidence, all of it from this repo

- **`wrapping_*` was declared and never existed.** `csharp_core.json` recorded
  the overflow deviation and stated the mapping. The only occurrence of
  `wrapping_` under `scripts/` or `rulesdb/` was that sentence. A rule that
  spells a semantic out at every site has nowhere to put a test, so nothing
  noticed. `rt::checked_add(a, b)` has one definition and one test.
- **`OrderBy` maps to `{recv}`** — the receiver, unchanged. A sort that does not
  sort. It compiles, and it replays any trace that does not depend on ordering.
- **`First` maps to `{recv}.iter().next().unwrap()`.** C# throws
  `InvalidOperationException`; Rust panics. Under D4 those are not the same
  thing, and the difference is invisible in the template.
- **`Array2D<T>` is already this**, and nobody called it a layer. Rust has no
  rectangular array; `csharp-rt` has one, with tests. That worked.

## The rule

**A mapping belongs in the runtime when the semantic cannot be checked at the
call site.** Three tells, any one sufficient:

1. **It needs state or a data structure** — a multicast delegate list, a
   collection with C# ordering, a boxed value.
2. **It has an error mode** — C# throws where Rust panics or returns. The
   choice belongs in one place, not at 40 sites.
3. **It is spelled out rather than named.** If the template is more than a
   rename or a re-association of the same operation, it is an implementation,
   and an implementation wants a test.

Everything else stays a rule. `ConditionalOr` → `||` is a rename and must not
move.

## What this does not change

- **Rules are still the source code and the Rust is still a build artifact.**
  A runtime call is emitted by a rule; the rule is what a rule-set A/B moves.
- **`csharp-rt` still knows nothing about any corpus.** It is the C#-to-Rust
  analogue of IL2CPP's `libil2cpp`, not a Renode library. `check_layering.py`'s
  boundary applies.
- **Withholding still applies.** A semantic with no runtime function yet is a
  gap, not an approximation.

## Prior art, so this is not reinvented

`ccxt/ast-transpiler` (TypeScript → six languages including Rust) ships
`helpers/c#/helpers.cs`, 24 KB, for exactly this, and says why: *"Things like
falsy values, empty default objects, dynamic properties, different type
comparison, untyped arguments/return type, etc do not exist so I had to create a
set of wrappers that will emulate these features."* Its language mappings also
live in data — the fifth independent arrival at the `rulesdb` boundary.

IL2CPP ships `libil2cpp`, including Boehm libgc. Five of seven surveyed
C#-to-native pipelines kept a runtime. A multicast-delegate library exists in D,
which is an existence proof that C#'s combine/remove semantics are a component
rather than a rule.

See `docs/research/prior-art-2026-08-02.md`.

## What would overturn it

- A runtime function that cannot be written without knowing the corpus — that
  would mean the boundary is in the wrong place, not that the layer is wrong.
- Measurable cost: a call where an inline expression would do, in a hot path.
  Field reads are 0.34 ns against a ~409 ns per-access budget, so this is
  unlikely to bind, and it must be *measured* rather than assumed if claimed.
