# Transpiler work — issue drafts

Source of truth for `scripts/file_issues.py --draft docs/transpiler-issues-draft.md`.
One issue per `## <id> — <title>` heading; the line after the heading is labels.

Two tracks:

- **T-R\*** research. Deliverable is a document. No code, no collision, start now.
- **T-C\*** code. One emitter module each. **Blocked** until `emit.py` is split
  into `scripts/emitter/`; do not start one before the modules exist.

For what the converter can and cannot do today, and why the rule engine is not
yet built despite rules working, see
[rule-engine-readiness.md](rule-engine-readiness.md).

Everything below assumes [the work protocol](agents/transpiler-work-protocol.md).
Read it first — it is short, and it is the difference between a contribution and
a merge conflict.

---

## T-R1 — Research: nullable references and `?.`
transpiler, research, blocked-decision

**Deliverable**: `docs/research/nullability.md`. No code.

**Why this one first.** `?.` is the single construct blocking the most work: it
withholds `WriteChar` and both `Reset` methods. PLAN.md deferred it as deviation
D4 without deciding, and it is now the binding constraint rather than a
hypothetical.

**The problem.** C# lets any reference be null. This corpus is not annotated, so
every reference is *potentially* null, and a blanket `Option<T>` would be noise
at a scale that makes the output unreadable. But `x?.Foo()` has real
short-circuit semantics that cannot be dropped.

**Questions to answer**

1. How do translators decide which references actually need `Option<T>`? Is
   there a usable nullability *analysis* — dataflow, or a compiler's own flow
   state — as opposed to relying on annotations?
2. Roslyn exposes `NullableFlowState` and `NullableAnnotation` even on
   unannotated code. **Is that trustworthy without `#nullable enable`?** This is
   the crux. Answer it concretely, with a test against this corpus, not from
   documentation alone.
3. What did Kotlin (platform types), Swift (implicitly-unwrapped optionals) and
   C# 8's own nullable-reference migration do about exactly this problem —
   retrofitting null-safety onto unannotated code?
4. Is there a defensible middle: `Option<T>` only where the corpus actually
   assigns null, compares to null, or uses `?.`/`??`?

**Corpus evidence to include**

```sql
SELECT COUNT(*) FROM operation WHERE kind='ConditionalAccess';
SELECT COUNT(*) FROM operation WHERE kind IN ('Coalesce','CoalesceAssignment');
SELECT COUNT(*) FROM operation WHERE kind='Literal' AND type IS NULL;
```

---

## T-R2 — Research: exceptions to Result
transpiler, research, blocked-decision

**Deliverable**: `docs/research/exceptions.md`. No code.

`throw` withholds `SetConnectionStateBit`, and `try`/`catch`/`finally`/`using`
appear across the corpus. This is D4's other half.

**Questions**

1. How do translators map exceptions onto a language without them? Java-to-Go,
   C#-to-C++, and IL2CPP are the obvious places to look.
2. This corpus throws a recoverable-error type for *user* errors and uses
   exceptions for control flow in places. Does that distinction survive?
3. What happens to `finally` and to `using`? Is `Drop` sufficient, and where
   exactly does it differ — early return, panic, nested scopes?
4. **The hard one**: what does `Result` propagation do to callbacks whose
   signatures are fixed by an external DSL and cannot return `Result`? That
   constraint is real here and may rule out the obvious answer.

```sql
SELECT kind, COUNT(*) FROM operation
WHERE kind IN ('Throw','Try','CatchClause','Finally','Using') GROUP BY kind;
```

---

## T-R3 — Research: LINQ to Rust iterators
transpiler, research

**Deliverable**: `docs/research/linq.md`. No code.

**Questions**

1. Which LINQ operators map cleanly onto `Iterator`, and which do not?
2. Deferred execution: both LINQ and `Iterator` are lazy, but the *points of
   materialisation* differ. Where does that change observable behaviour?
