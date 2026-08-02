//! Register layout for `STM32_SYSCFG`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32_SYSCFG.CreateRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - ExternalInterruptConfiguration1: located at 0x8 but no field emitted -- the register is NOT in the bank
//!   - GetLocalReceiver: withheld, return type `Antmicro.Renode.Core.IGPIOReceiver` has no Rust mapping
//!   - Reset: withheld, reaches state this peripheral does not have: st.internal_receivers_cache
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 5
//!   - state field `internalReceiversCache`: no Rust mapping for `System.Collections.Generic.Dictionary<int, Antmicro.Renode.Peripherals.Miscellaneous.STM32_SYSCFG.InternalReceiver>`

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
    pub const EXTERNAL_INTERRUPT_CONFIGURATION1: u64 = 0x08;
}

/// Field handles bound by `out` parameters in the C#.
#[derive(Default)]
pub struct Fields {
}

/// The peripheral's own state: every C# instance member that actually
/// stores something. Computed properties are excluded -- they hold
/// nothing, so a field here would invent storage the C# lacks.
#[derive(Default)]
pub struct State {
    /// Register field handles, bound by the C# `out` parameters.
    pub f: Fields,
}

// The peripheral's own methods. C# reaches its state through
// `this`; these receive it as (bank, st) instead, so a callback
// can call them -- a closure cannot borrow what it lives inside.
fn read_double_word(bank: &Bank<State>, st: &mut State, offset: i64) -> u32 {
    return bank.read(offset as u64, st).unwrap_or(0) as u32;
}

fn size(bank: &Bank<State>, st: &mut State) -> i64 {
    return (1024 as i64);
}

fn write_double_word(bank: &Bank<State>, st: &mut State, offset: i64, value: u32) -> () {
    bank.write(offset as u64, value as u64, st);
}

/// C# `DefineRegisters()`, field for field.
pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
}
