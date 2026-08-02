# The corpus database — design

The LLM is invoked once per *pattern*, not once per function. That requires
answering, for any proposed rule, "where else does this shape occur?" — which
requires the whole corpus in a queryable database *before* translation starts.

Schema and the discipline that enforces it.

## The lesson this is designed around

`linux-rs` ran two tracks in the same period. Measured from its `patterns.db`,
2026-07-31:

| Track | Corpus ingested? | Outcome |
|---|---|---|
| **c2rust-breadth** | Yes — `c2rust_decl_outcomes` 897,814 rows, `function_safety_status` 43,348 rows | Corpus-scale. A single transpiler fix flipped 317 files from crash to clean transpile |
| **rule-learning translation** | **No** — `functions` **0 rows**, `statement_families` **0 rows** | 31 rules / 58 validation instances = **1.87 instances per rule**, across 38 translated TUs |

Its own plan named the census as the Phase-1 go/no-go gate. The gate was skipped;
work went straight to per-file translation, which then needed a per-file review
loop to hold quality.

**The causal chain:** with no corpus in the DB, "validate this rule against all
structurally-equivalent occurrences" is not a runnable operation. A rule can then
only be justified by the file that motivated it — a patch wearing a rule's label
— leaving per-file review as the only quality mechanism. 1.87 is that failure,
quantified.

## Four structural defences

Process rules do not survive schedule pressure. These are mechanical.

1. **The translator reads only from the database.** It takes a `method_id` and a
   rule set; no path reads a `.cs` file. An empty DB translates nothing.
2. **A rule needs N validated instances.** `rule.status` cannot reach `committed`
   while `COUNT(rule_instance) < min_instances_required` (default **3**). Below
   that it is a `patch`, and patches must trend to zero. Direct antidote to 1.87.
3. **The health metric is instances-per-rule**, not files translated. A fall
   toward 1 means drift, visible the week it starts.
4. **Everything carries `run_id`.** Each translation records the exact rule
   versions that produced it, so a v3→v4 bump re-validates exactly those rather
   than everything.

## Schema

SQLite. `run_id` on every table; a run is one ingest of one Renode commit.

### Provenance

```sql
CREATE TABLE corpus_run (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,          -- ISO 8601 with offset
    renode_commit TEXT NOT NULL,
    tool_version  TEXT NOT NULL,          -- ingest tool git describe
    config        TEXT NOT NULL,          -- run purpose: 'tree' | 'breadth'
    notes         TEXT
);
```

### Structure — what Roslyn gives us

```sql
CREATE TABLE file (
    id      INTEGER PRIMARY KEY,
    run_id  INTEGER NOT NULL REFERENCES corpus_run(id),
    path    TEXT NOT NULL,                -- repo-relative, never absolute
    sha256  TEXT NOT NULL,
    loc     INTEGER NOT NULL
);

CREATE TABLE type (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES corpus_run(id),
    file_id       INTEGER NOT NULL REFERENCES file(id),
    namespace     TEXT NOT NULL,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,          -- class|struct|interface|enum|delegate
    base_type_id  INTEGER REFERENCES type(id),
    is_abstract   INTEGER NOT NULL,
    is_generic    INTEGER NOT NULL,
    accessibility TEXT NOT NULL
);

CREATE TABLE type_implements (             -- interfaces, many-to-many
    type_id      INTEGER NOT NULL REFERENCES type(id),
    interface_id INTEGER NOT NULL REFERENCES type(id),
    PRIMARY KEY (type_id, interface_id)
);

CREATE TABLE member (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES corpus_run(id),
    type_id       INTEGER NOT NULL REFERENCES type(id),
    kind          TEXT NOT NULL,          -- field|property|method|event|ctor
    name          TEXT NOT NULL,
    declared_type TEXT NOT NULL,
    accessibility TEXT NOT NULL,
    is_static     INTEGER NOT NULL,
    is_readonly   INTEGER NOT NULL
);

CREATE TABLE method (
    member_id   INTEGER PRIMARY KEY REFERENCES member(id),
    signature   TEXT NOT NULL,
    return_type TEXT NOT NULL,
    is_virtual  INTEGER NOT NULL,
    is_abstract INTEGER NOT NULL,
    is_override INTEGER NOT NULL,
    has_body    INTEGER NOT NULL
);

CREATE TABLE parameter (
    id        INTEGER PRIMARY KEY,
    method_id INTEGER NOT NULL REFERENCES method(member_id),
    ordinal   INTEGER NOT NULL,
    name      TEXT NOT NULL,
    type      TEXT NOT NULL,
    is_out    INTEGER NOT NULL,           -- the register-DSL `out` pattern
    is_ref    INTEGER NOT NULL,
    has_default INTEGER NOT NULL
);

CREATE TABLE local (
    id        INTEGER PRIMARY KEY,
    method_id INTEGER NOT NULL REFERENCES method(member_id),
    name      TEXT NOT NULL,
    type      TEXT NOT NULL,
    is_captured INTEGER NOT NULL          -- closure capture: matters for Rust
);
```