3. `IEnumerable<T>` stored in a field, rather than consumed — what is the Rust
   shape when it must be stored?
4. How do the JVM-to-JS and JVM-to-native translators handle streams?

```sql
SELECT symbol, COUNT(*) FROM operation
WHERE symbol LIKE '%System.Linq%' GROUP BY symbol ORDER BY 2 DESC;
```

---

## T-R4 — Research: inheritance, flattening versus traits
transpiler, research, blocked-decision

**Deliverable**: `docs/research/inheritance.md`. No code.

**This issue exists to challenge a decision already implemented.** We flatten a
base class into the derived type: base fields join the state struct, base
methods become free functions. The stated reasoning is that a trait cannot carry
the base's *fields*, which is what derived code reaches for.

**Try to prove that wrong.** It is cheap to change now and expensive later.

**Questions**

1. What do object-oriented-to-Rust translators actually do — traits,
   composition, enum dispatch, or flattening?
2. Where does flattening break? Deep hierarchies, diamond interfaces, virtual
   dispatch through a base reference, heterogeneous collections.
3. This corpus dispatches polymorphically through an interface. Does flattening
   survive that, or does it force an enum over every implementer?
4. What does the choice do to deviation D1 (the `Rc<RefCell>` object graph)?

```sql
SELECT COUNT(*) FROM type WHERE base_type_id IS NOT NULL;
SELECT COUNT(*) FROM method WHERE is_virtual=1 OR is_override=1;
```

---

## T-R5 — Research: closures that capture the receiver
transpiler, research

**Deliverable**: `docs/research/closures.md`. No code.

We turn a lambda capturing `this` into a free function over `(bank, state)`,
because a closure cannot be stored inside the object it borrows.

**Questions**

1. Is that what other translators do, or is there a better shape?
2. State of the art for self-referential structures in Rust: arenas, index
   handles, `Pin`, generational arenas — which apply here?
3. We store callbacks as `fn` pointers, which cannot capture. What do we lose,
   and when will that bite?
4. How does this interact with deviation D2 (arena plus typed index handles)?

---

## T-R6 — Research: prior art, has anyone built a C#-to-Rust transpiler?
transpiler, research

**Deliverable**: `docs/research/prior-art.md`. No code.

We concluded that none exists, having checked GitHub and a handful of
lookalikes. **That check was shallow, and a wrong answer is expensive.** Verify
it independently and go wider.

**Questions**

1. Search beyond GitHub: GitLab, Codeberg, sr.ht, Bitbucket, SourceForge,
   grep.app, SearchCode, and the academic literature on source-to-source
   translation.
2. Include partial and **abandoned** attempts. An abandoned one may record *why*
   it was abandoned, which is the most valuable finding available here.
3. Adjacent targets: C#-to-C++, C#-to-Go, IL-to-native. **IL2CPP is especially
   relevant** — it solves C# semantics on a non-garbage-collected target, which
   is most of our problem.
4. If something exists: what is its architecture, and what can we take?

A negative result is a real finding. Say so plainly if that is the answer, and
show what you searched.

---

## T-R7 — Research: numeric faithfulness
transpiler, research, oracle

**Deliverable**: `docs/research/numerics.md`. No code.

Silent numeric divergence is what our oracle is worst at catching. We have
already shipped one: a `16.0` literal emitted as `16`, turning an f64 division
into integer division. It compiled, and no test saw it.

**Questions**

1. The complete set of places C# converts numerically where Rust will not:
   `checked`/`unchecked`, integer promotion, implicit widening.
2. Shift semantics on negative and oversized shift counts; integer division and
   modulo on negatives; float-to-double promotion.
3. How do translators *verify* numeric equivalence — differential testing over
   random inputs, symbolic execution, exhaustive small-domain enumeration?
4. **Specifically: what could we add to the oracle that would have caught the
   `16.0` bug?** Answer this one concretely.

