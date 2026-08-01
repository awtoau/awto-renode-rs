# Nullability: which C# references become `Option<T>`

Research for issue #38. Every claim about an external tool has a link; every
claim about this corpus has a query you can re-run.

**Summary.** Roslyn's `NullableFlowState` is *not* usable on this corpus, and
the reason is measured rather than assumed — see §3, where every `?.` receiver
in real Renode source reports `NotNull`, in all three nullable-context settings
and with the `run-nullable-analysis=always` override on. The workable approach
is the one `c2rust-analyze` already uses for C pointers and NullAway runs in
production for Java: **assume non-null, and demote to `Option<T>` only where the
corpus itself provides evidence of null.** On the f427 cut that promotes 41 of
1,031 reference-typed members (4.0%), which is the difference between a
readable translation and an unreadable one. Its failure mode is stated in §7
and it is real: null evidence is sparse and non-redundant — 12 of the 17 `?.`
receivers have no *other* null evidence anywhere in the cut — so a
genuinely-nullable reference with no syntactic tell is silently translated as
non-nullable.

**Sources.** Six, all quoted from primary source: `c2rust-analyze` (§4a),
Kotlin's J2K converter (§4b), NullAway (§4c), Kotlin platform types (§5a),
Swift SE-0054 and Apple's audited regions (§5b), and Roslyn / the C# 8 spec
(§3, §5c). Plus original measurement against `rulesdb/patterns.db` and a Roslyn
harness run over real Renode source.

---

## 1. What the question actually is

C# lets any reference be null. Renode is *null-oblivious*: it carries no
nullable-reference annotations at all.

    $ grep -rl "#nullable" $RENODE_SRC/src --include=*.cs | wc -l
    0
    $ grep -rn "<Nullable>" $RENODE_SRC --include=*.csproj --include=*.props
    tools/models_analyzer/ModelsAnalyzer/Utils/Utils.csproj:6:    <Nullable>enable</Nullable>
    tools/models_analyzer/ModelsAnalyzer/Runner/Runner.csproj:7:    <Nullable>enable</Nullable>
    tools/models_analyzer/ModelsAnalyzer/Analyzers/Analyzers.csproj:8:    <Nullable>enable</Nullable>

Three hits, all in a separate analyser tool, none in the emulator. The
translated cut is 100% unannotated.

So a *sound* translation would wrap every reference-typed field, parameter,
local and return in `Option<T>` — on top of D1's `Rc<RefCell<T>>`, giving
`Option<Rc<RefCell<T>>>` for 1,031 members. That is unreadable, and it makes
every field access a match. Meanwhile `x?.Foo()` has short-circuit semantics we
cannot drop.

### Correcting the framing

The issue describes `?.` as "the single construct blocking the most work". The
census does not support that as stated:

    $ python3 scripts/gap_census.py --blocking

    gap category                             count  share
    null safety (?. and ??)                      7   1.7%

    ROOT CAUSES, ranked by gaps blocked
    type  IMachine                                      10
    type  IGPIO>                                         8
    construct  CompoundAssignment                        8
    construct  Throw                                     7
    type  T                                              7
    construct  ConditionalAccess (?.)                    7    <-- joint 4th
    type  IBusController                                 7

`?.` is joint fourth, not first. **But** the nullability *family* — `?.` plus
every `Nullable<T>` type that has no Rust mapping — is the largest single theme:

| root cause | blocks |
|---|---|
| `construct  ConditionalAccess (?.)` | 7 |
| `type  int?` | 3 |
| `type  uint?` | 2 |
| `type  Func<long, T, T?>` | 2 |
| `type  Func<long, T, T?>>` | 2 |
| **total** | **16 of 180 direct gaps (8.9%)** |

ahead of `IMachine` at 10. That reframing matters for the work estimate in §8:
the `Nullable<T>` half is nearly free and should be done in the same change.

---

## 2. Corpus evidence (measured)

All against `rulesdb/patterns.db`, run 1, config `f427`, Renode `dc52b24c`.

    SELECT COUNT(*) FROM operation WHERE kind='ConditionalAccess';   -->  23
    SELECT COUNT(*) FROM operation WHERE kind='Coalesce';            -->  30
    SELECT COUNT(*) FROM operation WHERE kind='CoalesceAssignment';  -->   0

Both headline numbers overstate the reference-nullability problem, and it is
worth being precise about why.

### `??` is mostly not about references at all

Splitting the 30 `Coalesce` sites by whether the left operand is a
`Nullable<T>` *value* type or a reference type:

| left operand | count |
|---|---|
| `Nullable<T>` value type (`int?`, `uint?`, `byte?`, `bool?`, `T?`) | 22 |
| reference type (`string`, `System.Type`) | 8 |

`Nullable<T>` is *already* `Option<T>`. Those 22 need a type mapping, not a
nullability analysis. Only **8** `??` sites involve a reference.

### `?.` breaks down into two idioms

Of the 23 `ConditionalAccess` sites, on 17 distinct receivers:

| receiver shape | sites |
|---|---|
| delegate or event, i.e. `handler?.Invoke(...)` | 6 |
| optional collaborator object field (`nvic`, `child`, `cpu`, `logAggregatorTimer`, `idleLineDetectedCancellationTokenSrc`) | 14 |
| local / `params` array | 3 |

The 6 delegate/event cases are **already decided**: PLAN.md's mapping table
gives `event` / `Action<T>` → `Option<Box<dyn Fn>>` for the single-subscriber
case. They need no new analysis, only the `?.` emission.

### Null literals

197 `null` literals in the cut. Their effective parent operation, skipping
`Conversion` wrappers:

| context | count |
|---|---|
| `Binary` (`== null` / `!= null`) | 111 |
| `Conditional` (`c ? x : null`) | 27 |
| `SimpleAssignment` (`x = null`) | 21 |
| `Argument` (`f(null)`) | 21 |
| `VariableInitializer` (`T x = null`) | 10 |
| `Return` (`return null`) | 7 |

Split of the comparisons: 62 `Equals`, 49 `NotEquals`, over **85 distinct
symbols**.

There are **no `is null` / `is not null` patterns** in the cut — all 14
`IsPattern` operations are `DeclarationPattern` (`x is Foo f`). So the evidence
rule needs to recognise five shapes, not six.

### The headline number

Taking "the corpus proves this can be null" as: compared to `null`, assigned
`null`, receiver of `?.`, or left of `??`:

| | |
|---|---|
| distinct symbols with null evidence (fields, properties, params, locals, events) | **126** |
| of those, type members (fields / properties / events) | **41** |
| reference-typed field / property / event members declared in the cut | **1,031** |
| **share of reference-typed members needing `Option<T>`** | **4.0%** |

