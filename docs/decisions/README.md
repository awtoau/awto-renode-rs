# Decisions

PLAN.md holds the four declared deviations D1–D4. This directory holds decisions
that are **not** one of those four but still bind the whole program — and, until
PLAN.md is reconciled, the record of where PLAN.md and the implementation
disagree.

Rules, in the order they matter:

1. **A decision is a document, not a commit message.** The commit says what
   changed; this says what was chosen, what it costs, and what was rejected.
2. **Every number is a link into `docs/status/`, never a retyped figure.** A
   decision that quotes a count in prose keeps quoting it after it stops being
   true, and reads exactly the same when it does. The scripts that produce those
   files are named in each document.
3. **State the failure mode.** An option list without one is not a decision, it
   is a preference.
4. **Say what would overturn it.** A decision recorded without that is an
   opinion with a date on it.
5. **Reconciling PLAN.md is the maintainer's act.** An agent that edits PLAN.md
   to match what it just built has removed the disagreement instead of resolving
   it — which is exactly the failure #56 exists to correct.

The rule from CLAUDE.md governs everything here:

> The declared deviations are whole-program decisions; do not make a per-file
> choice that contradicts one, and do not silently revisit one — reopen the
> decision issue.

It is in this repo because it was broken: inheritance was implemented as
flattening and argued for as though it were a fresh decision, when PLAN.md line
437 had already decided composition-plus-trait.

| # | decision | state |
|---|---|---|
| — | [remove the corpus cut; retier `committed` on `oracle_tier`](remove-the-cut.md) | taken 2026-08-02 |
| [#56](inheritance-layout.md) | inheritance: dispatch trait + collision guard | **taken 2026-08-02** — merge-vs-embed deliberately deferred until the cut is closed |
| — | [prove behaviour generation on UART before widening](target-one-peripheral-end-to-end.md) | taken 2026-08-02 |
| — | [read the C# beside the Rust, one peripheral per session](audit-cadence.md) | taken 2026-08-02 |
| — | [define a build target: the floor that runs, and a named Renode Robot test as its acceptance criterion](the-floor-that-runs.md) | taken 2026-08-03 |
| — | [logging: `Logger.*Log` maps to Rust's `log` crate facade](logging-facade.md) | taken 2026-07-31, **backfilled** 2026-08-03 |
