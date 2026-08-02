//! Register layout for `STM32_SYSCFG`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32_SYSCFG.CreateRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - ExternalInterruptConfiguration1: form `DICTIONARY_ADD` reads the reset value from the constructor at the root of the chain, and there is no object creation there -- the reset value is unknown, not 0
//!   - ExternalInterruptConfiguration1: located at 0x8 but no field emitted -- the register is NOT in the bank
//!   - GetLocalReceiver: withheld, return type `Antmicro.Renode.Core.IGPIOReceiver` has no Rust mapping
//!   - Reset: withheld, reaches state this peripheral does not have: st.internal_receivers_cache
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 2
//!   - state field `internalReceiversCache`: no Rust mapping for `System.Collections.Generic.Dictionary<int, Antmicro.Renode.Peripherals.Miscellaneous.STM32_SYSCFG.InternalReceiver>`

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Every member of the C# `enum Registers`, whether or
/// not this file defines the register. A constant with no
/// matching `bank.define` below is an address the C# declares
/// and the converter did not emit.
pub mod reg {
    pub const MEMORY_REMAP: u64 = 0x00;
    pub const PERIPHERAL_MODE_CONFIGURATION: u64 = 0x04;
    pub const EXTERNAL_INTERRUPT_CONFIGURATION1: u64 = 0x08;
    pub const EXTERNAL_INTERRUPT_CONFIGURATION2: u64 = 0x0C;
    pub const EXTERNAL_INTERRUPT_CONFIGURATION3: u64 = 0x10;
    pub const EXTERNAL_INTERRUPT_CONFIGURATION4: u64 = 0x14;
    pub const CONFIGURATION_REGISTER: u64 = 0x18;
    pub const COMPENSATION_CELL_CONTROL: u64 = 0x20;
    pub const COMPENSATION_CELL_VALUE: u64 = 0x24;
    pub const COMPENSATION_CELL_CODE: u64 = 0x28;
    pub const POWER_CONTROL: u64 = 0x2C;
    pub const PACKAGE_TYPE: u64 = 0x124;
    pub const USER0: u64 = 0x300;
    pub const USER1: u64 = 0x304;
    pub const USER2: u64 = 0x308;
    pub const USER3: u64 = 0x30C;
    pub const USER4: u64 = 0x310;
    pub const USER5: u64 = 0x314;
    pub const USER6: u64 = 0x318;
    pub const USER7: u64 = 0x31C;
    pub const USER8: u64 = 0x320;
    pub const USER9: u64 = 0x324;
    pub const USER10: u64 = 0x328;
    pub const USER11: u64 = 0x32C;
    pub const USER12: u64 = 0x330;
    pub const USER13: u64 = 0x334;
    pub const USER14: u64 = 0x338;
    pub const USER15: u64 = 0x33C;
    pub const USER16: u64 = 0x340;
    pub const USER17: u64 = 0x344;
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
