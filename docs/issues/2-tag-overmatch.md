TITLE: Unbound `WithValueField` emitted as a tag, so writes are silently ignored

**An over-match, which the project rules call worse than an under-match, because
the oracle may not catch it.** It does not.

C# `WithValueField(0, 32, name: "EMR")` with no `out` still creates a STORED
field: writes stick, reads return them. The fallback rules conflate that with
`WithTag` / `WithTaggedFlag`, which are genuine tags. `renode_regs::with_tag`
pushes with `reserved = true`, and `Bank::write` skips reserved fields entirely.

So the register becomes write-ignored / read-as-zero where C# has a read-write
scratch register.

## Confirmed instance

`STM32F4_EXTI` EMR, whose C# comment reads "Blank implementation to preserve
backwards compatibility" -- it is deliberately a scratch register, and that is
exactly the behaviour lost.

The exti trace is 25 accesses with ZERO writes, so a write-ignored register is
unobservable. exti currently scores 0 divergences.

## Scope

159 sites in the cut: STM32F4_RCC 131, STM32SPI 8, STM32F4_RTC 7, NVIC 4,
STM32_PWR 4, STM32F4_FlashController 2, STM32_RNG 1, STM32_Timer 1,
STM32F4_EXTI 1.

## The distinction to encode

- `WithTag` / `WithTaggedFlag` -> a tag. Named, unimplemented, not stored.
- `WithValueField` / `WithFlag` with no `out` -> STORED, just not handed back
  as a handle.

Both are anonymous; only one is reserved. The rule currently keys on "no `out`",
which is the wrong discriminator.

## Acceptance

- Anonymous stored fields allocate storage; only genuine tags are reserved
- A negative example is recorded, so the rule cannot drift back to over-matching
- The count of affected sites is reported before and after
- Where a trace has writes to such a register, the divergence count moves
