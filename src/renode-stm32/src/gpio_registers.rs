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
//!   - AlternateFunctionHigh: located at 0x24 but no field emitted -- the register is NOT in the bank
//!   - AlternateFunctionLow: callback for bit 0 needs peer method(s) not yet emitted: st.alternate_function_outputs
//!   - AlternateFunctionLow: located at 0x20 but no field emitted -- the register is NOT in the bank
//!   - BitReset: callback for bit 0 needs peer method(s) not yet emitted: write_state, st.get_value_from_bits_array
//!   - BitSet: callback for bit 0 needs peer method(s) not yet emitted: write_state, st.get_value_from_bits_array
//!   - BitSet: callback for bit 16 needs peer method(s) not yet emitted: write_state, st.get_value_from_bits_array
//!   - ChangeMode: withheld, reaches state this peripheral does not have: st.alternate_function_outputs
//!   - GetLocalReceiver: withheld, return type `Antmicro.Renode.Core.IGPIOReceiver` has no Rust mapping
//!   - GetSetConnectionBits: withheld, reaches state this peripheral does not have: st.connections
//!   - InputData: callback for bit 0 needs peer method(s) not yet emitted: get_value_from_bits_array
//!   - Mode: callback for bit 0 needs peer method(s) not yet emitted: change_mode
//!   - Mode: located at 0x0 but no field emitted -- the register is NOT in the bank
//!   - OnGPIO: withheld, reaches state this peripheral does not have: st.irq
//!   - OutputData: callback for bit 0 needs peer method(s) not yet emitted: get_value_from_bits_array
//!   - OutputData: callback for bit 0 needs peer method(s) not yet emitted: write_state
//!   - OutputSpeed: located at 0x8 but no field emitted -- the register is NOT in the bank
//!   - PullUpPullDown: located at 0xC but no field emitted -- the register is NOT in the bank
//!   - Register: parameter `peripheral` has no Rust mapping for `Antmicro.Renode.Core.IGPIOSender`
//!   - Reset: withheld, reaches state this peripheral does not have: st.alternate_function_outputs, st.get_value
//!   - SetConnectionStateBit: withheld, cannot emit stmt:Throw
//!   - Unregister: parameter `peripheral` has no Rust mapping for `Antmicro.Renode.Core.IGPIOSender`
//!   - WritePin: withheld, reaches state this peripheral does not have: st.irq
//!   - base_gpio_port_reset: withheld, calls withheld method(s): connections, unset
//!   - set_connections_state_using_bits: withheld, calls withheld method(s): connections, set, unset
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 5
//!   - state field `alternateFunctionOutputs`: reference-typed, so the object-graph rule maps it to `Vec<Gc<GPIOAlternateFunction>>`; blocked: `GPIOAlternateFunction` has no emitted Rust type yet, so there is nothing to point at
//!   - state field `invertedAFPins`: no Rust mapping for `System.Collections.Generic.HashSet<Antmicro.Renode.Peripherals.GPIOPort.STM32_GPIOPort.InvertedAFPin>`
//!   - state field `machine`: needs trait `IMachine` (D1 maps the field; the trait is issue #41). IMachine declares 112 members, the corpus calls 38
//!   - write_state: withheld, calls withheld method(s): write_pin

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

/// C# `enum Mode`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum Mode {
    #[default] Input = 0,
    Output = 1,
    AlternateFunction = 2,
    AnalogMode = 3,
}

impl Mode {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::Input,
            1 => Self::Output,
            2 => Self::AlternateFunction,
            3 => Self::AnalogMode,
            _ => Self::default(),
        }
    }
}

/// C# `enum OutputSpeed`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum OutputSpeed {
    #[default] Low1 = 0,
    Medium = 1,
    Low2 = 2,
    High = 3,
}

impl OutputSpeed {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::Low1,
            1 => Self::Medium,
            2 => Self::Low2,
            3 => Self::High,
            _ => Self::default(),
        }
    }
}

/// C# `enum PullUpPullDown`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum PullUpPullDown {
    #[default] No = 0,
    Up = 1,
    Down = 2,
    Reserved = 3,
}

impl PullUpPullDown {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::No,
            1 => Self::Up,
            2 => Self::Down,
            3 => Self::Reserved,
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
    pub number_of_connections: i32,
    pub state: Vec<bool>,
    pub mode: Vec<Mode>,
    pub mode_reset_value: u32,
    pub number_of_a_fs: u32,
    pub output_speed: Vec<OutputSpeed>,
    pub output_speed_reset_value: u32,
    pub pull_up_pull_down: Vec<PullUpPullDown>,
    pub pull_up_pull_down_reset_value: u32,
}

// The peripheral's own methods. C# reaches its state through
// `this`; these receive it as (bank, st) instead, so a callback
// can call them -- a closure cannot borrow what it lives inside.
fn base_gpio_port_on_gpio(bank: &Bank<State>, st: &mut State, number: i32, value: bool) -> () {
    if !check_pin_number(bank, st, number) {
        return;
    }
    st.state[number as usize] = value;
}

fn check_pin_number(bank: &Bank<State>, st: &mut State, number: i32) -> bool {
    if ((number < 0) || (number >= st.number_of_connections)) {
        log::error!("This peripheral supports gpio inputs from 0 to {}, but {} was called.", st.number_of_connections, number);
        return false;
    }
    return true;
}

fn read_double_word(bank: &Bank<State>, st: &mut State, offset: i64) -> u32 {
    return bank.read(offset as u64, st).unwrap_or(0) as u32;
}

fn write_double_word(bank: &Bank<State>, st: &mut State, offset: i64, value: u32) -> () {
    bank.write(offset as u64, value as u64, st);
}

// Callbacks for computed fields. C# writes these as lambdas capturing
// `this`; a closure cannot live inside the object it borrows, so each
// becomes a free fn over (bank, state). See rulesdb/rules/.
fn mode_0_provider(bank: &Bank<State>, st: &mut State, idx: usize, _current: u64) -> u64 {
    return st.mode[idx as usize] as u64;
}

fn output_speed_0_provider(bank: &Bank<State>, st: &mut State, idx: usize, _current: u64) -> u64 {
    return st.output_speed[idx as usize] as u64;
}

fn output_speed_0_writer(bank: &Bank<State>, st: &mut State, idx: usize, _old: u64, val: u64) -> () {
    st.output_speed[idx as usize] = OutputSpeed::from_u64(val);
    return;
}

fn pull_up_pull_down_0_provider(bank: &Bank<State>, st: &mut State, idx: usize, _current: u64) -> u64 {
    return st.pull_up_pull_down[idx as usize] as u64;
}

fn pull_up_pull_down_0_writer(bank: &Bank<State>, st: &mut State, idx: usize, _old: u64, val: u64) -> () {
    st.pull_up_pull_down[idx as usize] = PullUpPullDown::from_u64(val);
    return;
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
