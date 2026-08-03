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
//!   - CAN_RDT0R: the case body is not a layout shape -- 1 statement(s), the first a `Conditional`, compute rather than store. The register is NOT in the bank.
//!   - CAN_RDT1R: the case body is not a layout shape -- 1 statement(s), the first a `Conditional`, compute rather than store. The register is NOT in the bank.
//!   - CAN_RF0R: `ReceiveFifoRegister.GetValue()` composes a term this rule cannot place (the masked operand is computed, not stored); those bits are absent from the register.
//!   - CAN_RF0R: `ReceiveFifoRegister.SetValue()` has 2 statement(s) whose write semantics this rule cannot express (a conditional this rule cannot read); the bits they touch are emitted READ-ONLY, so a write the C# accepts is dropped here.
//!   - CAN_RF1R: `ReceiveFifoRegister.GetValue()` composes a term this rule cannot place (the masked operand is computed, not stored); those bits are absent from the register.
//!   - CAN_RF1R: `ReceiveFifoRegister.SetValue()` has 2 statement(s) whose write semantics this rule cannot express (a conditional this rule cannot read); the bits they touch are emitted READ-ONLY, so a write the C# accepts is dropped here.
//!   - CAN_RH0R: the case body is not a layout shape -- 1 statement(s), the first a `Conditional`, compute rather than store. The register is NOT in the bank.
//!   - CAN_RH1R: the case body is not a layout shape -- 1 statement(s), the first a `Conditional`, compute rather than store. The register is NOT in the bank.
//!   - CAN_RI0R: the case body is not a layout shape -- 1 statement(s), the first a `Conditional`, compute rather than store. The register is NOT in the bank.
//!   - CAN_RI1R: the case body is not a layout shape -- 1 statement(s), the first a `Conditional`, compute rather than store. The register is NOT in the bank.
//!   - CAN_RL0R: the case body is not a layout shape -- 1 statement(s), the first a `Conditional`, compute rather than store. The register is NOT in the bank.
//!   - CAN_RL1R: the case body is not a layout shape -- 1 statement(s), the first a `Conditional`, compute rather than store. The register is NOT in the bank.
//!   - CAN_TSR: `TransmitStatusRegister.SetValue()` has 12 statement(s) whose write semantics this rule cannot express (a conditional this rule cannot read); the bits they touch are emitted READ-ONLY, so a write the C# accepts is dropped here.
//!   - EnableFifo0Interrupt: withheld, reaches state this peripheral does not have: st.registers
//!   - EnableFifo1Interrupt: withheld, reaches state this peripheral does not have: st.registers
//!   - EnableSCEInterrupt: withheld, reaches state this peripheral does not have: st.registers
//!   - EnableTransmitInterrupt: withheld, reaches state this peripheral does not have: st.registers
//!   - FilterCANMessage: parameter `msg` has no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN.CANMessage`
//!   - OnFrameReceived: parameter `message` has no Rust mapping for `Antmicro.Renode.Core.CAN.CANMessageFrame`
//!   - PrioritizeFiFoFilters: withheld, reaches state this peripheral does not have: st.fifo_filters_prioritized, st.filter_banks
//!   - ReadDoubleWord: withheld, cannot emit expr:StaticInvocation:Logger.LogUnhandledRead
//!   - ReceiveCANMessage: parameter `msg` has no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN.CANMessage`
//!   - Reset: withheld, reaches state this peripheral does not have: st.filter_banks, st.registers
//!   - STMCAN..ctor `STMCAN(STMCAN)`: no statement could be translated, so no initialiser is emitted at all
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 1 withheld -- assigns `master`, which the emitted struct has no storage for
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 10 withheld -- assigns `UpdateInterruptLine`, which the emitted struct has no storage for
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 11 withheld -- not an assignment to the type's own storage, but Conditional; an initialiser can only assign the struct it is building
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 12 withheld -- not an assignment to the type's own storage, but Invocation; an initialiser can only assign the struct it is building
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 2 withheld -- not an assignment to the type's own storage, but Loop; an initialiser can only assign the struct it is building
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 3 withheld -- not an assignment to the type's own storage, but VariableDeclarationGroup; an initialiser can only assign the struct it is building
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 4 withheld -- not an assignment to the type's own storage, but Loop; an initialiser can only assign the struct it is building
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 5 withheld -- assigns `Connections`, which the emitted struct has no storage for
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 6 withheld -- assigns `registers`, which the emitted struct has no storage for
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 7 withheld -- not an assignment to the type's own storage, but Invocation; an initialiser can only assign the struct it is building
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 8 withheld -- assigns `UpdateInterruptLine`, which the emitted struct has no storage for
//!   - STMCAN..ctor `STMCAN(STMCAN)`: statement 9 withheld -- not an assignment to the type's own storage, but Invocation; an initialiser can only assign the struct it is building
//!   - TransmitData: parameter `msg` has no Rust mapping for `Antmicro.Renode.Peripherals.CAN.STMCAN.CANMessage`
//!   - UpdateFifo0InterruptLine: withheld, cannot emit expr:StaticInvocation:IGPIOExtensions.Set, expr:StaticInvocation:IGPIOExtensions.Unset
//!   - UpdateFifo1InterruptLine: withheld, cannot emit expr:StaticInvocation:IGPIOExtensions.Set, expr:StaticInvocation:IGPIOExtensions.Unset
//!   - UpdateFilterCANAssignment: withheld, reaches state this peripheral does not have: st.filter_banks, st.registers
//!   - UpdateSCEInterruptLine: withheld, cannot emit expr:StaticInvocation:IGPIOExtensions.Set, expr:StaticInvocation:IGPIOExtensions.Unset
//!   - UpdateTransmitInterruptLine: withheld, cannot emit expr:StaticInvocation:IGPIOExtensions.Set, expr:StaticInvocation:IGPIOExtensions.Unset
//!   - WriteDoubleWord: withheld, cannot emit expr:StaticInvocation:Logger.LogUnhandledWrite
//!   - get_IsSlave: withheld, reaches state this peripheral does not have: st.master
//!   - offsets 0x240..0x31C are decoded by a RANGE TEST in front of the switch, not by a case, so they are a replicated block rather than named registers. NOTHING in that range is in the bank.
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 5
//!   - state field `FifoFiltersPrioritized`: no Rust mapping for `System.Collections.Generic.List<Antmicro.Renode.Peripherals.CAN.STMCAN.FilterBank>[]`
//!   - state field `FilterBanks`: reference-typed, so the object-graph rule maps it to `Vec<Gc<FilterBank>>`; blocked: `FilterBank` has no emitted Rust type yet, so there is nothing to point at
//!   - state field `FrameSent`: no Rust mapping for `System.Action<Antmicro.Renode.Core.CAN.CANMessageFrame>`
//!   - state field `RxFifo`: no Rust mapping for `System.Collections.Generic.Queue<Antmicro.Renode.Peripherals.CAN.STMCAN.CANMessage>[]`
//!   - state field `master`: reference-typed, so the object-graph rule maps it to `Gc<STMCAN>`; blocked: `STMCAN` has no emitted Rust type yet, so there is nothing to point at
//!   - state field `registers`: reference-typed, so the object-graph rule maps it to `Gc<DeviceRegisters>`; blocked: `DeviceRegisters` has no emitted Rust type yet, so there is nothing to point at
//!   - static call `IGPIOExtensions.Set` has no Rust mapping
//!   - static call `IGPIOExtensions.Unset` has no Rust mapping
//!   - static call `Logger.LogUnhandledRead` has no Rust mapping
//!   - static call `Logger.LogUnhandledWrite` has no Rust mapping
//!
//! SOURCE DEFECTS -- the C# is wrong here and this reproduces
//! the defect FAITHFULLY, which is what the oracle requires.
//! Do not `fix` one: see rulesdb/rules/bug_rules.json, which
//! carries the contradicting authority and the measured cost
//! of switching each to conformance.
//!   ? SRCBUG(can_btr_reserved_read_write) x1: C# defect: CAN_BTR bits 10-15, 23 and 26-29 are stored and read back; ST makes them reserved.
//!   ? SRCBUG(can_ffa1r_reserved_read_write) x1: C# defect: CAN_FFA1R bits 28-31 are stored and read back; ST makes them reserved.
//!   ? SRCBUG(can_fm1r_reserved_read_write) x1: C# defect: CAN_FM1R bits 28-31 are stored and read back; ST makes them reserved.
//!   ? SRCBUG(can_fmr_reserved_read_write) x1: C# defect: CAN_FMR bits 1-7 and 14-31 are stored and read back; ST makes them reserved.
//!   ? SRCBUG(can_fs1r_reserved_read_write) x1: C# defect: CAN_FS1R bits 28-31 are stored and read back; ST makes them reserved.
//!   ? SRCBUG(can_tsr_terr0_clears_terr1) x1: C# defect: writing 1 to CAN_TSR.TERR0 (bit 3) clears TERR1 (bit 11) and leaves TERR0 set.
//!
//! WARNINGS -- these DID emit, and their semantics DIFFER from
//! the source. Marked at every site, not only summarised here:
//!   ! WARN(condwrite) x4: the source performs this access only under a guard; here it is UNCONDITIONAL. The guard reads state this declaration cannot see.
//!   ! WARN(narrowed) x2: a value outside the declared set has no variant here: the source keeps the number, this falls back to the default.

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
    pub const CAN_MCR: u64 = 0x00;
    pub const CAN_MSR: u64 = 0x04;
    pub const CAN_TSR: u64 = 0x08;
    pub const CAN_RF0R: u64 = 0x0C;
    pub const CAN_RF1R: u64 = 0x10;
    pub const CAN_IER: u64 = 0x14;
    pub const CAN_ESR: u64 = 0x18;
    pub const CAN_BTR: u64 = 0x1C;
    pub const CAN_TI0R: u64 = 0x180;
    pub const CAN_TDT0R: u64 = 0x184;
    pub const CAN_TDL0R: u64 = 0x188;
    pub const CAN_TDH0R: u64 = 0x18C;
    pub const CAN_TI1R: u64 = 0x190;
    pub const CAN_TDT1R: u64 = 0x194;
    pub const CAN_TDL1R: u64 = 0x198;
    pub const CAN_TDH1R: u64 = 0x19C;
    pub const CAN_TI2R: u64 = 0x1A0;
    pub const CAN_TDT2R: u64 = 0x1A4;
    pub const CAN_TDL2R: u64 = 0x1A8;
    pub const CAN_TDH2R: u64 = 0x1AC;
    pub const CAN_FMR: u64 = 0x200;
    pub const CAN_FM1R: u64 = 0x204;
    pub const CAN_FS1R: u64 = 0x20C;
    pub const CAN_FFA1R: u64 = 0x214;
    pub const CAN_FA1R: u64 = 0x21C;
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

