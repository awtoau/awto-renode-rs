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

## What survived scrutiny

**Implemented 2026-08-03.** The five claims above were verified one at a time
against `STMicroelectronics/cmsis_device_f4`'s `stm32f427xx.h` and RM0090
before any of them was recorded. Two did not survive as written.

**Eight stanzas over three shapes**, in `rulesdb/rules/bug_rules.json`:

| shape | sites |
|---|---|
| `reserved_bits_read_write` | CAN_FMR, CAN_BTR, CAN_FM1R, CAN_FS1R, CAN_FFA1R |
| `status_flag_pinned` | USART_SR.ORE, USART_SR.TXE |
| `wrong_bit_cleared` | CAN_TSR |

`wrong_bit_cleared` was found while verifying the others: `STMCAN.cs:1661`
clears `TERR1` in the branch that tests `TERR0`. The other eight branches of
the same method each clear the bit they test, so the file is its own second
witness that it is a slip.

**Rejected, and why the rejections matter more than the additions:**

- *"`RF0R`/`RF1R` `FMP` and `RFOM` are computed, not stored."* True, and the
  C# is **right**. ST makes `FMP` read-only over the pending count and `RFOM`
  read-as-0; computing them is faithful. No contradicting authority, so it is
  not a bug rule — it is a fact about storage, which the converter already
  reports as a gap.
- *"`BTR`, `FM1R`, `FS1R`, `FFA1R`, `TDxR`, `TSR` are one 32-bit word where ST
  names 3–24 fields."* Rejected **as stated**: a representation claim, not a
  behavioural one. `TDL`/`TDH` genuinely are 32 bits of data. Narrowed, four of
  the six are the reserved-bit defect already recorded, so they became four
  more stanzas of an existing shape rather than a claim of their own. Taken as
  written it would have counted six instances on evidence supporting four.

**Two shapes are under the three-instance threshold** and say so in their own
`below_threshold` field. `wrong_bit_cleared` reaches one site and probably
always will — a copy-paste slip is not a pattern. That is why the count is
visible per shape rather than averaged into the class total.

### Measured switch-impact, not asserted

`scripts/measure_bug_switch.py` regenerates each module with and without
`emit.py --conformance ID`, strips the markers, compares the code, and replays
the traces. **No stanza moves any trace.** can1 stays at 28 and usart1 at 0,
including with all five reserved-bit stanzas switched at once.

That is a weaker result than it looks, and the stanzas say so: the traces never
write the reserved bits, so zero cost is the trace not reaching a difference —
not the trace agreeing there is none. **Every rule is left on fidelity.**

### Conformance is expressible for five of eight

`refine_fields` splits or narrows an emitted slot and covers all five
reserved-bit stanzas. The other three declare `action: unavailable`: `ORE`,
`TXE` and the `TSR` clear are **events**, not layout, and no field-mode change
expresses them. This is the honest partial form of the overturn condition
below — the switch exists and is exercised, and for three stanzas there is
currently nothing to switch to.

### What a bug rule is not

Worth stating because the cross-check that produced these was originally
expected to do more: **a bug rule does not help find or fix a translation
defect.** Our Rust is wrong when it differs from *the C#*, and a datasheet adds
nothing to that comparison — it speaks only where the Rust matches the C# and
both differ from silicon, which is not a translation defect at all. On bxCAN,
**zero of 99 divergences were diagnosed by reading ST**; all 71 that cleared
came from reading `STMCAN.cs`, and so did the 28 that remain.

The value is the one this record already gave: **preventing a wrong "fix."**

## What would overturn it

- Fewer than three instances surviving scrutiny — if the five collapse into one
  or two real defects, this is a patch mechanism wearing a rule's name, which is
  exactly what this project's rules forbid.
- Evidence that conformance mode can never be validated. A switch nothing can
  test is a switch nobody should throw, and the honest form would then be a
  record with no mechanism.
