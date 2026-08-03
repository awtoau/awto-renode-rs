# #52 status — interleaving oracle built; runtime measurement blocked

GitHub issue #52 remains open, and that status is correct.

## Acceptance

| requirement | verdict |
|---|---|
| Contention and hold times measured at marked sites on a real workload | **Not met.** No runnable translated machine currently instantiates and drives a lock-bearing peripheral. Static critical-section size is not a timing measurement. |
| Written verdict on D3, with `PLAN.md` reconciled | **Interim verdict met; final verdict not met.** Do not enact D3: preserve locks as `Mutex` pending runtime evidence. `PLAN.md` now records that operational decision. The final keep/remove verdict still requires the missing measurements. |
| An oracle tier that observes interleaving, or an explicit uncertified scorecard statement | **Met.** `renode-sync` provides deterministic tier-2.5 exploration; `scripts/check_sync_harness.py` proves it fails when locks are deleted; `scripts/scorecard.py` says threading is uncertified. |

## Current measurements

- Full-tree static census: **842 lock sites**, re-derived with
  `python3 scripts/sync_census.py --db tmp/breadth.db`.
- Distinct lock-target keys: **205**, including unresolved operation shapes
  that the static corpus cannot name as fields.
- Emitted translated lock sites: **0**; the only `SYNC(measure)` marker under
  `src/` is the example inside `renode-sync` itself.
- Runtime contention and hold time: **not measured**. Reporting zero would be
  misleading because the current architecture cannot run the required shared
  peripheral workload.

## Close condition

Integrate a translated lock-bearing peripheral into a runnable machine, decide
which host threads can reach it, instrument the marked critical sections, run a
representative workload, and record contention and hold-time distributions.
Then use those measurements to settle D3 and update the plan with the final
verdict.