// WARN(narrowed): a value outside the declared set has no variant here: the source keeps the number, this falls back to the default.
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

// WARN(narrowed): a value outside the declared set has no variant here: the source keeps the number, this falls back to the default.
impl FilterBankScale {
    pub fn from_u64(v: u64) -> Self {
        match v {
            0 => Self::FilterScale16Bit,
            1 => Self::FilterScale32Bit,
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
    bank.define(reg::CAN_MCR, 0x10002)
        .with_flag_anon(0, FieldMode::READ_WRITE)
        .with_flag_anon(1, FieldMode::READ_WRITE)
        .with_flag_anon(2, FieldMode::READ_WRITE)
        .with_flag_anon(3, FieldMode::READ_WRITE)
        .with_flag_anon(4, FieldMode::READ_WRITE)
        .with_flag_anon(5, FieldMode::READ_WRITE)
        .with_flag_anon(6, FieldMode::READ_WRITE)
        .with_flag_anon(7, FieldMode::READ_WRITE)
        .with_flag_anon(15, FieldMode::WRITE)
        .with_flag_anon(16, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_MSR, 0xC02)
        .with_flag_anon(0, FieldMode::READ)
        .with_flag_anon(1, FieldMode::READ)
        .with_flag_anon(2, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
        .with_flag_anon(3, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
        .with_flag_anon(4, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
        .with_flag_anon(8, FieldMode::READ)
        .with_flag_anon(9, FieldMode::READ)
        .with_flag_anon(10, FieldMode::READ)
        .with_flag_anon(11, FieldMode::READ)
        .done();

    // SRCBUG(can_tsr_terr0_clears_terr1): C# defect: writing 1 to CAN_TSR.TERR0 (bit 3) clears TERR1 (bit 11) and leaves TERR0 set.
    bank.define(reg::CAN_TSR, 0x1C000000)
        .with_value_anon(0, 32, FieldMode::READ)
        .done();

    bank.define(reg::CAN_RF0R, 0)
        .with_flag_anon(3, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
        .with_flag_anon(4, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
        .done();

    bank.define(reg::CAN_RF1R, 0)
        .with_flag_anon(3, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
        .with_flag_anon(4, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
        .done();

    bank.define(reg::CAN_IER, 0)
        .with_flag_anon(0, FieldMode::READ_WRITE)
        .with_flag_anon(1, FieldMode::READ_WRITE)
        .with_flag_anon(2, FieldMode::READ_WRITE)
        .with_flag_anon(3, FieldMode::READ_WRITE)
        .with_flag_anon(4, FieldMode::READ_WRITE)
        .with_flag_anon(5, FieldMode::READ_WRITE)
        .with_flag_anon(6, FieldMode::READ_WRITE)
        .with_flag_anon(8, FieldMode::READ_WRITE)
        .with_flag_anon(9, FieldMode::READ_WRITE)
        .with_flag_anon(10, FieldMode::READ_WRITE)
        .with_flag_anon(11, FieldMode::READ_WRITE)
        .with_flag_anon(15, FieldMode::READ_WRITE)
        .with_flag_anon(16, FieldMode::READ_WRITE)
        .with_flag_anon(17, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_ESR, 0)
        .with_flag_anon(0, FieldMode::READ)
        .with_flag_anon(1, FieldMode::READ)
        .with_flag_anon(2, FieldMode::READ)
        .with_value_anon(4, 3, FieldMode::READ_WRITE)
        .with_value_anon(16, 8, FieldMode::READ_WRITE)
        .with_value_anon(24, 8, FieldMode::READ_WRITE)
        .done();

    // WARN(condwrite): the source performs this access only under a guard; here it is UNCONDITIONAL. The guard reads state this declaration cannot see.
    // SRCBUG(can_btr_reserved_read_write): C# defect: CAN_BTR bits 10-15, 23 and 26-29 are stored and read back; ST makes them reserved.
    bank.define(reg::CAN_BTR, 0x1230000)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TI0R, 0)
        .with_flag_anon(0, FieldMode::READ)
        .with_value_anon(1, 31, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDT0R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDL0R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDH0R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TI1R, 0)
        .with_flag_anon(0, FieldMode::READ)
        .with_value_anon(1, 31, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDT1R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDL1R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDH1R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TI2R, 0)
        .with_flag_anon(0, FieldMode::READ)
        .with_value_anon(1, 31, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDT2R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDL2R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_TDH2R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    // SRCBUG(can_fmr_reserved_read_write): C# defect: CAN_FMR bits 1-7 and 14-31 are stored and read back; ST makes them reserved.
    bank.define(reg::CAN_FMR, 0x2A1C0E01)
        .with_flag_anon(0, FieldMode::READ_WRITE)
        .with_value_anon(1, 7, FieldMode::READ_WRITE)
        .with_value_anon(8, 6, FieldMode::READ_WRITE)
        .with_value_anon(14, 18, FieldMode::READ_WRITE)
        .done();

    // WARN(condwrite): the source performs this access only under a guard; here it is UNCONDITIONAL. The guard reads state this declaration cannot see.
    // SRCBUG(can_fm1r_reserved_read_write): C# defect: CAN_FM1R bits 28-31 are stored and read back; ST makes them reserved.
    bank.define(reg::CAN_FM1R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    // WARN(condwrite): the source performs this access only under a guard; here it is UNCONDITIONAL. The guard reads state this declaration cannot see.
    // SRCBUG(can_fs1r_reserved_read_write): C# defect: CAN_FS1R bits 28-31 are stored and read back; ST makes them reserved.
    bank.define(reg::CAN_FS1R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    // WARN(condwrite): the source performs this access only under a guard; here it is UNCONDITIONAL. The guard reads state this declaration cannot see.
    // SRCBUG(can_ffa1r_reserved_read_write): C# defect: CAN_FFA1R bits 28-31 are stored and read back; ST makes them reserved.
    bank.define(reg::CAN_FFA1R, 0)
        .with_value_anon(0, 32, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::CAN_FA1R, 0)
        .with_value_anon(0, 28, FieldMode::READ_WRITE)
        .with_value_anon(28, 4, FieldMode::READ)
        .done();

}
