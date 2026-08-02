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
//!   - BaseGPIOPort..ctor `BaseGPIOPort(IMachine, int)`: a base constructor, run by C# before the derived body and NOT inlined here -- inlining it means substituting the derived type's arguments for its parameters, so every field only this one assigns stays at Default
//!   - BitReset: callback for bit 0 needs peer method(s) not yet emitted: write_state, st.get_value_from_bits_array
//!   - BitSet: callback for bit 0 needs peer method(s) not yet emitted: write_state, st.get_value_from_bits_array
//!   - BitSet: callback for bit 16 needs peer method(s) not yet emitted: write_state, st.get_value_from_bits_array
//!   - ChangeMode: withheld, reaches state this peripheral does not have: st.alternate_function_outputs
//!   - GetLocalReceiver: withheld, return type `Antmicro.Renode.Core.IGPIOReceiver` has no Rust mapping
//!   - GetSetConnectionBits: withheld, reaches state this peripheral does not have: st.connections
//!   - InputData: callback for bit 0 needs peer method(s) not yet emitted: get_value_from_bits_array
//!   - Mode: callback for bit 0 needs peer method(s) not yet emitted: change_mode
//!   - Mode: callback for bit 0 needs peer method(s) not yet emitted: st.mode[..]
//!   - OnGPIO: withheld, reaches state this peripheral does not have: st.irq
//!   - OutputData: callback for bit 0 needs peer method(s) not yet emitted: get_value_from_bits_array
//!   - OutputData: callback for bit 0 needs peer method(s) not yet emitted: write_state
//!   - OutputSpeed: callback for bit 0 needs peer method(s) not yet emitted: st.output_speed[..]
//!   - PullUpPullDown: callback for bit 0 needs peer method(s) not yet emitted: st.pull_up_pull_down[..]
//!   - Register: parameter `peripheral` has no Rust mapping for `Antmicro.Renode.Core.IGPIOSender`
//!   - Reset: withheld, reaches state this peripheral does not have: st.alternate_function_outputs, st.get_value
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: `new` is emitted but nothing calls it. What arguments a given instance is constructed with is configuration of the system being modelled, not a fact in the corpus, so the converter cannot supply them
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: parameter(s) `modeResetValue`, `outputSpeedResetValue`, `pullUpPullDownResetValue`, `numberOfAFs` have a C# default value that the corpus does not record -- `parameter.has_default` is stored, the value is not -- so `Self::default()` cannot use them and leaves those fields at 0/false
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 1 withheld -- not an assignment to the type's own storage, but Conditional; an initialiser can only assign the struct it is building
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 11 withheld -- assigns `alternateFunctionOutputs`, which the emitted struct has no storage for
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 12 withheld -- not an assignment to the type's own storage, but Loop; an initialiser can only assign the struct it is building
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 13 withheld -- assigns `registers`, which the emitted struct has no storage for
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 14 withheld -- not an assignment to the type's own storage, but Invocation; an initialiser can only assign the struct it is building
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 2 withheld -- not an assignment to the type's own storage, but Conditional; an initialiser can only assign the struct it is building
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 3 withheld -- not an assignment to the type's own storage, but Loop; an initialiser can only assign the struct it is building
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 4 withheld -- the assigned value contains ArrayCreation, which an initialiser cannot evaluate
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 5 withheld -- the assigned value contains ArrayCreation, which an initialiser cannot evaluate
//!   - STM32_GPIOPort..ctor `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`: statement 6 withheld -- the assigned value contains ArrayCreation, which an initialiser cannot evaluate
//!   - SetConnectionStateBit: withheld, cannot emit stmt:Throw
//!   - Unregister: parameter `peripheral` has no Rust mapping for `Antmicro.Renode.Core.IGPIOSender`
//!   - WritePin: withheld, reaches state this peripheral does not have: st.irq
//!   - base_gpio_port_reset: withheld, calls withheld method(s): connections, unset
//!   - set_connections_state_using_bits: withheld, calls withheld method(s): connections, set, unset
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 2
//!   - state field `alternateFunctionOutputs`: reference-typed, so the object-graph rule maps it to `Vec<Gc<GPIOAlternateFunction>>`; blocked: `GPIOAlternateFunction` has no emitted Rust type yet, so there is nothing to point at
//!   - state field `invertedAFPins`: no Rust mapping for `System.Collections.Generic.HashSet<Antmicro.Renode.Peripherals.GPIOPort.STM32_GPIOPort.InvertedAFPin>`
//!   - state field `machine`: needs trait `IMachine` (D1 maps the field; the trait is issue #41). IMachine declares 112 members, the corpus calls 7
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

// C# constructors, as field assignments over the derived
// `Default`. Only assignments to this type's own storage can
// live here; everything else the constructor did is a gap above.
impl State {
    /// C# `STM32_GPIOPort(IMachine, uint, uint, uint, uint, List<List<int>>)`, field assignments only.
    pub fn new(mode_reset_value: u32, output_speed_reset_value: u32, pull_up_pull_down_reset_value: u32, number_of_a_fs: u32) -> Self {
        let mut st = Self::default();
        st.mode_reset_value = mode_reset_value;
        st.output_speed_reset_value = output_speed_reset_value;
        st.pull_up_pull_down_reset_value = pull_up_pull_down_reset_value;
        st.number_of_a_fs = number_of_a_fs;
        st
    }
}

// The peripheral's own methods. C# reaches its state through
// `this`; these receive it as (bank, st) instead, so a callback
// can call them -- a closure cannot borrow what it lives inside.
pub fn base_gpio_port_on_gpio(bank: &Bank<State>, st: &mut State, number: i32, value: bool) -> () {
    if !check_pin_number(bank, st, number) {
        return;
    }
    st.state[number as usize] = value;
}

pub fn check_pin_number(bank: &Bank<State>, st: &mut State, number: i32) -> bool {
    if ((number < 0) || (number >= st.number_of_connections)) {
        log::error!("This peripheral supports gpio inputs from 0 to {}, but {} was called.", st.number_of_connections, number);
        return false;
    }
    return true;
}

pub fn read_double_word(bank: &Bank<State>, st: &mut State, offset: i64) -> u32 {
    return bank.read(offset as u64, st).unwrap_or(0) as u32;
}

pub fn write_double_word(bank: &Bank<State>, st: &mut State, offset: i64, value: u32) -> () {
    bank.write(offset as u64, value as u64, st);
}

/// C# `DefineRegisters()`, field for field.
pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::MODE, 0)
        .with_values_cb(0, 2, 16, FieldMode::READ_WRITE, None, None)
        .done();

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

    bank.define(reg::OUTPUT_SPEED, 0)
        .with_values_cb(0, 2, 16, FieldMode::READ_WRITE, None, None)
        .done();

    bank.define(reg::PULL_UP_PULL_DOWN, 0)
        .with_values_cb(0, 2, 16, FieldMode::READ_WRITE, None, None)
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

    bank.define(reg::ALTERNATE_FUNCTION_LOW, 0)
        .with_values_cb(0, 4, 8, FieldMode::READ_WRITE, None, None)
        .done();

    bank.define(reg::ALTERNATE_FUNCTION_HIGH, 0)
        .with_values_cb(0, 4, 8, FieldMode::READ_WRITE, None, None)
        .done();

    bank.define(reg::BIT_RESET, 0)
        .with_value_cb(0, 16, FieldMode::WRITE, None, None)
        .with_reserved(16, 16)
        .done();

}
