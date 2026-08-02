//! Register layout for `STM32_UART`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32_UART.DefineRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - BasicDoubleWordPeripheral..ctor `BasicDoubleWordPeripheral(IMachine)`: a base constructor, run by C# before the derived body and NOT inlined here -- inlining it means substituting the derived type's arguments for its parameters, so every field only this one assigns stays at Default
//!   - Control1: conditional access `?.` needs nullability analysis
//!   - Data: conditional access `?.` needs nullability analysis
//!   - OffsetToString: withheld, reaches state this peripheral does not have: st.mapper
//!   - STM32_UART..ctor `STM32_UART(IMachine, uint)`: `new` is emitted but nothing calls it. What arguments a given instance is constructed with is configuration of the system being modelled, not a fact in the corpus, so the converter cannot supply them
//!   - STM32_UART..ctor `STM32_UART(IMachine, uint)`: parameter(s) `frequency` have a C# default value that the corpus does not record -- `parameter.has_default` is stored, the value is not -- so `Self::default()` cannot use them and leaves those fields at 0/false
//!   - STM32_UART..ctor `STM32_UART(IMachine, uint)`: statement 2 withheld -- not an assignment to the type's own storage, but Invocation; an initialiser can only assign the struct it is building
//!   - WriteChar: withheld, reaches state this peripheral does not have: st.machine
//!   - get_ParityBit: withheld, return type `Antmicro.Renode.Peripherals.UART.Parity` has no Rust mapping
//!   - get_StopBits: withheld, return type `Antmicro.Renode.Peripherals.UART.Bits` has no Rust mapping
//!   - state field `machine`: needs trait `IMachine` (D1 maps the field; the trait is issue #41). IMachine declares 112 members, the corpus calls 38
//!   - state field `sysbus`: needs trait `IBusController` (D1 maps the field; the trait is issue #41). IBusController declares 73 members, the corpus calls 66

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
    pub const STATUS: u64 = 0x00;
    pub const DATA: u64 = 0x04;
    pub const BAUD_RATE: u64 = 0x08;
    pub const CONTROL1: u64 = 0x0C;
    pub const CONTROL2: u64 = 0x10;
    pub const CONTROL3: u64 = 0x14;
}

/// Field handles bound by `out` parameters in the C#.
#[derive(Default)]
pub struct Fields {
    pub idle_line_detected: FlagId,
    pub read_fifo_not_empty: FlagId,
    pub transmission_complete: FlagId,
    pub divider_fraction: ValueId,
    pub divider_mantissa: ValueId,
    pub receiver_enabled: FlagId,
    pub transmitter_enabled: FlagId,
    pub idle_line_detected_interrupt_enabled: FlagId,
    pub receiver_not_empty_interrupt_enabled: FlagId,
    pub transmission_complete_interrupt_enabled: FlagId,
    pub transmit_data_register_empty_interrupt_enabled: FlagId,
    pub parity_selection: ValueId,
    pub parity_control_enabled: FlagId,
    pub usart_enabled: FlagId,
    pub oversampling_mode: ValueId,
    pub stop_bits: ValueId,
    pub dma_reception_request: FlagId,
}

/// C# `enum OversamplingMode`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum OversamplingMode {
    #[default] By16 = 0,
    By8 = 1,
}

impl OversamplingMode {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::By16,
            1 => Self::By8,
            _ => Self::default(),
        }
    }
}

/// C# `enum ParitySelection`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum ParitySelection {
    #[default] Even = 0,
    Odd = 1,
}

impl ParitySelection {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::Even,
            1 => Self::Odd,
            _ => Self::default(),
        }
    }
}

/// C# `enum StopBitsValues`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum StopBitsValues {
    #[default] One = 0,
    Half = 1,
    Two = 2,
    OneAndAHalf = 3,
}

impl StopBitsValues {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::One,
            1 => Self::Half,
            2 => Self::Two,
            3 => Self::OneAndAHalf,
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
    pub char_received: Option<Box<dyn FnMut(u8)>>,
    pub dma_request: bool,
    pub irq: bool,
    pub frequency: u32,
    pub idle_line_detected_cancellation_token_src: Option<std::rc::Rc<std::cell::Cell<bool>>>,
    pub receive_fifo: std::collections::VecDeque<u8>,
}

