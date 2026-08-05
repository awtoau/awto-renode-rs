//! STM32F427 peripherals, translated from Renode's C#.
//!
//! Faithful first. The oracle certifies equivalence against C# Renode, never
//! improvement, so a "better" translation is a failed one.

// A self-call where the C# called its BASE has already shipped here once:
// `base.Reset()` emitted as `reset()`, recursing forever. It compiled, and no
// test saw it because the method was never reached.
//
// rustc can see that statically and does not, by default. Denying it turns
// that class into a build failure -- the cheapest of the four bugs that
// "compiled cleanly and were wrong" to have prevented, and the only one a lint
// could have caught at all. Overload collapse (csharp_emitter.py) can still produce it,
// so this is a live guard, not a historical one.
#![deny(unconditional_recursion)]

pub mod uart;
pub mod gpio_port;
pub mod platform;
pub mod uart_registers;
pub mod gpio_registers;

/// GENERATED layout for STM32_SYSCFG. Under trace replay in
/// tests/generated_trace.rs -- the first generated module to be EXECUTED
/// rather than merely compiled.
pub mod syscfg_registers;

/// GENERATED layout for STM32F4_EXTI, under trace replay.
pub mod exti_registers;

/// GENERATED layout for STM32_ADC, under trace replay.
pub mod adc_registers;

/// GENERATED layout for STM32DMA, under trace replay.
pub mod dma_registers;

/// GENERATED layout for STMCAN, under trace replay.
pub mod can_registers;

/// GENERATED traits: every C# interface in the corpus that can be expressed
/// COMPLETELY. One that cannot is withheld whole and named in the module's
/// header with the reason, so the file states nothing it is not. The register
/// field traits here are the C# shape, not the shape this crate uses -- D2
/// replaces those handles with indices into a `Cell` arena -- so nothing
/// implements them yet; they are what the converter produces from the C#.
pub mod interfaces;

/// GENERATED virtual dispatch. One trait per in-corpus base class with virtual
/// members, implemented by every translated subclass that can supply the whole
/// contract -- so peripherals whose `State` types differ share one
/// `dyn` object. A member any implementor cannot supply leaves the trait
/// entirely and is named in the module header: forwarding it to the base's body
/// instead would run the wrong method, silently, in code that compiles.
pub mod dispatch;
