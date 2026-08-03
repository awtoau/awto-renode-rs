//! Register layout for `STM32DMA`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32DMA.DefineRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - BasicDoubleWordPeripheral..ctor `BasicDoubleWordPeripheral(IMachine)`: a base constructor, run by C# before the derived body and NOT inlined here -- inlining it means substituting the derived type's arguments for its parameters, so every field only this one assigns stays at Default
//!   - ClearIrqFlagOnCondition: parameter `flag` has no Rust mapping for `Antmicro.Renode.Core.Structure.Registers.IFlagRegisterField`
//!   - HighInterruptClear: callback for bit 11 needs peer method(s) not yet emitted: clear_irq_flag_on_condition
//!   - HighInterruptClear: callback for bit 11 reaches state this peripheral does not have: st.transfer_complete_irq_status
//!   - HighInterruptClear: callback for bit 21 needs peer method(s) not yet emitted: clear_irq_flag_on_condition
//!   - HighInterruptClear: callback for bit 21 reaches state this peripheral does not have: st.transfer_complete_irq_status
//!   - HighInterruptClear: callback for bit 27 needs peer method(s) not yet emitted: clear_irq_flag_on_condition
//!   - HighInterruptClear: callback for bit 27 reaches state this peripheral does not have: st.transfer_complete_irq_status
//!   - HighInterruptClear: callback for bit 5 needs peer method(s) not yet emitted: clear_irq_flag_on_condition
//!   - HighInterruptClear: callback for bit 5 reaches state this peripheral does not have: st.transfer_complete_irq_status
//!   - LowInterruptClear: callback for bit 11 needs peer method(s) not yet emitted: clear_irq_flag_on_condition
//!   - LowInterruptClear: callback for bit 11 reaches state this peripheral does not have: st.transfer_complete_irq_status
//!   - LowInterruptClear: callback for bit 21 needs peer method(s) not yet emitted: clear_irq_flag_on_condition
//!   - LowInterruptClear: callback for bit 21 reaches state this peripheral does not have: st.transfer_complete_irq_status
//!   - LowInterruptClear: callback for bit 27 needs peer method(s) not yet emitted: clear_irq_flag_on_condition
//!   - LowInterruptClear: callback for bit 27 reaches state this peripheral does not have: st.transfer_complete_irq_status
//!   - LowInterruptClear: callback for bit 5 needs peer method(s) not yet emitted: clear_irq_flag_on_condition
//!   - LowInterruptClear: callback for bit 5 reaches state this peripheral does not have: st.transfer_complete_irq_status
//!   - OffsetToString: withheld, reaches state this peripheral does not have: st.mapper
//!   - Reset: withheld, calls reset on each `Stream` -- the sub-block emits its register layout, not its methods
//!   - STM32DMA..ctor `STM32DMA(IMachine)`: no statement could be translated, so no initialiser is emitted at all
//!   - STM32DMA..ctor `STM32DMA(IMachine)`: statement 1 withheld -- the assigned value contains Invocation, which an initialiser cannot evaluate
//!   - STM32DMA..ctor `STM32DMA(IMachine)`: statement 2 withheld -- assigns `Connections`, which the emitted struct has no storage for
//!   - STM32DMA..ctor `STM32DMA(IMachine)`: statement 3 withheld -- assigns `engine`, which the emitted struct has no storage for
//!   - STM32DMA..ctor `STM32DMA(IMachine)`: statement 4 withheld -- assigns `transferCompleteIrqStatus`, which the emitted struct has no storage for
//!   - STM32DMA..ctor `STM32DMA(IMachine)`: statement 5 withheld -- not an assignment to the type's own storage, but Invocation; an initialiser can only assign the struct it is building
//!   - STM32DMA..ctor `STM32DMA(IMachine)`: statement 6 withheld -- not an assignment to the type's own storage, but Invocation; an initialiser can only assign the struct it is building
//!   - UpdateInterrupts: withheld, reaches state this peripheral does not have: st.irq
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 5
//!   - state field `engine`: reference-typed, so the object-graph rule maps it to `Gc<DmaEngine>`; blocked: `DmaEngine` has no emitted Rust type yet, so there is nothing to point at
//!   - state field `machine`: needs trait `IMachine` (D1 maps the field; the trait is issue #41). IMachine declares 112 members, the corpus calls 38
//!   - state field `sysbus`: needs trait `IBusController` (D1 maps the field; the trait is issue #41). IBusController declares 73 members, the corpus calls 66
//!   - stream: StreamConfiguration: callback for bit 0 needs peer method(s) not yet emitted: handle_enable
//!   - stream: state field `IRQ`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 5
//!   - stream: state field `parent`: reference-typed, so the object-graph rule maps it to `Gc<STM32DMA>`; blocked: `STM32DMA` has no emitted Rust type yet, so there is nothing to point at
//!
//! WARNINGS -- these DID emit, and their semantics DIFFER from
//! the source. Marked at every site, not only summarised here:
//!   ! WARN(narrowed) x3: a value outside the declared set has no variant here: the source keeps the number, this falls back to the default.

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
    pub const LOW_INTERRUPT_STATUS: u64 = 0x00;
    pub const HIGH_INTERRUPT_STATUS: u64 = 0x04;
    pub const LOW_INTERRUPT_CLEAR: u64 = 0x08;
    pub const HIGH_INTERRUPT_CLEAR: u64 = 0x0C;
    pub const STREAM_CONFIGURATION: u64 = 0x10;
    pub const STREAM_NUMBER_OF_DATA: u64 = 0x14;
    pub const STREAM_PERIPHERAL_ADDRESS: u64 = 0x18;
    pub const STREAM_MEMORY0_ADDRESS: u64 = 0x1C;
    pub const STREAM_MEMORY1_ADDRESS: u64 = 0x20;
    pub const STREAM_FIFO_CONTROL: u64 = 0x24;
}