// C# constructors, as field assignments over the derived
// `Default`. Only assignments to this type's own storage can
// live here; everything else the constructor did is a gap above.
impl State {
    /// C# `STM32_UART(IMachine, uint)`, field assignments only.
    pub fn new(frequency: u32) -> Self {
        let mut st = Self::default();
        st.frequency = frequency;
        st
    }
}

// The peripheral's own methods. C# reaches its state through
// `this`; these receive it as (bank, st) instead, so a callback
// can call them -- a closure cannot borrow what it lives inside.
pub fn basic_double_word_peripheral_reset(bank: &Bank<State>, st: &mut State) -> () {
    bank.reset();
}

pub fn baud_rate(bank: &Bank<State>, st: &mut State) -> u32 {
    let mut fraction = if (bank.value(st.f.oversampling_mode) == OversamplingMode::By16 as u64) { bank.value(st.f.divider_fraction) } else { (bank.value(st.f.divider_fraction) & 7) };
    let mut divisor = ((csharp_rt::unchecked_mul(8, csharp_rt::unchecked_sub(2, bank.value(st.f.oversampling_mode))) as f64) * ((bank.value(st.f.divider_mantissa) as f64) + ((fraction as f64) / 16.0)));
    return if (divisor == (0 as f64)) { 0 } else { (((st.frequency as f64) / divisor) as u32) };
}

pub fn read_double_word(bank: &Bank<State>, st: &mut State, offset: i64) -> u32 {
    return bank.read(offset as u64, st).unwrap_or(0) as u32;
}

pub fn report_idle_line_detected(bank: &Bank<State>, st: &mut State, ct: std::rc::Rc<std::cell::Cell<bool>>) -> () {
    if !ct.get() {
        bank.set_flag(st.f.idle_line_detected, true);
        update(bank, st);
    }
}

pub fn reset(bank: &Bank<State>, st: &mut State) -> () {
    basic_double_word_peripheral_reset(bank, st);
    if let Some(__v) = st.idle_line_detected_cancellation_token_src.as_ref() {
        __v.set(true);
    }
    st.receive_fifo.clear();
    st.irq = false;
}

pub fn update(bank: &Bank<State>, st: &mut State) -> () {
    st.irq = ((((bank.flag(st.f.idle_line_detected_interrupt_enabled) && bank.flag(st.f.idle_line_detected)) || (bank.flag(st.f.receiver_not_empty_interrupt_enabled) && bank.flag(st.f.read_fifo_not_empty))) || bank.flag(st.f.transmit_data_register_empty_interrupt_enabled)) || (bank.flag(st.f.transmission_complete_interrupt_enabled) && bank.flag(st.f.transmission_complete)));
}

pub fn write_double_word(bank: &Bank<State>, st: &mut State, offset: i64, value: u32) -> () {
    bank.write(offset as u64, value as u64, st);
}

// Callbacks for computed fields. C# writes these as lambdas capturing
// `this`; a closure cannot live inside the object it borrows, so each
// becomes a free fn over (bank, state). See rulesdb/rules/.
fn status_3_provider(bank: &Bank<State>, st: &mut State, _idx: usize, _current: u64) -> u64 {
    return u64::from(false);
}

fn status_7_provider(bank: &Bank<State>, st: &mut State, _idx: usize, _current: u64) -> u64 {
    return u64::from(true);
}

fn status_writer(bank: &Bank<State>, st: &mut State, _old: u64, __: u64) -> () {
    update(bank, st);
    return;
}

fn data_0_provider(bank: &Bank<State>, st: &mut State, _idx: usize, _current: u64) -> u64 {
    let mut value = 0;
    bank.set_flag(st.f.idle_line_detected, false);
    if (st.receive_fifo.len() > 0) {
        value = (st.receive_fifo.pop_front().unwrap() as u32);
    }
    bank.set_flag(st.f.read_fifo_not_empty, (st.receive_fifo.len() > 0));
    update(bank, st);
    return (value as u64);
}

fn data_0_writer(bank: &Bank<State>, st: &mut State, _idx: usize, _old: u64, value: u64) -> () {
    if (!bank.flag(st.f.usart_enabled) && !bank.flag(st.f.transmitter_enabled)) {
        log::warn!("Trying to transmit a character, but the transmitter is not enabled. dropping.");
        return;
    }
    /* GAP: `?.` needs nullability analysis (D4) */;
    bank.set_flag(st.f.transmission_complete, true);
    update(bank, st);
    return;
}

