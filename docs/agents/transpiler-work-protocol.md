# Working on the transpiler in parallel

Read this before starting any issue labelled `transpiler`.

## The one rule

**We are building a C#-to-Rust transpiler. We are not porting Renode.**

Renode is the corpus that tells us which C# constructs matter. It is the test
input, not the deliverable. Every change must be justifiable to someone
translating a completely different C# codebase.

## What an agent may touch

**One emitter module, and its own rules file. Nothing else.**

    scripts/emitter/lang/<construct>.py       generic C# -> Rust
    rulesdb/rules/lang/<construct>.json       its rules

    scripts/emitter/plugins/<idiom>.py        corpus-specific (Renode)
    rulesdb/rules/plugins/<idiom>.json        its rules

Creating a NEW pair is normal and expected -- a new construct is a new file.
Editing an existing pair is fine when the issue names it.

Everything else is **off limits**:

| do not touch | why |
|---|---|
| `scripts/emitter/core.py` | the dispatch registry; a change affects everyone |
| `scripts/emit.py` | the driver |
| `frontend/RenodeIngest/**` | a schema change forces everyone to re-ingest |
| `src/**/*_registers.rs` | converter OUTPUT, never an input |
| `rulesdb/schema.sql` | same as the ingest |
| another issue's module | the whole point of the split |

One module per agent means two agents never edit one file, and JSON rules
never merge-conflict because nobody shares a file.

## Requesting a master run

Some things only the maintainer does, because they affect every branch at once.
**Ask in the issue thread; do not do them yourself:**

- **Re-ingest** — needed if your construct requires a fact the corpus does not
  record (a Roslyn property we are not reading). Say which property and why.
  These get batched, because everyone must re-ingest together.
- **Regenerate** — the two `*_registers.rs` files are rebuilt from the
  converter after merge. Never commit them; never hand-edit them.
- **Schema change** — as above, and rarer.

If your construct needs an ingest change, that is a finding worth reporting on
its own. Eight have been found so far, and every one was a property Roslyn
already exposed that we were not reading. **None were Roslyn limitations.**

## How to know you are done

1. The named gap no longer appears in the generated file's `GAPS` header.
2. No NEW gap appears.
3. The construct is handled **generally**. Run the corpus query in the issue
   and state how many occurrences now emit. One site is not a rule.
4. The emitted Rust is **compared line by line against the C# it came from**,
   and that comparison is in the PR description.
5. Any difference Rust forces is recorded as a deviation in the rule, with
   reasoning -- never left looking like a faithful translation.
6. The gate passes:

        python3 scripts/check_paths.py
        python3 scripts/check_derived.py
        python3 scripts/check_layering.py
        python3 scripts/check_ingest.py
        cargo test --workspace

## "It compiles" is not evidence

Four bugs so far compiled cleanly and were wrong:

| bug | why it was invisible |
|---|---|
| `base.Reset()` emitted as a self-call | unbounded recursion; rustc accepts it |
| `/* GAP */` left in a loop increment | a comment is a valid statement; infinite loop |
| unmapped return type falling back to `-> ()` | silently dropped every caller's value |
| `16.0` emitted as `16` | f64 division became integer division |

None failed to compile. Read the generated output and compare it to the C#.

## Never edit by string match

Five edits in one session silently did nothing. Four were Python
`str.replace` against an anchor that had moved when `emit.py` was split into
modules; the fifth was a lookup against a key that had become a list entry.

Every one produced the same symptom, which is no symptom: the rule was in the
data, the code path was absent, and a rule with no handler reads exactly like
a rule that correctly declines. Two of them were reported as landed in commit
messages before anyone noticed.

**Use an editor that fails when its anchor does not match.** The remedy is a
tool that cannot silently miss, not a resolution to be careful -- each of
those five cost more to find than the fix cost to make.

The same principle is now enforced where it can be: a normalisation named in
data with no registered handler raises, rather than doing nothing.

## When you cannot do it generally

**Withhold and report a gap.** That is a correct outcome, not a failure.

A reported gap tells the next agent what to pick up. A plausible stub tells
nobody anything -- the `.with_reserved(9, 23)` that was invented by hand
survived a 33,000-access trace and 81% mutation testing, because behaviourally
inert wrong code is invisible to tests.

Never emit something that merely looks finished.

## The layer boundary is enforced

`scripts/check_layering.py` fails the commit if anything under
`scripts/emitter/lang/` or in the generic rules names a corpus construct --
Renode, a peripheral, a register, a bank, a UART.

If your mapping needs to know what a register is, it is a **plugin**, not a
language rule. Prose explaining WHY a mapping exists may cite the corpus; the
emitted template may not.

## Scope discipline

If your issue needs another issue's construct, **stop and say so in the
thread**. Do not implement both.

If you find a transpiler bug outside your module, **file it rather than fixing
it**. A drive-by fix in someone else's module is exactly the conflict this
protocol prevents.
