> **PREMISE DISPROVEN, 2026-08-03.** This draft claims the shape accounts for
> "all 623 remaining DMA divergences". It does not. The shape was implemented
> and every one of the 623 remained: 616 x HighInterruptStatus -> 0x8000000 and
> 7 x LowInterruptStatus -> 0x20. Those bits are now IN the bank and verified
> to land at the right positions; **nothing sets them**. TCIF is read-only, no
> trace write can reach it, and its only C# writer is
> `Stream.PerformTransfer` -> `DmaEngine`, a type with no Rust mapping.
>
> They are a BEHAVIOUR gap wearing a layout gap's clothes. A trace count alone
> cannot tell a missing layout from a missing writer, and that is the mistake
> this draft made. The feature itself landed and is correct.

TITLE: Register builder held in a local and extended from a loop

A layout method may bind a register builder to a local and extend it later:

```csharp
var lowInterruptStatusReg = Registers.LowInterruptStatus.Define(this)
    .WithReservedBits(12, 4)
    .WithReservedBits(28, 4);

for(var streamIdx = 0; streamIdx < NrOfStreams / 2; streamIdx++)
{
    var offset = streamRegOffset[streamIdx];
    lowInterruptStatusReg
        .WithTaggedFlag($"FEIF{streamIdx}", offset)
        .WithFlag(offset + 5, out transferCompleteIrqStatus[streamIdx], FieldMode.Read, ...);
}
```

`emit_registers` associates combinator calls with a register by the span start
of the chain's root. Here the root is a *local reference*, not the `.Define(`
call, so the loop's combinators belong to no chain the walker found, and they
were dropped. Silently, until #55 added the check that reports a top-level
statement whose subtree calls combinators nothing emitted.

## Cost

Every remaining divergence on both DMA traces, and only these:

| trace | accesses | divergences | |
|---|---|---|---|
| dma1 | 183 | 7 | 92.8% |
| dma2 | 12,356 | 616 | 90.0% |

All of them read `LowInterruptStatus` or `HighInterruptStatus`. `0x20` is bit 5
(`TCIF0`); `0x8000000` is bit 27 (`TCIF3`) — exactly the flags that loop binds.
`transferCompleteIrqStatus` is a stored field, so these are not tags: the C#
computes a value and the generated bank has nowhere to put it.

## What it needs

1. Track a register builder bound to a local, so a later reference to that local
   resolves to the register it was defined on. The corpus records the
   declarator and the local reference; nothing new needs ingesting.
2. Emit the enclosing loop, with the bit position an expression rather than a
   constant — the same generalisation #55 made for register *offsets*, applied
   to bit positions.
3. `out arr[i]` already binds correctly (fixed earlier); the array-collapse in
   `Fields` already sizes from the highest index seen.

## Why it generalises

A fluent builder captured in a variable and extended later is ordinary C#, not a
register idiom — item 1 is a language-layer fact about local aliasing. Item 2 is
the same expression-valued-argument change that has now been made once for
offsets. Worth querying the corpus for other layout methods whose combinators
have a local reference at the chain root before writing it, so it is written
against several sites rather than fitted to this one.

## Acceptance

- The corpus query for other sites with this shape, run and recorded
- `dma1` and `dma2` divergences at zero, or the remainder attributed
- No new gap introduced in the six peripherals that currently regenerate
