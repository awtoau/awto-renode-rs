# Prove behaviour generation on one peripheral before widening

**Taken 2026-08-02.**

The next target is **UART, generated completely — behaviour included — and
then run.** Not broader layout coverage, and not a push straight for booting
firmware.

## What was true when this was decided

Three bars, and the distance between them is large.

| bar | state |
|---|---|
| register layout for the cut | five of seven peripherals verified bit-for-bit against the C#; two broken from one cause |
| behaviour | 519 gaps, 445 lines still hand-written, and **nothing assembles a module into a peripheral that can be instantiated and driven** |
| runs firmware | tlib's FFI mechanism proven, callback set incomplete, no peripheral ever instantiated |

Every generated module today is a register map plus isolated free functions.
There is no dispatch wiring, no interrupt line, no state threading. That is the
gap, and no amount of additional layout coverage closes it.

## Why UART

It is the strongest position available. usart1 replays **33,164 accesses with
zero divergences**, and the audit found no bit-position or width error anywhere
in it. So a failure to generate its behaviour cannot be blamed on its layout,
which makes it a clean measurement.

`uart.rs` is 190 of the 445 hand-written lines. Those lines are the target: a
landed translation must be recreatable from the C# plus committed rules and
scripts alone, and today it is not.

## Why not broader layout coverage

Layout is the part we were most confident in, and on 2026-08-02 that confidence
turned out to be partly false — all four automated checks passed on a peripheral
whose register map was **empty**. Widening a base we have just discovered we
were wrong about spends effort where the information is lowest.

## Why not boot first

Nothing has ever instantiated a peripheral. Going straight for boot means a long
stall with no signal, and on failure no way to tell which of a dozen missing
things caused it.

## What this depends on

The four open architectural decisions are the blockers, and they are the path:
`Gc<T>` (#57), inheritance (#56), interface traits (#60), threading (#52). None
is incremental work; behaviour cannot generate until they land.

## What would overturn this

- The use-site comparison in #57 showing `Gc<T>` is worse than `Rc<RefCell<T>>`,
  which would make mechanical porting of reference fields unavailable and change
  what "generate the behaviour" costs
- Evidence that UART's behaviour is unrepresentative — if what it needs turns
  out not to generalise, a second peripheral has to join the slice before any
  claim is made about the approach
