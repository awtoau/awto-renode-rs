//! Register layout for `STMCAN`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STMCAN.AddressIsWithinFilterRegistersArea
//!
//! GAPS the converter reports rather than guessing:
//!   - AddressToFilterBankIdx: withheld, cannot emit expr:SizeOf
//!   - AddressToRegIdx: withheld, cannot emit expr:SizeOf
//!   - EnableFifo0Interrupt: withheld, reaches state this peripheral does not have: st.registers
//!   - EnableFifo1Interrupt: withheld, reaches state this peripheral does not have: st.registers
//!   - EnableSCEInterrupt: withheld, reaches state this peripheral does not have: st.registers
//!   - EnableTransmitInterrupt: withheld, reaches state this peripheral does not have: st.registers
//!   - FilterCANMessage: parameter `msg` has no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN.CANMessage`
//!   - OnFrameReceived: parameter `message` has no Rust mapping for `Antmicro.Renode.Core.CAN.CANMessageFrame`
//!   - PrioritizeFiFoFilters: withheld, reaches state this peripheral does not have: st.fifo_filters_prioritized, st.filter_banks
//!   - ReadDoubleWord: withheld, reaches state this peripheral does not have: st.filter_banks, st.registers, st.rx_fifo
//!   - ReceiveCANMessage: parameter `msg` has no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN.CANMessage`
//!   - Reset: withheld, reaches state this peripheral does not have: st.filter_banks, st.registers
//!   - TransmitData: parameter `msg` has no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN.CANMessage`
//!   - UpdateFifo0InterruptLine: withheld, reaches state this peripheral does not have: st.connections
//!   - UpdateFifo1InterruptLine: withheld, reaches state this peripheral does not have: st.connections
//!   - UpdateFilterCANAssignment: withheld, reaches state this peripheral does not have: st.filter_banks, st.registers
//!   - UpdateSCEInterruptLine: withheld, reaches state this peripheral does not have: st.connections
//!   - UpdateTransmitInterruptLine: withheld, reaches state this peripheral does not have: st.connections
//!   - WriteDoubleWord: withheld, reaches state this peripheral does not have: st.filter_banks, st.registers
//!   - get_IsSlave: withheld, reaches state this peripheral does not have: st.master
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 2
//!   - state field `FifoFiltersPrioritized`: no Rust mapping for `System.Collections.Generic.List<Antmicro.Renode.Peripherals.CAN.STMCAN.FilterBank>[]`
//!   - state field `FilterBanks`: no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN.FilterBank[]`
//!   - state field `FrameSent`: no Rust mapping for `System.Action<Antmicro.Renode.Core.CAN.CANMessageFrame>`
//!   - state field `RxFifo`: no Rust mapping for `System.Collections.Generic.Queue<Antmicro.Renode.Peripherals.CAN.STMCAN.CANMessage>[]`
//!   - state field `master`: no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN`
//!   - state field `registers`: no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN.DeviceRegisters`

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
}

/// Field handles bound by `out` parameters in the C#.
#[derive(Default)]
pub struct Fields {
}

/// C# `enum FilterBankMode`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum FilterBankMode {
    #[default] FilterModeIdMask = 0,
    FilterIdentifierList = 1,
}

impl FilterBankMode {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::FilterModeIdMask,
            1 => Self::FilterIdentifierList,
            _ => Self::default(),
        }
    }
}

/// C# `enum FilterBankScale`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum FilterBankScale {
    #[default] FilterScale16Bit = 0,
    FilterScale32Bit = 1,
}

impl FilterBankScale {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::FilterScale16Bit,
            1 => Self::FilterScale32Bit,
            _ => Self::default(),
        }
    }
}

/// C# `enum RegisterOffset`, discriminants as declared.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u64)]
pub enum RegisterOffset {
    #[default] CAN_MCR = 0,
    CAN_MSR = 4,
    CAN_TSR = 8,
    CAN_RF0R = 12,
    CAN_RF1R = 16,
    CAN_IER = 20,
    CAN_ESR = 24,
    CAN_BTR = 28,
    CAN_TI0R = 384,
    CAN_TDT0R = 388,
    CAN_TDL0R = 392,
    CAN_TDH0R = 396,
    CAN_TI1R = 400,
    CAN_TDT1R = 404,
    CAN_TDL1R = 408,
    CAN_TDH1R = 412,
    CAN_TI2R = 416,
    CAN_TDT2R = 420,
    CAN_TDL2R = 424,
    CAN_TDH2R = 428,
    CAN_RI0R = 432,
    CAN_RDT0R = 436,
    CAN_RL0R = 440,
    CAN_RH0R = 444,
    CAN_RI1R = 448,
    CAN_RDT1R = 452,
    CAN_RL1R = 456,
    CAN_RH1R = 460,
    CAN_FMR = 512,
    CAN_FM1R = 516,
    CAN_FS1R = 524,
    CAN_FFA1R = 532,
    CAN_FA1R = 540,
    CAN_F0R1 = 576,
    CAN_F27R2 = 796,
}

impl RegisterOffset {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::CAN_MCR,
            4 => Self::CAN_MSR,
            8 => Self::CAN_TSR,
            12 => Self::CAN_RF0R,
            16 => Self::CAN_RF1R,
            20 => Self::CAN_IER,
            24 => Self::CAN_ESR,
            28 => Self::CAN_BTR,
            384 => Self::CAN_TI0R,
            388 => Self::CAN_TDT0R,
            392 => Self::CAN_TDL0R,
            396 => Self::CAN_TDH0R,
            400 => Self::CAN_TI1R,
            404 => Self::CAN_TDT1R,
            408 => Self::CAN_TDL1R,
            412 => Self::CAN_TDH1R,
            416 => Self::CAN_TI2R,
            420 => Self::CAN_TDT2R,
            424 => Self::CAN_TDL2R,
            428 => Self::CAN_TDH2R,
            432 => Self::CAN_RI0R,
            436 => Self::CAN_RDT0R,
            440 => Self::CAN_RL0R,
            444 => Self::CAN_RH0R,
            448 => Self::CAN_RI1R,
            452 => Self::CAN_RDT1R,
            456 => Self::CAN_RL1R,
            460 => Self::CAN_RH1R,
            512 => Self::CAN_FMR,
            516 => Self::CAN_FM1R,
            524 => Self::CAN_FS1R,
            532 => Self::CAN_FFA1R,
            540 => Self::CAN_FA1R,
            576 => Self::CAN_F0R1,
            796 => Self::CAN_F27R2,
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
    pub frame_received: Option<Box<dyn FnMut(i32, Vec<u8>)>>,
}

/// C# `DefineRegisters()`, field for field.
pub fn define_registers(bank: &mut Bank<State>, f: &mut Fields) {
}