fn control1_writer(bank: &Bank<State>, st: &mut State, _old: u64, __: u64) -> () {
    if (!bank.flag(st.f.receiver_enabled) || !bank.flag(st.f.usart_enabled)) {
        /* GAP: `?.` needs nullability analysis (D4) */;
    }
    update(bank, st);
    return;
}

/// C# `DefineRegisters()`, field for field.
pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::STATUS, 192)
        .with_tagged_flag(0)
        .with_tagged_flag(1)
        .with_tagged_flag(2)
        .with_value_cb(3, 1, FieldMode::READ, Some(status_3_provider), None)
        .with_flag(4, &mut f.idle_line_detected, FieldMode::READ)
        .with_flag(5, &mut f.read_fifo_not_empty, FieldMode::READ | FieldMode::WRITE_ZERO_TO_CLEAR)
        .with_flag(6, &mut f.transmission_complete, FieldMode::READ | FieldMode::WRITE_ZERO_TO_CLEAR)
        .with_value_cb(7, 1, FieldMode::READ, Some(status_7_provider), None)
        .with_tagged_flag(8)
        .with_tagged_flag(9)
        .with_reserved(10, 22)
        .with_write_callback(Some(status_writer))
        .done();

    bank.define(reg::DATA, 0)
        .with_value_cb(0, 9, FieldMode::READ_WRITE, Some(data_0_provider), Some(data_0_writer))
        .done();

    bank.define(reg::BAUD_RATE, 0)
        .with_value(0, 4, &mut f.divider_fraction, FieldMode::READ_WRITE)
        .with_value(4, 12, &mut f.divider_mantissa, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CONTROL1, 0)
        .with_tagged_flag(0)
        .with_tagged_flag(1)
        .with_flag(2, &mut f.receiver_enabled, FieldMode::READ_WRITE)
        .with_flag(3, &mut f.transmitter_enabled, FieldMode::READ_WRITE)
        .with_flag(4, &mut f.idle_line_detected_interrupt_enabled, FieldMode::READ_WRITE)
        .with_flag(5, &mut f.receiver_not_empty_interrupt_enabled, FieldMode::READ_WRITE)
        .with_flag(6, &mut f.transmission_complete_interrupt_enabled, FieldMode::READ_WRITE)
        .with_flag(7, &mut f.transmit_data_register_empty_interrupt_enabled, FieldMode::READ_WRITE)
        .with_tagged_flag(8)
        .with_value(9, 1, &mut f.parity_selection, FieldMode::READ_WRITE)
        .with_flag(10, &mut f.parity_control_enabled, FieldMode::READ_WRITE)
        .with_tagged_flag(11)
        .with_tagged_flag(12)
        .with_flag(13, &mut f.usart_enabled, FieldMode::READ_WRITE)
        .with_reserved(14, 1)
        .with_value(15, 1, &mut f.oversampling_mode, FieldMode::READ_WRITE)
        .with_reserved(16, 16)
        .with_write_callback(Some(control1_writer))
        .done();

    bank.define(reg::CONTROL2, 0)
        .with_tag(0, 4)
        .with_reserved(5, 1)
        .with_tagged_flag(6)
        .with_reserved(7, 1)
        .with_tagged_flag(8)
        .with_tagged_flag(9)
        .with_tagged_flag(10)
        .with_tagged_flag(11)
        .with_value(12, 2, &mut f.stop_bits, FieldMode::READ_WRITE)
        .with_tagged_flag(14)
        .with_reserved(15, 17)
        .done();

    bank.define(reg::CONTROL3, 0)
        .with_tagged_flag(0)
        .with_tagged_flag(1)
        .with_tagged_flag(2)
        .with_tagged_flag(3)
        .with_tagged_flag(4)
        .with_tagged_flag(5)
        .with_flag(6, &mut f.dma_reception_request, FieldMode::READ_WRITE)
        .with_tagged_flag(7)
        .with_tagged_flag(8)
        .with_tagged_flag(9)
        .with_tagged_flag(10)
        .with_reserved(11, 21)
        .done();

}
