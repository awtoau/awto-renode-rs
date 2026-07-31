# The corpus database — design

The economic argument for this project is that **the LLM is invoked once per
*pattern*, not once per function**. That only works if you can answer, for any
proposed rule, "where else does this exact shape occur?" — which requires the
whole corpus to be in a queryable database *before* translation starts.

This document is the schema and the process discipline that enforces it.

## The lesson this is designed around

`linux-rs` ran two tracks in the same period. Measured from its `patterns.db`
on 2026-07-31:

| Track | Corpus ingested? | Outcome |
|---|---|---|
| **c2rust-breadth** | Yes — `c2rust_decl_outcomes` 897,814 rows, `function_safety_status` 43,348 rows | Corpus-scale. A single transpiler fix flipped 317 files from crash to clean transpile |
| **rule-learning translation** | **No** — `functions` **0 rows**, `statement_families` **0 rows** | 31 rules / 58 validation instances = **1.87 instances per rule**, across 38 translated TUs |

Its own plan named the pattern census as the Phase-1 go/no-go gate. That gate was
skipped and work went straight to per-file translation, which then needed a
documented per-file review loop to keep quality up.

**The causal chain matters:** with no corpus in the DB, "validate this rule
against all structurally-equivalent occurrences" is not a runnable operation. So
a rule can only ever be justified by the file that motivated it — which makes it
a patch wearing a rule's label, and makes per-file review the only remaining
quality mechanism. 1.87 instances per rule is that failure, quantified.

## Four structural defences

Process rules do not survive schedule pressure. These are mechanical.

### 1. The translator reads only from the database

The emitter takes a `method_id` and a rule set. It has no path that reads a
`.cs` file directly. An unpopulated database therefore translates nothing —
skipping ingestion is not possible, it is merely unproductive.

### 2. A rule is not a rule until it has N validated instances

`rule.status` cannot reach `committed` while
`COUNT(rule_instance) < rule.min_instances_required` (default **3**).

A proposed transformation matching one occurrence is recorded honestly as a
`patch`, not a rule, and patches are a tracked metric that must trend to zero.
This is the direct antidote to 1.87.

### 3. The health metric is instances-per-rule, and it is on the dashboard

Not "files translated". `progress_snapshot.instances_per_rule` falling toward 1
means the process has drifted into per-file work, and it is visible the week it
starts rather than at the retrospective.

### 4. Everything is versioned, so regression is attributable

Every row carries `run_id`. Every translation records the exact rule *versions*
that produced it. When a rule goes from v3 to v4 you can ask which translations
were produced by v3 and re-validate exactly those — instead of re-reviewing
everything.

## Schema

SQLite. `run_id` on every table; a run is one ingest of one Renode commit.

### Provenance

```sql
CREATE TABLE corpus_run (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,          -- ISO 8601 with offset
    renode_commit TEXT NOT NULL,
    tool_version  TEXT NOT NULL,          -- ingest tool git describe
    config        TEXT NOT NULL,          -- which corpus cut (F427)
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

### Progress — the honesty table

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
Renode C# (F427 cut)
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

## Cost model

This is the reason for all of the above.

| Approach | LLM invocations | Note |
|---|---|---|
| Per function | ~2,000 (F427) → ~20,000 (full peripheral tree) | What the linux-rs rule track effectively did |
| **Per cluster** | **~200–400, once** | Every subsequent instance is a database query and a template application |

The rules are also **the durable asset**: they carry forward to the other 419
DSL-style peripheral files (208,580 lines) at no additional LLM cost. Per-function
translation carries nothing forward.

**Caveat worth stating plainly:** for the F427 cut alone (~28k lines), this
tooling is more expensive up front than simply hand-translating. It pays off at
the full-tree scale, and it is only worth building because that is the intent.
If the goal were ever narrowed to F427-and-stop, hand-translation would be the
cheaper answer.
