# Script inventory

`python3 scripts/dev.py` is the supported entry point. Its help and JSON
`describe` output group the maintained scripts below by purpose. A script being
specialised or infrequently run does not make it debris: reproducible research
and negative controls are project evidence.

## Entry point and converter machinery

- `dev.py`: canonical command registry and workflow entry point.
- `emit.py`, `emit_pool.py`: converter and deterministic process pool.
- `rules.py`: rule-engine storage and promotion logic.
- `register_owners.py`, `emitted_modules.py`: shared structural queries used by
  multiple checks and reports.
- `regenerate.py`: rewrites every converter-owned generated file.
- `gates.py`: bounded-CPU validation orchestrator.

## Validation

Every top-level `check_*.py` script is a maintained regression check. This
includes the expensive CI-only determinism checks and `check_refactor.py`, which
now verifies byte-identical artefacts against a current baseline; refresh that
baseline intentionally with `python3 scripts/check_refactor.py --record` after
an intended output change. `compile_check.py` is the Rust compile census and
`prove_postconditions.py` is the deliberate negative control for postconditions.

## Analysis and reproducible research

- Core pipeline/corpus: `analyse_corpus.py`, `census.py`, `gap_census.py`,
  `floor_census.py`, `prescan.py`, `oracle_coverage.py`.
- Register shapes: `audit_anon_fields.py`, `census_case_bodies.py`,
  `census_handrolled_registers.py`, `census_memory_mapped.py`,
  `query_local_builders.py`.
- Language/runtime decisions: `inheritance_census.py`, `interface_census.py`,
  `semantic_differences_census.py`, `sync_census.py`.

These scripts retain value because they regenerate measurements cited by issue
and decision documents. They are analysis commands, not everyday gates.

## Oracle and traces

- `baseline_boot.py`, `capture_traces.py`: acquire the C# reference evidence.
- `analyse_divergences.py`, `diagnose_trace.py`: explain trace failures.
- `measure_bug_switch.py`, `mutate.py`: negative controls and oracle strength.
- `verify_emit.py`: compare hand-written translations with converter output.

## Reporting and generated evidence

- `scorecard.py`, `progress_graph.py`, `issue_index.py`: project status output.
- `parse_repl.py`, `record_translations.py`: generated platform/translation
  records.
- `dispatch_spike.py`: despite its historical name, this is maintained; it
  regenerates `docs/status/dispatch.json` cited by current decision documents.

## Inspection tools

- `dump_emitted.py`: write emitted modules under `tmp/out/` for human review.

## Historical debris

Scripts that provably depend on removed inputs live in `debris/scripts/`, not
on the supported `dev.py` command surface. See its README. No `one_off_test/`
directory is currently warranted: the apparent candidates are maintained
negative controls or evidence generators, and moving them there would hide
their continuing role.
