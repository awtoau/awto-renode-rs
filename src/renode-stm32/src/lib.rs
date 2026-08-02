//! STM32F427 peripherals, translated from Renode's C#.
//!
//! Faithful first. The oracle certifies equivalence against C# Renode, never
//! improvement, so a "better" translation is a failed one.

pub mod uart;
pub mod gpio_port;
pub mod platform;
pub mod uart_registers;
pub mod gpio_registers;

/// GENERATED layout for STM32_SYSCFG. Under trace replay in
/// tests/generated_trace.rs -- the first generated module to be EXECUTED
/// rather than merely compiled.
pub mod syscfg_registers;