An independent syntactic pass over 40 real source files (`STM32*`, `CortexM`,
`NVIC`) via Roslyn gave the same order of magnitude: 10 of 607 reference-typed
fields, **1.6%**.

That is the entire argument for the middle path. A blanket `Option<T>` would
wrap 1,031 members to catch 41.

### Propagation buys almost nothing

Seeding from direct evidence and then propagating through simple assignments
(`a = b` where `b` is known-nullable) to a fixpoint:

    seed (direct syntactic evidence): 126
    after assignment-flow fixpoint:   133  (2 iterations, +7)

+5.6%. Worth adding because it is ten lines, but it is not the interesting part.

### The cost the recommendation buys

Symbols in the evidence set are also dereferenced **without** a guard, 270
times across 65 symbols. Each becomes an `.expect(...)`:

    129  Antmicro.Renode.Peripherals.IRQControllers.NVIC.cpu
     15  result
     15  Antmicro.Renode.Peripherals.Memory.MappedMemory.segments
     10  System.Type t
      6  Antmicro.Renode.Peripherals.CPU.CortexM.nvic
      ...

`NVIC.cpu` alone accounts for 129. This is the ugliness, and it is
concentrated. §7 says why we take it anyway.

---

## 3. THE CRUX: what Roslyn actually reports on unannotated code

**Answer: nothing usable, and forcing it on produces a uniform lie.** This was
tested, not reasoned about.

The scratch harness is `CSharpCompilation.Create` over (a) a synthetic snippet
and (b) 40 real Renode files, reporting `TypeInfo.Nullability` and symbol-level
`NullableAnnotation` under both `NullableContextOptions.Disable` and
`.Enable`. Roslyn 4.11.0, .NET 9.

### 3a. With the nullable context off — which is how Renode compiles

Every single expression reports `None` for both properties:

    EXPERIMENT 1 — NullableContextOptions.Disable

    field collaborator     Type.NullableAnnotation=None   Symbol.NullableAnnotation=None
    field name             Type.NullableAnnotation=None   Symbol.NullableAnnotation=None
    param arg              Type.NullableAnnotation=None   Symbol.NullableAnnotation=None

    L13  collaborator     Annotation=None   FlowState=None
    L14  Fired            Annotation=None   FlowState=None
    L16  collaborator     Annotation=None   FlowState=None     <-- after `!= null` guard
    L19  local            Annotation=None   FlowState=None     <-- assigned `null` one line up

Not "probably nullable". Not a conservative default. **`None` is a sentinel
meaning the analysis did not run.** The API docs are explicit:

> **`NullableFlowState.None` (0)** — "Syntax is not an expression, or was not
> analyzed."
> — <https://learn.microsoft.com/en-us/dotnet/api/microsoft.codeanalysis.nullableflowstate>

> **`NullableAnnotation.None` (0)** — "The expression has not been analyzed, or
> the syntax is not an expression (such as a statement). There are a few
> different reasons the expression could have not been analyzed: 1. The symbol
> producing the expression comes from a method that has not been annotated,
> such as invoking a C# 7.3 or earlier method, or a method in this compilation
> that is in a disabled context. **2. Nullable is completely disabled in this
> compilation.**"
> — <https://learn.microsoft.com/en-us/dotnet/api/microsoft.codeanalysis.nullableannotation>

Case 2 is us. So the premise in the issue — that Roslyn exposes a usable
`NullableFlowState` on unannotated code — is **false**. It exposes the
*property*; the property is uniformly the "did not run" value.

### 3b. Forcing the context on, without touching the source

You can enable nullable analysis for a corpus you do not own, by passing
`nullableContextOptions: NullableContextOptions.Enable` to
`CSharpCompilationOptions`. No `#nullable enable` and no `.csproj` edit. Roslyn
then genuinely runs the flow analysis — and the answers are worse than useless,
because C# 8's rule is that an *unannotated* declaration in an *enabled*
context means **non-nullable**:

    EXPERIMENT 1 — NullableContextOptions.Enable

    field collaborator     Type.NullableAnnotation=NotAnnotated
    param arg              Type.NullableAnnotation=NotAnnotated

    L13  collaborator     Annotation=NotAnnotated  FlowState=NotNull   <-- receiver of `collaborator?.Run(...)`
    L14  Fired            Annotation=NotAnnotated  FlowState=NotNull   <-- receiver of `Fired?.Invoke(1)`
    L16  collaborator     Annotation=Annotated     FlowState=MaybeNull <-- narrowed by the `!= null` test
    L19  local            Annotation=Annotated     FlowState=MaybeNull <-- narrowed by `= null`

Line 13 is the whole problem in one line. The author wrote `?.` *because the
field can be null*, and Roslyn reports the receiver as `NotNull`.

At corpus scale this is not an edge case, it is the rule. Over 40 real Renode
files with the context forced on:

    ConditionalAccess sites  : 22 (receiver type resolved: 22)
      receiver FlowState MaybeNull : 0
      receiver FlowState NotNull   : 22
      receiver FlowState None      : 0

    reference-typed identifier references examined: 3837
      Annotation NotAnnotated : 3654   (95.2%)
      Annotation Annotated    :   49
      Annotation None         :  134
      FlowState  NotNull      : 3672   (95.7%)
      FlowState  MaybeNull    :   84
      FlowState  None         :   81

**All 22 `?.` receivers report `NotNull`. Zero report `MaybeNull`.** The one
construct we need the analysis for is the one it gets wrong 100% of the time.

The 84 `MaybeNull` results are not discoveries either — they come from *local
narrowing* after a null test or a null assignment, which is information the
corpus already states syntactically and which we can extract without Roslyn.

### 3c. What forcing it on *does* give you: bad diagnostics

Nullable diagnostics over the same 40 files, context forced on:

    CS8618 x88    Non-nullable field must contain a non-null value when exiting constructor
    CS8619 x6     Nullability of reference types in value doesn't match target type
    CS8601 x4     Possible null reference assignment
    CS8602 x3     Dereference of a possibly null reference
    CS8625 x1     Cannot convert null literal to non-nullable reference type
    CS8600 x1     Converting null literal or possible null value to non-nullable type
    CS8605 x1     Unboxing a possibly null value

88 of 104 are CS8618 — "you did not initialise this field in the constructor" —
which fires for nearly every field in a null-oblivious codebase and carries no
information about whether the field is ever *observed* null. Signal-to-noise is
about 1 in 6, and CS8600/CS8601/CS8625 are exactly the sites the syntactic
evidence rule finds anyway.

### 3d. The one genuinely useful thing Roslyn gives us for free

