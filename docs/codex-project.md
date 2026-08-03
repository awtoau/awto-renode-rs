# Codex project clauses

This repository builds a general, rule-driven C#-to-Rust transpiler. Renode is
the corpus and differential oracle, not the deliverable.

- Change the emitter or rule data; never hand-edit generated Rust.
- Match rules on corpus facts, never peripheral, register, or type names.
- Withhold and report unsupported output instead of emitting a plausible guess.
- The sandbox has no network. Do not re-ingest, run `gh`, or fetch dependencies.
- Before finishing, run `python3 scripts/dev.py gate`. Generated files must stay
  byte-identical and committed trace-divergence ratchets must not rise.
