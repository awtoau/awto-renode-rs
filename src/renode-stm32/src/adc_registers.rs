//! Register layout for `STM32_ADC`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32_ADC.DefineRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - Control2: WithFlag bit 0: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - Control2: callback for bit 30 needs peer method(s) not yet emitted: start_conversion
//!   - EnableADC: withheld, reaches state this peripheral does not have: st.channels, st.current_channel
//!   - FeedSample: withheld, reaches state this peripheral does not have: st.channels
//!   - IsValidChannel: withheld, cannot emit stmt:Throw
//!   - OffsetToString: withheld, reaches state this peripheral does not have: st.mapper
//!   - OnConversionFinished: withheld, reaches state this peripheral does not have: st.channels, st.current_channel, st.machine, st.sampling_timer
//!   - Reset: withheld, reaches state this peripheral does not have: st.channels
//!   - StartConversion: withheld, reaches state this peripheral does not have: st.machine, st.sampling_timer
//!   - state field `channels`: no Rust mapping for `Antmicro.Renode.Peripherals.Analog.ADCChannel[]`
//!   - state field `currentChannel`: no Rust mapping for `Antmicro.Renode.Peripherals.Analog.ADCChannel`
//!   - state field `machine`: needs trait `IMachine` (D1 maps the field; the trait is issue #41). IMachine declares 112 members, the corpus calls 7
//!   - state field `samplingTimer`: no Rust mapping for `Antmicro.Renode.Peripherals.Timers.LimitTimer`
//!   - state field `sysbus`: needs trait `IBusController` (D1 maps the field; the trait is issue #41). IBusController declares 73 members, the corpus calls 17

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
    pub const STATUS: u64 = 0x00;
    pub const CONTROL1: u64 = 0x04;
    pub const CONTROL2: u64 = 0x08;
    pub const SAMPLE_TIME1: u64 = 0x0C;
    pub const SAMPLE_TIME2: u64 = 0x10;
    pub const INJECTED_CHANNEL_DATA_OFFSET1: u64 = 0x14;
    pub const INJECTED_CHANNEL_DATA_OFFSET2: u64 = 0x18;
    pub const INJECTED_CHANNEL_DATA_OFFSET3: u64 = 0x1C;
    pub const INJECTED_CHANNEL_DATA_OFFSET4: u64 = 0x20;
    pub const REGULAR_SEQUENCE1: u64 = 0x2C;
    pub const REGULAR_SEQUENCE2: u64 = 0x30;
    pub const REGULAR_SEQUENCE3: u64 = 0x34;
    pub const REGULAR_DATA: u64 = 0x4C;
}

/// Field handles bound by `out` parameters in the C#.
#[derive(Default)]
pub struct Fields {
    pub end_of_conversion: FlagId,
    pub eoc_interrupt_enable: FlagId,
    pub scan_mode: FlagId,
    pub adc_on: FlagId,
    pub continuous_conversion: FlagId,
    pub dma_enabled: FlagId,
    pub dma_issue_request: FlagId,
    pub end_of_conversion_select: FlagId,
    pub regular_sequence: [ValueId; 16],
}

/// The peripheral's own state: every C# instance member that actually
/// stores something. Computed properties are excluded -- they hold
/// nothing, so a field here would invent storage the C# lacks.
#[derive(Default)]
pub struct State {
    /// Register field handles, bound by the C# `out` parameters.
    pub f: Fields,
    pub dma_request: bool,
    pub irq: bool,
    pub adc_data: u32,
    pub current_channel_idx: u32,
    pub regular_sequence_len: u32,
}

// The peripheral's own methods. C# reaches its state through
// `this`; these receive it as (bank, st) instead, so a callback
// can call them -- a closure cannot borrow what it lives inside.
pub fn basic_double_word_peripheral_reset(bank: &Bank<State>, st: &mut State) -> () {
    bank.reset();
}

pub fn read_double_word(bank: &Bank<State>, st: &mut State, offset: i64) -> u32 {
    return bank.read(offset as u64, st).unwrap_or(0) as u32;
}

pub fn size(bank: &Bank<State>, st: &mut State) -> i64 {
    return (80 as i64);
}

pub fn write_double_word(bank: &Bank<State>, st: &mut State, offset: i64, value: u32) -> () {
    bank.write(offset as u64, value as u64, st);
}

// Callbacks for computed fields. C# writes these as lambdas capturing
// `this`; a closure cannot live inside the object it borrows, so each
// becomes a free fn over (bank, state). See rulesdb/rules/.
fn control2_30_provider(bank: &Bank<State>, st: &mut State, _idx: usize, _current: u64) -> u64 {
    return u64::from(false);
}

fn regular_sequence1_20_writer(bank: &Bank<State>, st: &mut State, _idx: usize, _old: u64, val: u64) -> () {
    st.regular_sequence_len = ((val as u32) + 1);
    return;
}

fn regular_data_0_provider(bank: &Bank<State>, st: &mut State, _idx: usize, _current: u64) -> u64 {
    log::debug!("Reading ADC data {}", st.adc_data);
    bank.set_flag(st.f.end_of_conversion, false);
    st.irq = false;
    return (st.adc_data as u64);
}

