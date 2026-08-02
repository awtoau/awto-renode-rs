TITLE: Register DSL families the rule table does not cover

The combinator table names ONE extension class and ONE binding shape. Four
families fall outside it. Until 2026-08-02 every one was dropped in silence;
they now report, but the capability is still missing.

## The four

**1. Instance methods, not extension methods.** `reg.DefineValueField(pos, w,
name:, changeCallback:)` is an instance method on `DoubleWordRegister`.
`combinator()` returns None and the call is skipped.
Cost: **STM32_SYSCFG's entire register map.** `define_registers` was `{}`, an
offset constant was declared and never used, and the file reported four gaps,
none about registers. Four registers, sixteen 4-bit EXTICR mux fields.

**2. Plural combinators with a callback and no `out`.** `WithValueFields` /
`WithEnumFields` bound by callback rather than by `out` match no rule --
`register_forms` has only `WITH_FIELDS_BOUND` (`"when": "field"`), with no
computed counterpart.
Cost: **five of STM32_GPIOPort's eleven registers** -- Mode, OutputSpeed,
PullUpPullDown, AlternateFunctionLow, AlternateFunctionHigh. Corroborated by
five dead-callback `never used` warnings, buried in 123 warnings that nothing
gates on. gpioPortA diverges at exactly 0x0, 0x8 and 0xC.

**3. Register-level callbacks.** `.WithWriteCallback(...)` resolves to
`DoubleWordRegisterExtensions`, a different extension class.
Cost: 18 sites. In STM32_UART the two dropped callbacks sit on registers whose
flags are WriteZeroToClear, so an ISR clearing RXNE/TC never recomputes the IRQ
line and it stays asserted. usart1 replays 33,164 accesses at 100% because a
trace cannot observe an IRQ.
Note: a `REGISTER_CALLBACK` rule EXISTS in the data, with gap text that has
never appeared in any generated file -- a rule with no reachable code path.

**4. Callback kinds never inspected at all.** `emit_call` looks only at
`valueProviderCallback` and `writeCallback`. The corpus records `changeCallback`
(19 sites), `readCallback` (6), `shadowReloadCallback` (4) and
`softResettable: false` (6) as fully bound arguments with `DelegateCreation`
inner operations. Nothing about the ingest prevents reading them.
Cost: writing ADON=1 on STM32_ADC no longer calls `EnableADC()`, and bit 0
reports no gap while bit 30's `writeCallback` does -- an asymmetry with no
principle behind it.

## Why one issue

One cause: the rule table describes a narrower DSL than the corpus uses. Fixing
any one in isolation invites the same shape of miss for the next.

## Acceptance

- Each family is a RULE, matched against every corpus site, not fitted to one
- SYSCFG emits four registers with sixteen fields; GPIO emits eleven registers
- The `REGISTER_CALLBACK` rule becomes reachable, or is deleted
- Corpus counts recorded per family, before and after
- No trace row regresses; usart1 and exti stay at zero divergences