### Code — the `IOperation` tree

One row per node. This is the largest table and the thing rules match against.

```sql
CREATE TABLE operation (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES corpus_run(id),
    method_id   INTEGER NOT NULL REFERENCES method(member_id),
    parent_id   INTEGER REFERENCES operation(id),
    ordinal     INTEGER NOT NULL,         -- position among siblings
    kind        TEXT NOT NULL,            -- IOperation.Kind
    type        TEXT,                     -- resolved type, null for statements
    symbol      TEXT,                     -- resolved target for invocations
    const_value TEXT,                     -- literal, if constant
    span_start  INTEGER NOT NULL,         -- source span, for provenance
    span_len    INTEGER NOT NULL
);
CREATE INDEX idx_operation_method ON operation(method_id);
CREATE INDEX idx_operation_parent ON operation(parent_id);
CREATE INDEX idx_operation_kind   ON operation(kind);
```

### Graphs — what makes call-site checking possible

```sql
CREATE TABLE call_site (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES corpus_run(id),
    caller_id    INTEGER NOT NULL REFERENCES method(member_id),
    callee_id    INTEGER REFERENCES method(member_id),  -- null if unresolved
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    is_virtual   INTEGER NOT NULL,        -- one row per candidate if virtual
    callee_extern TEXT                    -- BCL/external target, when callee_id null
);

CREATE TABLE field_access (
    method_id    INTEGER NOT NULL REFERENCES method(member_id),
    member_id    INTEGER NOT NULL REFERENCES member(id),
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    is_write     INTEGER NOT NULL
);
```

### Derived analysis — the work queue

```sql
CREATE TABLE method_metrics (
    method_id      INTEGER PRIMARY KEY REFERENCES method(member_id),
    ast_nodes      INTEGER NOT NULL,
    cyclomatic     INTEGER NOT NULL,
    max_depth      INTEGER NOT NULL,
    n_locals       INTEGER NOT NULL,
    n_calls        INTEGER NOT NULL,
    n_field_writes INTEGER NOT NULL,
    is_leaf        INTEGER NOT NULL,      -- calls nothing in corpus
    is_pure        INTEGER NOT NULL       -- fixpoint over the call graph
);

CREATE TABLE method_fingerprint (
    method_id     INTEGER PRIMARY KEY REFERENCES method(member_id),
    fingerprint   TEXT NOT NULL,          -- normalised structural hash
    norm_version  TEXT NOT NULL           -- normalisation algorithm version
);
CREATE INDEX idx_fingerprint ON method_fingerprint(fingerprint);

CREATE TABLE pattern_cluster (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES corpus_run(id),
    fingerprint  TEXT NOT NULL,
    member_count INTEGER NOT NULL,
    exemplar_id  INTEGER NOT NULL REFERENCES method(member_id)
);

-- The work queue: topological order, simplest first within each level.
CREATE TABLE translation_order (
    method_id  INTEGER PRIMARY KEY REFERENCES method(member_id),
    topo_level INTEGER NOT NULL,          -- 0 = leaves
    rank       INTEGER NOT NULL           -- by ast_nodes within level
);
```

