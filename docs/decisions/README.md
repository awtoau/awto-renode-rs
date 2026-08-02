# Decisions

PLAN.md holds the four declared deviations D1–D4. This directory holds
decisions that are **not** one of those four but still bind the whole program —
and, until PLAN.md is reconciled, the record of where PLAN.md and the
implementation disagree.

Rules, in the order they matter:

1. **A decision is a document, not a commit message.** The commit says what
   changed; this says what was chosen, what it costs, and what was rejected.
2. **Every number is a link into `docs/status/`, never a retyped figure.** A
   decision that quotes a count in prose keeps quoting it after it stops being
   true, and reads exactly the same when it does. The scripts that produce
   those files are named in each document.
3. **State the failure mode.** An option list without one is not a decision, it
   is a preference.
4. **Reconciling PLAN.md is the maintainer's act.** An agent that edits
   PLAN.md to match what it just built has removed the disagreement instead of
   resolving it — which is exactly the failure #56 exists to correct.

| # | decision | state |
|---|---|---|
| [#56](inheritance-layout.md) | Inheritance: merge, embed, or a trait | **open — evidence gathered, choice is the maintainer's** |