**Symbol-level annotations on *referenced* assemblies are correct regardless of
the consuming compilation's nullable context.** The BCL is annotated; Renode is
not; and the annotation survives the boundary:

    (b) ANNOTATED BCL BOUNDARY, consumer context = Disable

    GetEntryAssembly         ReturnNullableAnnotation=Annotated     expr Annotation=None  FlowState=None
    Type.GetType             ReturnNullableAnnotation=Annotated     expr Annotation=None  FlowState=None
    Dictionary.TryGetValue   ReturnNullableAnnotation=NotAnnotated  expr Annotation=None  FlowState=None
    GetEnvironmentVariable   ReturnNullableAnnotation=Annotated     expr Annotation=None  FlowState=None

The *expression-level* `NullabilityInfo` is `None`, as in 3a. But
`IMethodSymbol.ReturnNullableAnnotation` is right: `Type.GetType` is
`Annotated` (can return null), `TryGetValue` is `NotAnnotated`. Reading that
property costs nothing and needs no context change — it just is not being read
today. See §8; it is the one ingest change worth requesting.

### 3e. The last escape hatch: `run-nullable-analysis=always`

Roslyn gates the flow analysis for performance. `CSharpCompilation.cs`:

```csharp
internal bool IsNullableAnalysisEnabledIn(CSharpSyntaxTree tree, TextSpan span)
{
    return GetNullableAnalysisValue() ??
        tree.IsNullableAnalysisEnabled(span) ??
        (Options.NullableContextOptions & NullableContextOptions.Warnings) != 0;
}
```
<https://github.com/dotnet/roslyn/blob/main/src/Compilers/CSharp/Portable/Compilation/CSharpCompilation.cs>

`GetNullableAnalysisValue()` reads the compiler feature flag
`run-nullable-analysis`, which can force the `NullableWalker` to run
**regardless of the nullable context** — set via
`parseOptions.WithFeatures([new("run-nullable-analysis", "always")])`. The perf
motivation is public: dotnet/roslyn#70609 reports semantic classification going
from "an average of 372ms reduced to 132ms" with nullable analysis skipped.

This is the most promising-sounding lever, so it was tested too. It does work —
the walker runs and `FlowState` becomes real while `Annotation` stays `None`,
correctly preserving obliviousness:

    run-nullable-analysis=always, NullableContextOptions.Disable

    L9   collaborator   Annotation=None       FlowState=NotNull    <-- `collaborator?.Run(arg)`
    L10  Fired          Annotation=None       FlowState=NotNull    <-- `Fired?.Invoke(1)`
    L11  collaborator   Annotation=Annotated  FlowState=MaybeNull  <-- narrowed by `!= null`
    L14  local          Annotation=Annotated  FlowState=MaybeNull  <-- narrowed by `= null`

**And it does not change the answer.** On the real corpus, across every
combination:

    CORPUS ?. receivers — run-nullable-analysis=always
      NullableContextOptions.Disable      total 22   MaybeNull 0   NotNull 22
      NullableContextOptions.Annotations  total 22   MaybeNull 0   NotNull 22
      NullableContextOptions.Enable       total 22   MaybeNull 0   NotNull 22

Twenty-two out of twenty-two, three ways. The flow state is derived *from* the
declared annotations, and an oblivious declaration seeds the walker as non-null.
Forcing the analysis to run cannot recover information the declarations never
carried.

The one incidental gain: with `always` + `Disable`, `Annotation=None` still
distinguishes an oblivious declaration from an annotated one, which
`NullableContextOptions.Enable` destroys by rewriting everything to
`NotAnnotated`. If we ever *do* want Roslyn flow state, that is the
configuration to use. It is not enough to build on.

### Verdict on the crux

