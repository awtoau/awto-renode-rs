//! Register layout for `STM32_GPIOPort`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32_GPIOPort.CreateRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - AlternateFunctionHigh: callback for bit 0 needs peer method(s) not yet emitted: st.alternate_function_outputs
//!   - AlternateFunctionLow: callback for bit 0 needs peer method(s) not yet emitted: st.alternate_function_outputs
//!   - BitReset: callback for bit 0 needs peer method(s) not yet emitted: get_value_from_bits_array, st.state, st.write_state
//!   - BitSet: callback for bit 0 needs peer method(s) not yet emitted: get_value_from_bits_array, st.state, st.write_state
//!   - BitSet: callback for bit 16 needs peer method(s) not yet emitted: get_value_from_bits_array, st.state, st.write_state
//!   - InputData: callback for bit 0 needs peer method(s) not yet emitted: get_value_from_bits_array, st.state
//!   - Mode: callback for bit 0 needs peer method(s) not yet emitted: change_mode
//!   - Mode: callback for bit 0 needs peer method(s) not yet emitted: st.mode
//!   - OutputData: callback for bit 0 needs peer method(s) not yet emitted: get_value_from_bits_array, st.state
//!   - OutputData: callback for bit 0 needs peer method(s) not yet emitted: write_state
//!   - OutputSpeed: callback for bit 0 needs peer method(s) not yet emitted: st.output_speed
//!   - PullUpPullDown: callback for bit 0 needs peer method(s) not yet emitted: st.pull_up_pull_down
//!   - state field `alternateFunctionOutputs`: no Rust mapping for `Antmicro.Renode.Peripherals.GPIOPort.STM32_GPIOPort.GPIOAlternateFunction[]`
//!   - state field `invertedAFPins`: no Rust mapping for `System.Collections.Generic.HashSet<Antmicro.Renode.Peripherals.GPIOPort.STM32_GPIOPort.InvertedAFPin>`
//!   - state field `mode`: no Rust mapping for `Antmicro.Renode.Peripherals.GPIOPort.STM32_GPIOPort.Mode[]`
//!   - state field `outputSpeed`: no Rust mapping for `Antmicro.Renode.Peripherals.GPIOPort.STM32_GPIOPort.OutputSpeed[]`
//!   - state field `pullUpPullDown`: no Rust mapping for `Antmicro.Renode.Peripherals.GPIOPort.STM32_GPIOPort.PullUpPullDown[]`
//!   - state field `registers`: no Rust mapping for `Antmicro.Renode.Core.Structure.Registers.DoubleWordRegisterCollection`

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
    pub const MODE: u64 = 0x00;
    pub const OUTPUT_TYPE: u64 = 0x04;
    pub const OUTPUT_SPEED: u64 = 0x08;
    pub const PULL_UP_PULL_DOWN: u64 = 0x0C;
    pub const INPUT_DATA: u64 = 0x10;
    pub const OUTPUT_DATA: u64 = 0x14;
    pub const BIT_SET: u64 = 0x18;
    pub const CONFIGURATION_LOCK: u64 = 0x1C;
    pub const ALTERNATE_FUNCTION_LOW: u64 = 0x20;
    pub const ALTERNATE_FUNCTION_HIGH: u64 = 0x24;
    pub const BIT_RESET: u64 = 0x28;
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
    pub mode_reset_value: u32,
    pub number_of_a_fs: u32,
    pub output_speed_reset_value: u32,
    pub pull_up_pull_down_reset_value: u32,
}

/// C# `DefineRegisters()`, field for field.
pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::OUTPUT_TYPE, 0)
        .with_tagged_flag(0)
        .with_tagged_flag(1)
        .with_tagged_flag(2)
        .with_tagged_flag(3)
        .with_tagged_flag(4)
        .with_tagged_flag(5)
        .with_tagged_flag(6)
        .with_tagged_flag(7)
        .with_tagged_flag(8)
        .with_tagged_flag(9)
        .with_tagged_flag(10)
        .with_tagged_flag(11)
        .with_tagged_flag(12)
        .with_tagged_flag(13)
        .with_tagged_flag(14)
        .with_tagged_flag(15)
        .with_reserved(16, 16)
        .done();

    bank.define(reg::INPUT_DATA, 0)
        .with_value_cb(0, 16, FieldMode::READ, None, None)
        .with_reserved(16, 16)
        .done();

    bank.define(reg::OUTPUT_DATA, 0)
        .with_value_cb(0, 16, FieldMode::READ_WRITE, None, None)
        .with_reserved(16, 16)
        .done();

    bank.define(reg::BIT_SET, 0)
        .with_value_cb(0, 16, FieldMode::WRITE, None, None)
        .with_value_cb(16, 16, FieldMode::WRITE, None, None)
        .done();

    bank.define(reg::CONFIGURATION_LOCK, 0)
        .with_tagged_flag(0)
        .with_tagged_flag(1)
        .with_tagged_flag(2)
        .with_tagged_flag(3)
        .with_tagged_flag(4)
        .with_tagged_flag(5)
        .with_tagged_flag(6)
        .with_tagged_flag(7)
        .with_tagged_flag(8)
        .with_tagged_flag(9)
        .with_tagged_flag(10)
        .with_tagged_flag(11)
        .with_tagged_flag(12)
        .with_tagged_flag(13)
        .with_tagged_flag(14)
        .with_tagged_flag(15)
        .with_tagged_flag(16)
        .with_reserved(17, 15)
        .done();

    bank.define(reg::BIT_RESET, 0)
        .with_value_cb(0, 16, FieldMode::WRITE, None, None)
        .with_reserved(16, 16)
        .done();

}
