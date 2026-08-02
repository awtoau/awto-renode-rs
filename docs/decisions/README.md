# Decisions

Whole-program choices, and the reasoning behind them.

PLAN.md's D1–D4 are the original four and stay there. This directory holds the
ones taken since, in the form that made them decidable: what was chosen, what
was rejected, and **what evidence would overturn it**. A decision recorded
without that last part is an opinion with a date on it.

The rule from CLAUDE.md applies to everything here:

> The declared deviations are whole-program decisions; do not make a per-file
> choice that contradicts one, and do not silently revisit one — reopen the
> decision issue.

That rule exists because it was broken: inheritance was implemented as
flattening and argued for as though it were a fresh decision, when PLAN.md line
437 had already decided composition-plus-trait. That is issue #56.

| | decision | status |
|---|---|---|
| [target-one-peripheral-end-to-end](target-one-peripheral-end-to-end.md) | prove behaviour generation on UART before widening | taken 2026-08-02 |
| [audit-cadence](audit-cadence.md) | read the C# beside the Rust, one peripheral per session | taken 2026-08-02 |
