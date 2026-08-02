//! Register layout for `STM32DMA`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32DMA.DefineRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - ClearIrqFlagOnCondition: parameter `flag` has no Rust mapping for `Antmicro.Renode.Core.Structure.Registers.IFlagRegisterField`
//!   - OffsetToString: withheld, reaches state this peripheral does not have: st.mapper
//!   - OnGPIO: withheld, reaches state this peripheral does not have: st.streams
//!   - Reset: withheld, reaches state this peripheral does not have: st.streams
//!   - UpdateInterrupts: withheld, reaches state this peripheral does not have: st.irq, st.nr_of_streams, st.streams
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 2
//!   - state field `engine`: no Rust mapping for `Antmicro.Renode.Peripherals.DMA.DmaEngine`
//!   - state field `machine`: needs trait `IMachine` (D1 maps the field; the trait is issue #41). IMachine declares 112 members, the corpus calls 7
//!   - state field `streams`: no Rust mapping for `Antmicro.Renode.Peripherals.DMA.STM32DMA.Stream[]`
//!   - state field `sysbus`: needs trait `IBusController` (D1 maps the field; the trait is issue #41). IBusController declares 73 members, the corpus calls 17

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
    pub const LOW_INTERRUPT_STATUS: u64 = 0x00;
    pub const HIGH_INTERRUPT_STATUS: u64 = 0x04;
    pub const LOW_INTERRUPT_CLEAR: u64 = 0x08;
    pub const HIGH_INTERRUPT_CLEAR: u64 = 0x0C;
}

/// Field handles bound by `out` parameters in the C#.
#[derive(Default)]
pub struct Fields {
}

/// C# `enum DataSize`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum DataSize {
    #[default] Byte = 0,
    HalfWord = 1,
    Word = 2,
    Reserved = 3,
}

impl DataSize {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::Byte,
            1 => Self::HalfWord,
            2 => Self::Word,
            3 => Self::Reserved,
            _ => Self::default(),
        }
    }
}

/// C# `enum Direction`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum Direction {
    #[default] PeripheralToMemory = 0,
    MemoryToPeripheral = 1,
    MemoryToMemory = 2,
    Reserved = 3,
}

impl Direction {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::PeripheralToMemory,
            1 => Self::MemoryToPeripheral,
            2 => Self::MemoryToMemory,
            3 => Self::Reserved,
            _ => Self::default(),
        }
    }
}

/// C# `enum FIFOThreshold`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum FIFOThreshold {
    #[default] OneFourth = 0,
    Half = 1,
    ThreeFourths = 2,
    Full = 3,
}

impl FIFOThreshold {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::OneFourth,
            1 => Self::Half,
            2 => Self::ThreeFourths,
            3 => Self::Full,
            _ => Self::default(),
        }
    }
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
fn basic_double_word_peripheral_reset(bank: &Bank<State>, st: &mut State) -> () {
    bank.reset();
}

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
    bank.define(reg::LOW_INTERRUPT_STATUS, 0)
        .with_reserved(12, 4)
        .with_reserved(28, 4)
        .done();

    bank.define(reg::HIGH_INTERRUPT_STATUS, 0)
        .with_reserved(12, 4)
        .with_reserved(28, 4)
        .done();

    bank.define(reg::LOW_INTERRUPT_CLEAR, 0)
        .with_reserved(12, 4)
        .with_reserved(28, 4)
        .done();

    bank.define(reg::HIGH_INTERRUPT_CLEAR, 0)
        .with_reserved(12, 4)
        .with_reserved(28, 4)
        .done();

}
