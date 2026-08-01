# What exists today, and what #35 still has to build

Written because the two are easy to confuse. The converter emits real Rust from
rules held as data, so it *looks* like the rule engine is built. It is not, and
the missing half is the half that measures.

## What exists

A **hand-authored, rule-driven emitter**.

- Rules live as data in `rulesdb/rules/*.json`, split by layer: `csharp_core.json`
  is generic C#, the rest are corpus idioms.
- `scripts/emit.py` reads them and emits a peripheral when pointed at one.
- Constructs it cannot handle are **withheld and reported by name**, never
  stubbed.
- `scripts/check_generated.py` proves the output is reproducible from rules
  alone, byte for byte.

That is genuinely rule-driven: adding a construct is a data change plus an
emitter module, not a per-file edit. The breadth run is evidence it generalises
— ten peripherals nobody had looked at emitted from rules written for two
others.

## What does not exist

Everything in `rule`, `rule_instance`, `rule_match` and `pattern_cluster`. All
four tables are **empty**, and five things in #35 are unbuilt:

| # | missing | consequence |
|---|---|---|
| 1 | a matcher over the operation **tree** | today's matching is symbol-substring and kind checks |
| 2 | `rule_match` populated **by querying the corpus** | we have never asked "where else does this rule apply?" |
| 3 | `rule_negative` — shapes a rule must NOT match | nothing guards against a rule over-matching |
| 4 | cluster → one LLM call per cluster → propose a general rule | every rule so far was written by hand after reading the C# |
| 5 | the DB lifecycle `proposed → validated → committed` | no rule has a recorded status |

### The consequence that matters

**Nothing computes instances-per-rule**, and CLAUDE.md calls that the headline
metric — the one that shows drift into per-file work "the week it starts".

So the project currently *cannot detect* the failure mode it was designed to
avoid. `linux-rs` reached 1.87 instances per rule while "38 TUs translated"
still looked healthy; we would not currently see that happening. The scorecard
reports "no committed rules" rather than papering over it, which is the honest
position but not a substitute for the measurement.

## `gap_census.py` is a partial step toward #35 step 2

It already does the corpus-wide half:

- queries the corpus for every type with a register-defining method
- runs the emitter over **all** of them (569 across the tree, 25 in the cut)
- classifies what stopped it, and ranks **root causes** by how many gaps each
  one blocks

What it does **not** do is the recording half: it writes nothing to
`rule_match`, associates no result with a rule, and validates nothing against
the oracle. It answers "what is blocked, and by what" — not "where does rule R
apply, and is R correct at each site".

Turning it into step 2 means keeping the traversal and adding the bookkeeping.
The traversal is the part that was unclear; it works and it is fast.

## When the ≥3 threshold gets its first real test

**Not now.** `min_instances_required` defaults to 3 and is enforced by triggers
in `rulesdb/schema.sql`, but with `rule_instance` empty it currently blocks
nothing.

It bites the first time #35 lands and the roughly thirty rules now in JSON are
migrated into the `rule` table with their instances. That migration is a task
of #35, not a separate cleanup, and it is the moment to find out which rules
genuinely generalise:

- a rule matching ≥3 validated sites **in the cut** → `committed`
- a rule matching ≥3 sites **anywhere**, breadth included → `general` (emits,
  correctness unverified — see decision D5, issue #51)
- a rule matching one site → a **patch**, counted on the scorecard and required
  to trend to zero

Expect some of the thirty to fail the threshold. That is the mechanism working,
not a setback: a rule that matches one site is a hand-written file wearing a
rule's name, and recording it as a patch is what keeps the leverage measurement
truthful.

D5 makes the threshold much cheaper to clear than it was — instances may now
come from 448k lines rather than the cut's 20k — so the failures that remain
after migration are informative rather than an artifact of a small corpus.
