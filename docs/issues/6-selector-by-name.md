TITLE: the register-method selector is a name match, and both of its failure modes are silent

Diagnosed while investigating `can1` -- the worst row on the generated-trace
scoreboard, 99 divergences over 115 reads, 13.9%. **The cause is not in `can1`.**
It is the selector, and `STMCAN` is one of seven types it mishandles.

Reproduce: `python3 scripts/census_memory_mapped.py`

## The selector

Three tools share one query -- `compile_check.py`, `check_emitted_registers.py`
and `emitted_modules.py` -- and it picks a type's register-defining method by
NAME:

    SELECT t.name, MIN(mb.name) ... WHERE mb.name LIKE '%Register%'
                                       OR mb.name LIKE '%DefineReg%'

`MIN` over names is alphabetical order, which is not a property of anything.

## Failure one: it keeps types that define no registers

`STMCAN` has **zero** register-combinator calls -- not in `STMCAN`, not in its
nested `FilterBank`, not in its nested `DeviceRegisters`. It hand-rolls a
register per nested class with `SetValue(uint)`/`GetValue()` over `bool` fields
and `const uint` masks, and dispatches with `switch((RegisterOffset)offset)`
inside `ReadDoubleWord`. There is no DSL to translate.

The selector nevertheless picks `AddressIsWithinFilterRegistersArea` -- a
`bool` predicate, alphabetically first among the two members whose names contain
"Register" (the other is the field `registers`). So a module IS emitted, with

    pub mod reg { }
    pub struct Fields { }
    pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) { }

and **none of its 40 header gaps says the type defines no registers**. The
project's own rule -- a path that emits nothing must say why -- is broken here,
and the path is a whole peripheral.

`check_emitted_registers.py` cannot catch it. That check asks "the corpus says N
combinator calls, the converter emitted M registers, is N > 0 and M == 0?" For
`STMCAN`, N is 0, so it passes.

Corpus-wide: **388 types serve a memory-mapped bus** (`ReadDoubleWord`/`ReadWord`/
`ReadByte` with a body), **284 use the register DSL and 104 do not**. All 104 are
invisible to that check. For 7 of them the name selector still picks a method,
so each emits a silent empty module:

    BusControllerProxy   IRegisterablePeripheral<...>.Unregister
    EHCIHostController   Register
    EmulatorController   GetCurrentStringRegister
    ISP1761              Register
    PL050                HandleStatusRegister
    STMCAN               AddressIsWithinFilterRegistersArea
    VersatilePCI         Register

## Failure two: it drops types that do define registers

Already recorded in `check_emitted_registers.py`'s docstring -- a register
collection built in a constructor rather than a named method matches nothing.

## Both are one fix, and half of it is already in the tree

`plugins/sub_blocks.child_register_method` finds a child's register method **by
trying**, not by name: it runs `find_registers` over each member and keeps the
one that yields registers. Its docstring already says why -- "matching on a name
would make the rule fit one corpus".

Running that same test over every member WITH A BODY, constructors included,
resolves both directions at once. Measured:

| type | name selector | `find_registers` over all members |
|---|---|---|
| STM32_UART | DefineRegisters | DefineRegisters |
| STM32_GPIOPort | CreateRegisters | CreateRegisters |
| STM32_ADC | DefineRegisters | DefineRegisters |
| STM32DMA | DefineRegisters | DefineRegisters |
| STM32F4_RCC | *dropped* | `.ctor`, 24 registers |
| STM32F4_RTC | *dropped* | `.ctor`, 20 registers |
| STM32_RNG | *dropped* | `.ctor`, 4 registers |
| STM32_CRC | *dropped* | `.ctor`, 5 registers |
| STM32_Timer | Register *(empty)* | `.ctor`, 12 registers |
| STMCAN | AddressIsWithin... *(empty)* | none -- correctly declines |
| the other 6 above | *(empty)* | none -- correctly declines |

It agrees with all four methods currently hardcoded in `check_generated.py`,
recovers five peripherals, and declines all seven non-DSL types.

Note `child_register_method` as written scans `mb.kind = 'method'` only, so it
would still drop the five constructor peripherals. That restriction is the one
line that has to change.

## What this does NOT fix

`can1` does not improve. A selector that correctly declines `STMCAN` turns 99
silent divergences into 99 divergences plus a gap that explains them -- which is
the right state, and not a better number.

Translating `STMCAN` at all needs the hand-rolled-register idiom, and that is a
separate and much larger question: the idiom appears **twice** in 448k lines
(`STMCAN`, and `EHCIHostController`/`ISP1761` under `USBDeprecated`). A plugin
matching two sites is what CLAUDE.md calls a hand-written file wearing a rule's
name. Do not build it to move this row.

### CORRECTION -- the paragraph above drew the boundary too tight

It is right about the *accessor class*: `GetValue()`/`SetValue(uint)` over
`const uint` masks occurs in **3** types corpus-wide (`STMCAN`,
`EHCIHostController`, `ISP1761`), which is the project's threshold and no more.

It is wrong that this is all there is. That idiom is only the FIELD half of the
shape. The OFFSET half -- a bus method dispatching a `switch` whose case clauses
are all compile-time constants -- occurs in **59 of the 104**, 50 on a cast
offset and 9 on the raw parameter (`scripts/census_handrolled_registers.py`).
And a third rule sits between them: a case body that reads a plain field is a
full-width storage register, and that is **145 case bodies across 27 types**
(`scripts/census_case_bodies.py`). Three rules, not one, so the narrow one
cannot borrow the broad ones' counts.

Built as `rulesdb/rules/offset_switch.json` +
`scripts/emitter/plugins/offset_switch_registers.py`. Measured reach
(`scripts/check_offset_switch.py`): **30 of the 104 types now yield a register
map -- 144 registers, 188 fields**; 74 decline WITH a gap saying so; none
raises; none is silent. `can1` went 99 divergences to **28**, 13.9% to 75.7%.

The census that made the difference is the second one. The first counted types
and said 104; that number alone justifies nothing, because 104 types sharing no
shape are 104 special cases. Asking what the case BODIES do is what separated a
rule family from a special case, and it also confirmed which half of the
original claim was correct.

The acceptance criterion "a memory-mapped type that yields no registers emits a
GAP saying so" is now met on the EMIT side for all 104: a type with a bus read
method and no constant-case switch reports `no register map could be found`,
and a case body that computes rather than stores reports which case and why.

Nothing here touches the selector, which landed separately as the by-content
change. The two are independent and compose: the selector decides WHICH method
is asked, and these rules decide what a method that uses no DSL yields. STMCAN
is the case where the selector's answer used to be a `bool` predicate picked in
alphabetical order and the emitter had nothing to say about it either way.

## Acceptance

- The selector is `find_registers`-based, over every member with a body
- A memory-mapped type that yields no registers emits a GAP saying so, and is
  not silently emitted as an empty module
- `check_emitted_registers.py` keys on "serves a bus" as well as "calls
  combinators", so the 104 stop being invisible
- `scripts/census_memory_mapped.py` reports 0 in its "silent empty module" list