### Rules

```sql
CREATE TABLE rule (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    family      TEXT NOT NULL,            -- REGISTER_FIELD, LOCKED_REGION, ...
    description TEXT NOT NULL,
    matcher     TEXT NOT NULL,            -- operation-tree pattern
    emitter     TEXT NOT NULL,            -- Rust emission template
    status      TEXT NOT NULL,            -- proposed|validated|committed|retired
    min_instances_required INTEGER NOT NULL DEFAULT 3,
    requires_human_gate    INTEGER NOT NULL DEFAULT 0,
    created_run_id INTEGER NOT NULL REFERENCES corpus_run(id),
    UNIQUE (name, version)
);

-- Every place the rule matches, found by querying the corpus -- not by hand.
CREATE TABLE rule_match (
    rule_id      INTEGER NOT NULL REFERENCES rule(id),
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    run_id       INTEGER NOT NULL REFERENCES corpus_run(id),
    PRIMARY KEY (rule_id, operation_id, run_id)
);

-- Matches that have been *validated* by the oracle. The count gates commit.
CREATE TABLE rule_instance (
    rule_id      INTEGER NOT NULL REFERENCES rule(id),
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    validated_at TEXT NOT NULL,
    oracle_tier  INTEGER NOT NULL,
    evidence     TEXT NOT NULL,
    PRIMARY KEY (rule_id, operation_id)
);

-- Shapes the rule must NOT match. Guards against over-generalisation.
CREATE TABLE rule_negative (
    rule_id      INTEGER NOT NULL REFERENCES rule(id),
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    reason       TEXT NOT NULL
);

CREATE TABLE rule_deviation (
    rule_id       INTEGER NOT NULL REFERENCES rule(id),
    description   TEXT NOT NULL,
    justification TEXT NOT NULL
);
```

### Translation state

```sql
CREATE TABLE translation (
    id             INTEGER PRIMARY KEY,
    method_id      INTEGER NOT NULL REFERENCES method(member_id),
    run_id         INTEGER NOT NULL REFERENCES corpus_run(id),
    status         TEXT NOT NULL,         -- stub|translated|verified
    rule_versions  TEXT NOT NULL,         -- hash of the exact rule set used
    rust_path      TEXT NOT NULL,
    rust_symbol    TEXT NOT NULL,
    code_sha256    TEXT,
    oracle_tier    INTEGER NOT NULL DEFAULT 0,
    is_patch       INTEGER NOT NULL DEFAULT 0,  -- hand edit: must trend to zero
    UNIQUE (method_id, run_id)
);
```

### Progress

```sql
CREATE TABLE progress_snapshot (
    id                 INTEGER PRIMARY KEY,
    run_id             INTEGER NOT NULL REFERENCES corpus_run(id),
    taken_at           TEXT NOT NULL,
    n_methods          INTEGER NOT NULL,
    n_stubbed          INTEGER NOT NULL,
    n_translated       INTEGER NOT NULL,
    n_verified         INTEGER NOT NULL,
    n_rules_committed  INTEGER NOT NULL,
    n_patches          INTEGER NOT NULL,  -- hand edits outstanding
    instances_per_rule REAL NOT NULL      -- THE health metric
);
```

## The pipeline

```
Renode C# (the whole tree)
      │
      ▼  [ingest]  Roslyn IOperation walk → serialised IR
corpus database ──────────────────────────────────────────┐
      │                                                    │
      ▼  [analyse]                                         │
metrics · purity fixpoint · call graph · fingerprints      │
clusters · topological work queue                          │
      │                                                    │
      ▼  [stub]                                            │
Rust crate: EVERY method emitted as todo!()  ── compiles from day one
      │                                                    │
      ▼  [translate]  work the queue: leaves first, simplest first
   ┌──────────────────────────────────────────────┐        │
   │ match rules against operation tree           │        │
   │  ├─ hit  → emit Rust ──────────────────┐     │        │
   │  └─ miss → cluster with similar misses │     │        │
   │            → ONE LLM call per cluster  │     │        │
   │            → proposed rule             │     │        │
   │            → query ALL matches ────────┼─────┼────────┘
   │            → validate each             │     │
   │            → ≥3 instances? commit      │     │
   │               else: record as patch    │     │
   └────────────────────────────────────────┼─────┘
                                            ▼
                            oracle: trace replay → lockstep → boot
```