```sql
SELECT COUNT(*) FROM operation WHERE kind='Conversion';
SELECT detail, COUNT(*) FROM operation WHERE kind='Binary' GROUP BY detail;
```

---

## T-R8 — Research: how do transpiler projects prove equivalence?
transpiler, research, oracle

**Deliverable**: `docs/research/equivalence.md`. No code.

Our oracle is trace replay plus mutation testing. **Four bugs still got through
that were invisible to both**: a self-call producing unbounded recursion, a
comment left in a loop increment producing an infinite loop, an unmapped return
type silently dropping values, and the numeric bug above.

**Questions**

1. What do established source-to-source projects and the compiler-testing
   literature do to establish that a translation preserves behaviour?
2. Differential fuzzing of translated versus original — practical here, given we
   can run the C# original alongside?
3. Metamorphic testing, translation validation, equivalence checking: which are
   real engineering practice and which are papers?
4. **Specifically: what test would have caught a `/* GAP */` comment left inside
   a loop body, producing an infinite loop that compiles?**

---

## T-C1 — Emit: throw and the exception statements
transpiler, code, blocked-on-split

**Blocked** on the `emit.py` split and on **T-R2**, which decides the mapping.
Do not start before both land.

**Module**: `scripts/emitter/lang/exceptions.py` + `rulesdb/rules/lang/exceptions.json`

Implement whatever T-R2 concludes. Currently `SetConnectionStateBit` is withheld
with `cannot emit stmt:Throw`.

**Done when**: that gap is gone, no new gap appears, the corpus query shows how
many `Throw`/`Try`/`Catch` sites now emit, and the emitted Rust is compared to
the C# in the PR.

---

## T-C2 — Emit: LINQ operators
transpiler, code, blocked-on-split

**Blocked** on the split and on **T-R3**.

**Module**: `scripts/emitter/lang/linq.py` + `rulesdb/rules/lang/linq.json`

There is also a **real bug** to fix here: `Where`, `Select` and `OrderBy` are
currently being read as *state fields* (`st.where`, `st.select`), which is why
`GetSetConnectionBits` is withheld. Extension-method receivers are being
mishandled, not just unmapped.

---

## T-C3 — Emit: nested struct generation
transpiler, code, blocked-on-split

**Blocked** on the split only. No research needed.

**Module**: `scripts/emitter/plugins/` or `lang/` — decide and justify. Nested
*enums* are generated already (`scripts/emit.py`, `nested_enums`); structs are
not, which is why two state fields have no mapping.

Generating a struct nested in a type is generic C#, so it likely belongs in
`lang/` — but the field-type mapping it needs may not be. State your reasoning.

**Done when**: the two `no Rust mapping` gaps for nested struct types are gone,
and the generated structs match the C# field for field.

---

## T-C4 — Emit: collection and interface type mapping
transpiler, code, blocked-on-split

**Blocked** on the split.

**Module**: `scripts/emitter/lang/collections.py` + its rules file.

Unmapped today: `IReadOnlyDictionary<K,V>`, and several interface types used as
parameters and return values. The existing `stdlib` table covers concrete
collections; interfaces are the gap.

**Watch out**: an interface as a *parameter* type is a different problem from an
interface as a *field* type — one may become a generic bound, the other needs a
concrete representation. Do not conflate them.

---

## T-C5 — Emit: the scheduler dependency
transpiler, code, blocked-on-split, decision

**Blocked** on the split. **Needs a decision, not just code.**

`WriteChar` reaches `st.machine` to schedule a delayed action. The machine and
its time framework are not modelled at all, and modelling them is a much larger
piece of work than an emitter module.

**This issue is to scope that, not to build it.** Report:

1. What the corpus actually uses the machine for, with counts.
2. The smallest thing that would unblock the peripherals currently withheld.
3. Whether that smallest thing is faithful, or a divergence that must be
   recorded as a deviation.

If the answer is "this needs a real time framework", say so and propose the
issue that builds it. Do not stub it.