/// Field handles bound by `out` parameters in the C#.
#[derive(Default)]
pub struct Fields {
    pub transfer_complete_irq_status: [FlagId; 8],
    /// One set of handles per `Stream`; the register map is the parent's.
    pub streams: Vec<stream::Fields>,
}

/// C# `const int NrOfStreams`.
pub const NR_OF_STREAMS: usize = 8;

/// C# nested `Stream`, 8 instances. Each one
/// defines its registers into the PARENT's bank at a computed
/// offset, so there is one flat register map and no dispatch.
pub mod stream {
    use super::{Bank, FieldMode, FlagId, ValueId, reg};

    /// Handles bound by this instance's `out` parameters.
    #[derive(Default)]
    pub struct Fields {
        pub is_enabled: FlagId,
        pub transfer_complete_irq_enable: FlagId,
        pub direction: ValueId,
        pub peripheral_increment_offset: FlagId,
        pub memory_increment_offset: FlagId,
        pub peripheral_data_size: ValueId,
        pub memory_data_size: ValueId,
        pub nr_of_data: ValueId,
        pub peripheral_address: ValueId,
        pub memory0_address: ValueId,
        pub fifo_threshold: ValueId,
        pub direct_mode: FlagId,
    }

    /// The child's own state. The C# back-reference to the parent is
    /// dropped: the parent arrives as `bank`, so storing it would be a
    /// cycle Rust cannot express and the C# only needed for reachability.
    #[derive(Default)]
    pub struct State {
        pub data_offset: u64,
        pub id: i32,
    }