| question | answer |
|---|---|
| Does Roslyn expose `NullableFlowState` on unannotated code? | The property exists and always reads `None`. |
| Is `None` a conservative default? | No. It is documented as "was not analyzed". C# calls this state *oblivious* and gives it a fourth position in the type system. |
| Does Roslyn even run the analysis? | Not by default on disabled code — it is gated for performance (dotnet/roslyn#70609). |
| Can we force it? | Yes, two ways: `NullableContextOptions.Enable`, or the `run-nullable-analysis=always` feature flag. |
| Is the result trustworthy? | **No.** Both levers seed oblivious declarations as non-null, so `?.` receivers come back `NotNull` — 22 of 22, in all three context settings, with the force flag on. |
| Is *any* of it useful? | Two things: intra-method narrowing (which we can derive ourselves from the same syntax), and `NullableAnnotation` on symbols from *annotated referenced assemblies*, which is correct and free. |

Reproduce with the harness in the scratchpad (not committed — it is a
throwaway; the corpus queries in §2 are the durable evidence).

---

## 4. What existing translators do

### 4a. `c2rust-analyze` — the closest analogue, and it does exactly this

c2rust's static-analysis rewriter faces the identical problem one language
over: C pointers are all nullable, C has no annotations, and the target is
Rust. Its answer is a **permission lattice with a `NON_NULL` bit that is
assumed and then dropped on evidence**.

<https://github.com/immunant/c2rust/blob/master/c2rust-analyze/src/context.rs>

```rust
bitflags! {
    /// Permissions are created such that we allow dropping permissions in any assignment.
    /// This means removing a permission from a pointer's [`PermissionSet`]
    /// must allow the pointer to take on more values, not restrict it to fewer values.
    pub struct PermissionSet: u16 {
        ...
        /// This pointer is non-null.
        ///
        /// [`NON_NULL`] is set (or not) when the pointer is created,
        /// and it flows forward along dataflow edges.
        ///
        /// The following should be set to [`NON_NULL`]:
        /// * the results of [`Rvalue::Ref`] and [`Rvalue::AddressOf`]
        /// * the result of a known function like [`_.offset`] that never returns null pointers
        ///
        /// The following should not be set to [`NON_NULL`]:
        /// * [`core::ptr::null`]
        /// * [`core::ptr::null_mut`]
        /// ...
        ///
        /// [`NON_NULL`] pointers will become references, e.x. `&T`.\
        /// Non-[`NON_NULL`] pointers will become [`Option<&T>`].
        ///
        /// Casts/transitions from [`NON_NULL`] to non-[`NON_NULL`] will become [`Some(_)`].\
        /// Casts/transitions from non-[`NON_NULL`] to [`NON_NULL`] will become [`_.unwrap()`].
        ///
        /// [`_.is_null()`] on a [`NON_NULL`] pointer will become [`false`].\
        /// [`_.is_null()`] on a non-[`NON_NULL`] pointer will become [`_.is_some()`].
        const NON_NULL = 0x0080;
        ...
    }
}
```

Read that rewrite table against our problem and it is line-for-line what we
need:

| c2rust-analyze | this project |
|---|---|
| `NON_NULL` pointer → `&T` | non-nullable reference → `Rc<RefCell<T>>` (D1) |
| non-`NON_NULL` → `Option<&T>` | nullable reference → `Option<Rc<RefCell<T>>>` (D1, already written) |
| `_.is_null()` on non-`NON_NULL` → `_.is_some()` | `x != null` → `x.is_some()` |
| `NON_NULL` → non-`NON_NULL` becomes `Some(_)` | assigning a known value into an `Option` field |
| non-`NON_NULL` → `NON_NULL` becomes `_.unwrap()` | unguarded deref of an evidence-nullable field |

This is a real, shipping tool making the same decision, with the same
mechanism, for the same target language. It is the single strongest argument
for the recommendation in §7.

**What it gets wrong / gives up**, from its own README
(<https://github.com/immunant/c2rust/blob/master/c2rust-analyze/README.md>):

> "`c2rust-analyze` is currently at a prototype stage..."
>
> "The automated safety rewrites in `c2rust-analyze` only apply to a small
> subset of unsafe Rust code. When `c2rust-analyze` encounters unsupported
> code, it will report an error and skip rewriting the function in question."
>
> "`c2rust-analyze` may take a long time to run even on medium-sized
> codebases. In particular, running the Polonius analysis on very large
> functions may take several minutes..."

Three things to take from that. First, it **withholds** on code it cannot
handle rather than guessing — the same discipline as
`docs/agents/transpiler-work-protocol.md`. Second, it is a *whole-program
dataflow* analysis (Polonius-backed) and it is slow; our evidence rule is a
single pass over an already-built table and runs in under a second, because it
is much weaker. Third, "prototype stage" after years of work is the honest
signal about how hard the sound version is.

Note also the direction of its unsoundness: `NON_NULL` is assumed and dropped
on evidence, so a pointer that is null only through a path the analysis cannot
see stays `NON_NULL` and the rewrite inserts a dereference that can fault. That
is precisely our failure mode in §7, and it is accepted by a production tool.

### 4b. Kotlin's J2K converter — the closest precedent, and it refuses the third state

J2K converts unannotated Java to Kotlin, which is the same job as ours with a
different target. Two facts about it matter.

**It runs a real iterative dataflow inference**, not a syntactic default.
`J2KNullityInferrer.java` in `JetBrains/intellij-community`, under
`plugins/kotlin/j2k/k2/src/org/jetbrains/kotlin/j2k/`:

```java
private void inferNullabilityIteratively(@NotNull PsiFile file) {
    int prevNumAnnotationsAdded;
    int pass = 0;
    do {
        final NullityInferrerVisitor visitor = new NullityInferrerVisitor();
        prevNumAnnotationsAdded = numAnnotationsAdded;
        file.accept(visitor);
        pass++;
    }
    while (prevNumAnnotationsAdded < numAnnotationsAdded && pass < MAX_PASSES);
}
```

Its inputs are explicit `@Nullable`/`@NotNull` annotations *plus* IntelliJ's
Java dataflow (`CommonDataflow`, `DfaNullability`, `DfaUtil.inferMethodNullability`),
with whole-file `ReferencesSearch` and `OverridingMethodsSearch`.

**And its lattice has three values, where the third resolves to nullable.**
[`Nullability.kt`](https://github.com/JetBrains/intellij-community/blob/master/plugins/kotlin/j2k/k2/src/org/jetbrains/kotlin/j2k/Nullability.kt):

```kotlin
enum class Nullability {
    Nullable,
    NotNull,
    Default
}
```

`printing/JKPrinter.kt` decides what `Default` prints as, and says why:

```kotlin
// we print undefined types as nullable because we need smartcast to work in nullability inference in post-processing
if (type !is JKWildCardType
    && (type.nullability == Nullability.Default
            && owner?.safeAs<JKLambdaExpression>()?.functionalType?.type != type
            || type.nullability == Nullability.Nullable)
) {
    this.print("?")
}
```

So: emit `T` only where not-null is *proved*; emit `T?` for proven-nullable
**and for unknown**; then narrow `T?` back to `T` in a post-processing pass
(`conversions/NullabilityConversion.kt`) that has Kotlin smart-casts available.

**This is the opposite default from our recommendation, and the difference is
the target language, not the principle.** J2K resolves unknown toward the side
the compiler can still *check* — Kotlin `T?` is safe and noisy, and a later
pass tightens it. In Rust there is no later pass with more information, and
`Option<T>` is not merely noisy: at 1,031 members it destroys the line-by-line
comparability against the C# that this project depends on for review. We are
choosing readability over conservatism where J2K chose the reverse, and §7
states the price.

**What J2K gets wrong / gives up:** it produces code with far more `?` and `!!`
than a human would write, and its own docs treat the output as a starting point
requiring manual cleanup. The narrowing pass is best-effort. And the inference
is whole-*file*, so nullability facts do not cross file boundaries — the same
limitation our cut-scoped evidence has.

### 4c. NullAway — production null checking, and it defaults exactly the way we propose

NullAway is Uber's Java null checker, run on every build across Uber's
codebase. Two things it says are directly load-bearing for §7.

**It assumes unannotated means non-null.**
<https://github.com/uber/NullAway/wiki/How-NullAway-Works>:

> "**By default, NullAway assumes unannotated methods return `@NonNull`.**
> However, the `LibraryModelsHandler` changes that value for those methods for
> which an explicit library model exists which shows the return method to be
> `@Nullable`…"

That is our recommendation, running in production at scale: optimistic default,
with an explicit override list for the cases that are known to be nullable.
(Our override list is derived from corpus evidence rather than hand-maintained
models; §8 notes that annotated-BCL import would give us NullAway's
`LibraryModelsHandler` equivalent for free.)

**It says why it does not do whole-program inference.** From the same page,
about the Rx handler:

> "This is an example of handlers being used to add limited forms of
> inter-procedural inference, **which is prohibitively expensive in the general
> case.**"

**And it publishes a page titled "Deliberate Unsoundness".**
<https://github.com/uber/NullAway/wiki/Deliberate-Unsoundness>:

> "NullAway **deliberately eschews fully sound analysis** in certain cases for
> simplicity and a reduced annotation burden. This page documents some known
> false negatives that come from this design decision."

Five documented classes of missed NPE: zero-argument methods assumed pure and
deterministic; nullness facts not invalidated on reassignment; map lookups
treated optimistically after `containsKey`; array element reads assumed
non-null outside JSpecify mode; and no soundness under multithreading. It
closes by pointing elsewhere:

> "The Checker Framework Nullness Checker performs more sound checking for
> nullness issues, particularly around pure methods and maps. **If you require
> deeper verification, consider using that checker.**"

The README is equally direct about the trade:

> "NullAway is also *practical*: **it does not prevent all possible NPEs in
> your code**, but it catches most of the NPEs we have observed in production
> while imposing a reasonable annotation burden, giving a great "bang for your
> buck.""
> — <https://github.com/uber/NullAway/blob/master/README.md>

**What it gets wrong:** all five classes above, by choice, plus the base
assumption itself — NullAway does not *infer* nullability, it *checks*
hand-written `@Nullable` annotations. The inference tool built on top of it,
`NullAwayAnnotator`, is instructive about how far inference gets. Its own
worked example
(<https://github.com/nimakarimipour/NullAwayAnnotator/blob/master/README.md>)
shows it resolving a field it *cannot* type consistently by suppressing the
error rather than solving it:

```java
@Nullable Object f1 = null;
@SuppressWarnings("NullAway") Object f2 = null; // inferred to be @Nonnull, and null assignment is suppressed.
```

Its objective function is "minimise reported errors", not "be correct" — so
where the two diverge it papers over the site. A translator cannot do that:
suppressing a warning leaves working Java, whereas mistyping a field leaves
Rust that behaves differently. This is the argument for §7's requirement that
unresolvable sites are **withheld and reported**, never suppressed.

---

## 5. Retrofitting null-safety onto unannotated code

All three mainstream attempts shipped a **third state** for "nobody said", and
all three found it expensive. None of them is available to us, because Rust has
no type that is sometimes checked. The useful part is what they did *instead*.

### 5a. Kotlin platform types (`T!`)

<https://kotlinlang.org/docs/java-interop.html#null-safety-and-platform-types>

> "Any reference in Java may be `null`, which makes Kotlin's requirements of
> strict null-safety impractical for objects coming from Java. Types of Java
> declarations are treated in Kotlin as non-denotable and called **platform
> types**. […] **Null-checks are relaxed for such types, so that safety
> guarantees for them are the same as in Java.**"

> "When you call methods on variables of platform types, Kotlin **does not
> issue nullability errors at compile time, but the call may fail at runtime**,
> because of a null-pointer exception or an assertion that Kotlin generates to
> prevent nulls from propagating:
> ```kotlin
> item.substring(1) // allowed, throws an exception if item == null
> ```"

Notation, from the same page: "`T!` means "`T` or `T?`"".

The spec makes it a *flexible type*
(<https://kotlinlang.org/spec/type-system.html#flexible-types>):

> "A flexible type represents a range of possible types between type L (lower
> bound) and type U (upper bound), written as **(L..U)**. Flexible types are
> **non-denotable**."
>
> "…**thus making the substitution possibly unsafe, which is why Kotlin
> generates dynamic assertions when it is impossible to prove statically the
> safety of flexible type use**."

**What it gets wrong.** The failure is deferred to runtime by design — the docs
say so outright. The assertion boundary leaks: "sometimes this is impossible to
eliminate entirely, because of generics". Diagnostics are lost in both
directions — "The compiler won't highlight any redundant null checks"
(<https://kotlinlang.org/docs/java-to-kotlin-nullability-guide.html>). And the
type-system price is permanent: `String!` is formally `(String..String?)`,
which makes **type equivalence non-transitive** (`A ≡ (A..B)` and `B ≡ (A..B)`
but `A ≢ B`) — a complexity tax every Kotlin user pays for interop. The
tracking issue, YouTrack `KT-4850` "Platform types", has been **open since
2014**.

Kotlin's actual remedy was not to improve `T!` but to let the *Java* side opt
whole scopes into non-null: JSpecify `@NullMarked`
(<https://kotlinlang.org/docs/java-interop.html#jspecify-support>) and JSR-305
`@TypeQualifierDefault`. Note also that Kotlin ships a severity dial
(`-Xjspecify-annotations=strict|warn|ignore`) *separate* from the annotation,
where only `strict` actually changes the types.

### 5b. Swift implicitly-unwrapped optionals (`T!`)

Every unaudited Objective-C API was imported as `T!`. Apple's own explanation
(archived, as Apple no longer serves the page —
<https://web.archive.org/web/20190301000000/https://developer.apple.com/swift/blog/?id=25>):

> "in Swift there's a strong distinction between optional and non-optional
> references, e.g. `NSView` vs. `NSView?`, while Objective-C represents both of
> these two types as `NSView *`. **Because the Swift compiler can't be sure
> whether a particular `NSView *` is optional or not, the type is brought into
> Swift as an implicitly unwrapped optional, `NSView!`.**"

SE-0054 "Abolish ImplicitlyUnwrappedOptional type" (implemented, Swift 4.2) —
<https://github.com/swiftlang/swift-evolution/blob/main/proposals/0054-abolish-iuo.md>:

> "**However, IUOs are a transitional technology; they represent an easy way to
> work around un-annotated APIs, or the lack of language features that could
> more elegantly handle certain patterns of code. As such, we would like to
> limit their usage moving forward**… **Except for a few specific scenarios,
> optionals are always the safer bet**…"
>
> "…**put the Swift language on the path to removing implicitly unwrapped
> optionals from the system entirely**… **It also completely abolishes any
> notion of IUOs below the type-checker level of the compiler, which will
> substantially simplify the compiler implementation.**"

The fix was to demote IUO from a **type** to a **declaration attribute**:

> "**This model is more predictable because it prevents IUOs from propagating
> implicitly through the codebase, and converts them to strong optionals, the
> safer option, by default.**"
>
> "**Types with nested IUOs are no longer allowed. This includes types such as
> `[Int!]` and `(Int!, Int!)`.**"

And, under alternatives considered:

> "**Remove IUOs completely. Untenable due to the prevalence of deferred
> initialization and unannotated Objective-C API in today's Swift ecosystem.**"

**What it gets wrong.** Being a *type* meant it propagated silently through
code the importer never touched, including into nested positions. It leaked
below the type checker into every compiler pass. And once emitted at scale it
could not be removed — the transitional state became load-bearing.

**Apple's real answer was bulk annotation**, which is the part relevant to us:

> "To ease adoption of the new annotations, you can mark certain regions of your
> Objective-C header files as **audited for nullability. Within these regions,
> any simple pointer type will be assumed to be `nonnull`.**"

```objc
NS_ASSUME_NONNULL_BEGIN
@interface AAPLList : NSObject
- (nullable AAPLListItem *)itemWithName:(NSString *)name;
@property (copy, readonly) NSArray *allItems;
@end
NS_ASSUME_NONNULL_END
```

Critically, Apple documented **carve-outs** — the empirical list of positions
where "assume non-null" is wrong:

> "For safety, there are a few exceptions to this rule:
> - **`typedef` types don't usually have an inherent nullability**…
> - **More complex pointer types like `id *` must be explicitly annotated.**…
> - The particular type `NSError **` … is always assumed to be a nullable
>   pointer to a nullable `NSError` reference."

And the honest caveat about what the annotation buys:

> "**This also means that existing code will not catch incorrect passing of
> `nil` at runtime.**"
> "you should look at `nullable` and `nonnull` roughly the way you currently
> use assertions or exceptions: **violating the contract is a programmer
> error.**"

Our recommendation is `NS_ASSUME_NONNULL_BEGIN` for the whole corpus, with the
five evidence shapes of §6 playing the role of `nullable` annotations. The
lesson to actually take is the third one: **a bulk default needs a written list
of positions where it is known to be wrong.** §7's failure mode is our version
of that list, and it is currently shorter than Apple's — which should be read
as incompleteness, not as safety.

### 5c. C# 8's own migration

C# is the interesting case because it is the *same language as our corpus*, and
it named the third state instead of hiding it. The specification
(<https://github.com/dotnet/csharplang/blob/main/proposals/csharp-8.0/nullable-reference-types-specification.md>):

> "A given type can have one of **four** nullabilities: ***Oblivious*,
> *nonnullable*, *nullable* and *unknown*.**"
>
> "***Oblivious* and *nonnullable* types can be dereferenced or assigned without
> warnings.** Values of *nullable* and *unknown* types, however, are
> "*null-yielding*"…"
>
> "- An **unannotated reference type `C` in a *disabled* annotation context is
> *oblivious***
> - An unannotated reference type `C` in an *enabled* annotation context is
> *nonnullable*"

That second pair is exactly the trap in §3b: flipping the context does not
discover anything, it **redefines every unannotated declaration from oblivious
to non-nullable**.

And obliviousness is sticky:

> "**Whether a given reference type `C` in source code is interpreted as
> oblivious or nonnullable depends on the annotation context of that source
> code. But once established, it is considered part of that type, and "travels
> with it" e.g. during substitution of generic type arguments. It is as if
> there is an annotation like `?` on the type, but invisible.**"

Roslyn's design doc opens with the same three-way split
(<https://github.com/dotnet/roslyn/blob/main/docs/features/nullable-reference-types.md>):

> "**Reference types may be nullable, non-nullable, or null-oblivious
> (abbreviated here as `?`, `!`, and `~`).**"

In metadata it is three-valued on the wire
(<https://github.com/dotnet/roslyn/blob/main/docs/features/nullable-metadata.md>):

> "Each type reference in metadata may have an associated `NullableAttribute`
> with a `byte[]` where each `byte` represents nullability: **0 for oblivious,
> 1 for not annotated, and 2 for annotated.**"

**Microsoft's recommended migration**
(<https://learn.microsoft.com/en-us/dotnet/csharp/nullable-migration-strategies>)
is a two-axis dial — annotations and warnings are independent — and the
guidance is explicitly about *sequencing*, not about inference:

> "**Migration is about *sequencing* the work**: choosing a default context,
> exposing warnings file by file or section by section, and converging on
> `<Nullable>enable</Nullable>` for the whole project."
>
> "1. Pick a file. **Start with the deepest leaf types in your dependency
> graph, then move outward. Annotating a type causes new warnings in its
> callers, so working bottom-up minimizes rework.**"
>
> "**One phase changes only behavior, and the other changes only types.** The
> disadvantage is that **you visit each file twice.**"

**What C# 8 gets wrong.** The default is opt-out silence: "If no project level
settings are provided the default is for both contexts to be *disabled*."
Obliviousness is infectious under covariant type merging, so untouched legacy
code launders itself through annotated code. `None` sits at value `0`, so
`default(NullabilityInfo)` and a genuine third state are the same bit pattern —
a consumer that forgets to check for `None` reads unanalysed code as data,
which is precisely the mistake this document exists to prevent. And the whole
analysis is skipped by default for performance (§3e).

Most importantly for us: **C#'s own answer is human annotation, file by file,
bottom-up, visiting each file twice.** Microsoft, with the compiler team and
the language spec on their side, did not propose inferring it. That is the
strongest available evidence that the sound automatic answer does not exist.

---

## 6. The defensible middle, stated precisely

**A reference becomes `Option<T>` if and only if the corpus provides evidence
that it can be null.** Evidence is one of five syntactic shapes, all already
present in the `operation` table:

| # | shape | corpus representation | sites in cut |
|---|---|---|---|
| 1 | `x == null` | `Binary` with `symbol='Equals'`, one operand a `Literal` with `const_value='null'` | 62 |
| 2 | `x != null` | same with `symbol='NotEquals'` | 49 |
| 3 | `x = null` | `SimpleAssignment` / `VariableInitializer` whose RHS is the null literal | 31 |
| 4 | `x?.M()` | `ConditionalAccess`, first child (receiver) | 23 |
| 5 | `x ?? d` | `Coalesce`, first child | 30 |

plus one closure step: if `a = b` and `b` is nullable, `a` is nullable
(+7 symbols, §2).

Everything else is non-nullable and gets the plain D1 mapping.

Three details make it faithful rather than merely convenient:

**`Nullable<T>` is separate and unconditional.** `int?`, `uint?`, `bool?`,
`T?` are `Option<T>` always, with no analysis, because C# already said so.
That is 22 of the 30 `??` sites and 5 of the 16 nullability root causes, and it
should land in the same change.

**Unguarded dereference of an evidence-nullable value becomes `.expect(...)`,
not a hoisted binding.** C# throws `NullReferenceException` at the *first*
dereference on the taken path; D4 already says a `NullReferenceException`
becomes a panic. Binding `let cpu = self.cpu.as_ref().expect("cpu");` at the
top of a method would be prettier and would move the panic earlier — to a path
where C# might never have thrown. Faithful-first says do not hoist. Record the
hoist as a candidate Stage-3 lift.

**`??` is lazy on the right.** C# does not evaluate the right operand unless
the left is null. `unwrap_or(rhs)` evaluates it always; `unwrap_or_else(|| rhs)`
does not. Four of the 8 reference-typed `??` sites have an *invocation* on the
right (`Misc.FormatWith(...)`), so this is not theoretical. The rule must emit
`unwrap_or_else`.

### Known carve-outs — where the default is known to be wrong

Apple's audited regions came with a documented list of positions where "assume
non-null" is unsafe (§5b), and NullAway publishes the same kind of list (§4c).
A bulk default without one is a bulk default whose holes nobody has looked for.
Ours, so far:

**1. Reference-typed array elements.** `new Widget[10]` yields ten nulls in C#,
and no `?.` or `== null` need ever appear. The cut has **18 reference-typed
array fields/properties**, of which roughly half hold genuine references
(`IMappedSegment[]`, `IValueRegisterField[]`, `ADCChannel[]`, `FilterBank[]`,
`Stream[]`, `Queue<CANMessage>[]`, `T[]`) rather than enums. The evidence rule
does not look inside array element types and will type these
`Vec<Rc<RefCell<T>>>`, which cannot represent the freshly-allocated state.
NullAway has exactly this carve-out:

> "Outside JSpecify mode, NullAway cannot represent nullable array element
> types and **unsoundly treats all array element reads as `@NonNull`**."

This one is concrete enough to fix rather than merely record: a reference-typed
array should be `Vec<Option<...>>` unconditionally, on the same reasoning that
makes `Nullable<T>` unconditional — C# already told us, via the allocation
semantics rather than via a `?`.

**2. Fields initialised after construction.** A field the constructor leaves at
its default and an `Init`/`Reset` method fills in is null for a real window,
with no syntactic tell. Partially detectable — reference-typed field with no
constructor assignment — but that shape is common and mostly benign, so it
would over-match badly if used as evidence. Record, do not act.

**3. Nulls crossing the cut boundary.** A caller in uningested code that passes
`null`, or a null check that lives in a file outside the cut. Not detectable
from within the cut by construction. This is the main driver of §7's failure
mode.

**4. `out` parameters and `Try*` patterns.** C# `TryGet`-shaped methods
conventionally leave the `out` parameter null on failure. The corpus records
`parameter.is_out`, so this is checkable; it is not covered by the five shapes
today.

Items 2–4 are unfixed and belong in the issue thread as named follow-ups, not
in the emitter's first cut.

### The `?.` mapping itself

`?.` short-circuits and evaluates the receiver exactly once. Two forms:

| C# | Rust |
|---|---|
| `x?.M();` (statement, `M` returns void) | `if let Some(x) = self.x.as_ref() { x.borrow_mut().m(); }` |
| `x?.M()` (expression, lifts to `T?`) | `self.x.as_ref().map(\|x\| x.borrow().m())` |
| `x?.M() ?? d` | `self.x.as_ref().map(\|x\| x.borrow().m()).unwrap_or_else(\|\| d)` |
| `a?.b?.c` | `.and_then(...)` chain — same whole-chain short-circuit |
| `handler?.Invoke(v)` | `if let Some(h) = self.handler.as_ref() { h(v); }` |

`if let` and `.map` both evaluate the receiver once, which a naive expansion to
`if (x != null) x.M()` would not — relevant when the receiver is a property
with a side-effecting getter.

The corpus already carries what the emitter needs: `ConditionalAccessInstance`
appears exactly 23 times, matching the 23 `ConditionalAccess` nodes, and is the
node inside the `whenNotNull` subtree that refers back to the receiver. It
binds to the `if let` / closure parameter. **No ingest change is needed for
this.**

### Worked example, real code

`STM32_UART.cs` lines 46 and 50 — the same field, guarded once and bare once:

```csharp
private CancellationTokenSource idleLineDetectedCancellationTokenSrc;   // line 240
...
idleLineDetectedCancellationTokenSrc?.Cancel();                          // line 46
var idleLineIn = (8 * 1000000) / BaudRate;
idleLineDetectedCancellationTokenSrc = new CancellationTokenSource();
machine.ScheduleAction(..., _ => ReportIdleLineDetected(
    idleLineDetectedCancellationTokenSrc.Token), ...);                   // line 50 — unguarded
```

Evidence shape 4 fires on line 46, so the field is `Option<...>`. Line 50 is an
unguarded dereference and becomes `.expect(...)`. That is *exactly* faithful:
if the field were null at line 50 the C# throws `NullReferenceException`, and
D4 maps that to a panic. The two rules meet in the right place without either
being bent.

---

## 7. Recommendation, and its failure mode

**Adopt evidence-based demotion.** Assume non-null; demote to `Option<T>` on
the five shapes in §6 plus the assignment closure. Handle `Nullable<T>`
unconditionally in the same change.

Why this and not the alternatives:

| approach | why not |
|---|---|
| Blanket `Option<T>` | Sound, and unusable: 1,031 members wrapped to catch 41. Every field access becomes a match. The oracle would still pass; nobody could read the diff against the C#, which is how four invisible bugs were caught so far. |
| Roslyn `NullableFlowState` with context forced on | Measured wrong on 22 of 22 `?.` receivers (§3b). It would emit a non-nullable field for every field the author explicitly guarded — the worst possible answer, because it is confidently wrong exactly where the code told us. |
| Whole-program dataflow (c2rust-analyze style) | The right answer eventually, and out of proportion now. It is a Polonius-class analysis, "prototype stage" after years in c2rust, minutes per large function. Our evidence rule captures 95% of what a naive flow extension finds (§2, +7 of 133) at a fraction of the cost. |
| Unknown → nullable, then narrow (J2K, §4b) | The conservative choice, and correct for Kotlin because `T?` is checked and a later pass can tighten it. In Rust there is no later pass with more information, and wrapping 1,031 members destroys the line-by-line comparability against the C# that this project's review depends on. We take the opposite default, and pay for it in the failure mode below. |
| Platform types / "trust me" (`T!`) | Rust has no such thing. There is no type that is sometimes checked — and both languages that tried one (Kotlin, Swift) documented regretting it (§5a, §5b). |

### Failure mode

**Null evidence is sparse and non-redundant, so a nullable reference with no
syntactic tell in the ingested cut is silently translated as non-nullable.**

This is measured, not hypothetical. Of the 17 symbols used as a `?.` receiver,
**12 have `?.` as their *only* null evidence** — no `== null`, no `= null`
anywhere in the cut:

    Antmicro.Renode.Peripherals.CAN.STMCAN.FrameReceived
    Antmicro.Renode.Peripherals.CPU.CortexM.nvic
    Antmicro.Renode.Peripherals.CRC.STM32_CRC.polySize
    Antmicro.Renode.Peripherals.CRC.STM32_CRC.reverseOutputData
    Antmicro.Renode.Peripherals.I2C.STM32F1_I2C.scheduledAction
    Antmicro.Renode.Peripherals.IRQControllers.NVIC.SecurityBanked<T>.SecureVal
    Antmicro.Renode.Peripherals.UART.STM32_UART.CharReceived
    Antmicro.Renode.Peripherals.UART.STM32_UART.idleLineDetectedCancellationTokenSrc
    ... and 4 more

Each of those hangs on a *single* occurrence of a *single* shape. Remove that
one `?.` — because the guard lives in a file outside the cut, or a caller in
uningested code passes null, or the field is only ever null during construction
— and the evidence disappears and the reference is typed non-nullable.

The consequence is concrete and it is not a compile error: the generated struct
has no way to represent the null state, so the constructor must fabricate a
value. Where C# had `null` and would have thrown, Rust has a real object and
proceeds. **That is a behavioural divergence that compiles, and one that
"it compiles" will not catch** — the same class as the four bugs in the work
protocol.

§6 lists four known carve-outs where the default is already known to be wrong;
one of them (reference-typed array elements) is fixable in the same change, and
three are not.

Three things bound the rest:

1. **The direction is knowable.** The analysis under-approximates the nullable
   set. It never wrongly wraps; it wrongly unwraps. So every miss shows up as
   a fabricated non-null value at construction, which is inspectable.
2. **Detection is cheap and should be built with the rule, not after.** Emit a
   `debug_assert` or a recorded deviation at each construction site that had to
   fabricate a value for a reference-typed field, so a miss surfaces as a named
   thing rather than as silently different behaviour.
3. **Evidence gets stronger as the cut grows.** The 4.0% figure is over the
   f427 cut only. Whether evidence may also be gathered from the breadth run is
   a question for the maintainer: CLAUDE.md forbids breadth data producing
   *rules*, and a fact about one named symbol is arguably not a rule — but that
   is the maintainer's call to make explicitly, not ours to assume.

### Withholding is still available

If a `?.` receiver cannot be resolved to a symbol (a chained expression, an
indexer result), the emitter must **withhold and report a gap**, not guess a
mapping. That is the c2rust-analyze behaviour quoted in §4a and the protocol's
rule.

---

## 8. Cost

### Ingest: not needed for the core

The entire evidence analysis was computed in this research from the existing
`operation` table, with no schema change and no re-ingest. `ConditionalAccess`,
`ConditionalAccessInstance`, `Coalesce`, `Binary`/`Equals`, `SimpleAssignment`
and null `Literal`s are all already recorded, and `ConditionalAccessInstance`
counts match `ConditionalAccess` exactly, so the receiver binding is present.

**No ingest change is required.** That is the expensive thing avoided.

### One ingest change worth requesting separately

Read `IMethodSymbol.ReturnNullableAnnotation` and
`IParameterSymbol.NullableAnnotation` into `operation.detail` for `Invocation`
and `PropertyReference`. §3d proves these are *correct* across the annotated-BCL
boundary even with the corpus's nullable context disabled — `Type.GetType()` is
`Annotated`, `Dictionary.TryGetValue` is `NotAnnotated`. It gives real
nullability at every library call for free.

This is a ninth instance of the recurring finding in the work protocol: a
property Roslyn already exposes that the walker does not read. **It is not a
prerequisite for §7** and should be batched, not blocking.

### Rules files

| file | change |
|---|---|
| `rulesdb/rules/lang/nullability.json` | **new.** The five evidence shapes, the `?.` and `??` templates, `Option<T>` wrapping, `.expect` for unguarded deref, `Nullable<T>` → `Option<T>`, and a `deviations` entry for the non-hoisting decision and the `unwrap_or_else` laziness. |
| `rulesdb/rules/csharp_core.json` | the `statements.ConditionalAccess` gap stanza is removed. **Shared file — coordinate in the issue thread rather than editing unilaterally.** |
| `rulesdb/rules/register_dsl.json` | possibly none. The 6 delegate/event `?.` sites map through PLAN.md's existing `Option<Box<dyn Fn>>` decision; confirm rather than assume. |

### Emitter

| module | work |
|---|---|
| `scripts/emitter/lang/nullability.py` | **new**, and the bulk of it. A single pass building the evidence set from the `operation` table (about 60 lines — the queries in §2 are the prototype), the closure step, and a `is_nullable(symbol)` predicate the other modules call. |
| `scripts/emitter/lang/expressions.py` | replace the `ConditionalAccess` gap at line 139 with real emission; add `Coalesce`; bind `ConditionalAccessInstance`. Roughly 60–90 lines. |
| `scripts/emitter/lang/types.py` | `rust_type` learns the `T?` suffix → `Option<...>`, wraps when `is_nullable`, and makes reference-typed arrays `Vec<Option<...>>` (§6 carve-out 1). Small, maybe 20 lines. |

Estimate: one module plus two touched files, and the analysis pass is the only
part with real design in it. The `Nullable<T>` half is close to free and clears
5 of the 16 nullability root causes on its own.

The protocol allows one emitter module and its own rules file per agent. This
fits, with the `csharp_core.json` stanza removal as the one thing to raise in
the thread.

### What it unblocks

16 of 180 direct gaps (8.9%), plus whatever cascades behind `NVIC::Reset` and
the other withheld methods. Not the largest single item, but the largest
coherent theme, and it is currently a hard stop rather than a partial one.

---

## 9. Is the honest answer "nobody solves this well"?

**Yes, and it should be said plainly: there is no sound, cheap, automatic
answer, and the people best placed to build one decided not to.**

The evidence for that is not an absence of results, it is a set of explicit
published decisions:

- **Uber** ships a wiki page titled **"Deliberate Unsoundness"** listing five
  classes of NPE its production checker knowingly misses, and says
  inter-procedural inference is "prohibitively expensive in the general case"
  (§4c).
- **Microsoft**, holding the compiler and the language spec, recommends
  migrating C# codebases by **human annotation, file by file, bottom-up,
  visiting each file twice** (§5c). They did not propose inferring it.
- **Apple** abandoned the inferred-third-state approach (`T!`) and replaced it
  with **bulk manual annotation plus a documented carve-out list**
  (`NS_ASSUME_NONNULL_BEGIN`, §5b), and SE-0054 describes IUOs as a
  "transitional technology" it wants removed entirely.
- **JetBrains** shipped a third state that is still tracked as an open issue
  after 12 years, and made **type equivalence non-transitive** to accommodate it
  (§5a).
- **immunant**'s `c2rust-analyze`, doing the identical C-to-Rust job with a
  Polonius-backed whole-program analysis, describes itself as "at a prototype
  stage" and skips functions it cannot handle (§4a).

Every approach surveyed either assumes non-null and is unsound
(c2rust-analyze's `NON_NULL`, NullAway's default, ours), defers the check to
runtime (Kotlin platform types, Swift IUOs), requires human annotation at scale
(audited regions, `#nullable enable`), or resolves unknown to nullable and
accepts the noise (J2K). **Rust removes the runtime-deferral option entirely** —
there is no type that is sometimes checked — so the real choice is between
"unsound and readable" and "sound and unreadable". We are picking the first,
with eyes open, and §7 says what it costs.

Two things are not a shrug, and they are what this research actually bought:

**The cheapest-looking option is closed.** The specific idea in the issue —
lean on Roslyn's own flow state — was testable, was tested three ways including
the `run-nullable-analysis=always` override, and is wrong on this corpus in a
specific and measurable way: **22 of 22 `?.` receivers reported `NotNull`**. The
option that looked free is not merely weak, it is confidently wrong exactly
where the source code told us the answer. Nobody has to spend a week finding
that out now.

**The recommendation is a copy, not an invention.** `c2rust-analyze` reached
the same design independently for C-to-Rust and wrote the rewrite table down
(§4a); NullAway runs the same default in production (§4c). Where we differ from
J2K — unknown resolves to non-null rather than nullable — the reason is the
target language and the review process, and it is recorded as the failure mode
rather than hidden as a simplification.
