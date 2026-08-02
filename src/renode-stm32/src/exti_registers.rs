//! Register layout for `STM32F4_EXTI`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32F4_EXTI.DefineRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - OffsetToString: withheld, reaches state this peripheral does not have: st.mapper
//!   - OnGPIO: withheld, cannot emit expr:DeclarationExpression
//!   - PendingRegister: callback for bit 0 needs peer method(s) not yet emitted: foreach_active_bit, st.connections, st.unset
//!   - SoftwareInterruptEvent: callback for bit 0 needs peer method(s) not yet emitted: foreach_active_bit, st.connections, st.set
//!   - number_of_lines: withheld, calls withheld method(s): connections
//!   - reset: withheld, calls withheld method(s): connections, unset
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 2
//!   - state field `core`: no Rust mapping for `Antmicro.Renode.Peripherals.IRQControllers.STM32_EXTICore`
//!   - state field `machine`: needs trait `IMachine` (D1 maps the field; the trait is issue #41). IMachine declares 112 members, the corpus calls 7
//!   - state field `sysbus`: needs trait `IBusController` (D1 maps the field; the trait is issue #41). IBusController declares 73 members, the corpus calls 17

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Every member of the C# `enum Registers`, whether or
/// not this file defines the register. A constant with no
/// matching `bank.define` below is an address the C# declares
/// and the converter did not emit.
pub mod reg {
    pub const INTERRUPT_MASK: u64 = 0x00;
    pub const EVENT_MASK: u64 = 0x04;
    pub const RISING_TRIGGER_SELECTION: u64 = 0x08;
    pub const FALLING_TRIGGER_SELECTION: u64 = 0x0C;
    pub const SOFTWARE_INTERRUPT_EVENT: u64 = 0x10;
    pub const PENDING_REGISTER: u64 = 0x14;
}

/// Field handles bound by `out` parameters in the C#.
#[derive(Default)]
pub struct Fields {
    pub interrupt_mask: ValueId,
    pub rising_edge_mask: ValueId,
    pub falling_edge_mask: ValueId,
    pub pending_interrupts: ValueId,
}

/// The peripheral's own state: every C# instance member that actually
/// stores something. Computed properties are excluded -- they hold
/// nothing, so a field here would invent storage the C# lacks.
#[derive(Default)]
pub struct State {
    /// Register field handles, bound by the C# `out` parameters.
    pub f: Fields,
    pub number_of_lines_mask: u64,
    pub software_interrupt: u64,
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

// Callbacks for computed fields. C# writes these as lambdas capturing
// `this`; a closure cannot live inside the object it borrows, so each
// becomes a free fn over (bank, state). See rulesdb/rules/.
fn software_interrupt_event_0_provider(bank: &Bank<State>, st: &mut State, _idx: usize, _current: u64) -> u64 {
    return st.software_interrupt;
}

/// C# `DefineRegisters()`, field for field.
pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::INTERRUPT_MASK, 0)
        .with_value(0, 32, &mut f.interrupt_mask, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::EVENT_MASK, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::RISING_TRIGGER_SELECTION, 0)
        .with_value(0, 32, &mut f.rising_edge_mask, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::FALLING_TRIGGER_SELECTION, 0)
        .with_value(0, 32, &mut f.falling_edge_mask, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::SOFTWARE_INTERRUPT_EVENT, 0)
        .with_value_cb(0, 32, FieldMode::READ_WRITE, Some(software_interrupt_event_0_provider), None)
        .done();

    bank.define(reg::PENDING_REGISTER, 0)
        .with_value(0, 32, &mut f.pending_interrupts, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
        .done();

}