    pub fn define_registers(bank: &mut Bank<super::State>, f: &mut Fields, st: &State) {
        let mut stream_offset = csharp_rt::unchecked_mul(st.id, 24);

        bank.define(reg::STREAM_CONFIGURATION + (stream_offset) as u64, 0)
            .with_flag_cb(0, &mut f.is_enabled, FieldMode::READ_WRITE, None, None)
            .with_tagged_flag(1)
            .with_tagged_flag(2)
            .with_tagged_flag(3)
            .with_flag(4, &mut f.transfer_complete_irq_enable, FieldMode::READ_WRITE)
            .with_tagged_flag(5)
            .with_value(6, 2, &mut f.direction, FieldMode::READ_WRITE)
            .with_tagged_flag(8)
            .with_flag(9, &mut f.peripheral_increment_offset, FieldMode::READ_WRITE)
            .with_flag(10, &mut f.memory_increment_offset, FieldMode::READ_WRITE)
            .with_value(11, 2, &mut f.peripheral_data_size, FieldMode::READ_WRITE)
            .with_value(13, 2, &mut f.memory_data_size, FieldMode::READ_WRITE)
            .with_tagged_flag(15)
            .with_tag(16, 2)
            .with_tagged_flag(18)
            .with_tagged_flag(19)
            .with_tagged_flag(20)
            .with_tag(21, 2)
            .with_tag(23, 2)
            .with_reserved(25, 7)
            .done();

        bank.define(reg::STREAM_NUMBER_OF_DATA + (stream_offset) as u64, 0)
            .with_value(0, 16, &mut f.nr_of_data, FieldMode::READ_WRITE)
            .with_reserved(16, 16)
            .done();

        bank.define(reg::STREAM_PERIPHERAL_ADDRESS + (stream_offset) as u64, 0)
            .with_value(0, 32, &mut f.peripheral_address, FieldMode::READ_WRITE)
            .done();

        bank.define(reg::STREAM_MEMORY0_ADDRESS + (stream_offset) as u64, 0)
            .with_value(0, 32, &mut f.memory0_address, FieldMode::READ_WRITE)
            .done();

        bank.define(reg::STREAM_MEMORY1_ADDRESS + (stream_offset) as u64, 0)
            .with_tag(0, 32)
            .done();

        bank.define(reg::STREAM_FIFO_CONTROL + (stream_offset) as u64, 0)
            .with_value(0, 2, &mut f.fifo_threshold, FieldMode::READ_WRITE)
            .with_flag(2, &mut f.direct_mode, FieldMode::READ_WRITE)
            .with_tag(3, 3)
            .with_reserved(6, 1)
            .with_tagged_flag(7)
            .with_reserved(8, 24)
            .done();

    }
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

// WARN(narrowed): a value outside the declared set has no variant here: the source keeps the number, this falls back to the default.
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

// WARN(narrowed): a value outside the declared set has no variant here: the source keeps the number, this falls back to the default.
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

// WARN(narrowed): a value outside the declared set has no variant here: the source keeps the number, this falls back to the default.
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
    pub streams: Vec<stream::State>,
}

// The peripheral's own methods. C# reaches its state through
// `this`; these receive it as (bank, st) instead, so a callback
// can call them -- a closure cannot borrow what it lives inside.
pub fn basic_double_word_peripheral_reset(bank: &Bank<State>, st: &mut State) -> () {
    bank.reset();
}

pub fn on_gpio(bank: &Bank<State>, st: &mut State, number: i32, value: bool) -> () {
    if ((number < 0) || (number >= st.streams.len())) {
        log::warn!("Attempted to signal DMA stream {}. Maximum value is {}", number, csharp_rt::unchecked_sub(st.streams.len(), 1));
        return;
    }
    st.streams[number as usize].on_gpio(value);
}

pub fn read_double_word(bank: &Bank<State>, st: &mut State, offset: i64) -> u32 {
    return bank.read(offset as u64, st).unwrap_or(0) as u32;
}

pub fn size(bank: &Bank<State>, st: &mut State) -> i64 {
    return (1024 as i64);
}

pub fn write_double_word(bank: &Bank<State>, st: &mut State, offset: i64, value: u32) -> () {
    bank.write(offset as u64, value as u64, st);
}