## Why bottom-up by complexity

`translation_order` is a topological sort of the call graph — leaves first —
ranked by `ast_nodes` within each level. Three reasons:

1. **Leaves are pure functions of their arguments**, so they are the cheapest
   things to test exhaustively and the least likely to need D1/D3 decisions.
2. **Each translated leaf makes its callers translatable**, so coverage grows
   monotonically rather than blocking on a dependency.
3. **Simple functions produce the general rules.** A rule derived from a 300-node
   method is usually over-specific; one derived from a 12-node method is often
   the general case. Starting complex is how you get 1.87 instances per rule.

## The test harness exists from commit one

Emitting `todo!()` stubs for the entire corpus before any translation gives:

- **A crate that builds on day one**, so CI is real immediately.
- **Signatures checked by rustc** before any body is written — the type mapping
  is validated corpus-wide up front, not discovered per file.
- **Call sites already wired**, so translating a function needs no plumbing.
- **An exact progress metric**: stubs remaining.

Each translated method gets its test generated from the tier-2 trace fixtures.
The CI gate is: crate builds, all generated tests pass, `n_patches` has not
increased, and `instances_per_rule` has not fallen.

## Parallelism — a design constraint, not a later optimisation

**Target: saturate all 31 available threads at every stage.** Conversion is
re-run constantly during rule development, so its wall-clock time is the
project's iteration speed. A stage that runs single-threaded is a defect with a
recorded reason, not an acceptable default.

The dev machine is an **i9-14900K: 24 physical cores — 8 P-cores (hyperthreaded,
16 threads) + 16 E-cores — 31 usable threads, 36 MiB shared L3, 62 GB RAM.** It
is heterogeneous, which naive thread pools schedule badly: a pool that assumes
uniform cores will put a long critical-path task on an E-core and stall the
whole stage behind it.

### What parallelises, and how

| Stage | Parallel? | Shape |
|---|---|---|
| Roslyn compilation load | **No** — serial, unavoidable | Cross-file type resolution needs the whole `Compilation`. Measure it; it is the Amdahl floor |
| `IOperation` walk | **Yes, per file** | `SemanticModel` is safe for concurrent reads once the compilation exists. One worker per file |
| DB write | Sharded | Per-worker SQLite, then one merge. WAL mode; never 31 writers on one file |
| Metrics, fingerprints | **Yes, per method** | Pure functions of one subtree |
| Purity fixpoint | **Yes, per iteration** | Parallel worklist over the call graph |
| Clustering | **Yes** | Parallel map, then group-by reduce |
| Topological sort | No — but milliseconds | Not worth parallelising |
| **Rule application / emission** | **Yes, fully** | See below — the important one |
| Rule validation | **Yes, per match** | Each match validates independently |
| `cargo build` | **Only if the crate graph allows it** | See below |
| LLM cluster calls | **Yes** | Independent per cluster; batch against rate limits |

### The emission insight

The leaves-first work queue orders **rule discovery**, not rule *application*.
Once a rule is committed, applying it is a pure function
`(operation subtree, rule set) → Rust`, with no shared state and no dependency
on call-graph position. So the whole corpus emits in parallel — 31 methods at a
time — and only the discovery loop is ordered.

That distinction is worth stating because conflating the two would serialise the
most expensive stage for no reason.

### Four rules this imposes on the design

**1. Output must be byte-identical regardless of worker count.** Non-negotiable:
if a 1-worker and a 31-worker run differ, every diff against the C# reference
becomes noise and the oracle is worthless. Concretely — no timestamps or paths in
generated code, stable IDs assigned from content rather than completion order,
sort before writing, and no dependence on hash-map iteration order. **Enforce it
with a CI check that runs the pipeline at `-j1` and `-j31` and diffs.**

