-- renode-rs corpus database. Issue #30 (R1).
--
-- Design and rationale: docs/rulesdb-design.md
--
-- The translator reads ONLY from this database -- no code path opens a .cs file.
-- An unpopulated database therefore translates nothing, which is what makes
-- "ingest the corpus first" a structural property rather than a process rule.
--
-- Every row carries run_id. A run is one ingest of one Renode commit, so a rule
-- version bump can re-validate exactly the translations it produced instead of
-- forcing a wholesale re-review.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;      -- concurrent readers during parallel ingest

-- ===========================================================================
-- Provenance
-- ===========================================================================

CREATE TABLE IF NOT EXISTS corpus_run (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT    NOT NULL,   -- ISO 8601 with offset
    finished_at   TEXT,
    renode_commit TEXT    NOT NULL,
    tool_version  TEXT    NOT NULL,   -- ingest tool git describe
    -- Run PURPOSE, not run scope. There is only one scope: the whole Renode
    -- tree (the corpus cut was removed -- docs/decisions/remove-the-cut.md).
    -- 'tree' is the canonical corpus; 'breadth' is a tooling health check
    -- written to a scratch database and refused by every rule/cluster consumer.
    config        TEXT    NOT NULL,
    host          TEXT,
    notes         TEXT
);

-- ===========================================================================
-- Structure, as Roslyn resolves it
-- ===========================================================================

CREATE TABLE IF NOT EXISTS file (
    id     INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    path   TEXT    NOT NULL,          -- relative to the Renode tree root, never absolute
    sha256 TEXT    NOT NULL,
    loc    INTEGER NOT NULL,
    UNIQUE (run_id, path)
);

CREATE TABLE IF NOT EXISTS type (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    file_id       INTEGER NOT NULL REFERENCES file(id),
    -- Roslyn symbol display string: the identity rules join on. Namespace+name
    -- is NOT unique -- nested types collide (several peripherals in the same
    -- namespace each declare a nested `Register` enum), and generic arity is
    -- not captured by name alone.
    key           TEXT    NOT NULL,
    namespace     TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    kind          TEXT    NOT NULL,   -- class|struct|interface|enum|delegate
    base_type_id  INTEGER REFERENCES type(id),
    base_extern   TEXT,               -- base outside the corpus (BCL), when base_type_id is null
    is_abstract   INTEGER NOT NULL DEFAULT 0,
    is_static     INTEGER NOT NULL DEFAULT 0,
    is_generic    INTEGER NOT NULL DEFAULT 0,
    accessibility TEXT    NOT NULL,
    UNIQUE (run_id, key)
);
CREATE INDEX IF NOT EXISTS idx_type_run  ON type(run_id);
CREATE INDEX IF NOT EXISTS idx_type_name ON type(run_id, namespace, name);
CREATE INDEX IF NOT EXISTS idx_type_base ON type(base_type_id);

CREATE TABLE IF NOT EXISTS type_implements (
    run_id         INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    type_id        INTEGER NOT NULL REFERENCES type(id),
    interface_id   INTEGER REFERENCES type(id),
    interface_name TEXT    NOT NULL,  -- always recorded; id is null for BCL interfaces
    PRIMARY KEY (run_id, type_id, interface_name)
);

CREATE TABLE IF NOT EXISTS member (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    type_id       INTEGER NOT NULL REFERENCES type(id),
    key           TEXT    NOT NULL,   -- symbol display string, incl. parameters
    kind          TEXT    NOT NULL,   -- field|property|method|event|ctor
    name          TEXT    NOT NULL,
    declared_type TEXT    NOT NULL,
    accessibility TEXT    NOT NULL,
    is_static     INTEGER NOT NULL DEFAULT 0,
    is_readonly   INTEGER NOT NULL DEFAULT 0,
    -- Does this member actually STORE anything? A computed property (`get { ... }`)
    -- has no backing field, so treating it as state would fabricate storage the
    -- C# does not have. Roslyn answers this via the backing field's
    -- AssociatedSymbol; it is recorded rather than re-derived per consumer.
    has_storage   INTEGER NOT NULL DEFAULT 1,
    -- Constant value, for `const` fields and ENUM MEMBERS. Enum discriminants
    -- are written into registers, so translating an enum without them would
    -- renumber the hardware.
    const_value   TEXT,
    UNIQUE (run_id, key)
);
CREATE INDEX IF NOT EXISTS idx_member_type ON member(type_id);
CREATE INDEX IF NOT EXISTS idx_member_kind ON member(run_id, kind);

