TITLE: Facts the corpus records and the converter does not read

Four small, independently verifiable omissions. Grouped because they share one
shape: **Roslyn already gave us the answer and nothing read it.** Eight ingest
gaps have been found this way before, and none was a Roslyn limitation.

## 1. Six of twelve `FieldMode` members are silently discarded

`FIELD_MODE` maps Read, Write, Set, Toggle, WriteOneToClear, WriteZeroToClear.
C# also declares `ReadToClear`, `WriteZeroToSet`, `WriteZeroToToggle`,
`ReadToSet`, `WriteToClear`, `WriteToSet`. `render_mode` drops unmapped bits
without comment.

`ReadToClear` alone renders as `FieldMode::default()` -- a field that ignores
reads AND writes. `Read|ReadToClear` renders as `READ`, losing clear-on-read,
which is a real hardware behaviour and a common interrupt-status idiom.

2 sites in the cut (`NVIC`, `STM32F1_I2C`); neither is in the seven files today,
so this is latent rather than active. `renode_regs::FieldMode` has no constants
for these either. There is no assertion anywhere that every C# mode bit maps.

## 2. Dictionary-form registers always get reset value 0

`register_forms`' `DICTIONARY_ADD` sets `"reset_from": null`, so `find_registers`
leaves `reset = "0"`. C# `new DoubleWordRegister(this, resetValue)` carries it.

82 such constructions in the cut; **11 pass a non-zero reset** -- STM32_CRC
(0xFFFFFFFF, 0x04C11DB7), STM32F4_RCC (5, e.g. 0x24003010), STM32F4_RTC (4,
e.g. 0x2101). Not yet exercised: the two dictionary-form peripherals emitted so
far both use `new DoubleWordRegister(this)`. When the others land, those
registers read back 0 instead of their hardware default.

## 3. Field-handle arrays are sized by usage, not by declaration

`adc_registers.rs` emits `[ValueId; 16]` where the C# declares
`new IValueRegisterField[19]`. The array is sized as *highest bound index + 1*,
while the comment beside it says the size is the declaration's.

The declared length is in the corpus, as the field initialiser's
`ArrayCreation` -- `plugins/sub_blocks.py` already reads exactly that shape via
`const_under`.

## 4. `mod reg` claims to be the C# enum and is only the emitted subset

The doc comment says "Register offsets, from the C# `enum Register`". It holds
only the registers that emitted: UART omits `GuardTimeAndPrescaler = 0x18`, ADC
emits 13 of 20, SYSCFG 1 of 30.

Non-behavioural, but the file states something it is not, which is the one
thing generated output may never do.

## Acceptance

- Every C# `FieldMode` member maps, or the emission is withheld with a gap
- Dictionary-form registers carry their reset value; the 11 sites verified
- Handle arrays sized from the declaration, with the 16-vs-19 case as the test
- `mod reg` either holds every enum member or says what it holds
