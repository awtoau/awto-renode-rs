# A register located through the dictionary form always resets to 0

Labels: `transpiler`, `bug`, `phase-3`

Found while fixing the register-owner selector (`scripts/register_owners.py`).
The selector change is what exposed it: the peripherals that build their
register map in a constructor had never been emitted, and every one of them
uses the dictionary form.

## What happens

`rulesdb/rules/register_dsl.json` declares two register forms. One reads a
reset value and the other does not:

    DEFINE_EXTENSION   symbol_contains ".Define("            reset_from "resetValue"
    DICTIONARY_ADD     symbol_contains "Dictionary<..>.Add"  reset_from null

`RegisterDsl.find_registers` therefore does

    reset = "0"
    if form.get("reset_from"): ...

and a register reached through `map.Add(offset, new DoubleWordRegister(this, X))`
emits `bank.define(reg::NAME, 0)` for every X.

## Why it is invisible

Nothing reports it. There is no gap, no warning and no unmatched call: the form
matched, the register was located, its fields emitted, and the one number that
came out wrong is a literal in the emitted line. `check_reset_bits_reserved.py`
compares the Rust read-after-reset against the C# read-after-reset **using the
same parsed reset value for both**, so it agrees with itself.

This is the `.with_reserved(9, 23)` shape of defect again -- output that reads
as finished and is wrong in a way no current check is looking at.

## Evidence

`STM32F4_RCC`, emitted from its `.ctor`:

| register | C# | emitted |
|---|---|---|
| ClockControl | `new DoubleWordRegister(this, 0x483)` | `bank.define(reg::CLOCK_CONTROL, 0)` |
| PLLConfiguration | `new DoubleWordRegister(this, 0x24003010)` | `..., 0)` |
| ClockControlAndStatus | `new DoubleWordRegister(this, 0x0E000000)` | `..., 0)` |
| PLLI2SConfiguration | `new DoubleWordRegister(this, 0x24003000)` | `..., 0)` |
| PLLSAIConfiguration | `new DoubleWordRegister(this, 0x24003000)` | `..., 0)` |

`STM32_CRC` loses `DefaultInitialValue` (0xFFFFFFFF) and `DefaultPolymonial`
(0x04C11DB7) the same way.

Corpus-wide: **462 register constructions across 88 types** pass a non-zero
literal reset value. Those reached through `.Define(resetValue: X)` are fine;
every one reached through a dictionary is not.

## Where the value is

The chain root of a `DICTIONARY_ADD` register is the `ObjectCreation` in the
`value` argument, and its second `Argument` is the reset. Roslyn materialises
the C# default, so the argument is present even when the source writes
`new DoubleWordRegister(this)` -- its `const_value` is then 0, which is the
right answer rather than a missing one.

So the fix is a form that can say "the reset is a constant inside the chain
root", not a new ingest fact. Nothing needs re-ingesting.

## The check that should exist either way

A form with no `reset_from` whose chain root carries a non-zero constant in a
reset position should be a **gap**, not a silent zero. A wrong reset value that
nothing reports is worse than a register that refuses to emit.