/// C# `DefineRegisters()`, field for field.
pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
    bank.define(reg::LOW_INTERRUPT_STATUS, 0)
        .with_reserved(12, 4)
        .with_reserved(28, 4)
        .with_tagged_flag(0)
        .with_tagged_flag(6)
        .with_tagged_flag(16)
        .with_tagged_flag(22)
        .with_reserved(1, 1)
        .with_reserved(7, 1)
        .with_reserved(17, 1)
        .with_reserved(23, 1)
        .with_tagged_flag(2)
        .with_tagged_flag(8)
        .with_tagged_flag(18)
        .with_tagged_flag(24)
        .with_tagged_flag(3)
        .with_tagged_flag(9)
        .with_tagged_flag(19)
        .with_tagged_flag(25)
        .with_tagged_flag(4)
        .with_tagged_flag(10)
        .with_tagged_flag(20)
        .with_tagged_flag(26)
        .with_flag(5, &mut f.transfer_complete_irq_status[0], FieldMode::READ)
        .with_flag(11, &mut f.transfer_complete_irq_status[1], FieldMode::READ)
        .with_flag(21, &mut f.transfer_complete_irq_status[2], FieldMode::READ)
        .with_flag(27, &mut f.transfer_complete_irq_status[3], FieldMode::READ)
        .done();

    bank.define(reg::HIGH_INTERRUPT_STATUS, 0)
        .with_reserved(12, 4)
        .with_reserved(28, 4)
        .with_tagged_flag(0)
        .with_tagged_flag(6)
        .with_tagged_flag(16)
        .with_tagged_flag(22)
        .with_reserved(1, 1)
        .with_reserved(7, 1)
        .with_reserved(17, 1)
        .with_reserved(23, 1)
        .with_tagged_flag(2)
        .with_tagged_flag(8)
        .with_tagged_flag(18)
        .with_tagged_flag(24)
        .with_tagged_flag(3)
        .with_tagged_flag(9)
        .with_tagged_flag(19)
        .with_tagged_flag(25)
        .with_tagged_flag(4)
        .with_tagged_flag(10)
        .with_tagged_flag(20)
        .with_tagged_flag(26)
        .with_flag(5, &mut f.transfer_complete_irq_status[4], FieldMode::READ)
        .with_flag(11, &mut f.transfer_complete_irq_status[5], FieldMode::READ)
        .with_flag(21, &mut f.transfer_complete_irq_status[6], FieldMode::READ)
        .with_flag(27, &mut f.transfer_complete_irq_status[7], FieldMode::READ)
        .done();

    bank.define(reg::LOW_INTERRUPT_CLEAR, 0)
        .with_reserved(12, 4)
        .with_reserved(28, 4)
        .with_tagged_flag(0)
        .with_tagged_flag(6)
        .with_tagged_flag(16)
        .with_tagged_flag(22)
        .with_reserved(1, 1)
        .with_reserved(7, 1)
        .with_reserved(17, 1)
        .with_reserved(23, 1)
        .with_tagged_flag(2)
        .with_tagged_flag(8)
        .with_tagged_flag(18)
        .with_tagged_flag(24)
        .with_tagged_flag(3)
        .with_tagged_flag(9)
        .with_tagged_flag(19)
        .with_tagged_flag(25)
        .with_tagged_flag(4)
        .with_tagged_flag(10)
        .with_tagged_flag(20)
        .with_tagged_flag(26)
        .with_value_cb(5, 1, FieldMode::SET, None, None)
        .with_value_cb(11, 1, FieldMode::SET, None, None)
        .with_value_cb(21, 1, FieldMode::SET, None, None)
        .with_value_cb(27, 1, FieldMode::SET, None, None)
        .done();

    bank.define(reg::HIGH_INTERRUPT_CLEAR, 0)
        .with_reserved(12, 4)
        .with_reserved(28, 4)
        .with_tagged_flag(0)
        .with_tagged_flag(6)
        .with_tagged_flag(16)
        .with_tagged_flag(22)
        .with_reserved(1, 1)
        .with_reserved(7, 1)
        .with_reserved(17, 1)
        .with_reserved(23, 1)
        .with_tagged_flag(2)
        .with_tagged_flag(8)
        .with_tagged_flag(18)
        .with_tagged_flag(24)
        .with_tagged_flag(3)
        .with_tagged_flag(9)
        .with_tagged_flag(19)
        .with_tagged_flag(25)
        .with_tagged_flag(4)
        .with_tagged_flag(10)
        .with_tagged_flag(20)
        .with_tagged_flag(26)
        .with_value_cb(5, 1, FieldMode::SET, None, None)
        .with_value_cb(11, 1, FieldMode::SET, None, None)
        .with_value_cb(21, 1, FieldMode::SET, None, None)
        .with_value_cb(27, 1, FieldMode::SET, None, None)
        .done();

    f.streams.resize_with(NR_OF_STREAMS, Default::default);
    for id in 0..NR_OF_STREAMS {
        let st = stream::State { id: id as i32, ..Default::default() };
        stream::define_registers(bank, &mut f.streams[id as usize], &st);
    }
}