/// C# `DefineRegisters()`, field for field.
pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::STATUS, 0)
        .with_tagged_flag(0)
        .with_flag(1, &mut f.end_of_conversion, FieldMode::READ_WRITE)
        .with_tagged_flag(2)
        .with_tagged_flag(3)
        .with_tagged_flag(4)
        .with_tagged_flag(5)
        .with_reserved(6, 26)
        .done();

    bank.define(reg::CONTROL1, 0)
        .with_tag(0, 5)
        .with_flag(5, &mut f.eoc_interrupt_enable, FieldMode::READ_WRITE)
        .with_tagged_flag(6)
        .with_tagged_flag(7)
        .with_flag(8, &mut f.scan_mode, FieldMode::READ_WRITE)
        .with_tagged_flag(9)
        .with_tagged_flag(10)
        .with_tagged_flag(11)
        .with_tagged_flag(12)
        .with_tag(13, 3)
        .with_reserved(16, 6)
        .with_tagged_flag(22)
        .with_tagged_flag(23)
        .with_tag(24, 2)
        .with_tagged_flag(26)
        .with_reserved(27, 5)
        .done();

    bank.define(reg::CONTROL2, 0)
        .with_flag(0, &mut f.adc_on, FieldMode::READ_WRITE)
        .with_flag(1, &mut f.continuous_conversion, FieldMode::READ_WRITE)
        .with_reserved(2, 6)
        .with_flag(8, &mut f.dma_enabled, FieldMode::READ_WRITE)
        .with_flag(9, &mut f.dma_issue_request, FieldMode::READ_WRITE)
        .with_flag(10, &mut f.end_of_conversion_select, FieldMode::READ_WRITE)
        .with_tagged_flag(11)
        .with_reserved(12, 4)
        .with_tag(16, 4)
        .with_tag(20, 2)
        .with_tagged_flag(22)
        .with_reserved(23, 1)
        .with_tag(24, 4)
        .with_tag(28, 2)
        .with_value_cb(30, 1, FieldMode::READ_WRITE, Some(control2_30_provider), None)
        .with_reserved(31, 1)
        .done();

    bank.define(reg::SAMPLE_TIME1, 0)
        .with_tag(0, 3)
        .with_tag(3, 3)
        .with_tag(6, 3)
        .with_tag(9, 3)
        .with_tag(12, 3)
        .with_tag(15, 3)
        .with_tag(18, 3)
        .with_tag(21, 3)
        .with_tag(24, 3)
        .with_reserved(27, 5)
        .done();

    bank.define(reg::SAMPLE_TIME2, 0)
        .with_tag(0, 3)
        .with_tag(3, 3)
        .with_tag(6, 3)
        .with_tag(9, 3)
        .with_tag(12, 3)
        .with_tag(15, 3)
        .with_tag(18, 3)
        .with_tag(21, 3)
        .with_tag(24, 3)
        .with_tag(27, 3)
        .with_reserved(30, 2)
        .done();

    bank.define(reg::INJECTED_CHANNEL_DATA_OFFSET1, 0)
        .with_tag(0, 12)
        .with_reserved(12, 20)
        .done();

    bank.define(reg::INJECTED_CHANNEL_DATA_OFFSET2, 0)
        .with_tag(0, 12)
        .with_reserved(12, 20)
        .done();

    bank.define(reg::INJECTED_CHANNEL_DATA_OFFSET3, 0)
        .with_tag(0, 12)
        .with_reserved(12, 20)
        .done();

    bank.define(reg::INJECTED_CHANNEL_DATA_OFFSET4, 0)
        .with_tag(0, 12)
        .with_reserved(12, 20)
        .done();

    bank.define(reg::REGULAR_SEQUENCE1, 0)
        .with_value(0, 5, &mut f.regular_sequence[12], FieldMode::READ_WRITE)
        .with_value(5, 5, &mut f.regular_sequence[13], FieldMode::READ_WRITE)
        .with_value(10, 5, &mut f.regular_sequence[14], FieldMode::READ_WRITE)
        .with_value(15, 5, &mut f.regular_sequence[15], FieldMode::READ_WRITE)
        .with_value_cb(20, 4, FieldMode::READ_WRITE, None, Some(regular_sequence1_20_writer))
        .done();

    bank.define(reg::REGULAR_SEQUENCE2, 0)
        .with_value(0, 5, &mut f.regular_sequence[6], FieldMode::READ_WRITE)
        .with_value(5, 5, &mut f.regular_sequence[7], FieldMode::READ_WRITE)
        .with_value(10, 5, &mut f.regular_sequence[8], FieldMode::READ_WRITE)
        .with_value(15, 5, &mut f.regular_sequence[9], FieldMode::READ_WRITE)
        .with_value(20, 5, &mut f.regular_sequence[10], FieldMode::READ_WRITE)
        .with_value(25, 5, &mut f.regular_sequence[11], FieldMode::READ_WRITE)
        .done();

    bank.define(reg::REGULAR_SEQUENCE3, 0)
        .with_value(0, 5, &mut f.regular_sequence[0], FieldMode::READ_WRITE)
        .with_value(5, 5, &mut f.regular_sequence[1], FieldMode::READ_WRITE)
        .with_value(10, 5, &mut f.regular_sequence[2], FieldMode::READ_WRITE)
        .with_value(15, 5, &mut f.regular_sequence[3], FieldMode::READ_WRITE)
        .with_value(20, 5, &mut f.regular_sequence[4], FieldMode::READ_WRITE)
        .with_value(25, 5, &mut f.regular_sequence[5], FieldMode::READ_WRITE)
        .done();

    bank.define(reg::REGULAR_DATA, 0)
        .with_value_cb(0, 32, FieldMode::READ_WRITE, Some(regular_data_0_provider), None)
        .done();

}
