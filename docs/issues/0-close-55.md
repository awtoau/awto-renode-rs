TITLE: comment to close #55 — sub-peripheral composition

**Done.** dma1 9.3% → **92.8%**, dma2 0.2% → **90.0%**. 5,629 of 6,252
divergences gone.

**The diagnosis in this issue was wrong**, and worth recording. It assumed a
bank per child with offset-range dispatch. The C# does the opposite:
`Stream.DefineRegisters` calls `(Registers.StreamConfiguration +
streamOffset).Define(parent)` — it defines into the **parent's** bank. One flat
map, no dispatch.

What was actually missing is that a register offset can be an **expression**.
The register form matched only a constant, so 48 registers were absent, every
read returned 0, and **nothing reported a gap** — an offset matching no form
does not exist as far as the walker is concerned.

**Also wrong: "one rule against four of the eight trace rows."** Only
`STM32DMA.streams` has this shape. Querying the corpus for the discriminator —
the child holds a back-reference typed as the parent **and** one of its own
methods yields registers when the forms run over it — five of the six
candidates are correctly rejected. GPIO, CAN and Timer hold arrays of children
with no registers of their own; that is an ordinary `Vec` and a different
problem.

The rule is detected, not named: instance count, index parameter and its type
all come from the constructor. Nothing is assumed, including that the index is
called `id`.

**Not claimed:** the child's *methods* are not emitted, only its layout. A
parent method calling one is withheld with that reason rather than emitting
`stream.reset()` against a struct with no methods.

**Remainder attributed, as the acceptance asked** — and the attribution was
later proven wrong, which is worth stating here rather than leaving in a commit
message. Every surviving divergence reads `LowInterruptStatus` or
`HighInterruptStatus`, whose per-stream flags are bound by a `for` loop
extending a builder held in a local. That shape was implemented on 2026-08-03
and **the divergences did not move**: the bits are now in the bank, and nothing
sets them. TCIF is read-only and its only C# writer reaches `DmaEngine`, which
has no Rust mapping. They are a behaviour gap, not a layout gap.

Commit `1ee0f55`.
