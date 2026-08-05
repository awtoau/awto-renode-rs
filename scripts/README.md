# Script inventory

`python3 scripts/dev.py` is the supported entry point. Its help and JSON
`describe` output group the maintained scripts below by purpose. A script being
specialised or infrequently run does not make it debris: reproducible research
and negative controls are project evidence.

Scripts are physically organised by category, matching `dev.py`'s own kind
classifier: `core/` (converter and shared library modules), `validation/`
(every `check_*.py` gate plus `compile_check.py`/`prove_postconditions.py`),
`analysis/` (census and other reproducible-research scripts), `oracle/`
(trace acquisition and replay tooling), `reports/` (generated status output).
A handful of top-level entry points (`dev.py`, `gates.py`, `regenerate.py`,
`dispatch_spike.py`, `record_translations.py`, `dump_emitted.py`, `rules.py`)
don't fit one category and stay at `scripts/` directly. `dev.py describe`
discovers commands from every one of these directories, so a script's kind on
the CLI and its physical directory can differ (`check_generated.py` lives in
`core/` because `csharp_emitter.py` itself imports it, but is still a `validation` gate
by kind).

## Entry point and converter machinery (`core/`)

- `dev.py`: canonical command registry and workflow entry point.
- `core/csharp_emitter.py`, `core/emit_pool.py`: converter and deterministic process pool.
- `rules.py`: rule-engine storage and promotion logic.
- `core/register_owners.py`, `core/emitted_modules.py`: shared structural
  queries used by multiple checks and reports.
- `core/parse_repl.py`: `.repl` parser, derives `docs/status/platform.json`.
- `core/check_generated.py`: the `GENERATED` list and the byte-identical diff
  check; lives in `core/` (not `validation/`) because `csharp_emitter.py` imports it
  directly.
- `regenerate.py`: rewrites every converter-owned generated file.
- `gates.py`: bounded-CPU validation orchestrator.
- `gates.py --fail-fast`: stop on first failure for quick triage/fix loops.
- `dev.py ci-fast`: full push-tier (`--full`) run with fail-fast enabled.
- `dev.py ci-determinism`: explicit issue-36 determinism proof run
  (`check_determinism.py` then `check_emit_determinism.py`).

## Validation (`validation/`)

Every `check_*.py` script is a maintained regression check. This includes the
expensive CI-only determinism checks and `check_refactor.py`, which now
verifies byte-identical artefacts against a current baseline; refresh that
baseline intentionally with `python3 scripts/validation/check_refactor.py
--record` after an intended output change. `compile_check.py` is the Rust
compile census and `prove_postconditions.py` is the deliberate negative
control for postconditions.

## Analysis and reproducible research (`analysis/`)

- Core pipeline/corpus: `analyse_corpus.py`, `census.py`, `gap_census.py`,
  `floor_census.py`, `prescan.py`, `oracle_coverage.py`.
- Register shapes: `audit_anon_fields.py`, `census_case_bodies.py`,
  `census_handrolled_registers.py`, `census_memory_mapped.py`,
  `query_local_builders.py`.
- Language/runtime decisions: `inheritance_census.py`, `interface_census.py`,
  `semantic_differences_census.py`, `sync_census.py`.

These scripts retain value because they regenerate measurements cited by issue
and decision documents. They are analysis commands, not everyday gates.

## Oracle and traces (`oracle/`)

- `baseline_boot.py`, `capture_traces.py`: acquire the C# reference evidence.
- `analyse_divergences.py`, `diagnose_trace.py`: explain trace failures.
- `measure_bug_switch.py`, `mutate.py`: negative controls and oracle strength.
- `verify_emit.py`: compare hand-written translations with converter output.

## Reporting and generated evidence (`reports/`)

- `reports/scorecard.py`, `reports/progress_graph.py`,
  `reports/issue_index.py`: project status output.
- `record_translations.py`: generated translation records.
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
