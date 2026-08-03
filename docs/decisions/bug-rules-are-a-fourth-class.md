# Bug rules are a fourth class

**Taken 2026-08-03.** A defect *in the source being translated* is recorded as a
`bug_rule` — data, switchable, with its own evidence and its own test. It is not
a comment, and it is not the same kind of thing as the other three rule classes.

## Why the existing three cannot hold it

| class | answers |
|---|---|
| extraction | what does Roslyn expose? |
| language mapping | how is this C# construct spelled in Rust? |
| project idiom | how is this corpus's DSL spelled in Rust? |

All three answer **"how do I express this construct?"** A bug rule answers a
different question: **"the source is wrong, and I know it."**

Nothing in the first three has a place for that, so it has been going into
prose. Three known instances live in three incompatible forms today — an English
note in `csharp_core.json`, a comment in a hand-written peripheral, and one
agent's report. None is countable, none is switchable, and nothing stops the
next reader "fixing" one and breaking a passing trace.

## The two modes, which cannot both be right

- **fidelity** — reproduce the defect. Required for trace replay: the oracle
  certifies equivalence with Renode's C#, so a "better" translation is a
  **failed** translation.
- **conformance** — emit what the hardware does. Required if this is ever to run
  firmware that Renode gets wrong.

**Fidelity is the default**, because it is what the oracle can check. Conformance
is a deliberate act with a recorded reason, and switching one must be a data
change, not an edit to emitted code.

## What a bug rule carries that an ordinary rule does not

1. **The C# site** — file and line, the defect as it exists.
2. **The contradicting authority** — RM0090 §32, `stm32f427xx.h`, an ST erratum.
   A disagreement with no third source is a *suspicion*, not a bug rule.
3. **Which mode is default**, and why.
4. **Which traces fail if you switch.** This is the field that makes switching
   safe rather than a coin flip, and it is checkable — the traces are right
   there. A bug rule whose switch-impact is unknown is not finished.

## The known instances

Five, which is above this project's three-instance threshold for a rule rather
than a patch. All five were found by reading the C# against ST's headers, none
by any automated check:

- bxCAN: `FMR` bits 1–7 and 14–31 are read-write in Renode; ST says reserved.
  Renode declares them as real fields and reads them back, and the trace
  confirms it.
- bxCAN: `BTR`, `FM1R`, `FS1R`, `FFA1R`, `TDxR`, `TSR` are stored as one 32-bit
  word where ST names 3–24 fields.
- bxCAN: `RF0R`/`RF1R` `FMP` and `RFOM` are computed, not stored.
- UART: `ORE` always reads 0 — the C# assumes no receive overruns.
- UART: `TXE` always reads 1 — the C# assumes the transmit register is always
  empty.

The last two are already recorded, in a doc comment, in a hand-written file that
`check_generated.py` does not own.

## What this is NOT

- **Not a licence to improve.** Fidelity is the default and the oracle enforces
  it. A bug rule makes a deviation *possible and recorded*, never automatic.
- **Not an escape from the central rule.** A landed translation must be
  recreatable from the C# plus committed rules and scripts alone. A bug rule is
  a committed rule, so that still holds — but only while it carries its own
  justification and its own test.
- **Not the WARNING tier.** That marks *"our mapping is narrower than the C#"*.
  This is *"the C# is narrower than the hardware"* — the opposite direction, and
  it needs its own severity rather than borrowing one.

## What would overturn it

- Fewer than three instances surviving scrutiny — if the five collapse into one
  or two real defects, this is a patch mechanism wearing a rule's name, which is
  exactly what this project's rules forbid.
- Evidence that conformance mode can never be validated. A switch nothing can
  test is a switch nobody should throw, and the honest form would then be a
  record with no mechanism.
