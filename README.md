# awto-renode-rs

A general, rule-driven C#-to-Rust transpiler. Renode supplies the current corpus
and differential oracle; it is not encoded into the language layer.

## Development commands

One entry point owns every supported operation:

```text
python3 scripts/dev.py --help
python3 scripts/dev.py describe
```

The primary workflows are:

```text
python3 scripts/dev.py build          # compile clean set + diff (fast, ~19s)
python3 scripts/dev.py regenerate     # rewrite converter-owned Rust
python3 scripts/dev.py test           # cargo test --workspace
python3 scripts/dev.py gate           # parallel everyday checks
python3 scripts/dev.py gate --fail-fast
python3 scripts/dev.py ci             # parallel full push-tier corpus checks
python3 scripts/dev.py ci --fail-fast
python3 scripts/dev.py ci-fast        # alias for ci --fail-fast
python3 scripts/dev.py report         # STATUS.md plus SVG and HTML
python3 scripts/dev.py cycle          # build -> ci -> report
python3 scripts/dev.py cycle --dry-run
```

Gate scheduling uses at least 32 workers, or the detected logical-CPU count when
that is higher. Explicit overrides must also be at least 32:

```text
python3 scripts/dev.py gate --jobs 32
python3 scripts/dev.py ci --jobs 64
```

All other checked-in Python tools are also registered as subcommands and appear
in `describe`; their underlying files are implementation details.

`codex` assembles briefs using the canonical rules from `awto-dan`, adds
[the project clauses](docs/codex-project.md), and runs only in an isolated
worktree. Set `AWTO_DAN` when that checkout is not beside this repository:

```text
python3 scripts/dev.py codex --work "implement issue 46" \
  --issue 46 --repo awtoau/awto-renode-rs --cd .claude/worktrees/issue-46
```