**2. Emit a cargo workspace of many small crates, not one large crate.** rustc
parallelises across crates far better than within one. One crate per peripheral
plus shared core crates gives real build parallelism and much faster incremental
rebuilds. This is a decision for the stub emitter (#R4) and it is expensive to
change later.

**3. Content-addressed caching.** A translation is a pure function of
`(subtree hash, rule-set hash)`. Cache on that key, and a re-run after a rule
change recomputes only what actually changed — which is what makes the
rule-development loop tolerable at all.

**4. Schedule for heterogeneous cores.** Long or critical-path tasks (the Roslyn
load, the merge) belong on P-cores; wide batches of short tasks can fill E-cores.
Prefer work-stealing over static partitioning, since E-cores finish short tasks
at roughly half a P-core's rate and static splits leave P-cores idle.

### Forking Roslyn

Probably unnecessary, and it should be a measured decision rather than an
assumption. The parallelism above is available through the public API:
`SemanticModel` reads are thread-safe, and the walk shards cleanly per file.

Two cheaper moves come first:

- **Skip `MSBuildWorkspace`.** Construct `CSharpCompilation.Create` directly with
  explicit references. Faster, more deterministic, and removes an MSBuild
  dependency that is slow and occasionally flaky.
- **Cache the compilation.** Roslyn supports serialising metadata references;
  the serial load only needs to happen when the corpus commit changes.

Fork only if a measured bottleneck traces to something the public API cannot
express — and record the measurement in the issue before forking anything.

### Tracked metric

Core utilisation per stage, alongside instances-per-rule, in
`progress_snapshot`. A stage that cannot saturate must carry a written reason.

## The codebase is a build artifact

Rules — not files — are the source code. Two consequences, neither available to
hand-translation at any price.

**1. Architectural decisions become re-runs.** Change two or three rules,
regenerate, re-run the oracle; the whole 28k-line structure changes in one run.
So D1–D4 are *reversible defaults*, not commitments:

| Decision | Rule-expressible | Cost to revisit |
|---|---|---|
| **D2** register layout | Fully | One rule + regenerate |
| **D1** object graph | Largely | A few rules + regenerate; hand-written core is manual |
| **D4** error model | Largely | Rule + regenerate |
| **D3** threading | Partially | Reaches hand-written core — the one genuinely expensive reversal |

**2. Alternative rule sets are benchmarked, not debated.** Generate variant A
(`Rc<RefCell>` per field) and variant B (`Cell` arena), build both, run both
against the same oracle and benchmark, pick on numbers.
`translation.rule_versions` makes variants addressable by construction.

Note what this does to **#P1**: its hand-built prototype comparing the two D2
layouts is the manual version of an experiment the pipeline runs permanently at
full-corpus scale. P1 still de-risks the premise first, but the capability it
prototypes should become standing infrastructure.

**3. So `n_patches == 0` is the capability, not hygiene.** A hand-edited file
will not regenerate. At 5% patched, a rule-set A/B moves only 95% of the codebase
and the comparison is quietly contaminated. Patches are holes in the ability to
regenerate, and that ability is the asset. Corollary, from `linux-rs` where it is
stated correctly even though the process drifted from it: *a landed translation
must be recreatable from the C# source plus committed rules and scripts alone.*

## Cost model

The narrower argument.

| Approach | LLM invocations | Note |
|---|---|---|
| Per function | ~2,000 (F427) → ~20,000 (full peripheral tree) | What the linux-rs rule track effectively did |
| **Per cluster** | **~200–400, once** | Every subsequent instance is a database query and a template application |

The rules are also **the durable asset**: they carry forward to the other 419
DSL-style peripheral files (208,580 lines) at no additional LLM cost. Per-function
translation carries nothing forward.

**Caveat, stated plainly:** for an F427-sized slice alone (~28k lines), this
tooling is more expensive up front than hand-translating. It is justified by two
things — the full-tree scale, and the regeneration capability above. If the goal
were ever narrowed to F427-and-stop *and* the architecture were known to be right
first time, hand-translation would be cheaper. Neither of those holds, and the
corpus is now the full tree
([docs/decisions/remove-the-cut.md](decisions/remove-the-cut.md)).
