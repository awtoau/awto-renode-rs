# Remove the corpus cut

**Taken 2026-08-02.** `frontend/RenodeIngest/CorpusCut.cs` goes. The ingest reads
the whole tree.

## What the cut was for

CLAUDE.md: *"Breadth discovers; only the cut validates."* Two tiers, enforced by
triggers rather than review:

| tier | threshold | guarantee |
|---|---|---|
| `general` | ≥3 instances anywhere, breadth included | emits on real code; correctness unknown |
| `committed` | ≥3 instances **in the cut**, each oracle-backed | the output is right |

The cut was the mechanism separating "a rule emits" from "a rule is right".

## Why it is being removed

**1. The mechanism it protects has never run.** `rule`, `rule_instance` and
`rule_negative` all hold **zero rows**. The rules live in `rulesdb/rules/*.json`;
the tiering is vestigial.

**2. The trigger does not do what it claims.** `rulesdb/schema.sql:338` counts
instances where `corpus_run.config <> 'breadth'` and **never reads
`oracle_tier`** — a column on the same table, line 304. So the tier already keys
on *which files were ingested* rather than on *whether a trace backs the
output*. Growing the cut by one file would have manufactured confidence; the
cut-closure analysis found this independently.

**3. It is a proxy for the wrong thing.** Trace availability is a fact about
which peripherals have recorded traces. It is not a fact about which files an
ingest walked. Removing the cut deletes no trace and weakens no oracle.

**4. It is measurably costing correctness.** It is hand-typed and not
transitively closed — it contains types whose base classes and base interfaces
it lacks, and `CorpusCut.cs` states the principle ("omitting a base is the same
omission as omitting a called method") while applying it exactly once, by hand.
Measured consequences:

- 69% of inheritance chains truncated; 79% of base-access sites reach a base the
  corpus cannot see
- 61 of 73 cascade-blocked interface members trace to `IPeripheral`, withheld
  only because two **member-less marker interfaces** were never ingested
- 114 of 126 interface declarations unresolved, including the one dispatch
  actually goes through
- two real field collisions (`STM32_Timer.initialLimit`, `CortexM.Clustered`)
  invisible, which is why #56's layout half had to be deferred

## The prerequisite, and it lands with the removal

**Retier on `oracle_tier`, not on corpus membership.** Delete the cut while the
trigger still counts `config <> 'breadth'` and every run becomes non-breadth, so
`committed` silently starts meaning nothing — the exact confidence-manufacturing
the two tiers exist to prevent, arriving through the front door.

After the change `committed` means *"≥3 instances whose output a trace has
checked"*, which is what was always wanted and is strictly stronger than what
the cut delivered.

## What is NOT changed

- **The oracle is untouched.** 24 traces, the same 8 replaying, the same
  peripherals. Nothing about what has been validated changes.
- **`--all` as a tooling health check stays.** Breadth found the `partial void`
  gap; a run that crashes or loses data is still a bug in our tooling.
- **Withholding stays.** A converter that cannot emit something reports a gap.
  A larger corpus means more gaps, and that is the correct result, not a
  regression.

## What this costs

- ~448k lines instead of 21,620; ~26,159 methods instead of 1,564
- Every ratchet rebases: compile errors, the gap census, the trace table's
  denominators, `compile_check`'s module count
- `compile_check` emits every type it can; that becomes a much larger crate
- The distinction between "in the corpus" and "worth emitting" now has to be
  made explicitly, by the emitter, rather than implicitly by the ingest

## What would overturn it

- Evidence that the whole-tree ingest is slow enough to stop being run every
  iteration. Conversion wall-clock is the iteration speed, and a corpus nobody
  re-ingests is a stale corpus.
- A tiering need the `oracle_tier` key cannot express.