CREATE TABLE IF NOT EXISTS method (
    member_id   INTEGER PRIMARY KEY REFERENCES member(id) ON DELETE CASCADE,
    signature   TEXT    NOT NULL,
    return_type TEXT    NOT NULL,
    is_virtual  INTEGER NOT NULL DEFAULT 0,
    is_abstract INTEGER NOT NULL DEFAULT 0,
    is_override INTEGER NOT NULL DEFAULT 0,
    is_extension INTEGER NOT NULL DEFAULT 0,  -- the register DSL is all extension methods
    has_body    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS parameter (
    id          INTEGER PRIMARY KEY,
    method_id   INTEGER NOT NULL REFERENCES method(member_id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    type        TEXT    NOT NULL,
    is_out      INTEGER NOT NULL DEFAULT 0,  -- `out IFlagRegisterField` -- the DSL's core pattern
    is_ref      INTEGER NOT NULL DEFAULT 0,
    is_params   INTEGER NOT NULL DEFAULT 0,
    has_default INTEGER NOT NULL DEFAULT 0,
    -- The default's VALUE, invariant-culture. `has_default` alone said a
    -- parameter was optional without saying what omitting it means, which is
    -- the whole content of an optional argument and of folding a constructor
    -- into `Default`. IParameterSymbol.ExplicitDefaultValue has always had it.
    --
    -- NULL here means EITHER no default OR a default of null; `has_default`
    -- separates them, so (has_default = 1, default_value IS NULL) is `= null`.
    -- A "null" sentinel string would have collided with the literal `"null"`.
    default_value TEXT,
    UNIQUE (method_id, ordinal)
);

CREATE TABLE IF NOT EXISTS local (
    id          INTEGER PRIMARY KEY,
    method_id   INTEGER NOT NULL REFERENCES method(member_id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    type        TEXT    NOT NULL,
    is_captured INTEGER NOT NULL DEFAULT 0   -- closure capture changes the Rust shape
);

-- ===========================================================================
-- Code: the IOperation tree, one row per node. Rules match against this.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS operation (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    -- The MEMBER the code belongs to, not necessarily a method. This referenced
    -- `method(member_id)`, which encoded the assumption that method bodies are
    -- the only code -- a field INITIALISER is code, and it belongs to a field.
    -- The COLUMN NAME stays `method_id` because every query in the tree reads
    -- it and renaming buys nothing; the constraint is what was wrong. A query
    -- that wants methods only should join `method`.
    method_id   INTEGER NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    parent_id   INTEGER REFERENCES operation(id),
    ordinal     INTEGER NOT NULL,   -- position among siblings
    depth       INTEGER NOT NULL,
    kind        TEXT    NOT NULL,   -- IOperation.Kind
    type        TEXT,               -- resolved type; null for statements
    symbol      TEXT,               -- resolved target for invocations/references
    const_value TEXT,               -- literal, when constant
    -- Per-kind facts Roslyn exposes, as JSON. `symbol` was being overloaded for
    -- operator kinds, which does not scale past one extra fact per node.
    -- `dotnet run -- --audit` lists what each kind offers.
    detail      TEXT,
    span_start  INTEGER NOT NULL,   -- source span, for provenance back to the C#
    span_len    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_op_method ON operation(method_id);
CREATE INDEX IF NOT EXISTS idx_op_parent ON operation(parent_id);
CREATE INDEX IF NOT EXISTS idx_op_kind   ON operation(run_id, kind);
CREATE INDEX IF NOT EXISTS idx_op_symbol ON operation(run_id, symbol);

-- ===========================================================================
-- Graphs. This is what makes "where else does this occur?" a query.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS call_site (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    -- A MEMBER, for the same reason as operation.method_id: a field initialiser
    -- calls things (`= Enumerable.Range(0, 8).ToArray()`) and is not a method.
    caller_id     INTEGER NOT NULL REFERENCES member(id),
    callee_id     INTEGER REFERENCES method(member_id),  -- null when outside the corpus
    callee_extern TEXT,             -- BCL/external target name, when callee_id is null
    operation_id  INTEGER NOT NULL REFERENCES operation(id),
    is_virtual    INTEGER NOT NULL DEFAULT 0   -- one row per candidate when virtual
);
CREATE INDEX IF NOT EXISTS idx_call_caller ON call_site(caller_id);
CREATE INDEX IF NOT EXISTS idx_call_callee ON call_site(callee_id);

CREATE TABLE IF NOT EXISTS field_access (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    method_id    INTEGER NOT NULL REFERENCES member(id),   -- see call_site.caller_id
    member_id    INTEGER NOT NULL REFERENCES member(id),
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    is_write     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_facc_method ON field_access(method_id);
CREATE INDEX IF NOT EXISTS idx_facc_member ON field_access(member_id);

-- ===========================================================================
-- Derived analysis: metrics, fingerprints, clusters, and the work queue
-- ===========================================================================

CREATE TABLE IF NOT EXISTS method_metrics (
    method_id      INTEGER PRIMARY KEY REFERENCES method(member_id) ON DELETE CASCADE,
    ast_nodes      INTEGER NOT NULL,
    cyclomatic     INTEGER NOT NULL,
    max_depth      INTEGER NOT NULL,
    n_locals       INTEGER NOT NULL,
    n_calls        INTEGER NOT NULL,
    n_field_reads  INTEGER NOT NULL,
    n_field_writes INTEGER NOT NULL,
    is_leaf        INTEGER NOT NULL,   -- calls nothing inside the corpus
    is_pure        INTEGER NOT NULL    -- fixpoint over the call graph
);

CREATE TABLE IF NOT EXISTS method_fingerprint (
    method_id    INTEGER PRIMARY KEY REFERENCES method(member_id) ON DELETE CASCADE,
    fingerprint  TEXT NOT NULL,        -- normalised structural hash
    norm_version TEXT NOT NULL         -- normalisation algorithm version
);
CREATE INDEX IF NOT EXISTS idx_fp ON method_fingerprint(fingerprint);

CREATE TABLE IF NOT EXISTS pattern_cluster (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    -- 'method'    whole-method shape: how many distinct method shapes exist
    -- 'statement' statement-level idiom: what rules actually match against
    granularity  TEXT    NOT NULL,
    fingerprint  TEXT    NOT NULL,
    member_count INTEGER NOT NULL,
    node_count   INTEGER NOT NULL,   -- AST size of the exemplar
    exemplar_id  INTEGER NOT NULL REFERENCES method(member_id),
    exemplar_op  INTEGER REFERENCES operation(id),   -- set for statement clusters
    UNIQUE (run_id, granularity, fingerprint),
    CHECK (granularity IN ('method','statement'))
);
CREATE INDEX IF NOT EXISTS idx_cluster_size
    ON pattern_cluster(run_id, granularity, member_count DESC);

-- Which cluster each operation belongs to, so a rule proposed from an exemplar
-- can be applied to every sibling by query rather than by search.
CREATE TABLE IF NOT EXISTS cluster_member (
    cluster_id   INTEGER NOT NULL REFERENCES pattern_cluster(id) ON DELETE CASCADE,
    operation_id INTEGER REFERENCES operation(id),
    method_id    INTEGER REFERENCES method(member_id),
    PRIMARY KEY (cluster_id, operation_id, method_id)
);
CREATE INDEX IF NOT EXISTS idx_cluster_member_op ON cluster_member(operation_id);

-- The work queue: leaves first, simplest first within each level. Ordering rule
-- DISCOVERY only -- rule APPLICATION is order-independent and fully parallel.
CREATE TABLE IF NOT EXISTS translation_order (
    method_id  INTEGER PRIMARY KEY REFERENCES method(member_id) ON DELETE CASCADE,
    topo_level INTEGER NOT NULL,   -- 0 = leaves
    rank       INTEGER NOT NULL    -- by ast_nodes within the level
);
CREATE INDEX IF NOT EXISTS idx_order ON translation_order(topo_level, rank);

-- ===========================================================================
-- Rules
-- ===========================================================================

CREATE TABLE IF NOT EXISTS rule (
    id             INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL,
    version        INTEGER NOT NULL,
    family         TEXT    NOT NULL,   -- REGISTER_FIELD, LOCKED_REGION, ...
    description    TEXT    NOT NULL,
    matcher        TEXT    NOT NULL,   -- operation-tree pattern
    emitter        TEXT    NOT NULL,   -- Rust emission template
    status         TEXT    NOT NULL DEFAULT 'proposed',  -- proposed|validated|general|committed|retired
    min_instances_required INTEGER NOT NULL DEFAULT 3,
    requires_human_gate    INTEGER NOT NULL DEFAULT 0,
    created_run_id INTEGER NOT NULL REFERENCES corpus_run(id),
    UNIQUE (name, version),
    -- Defence 2 from docs/rulesdb-design.md, enforced by the schema rather than
    -- by review: a rule cannot claim 'committed' status while its threshold is
    -- unmet. The trigger below checks the instance count.
    --
    -- TWO validated tiers, because there are two different guarantees:
    --
    --   general    >=3 instances ANYWHERE in the corpus. The rule demonstrably
    --              EMITS on real code. It carries NO correctness guarantee,
    --              because the oracle is trace replay and most of the corpus
    --              has no trace -- so a rule matched a thousand times has been
    --              shown to produce plausible output, never correct output.
    --              That is exactly the failure mode of the invented
    --              `.with_reserved(9, 23)`, which survived a 33k-access trace
    --              by being behaviourally inert.
    --
    --   committed  >=3 instances with oracle_tier > 0 -- each one an instance
    --              whose output a trace has actually checked. This is the only
    --              tier that claims the output is right.
    --
    -- Keeping them apart is what lets a wider corpus improve rule GENERALITY
    -- without inflating any number that claims correctness. Blur them and the
    -- coverage metric silently becomes a measure of how much we emitted.
    CHECK (status IN ('proposed','validated','general','committed','retired')),
    CHECK (min_instances_required >= 1)
);

-- Every place the rule matches, found by QUERYING the corpus -- never by hand.
-- This is the operation that was unavailable to linux-rs and the reason its
-- rules stayed one-offs at 1.87 instances each.
CREATE TABLE IF NOT EXISTS rule_match (
    rule_id      INTEGER NOT NULL REFERENCES rule(id) ON DELETE CASCADE,
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    run_id       INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    PRIMARY KEY (rule_id, operation_id, run_id)
);

-- Matches the oracle has actually validated. The count gates commit.
CREATE TABLE IF NOT EXISTS rule_instance (
    rule_id      INTEGER NOT NULL REFERENCES rule(id) ON DELETE CASCADE,
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    validated_at TEXT    NOT NULL,
    -- 0 means "no trace has checked this instance". The commit trigger below
    -- counts only rows above 0, so this column -- not corpus membership -- is
    -- what `committed` is keyed on.
    oracle_tier  INTEGER NOT NULL,
    evidence     TEXT    NOT NULL,
    PRIMARY KEY (rule_id, operation_id)
);

-- Shapes the rule must NOT match. A rule that over-matches is worse than one
-- that under-matches, because the oracle may not catch it.
CREATE TABLE IF NOT EXISTS rule_negative (
    rule_id      INTEGER NOT NULL REFERENCES rule(id) ON DELETE CASCADE,
    operation_id INTEGER NOT NULL REFERENCES operation(id),
    reason       TEXT    NOT NULL,
    PRIMARY KEY (rule_id, operation_id)
);

CREATE TABLE IF NOT EXISTS rule_deviation (
    id            INTEGER PRIMARY KEY,
    rule_id       INTEGER NOT NULL REFERENCES rule(id) ON DELETE CASCADE,
    description   TEXT NOT NULL,
    justification TEXT NOT NULL
);

-- Enforce the commit threshold in the database, not in review.
--
-- `committed` counts only instances with `oracle_tier > 0`: instances whose
-- emitted output a trace has actually checked. A rule may match a thousand
-- times across the tree and still not be committable, because matching is not
-- validation -- the oracle is trace replay, and most of the corpus has no
-- trace.
--
-- This used to count `corpus_run.config <> 'breadth'` instead, i.e. it keyed on
-- WHICH FILES WERE INGESTED rather than on whether anything checked the output.
-- That was already wrong while the cut existed (growing the cut by one file
-- manufactured confidence), and it would have become vacuous the moment the cut
-- was removed, since every canonical run is non-breadth. See
-- docs/decisions/remove-the-cut.md; scripts/check_commit_tier.py proves the
-- new key fires and the old one would not.
CREATE TRIGGER IF NOT EXISTS rule_commit_threshold
BEFORE UPDATE OF status ON rule
WHEN NEW.status = 'committed'
     AND (SELECT COUNT(*) FROM rule_instance ri
          WHERE ri.rule_id = NEW.id AND ri.oracle_tier > 0)
         < NEW.min_instances_required
BEGIN
    SELECT RAISE(ABORT,
        'rule cannot be committed below min_instances_required ORACLE-BACKED instances (oracle_tier > 0) -- a match no trace has checked does not count; record it as a patch, or as general');
END;

-- `general` has a threshold too, just a weaker one: instances from anywhere.
-- Without this a rule could claim generality from a single site, which is the
-- hand-written file wearing a rule's name that this whole schema exists to stop.
CREATE TRIGGER IF NOT EXISTS rule_general_threshold
BEFORE UPDATE OF status ON rule
WHEN NEW.status = 'general'
     AND (SELECT COUNT(*) FROM rule_instance WHERE rule_id = NEW.id)
         < NEW.min_instances_required
BEGIN
    SELECT RAISE(ABORT,
        'rule cannot be general below min_instances_required matches -- one site is a patch');
END;

-- Both of the above fire on UPDATE only, so a rule INSERTED at 'committed' or
-- 'general' walked straight past them. Nothing populates these tables yet, which
-- means the whole population path is still to be written -- and a tool that
-- creates a rule already carrying its status is the obvious way to write it.
--
-- A freshly inserted rule has no rule_instance rows at all (they reference it),
-- so the only correct answer is that no rule may be BORN validated: it earns the
-- status by accumulating instances and then being promoted.
CREATE TRIGGER IF NOT EXISTS rule_insert_status
BEFORE INSERT ON rule
WHEN NEW.status IN ('committed', 'general')
BEGIN
    SELECT RAISE(ABORT,
        'a rule cannot be INSERTED as committed or general -- it has no instances yet. Insert it as proposed and promote it once the threshold is met');
END;

-- ===========================================================================
-- Translation state
-- ===========================================================================

CREATE TABLE IF NOT EXISTS translation (
    id            INTEGER PRIMARY KEY,
    method_id     INTEGER NOT NULL REFERENCES method(member_id) ON DELETE CASCADE,
    run_id        INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    status        TEXT    NOT NULL DEFAULT 'stub',   -- stub|translated|verified
    rule_versions TEXT    NOT NULL DEFAULT '',       -- hash of the exact rule set used
    rust_path     TEXT    NOT NULL,
    rust_symbol   TEXT    NOT NULL,
    code_sha256   TEXT,
    oracle_tier   INTEGER NOT NULL DEFAULT 0,
    -- A hand edit. Not process debt: a hole in the ability to regenerate, which
    -- is the project's main asset. Must trend to zero.
    is_patch      INTEGER NOT NULL DEFAULT 0,
    patch_reason  TEXT,
    UNIQUE (method_id, run_id),
    CHECK (status IN ('stub','translated','verified'))
);
CREATE INDEX IF NOT EXISTS idx_tr_status ON translation(run_id, status);

-- ===========================================================================
-- Progress
-- ===========================================================================

CREATE TABLE IF NOT EXISTS progress_snapshot (
    id                 INTEGER PRIMARY KEY,
    run_id             INTEGER NOT NULL REFERENCES corpus_run(id) ON DELETE CASCADE,
    taken_at           TEXT    NOT NULL,
    git_commit         TEXT,
    n_methods          INTEGER NOT NULL,
    n_stubbed          INTEGER NOT NULL,
    n_translated       INTEGER NOT NULL,
    n_verified         INTEGER NOT NULL,
    n_rules_committed  INTEGER NOT NULL,
    n_patches          INTEGER NOT NULL,
    instances_per_rule REAL              -- THE health metric; null while no rules exist
);

-- Convenience view for the scorecard.
CREATE VIEW IF NOT EXISTS v_health AS
SELECT
    (SELECT COUNT(*) FROM method)                                    AS methods,
    (SELECT COUNT(*) FROM operation)                                 AS operations,
    (SELECT COUNT(*) FROM pattern_cluster)                           AS clusters,
    (SELECT COUNT(*) FROM rule WHERE status='committed')             AS rules_committed,
    (SELECT COUNT(*) FROM rule_instance)                             AS instances,
    (SELECT COUNT(*) FROM translation WHERE is_patch=1)              AS patches,
    CASE WHEN (SELECT COUNT(*) FROM rule WHERE status='committed') > 0
         THEN CAST((SELECT COUNT(*) FROM rule_instance) AS REAL)
              / (SELECT COUNT(*) FROM rule WHERE status='committed')
    END                                                              AS instances_per_rule;
