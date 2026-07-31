//! Register layout for `STM32_UART`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32_UART.DefineRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - Data: WithValueField: computed field: needs a dispatch arm
//!   - Status: WithFlag: computed field: needs a dispatch arm

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

/// C# `DefineRegisters()`, field for field.
pub fn define_registers<S>(bank: &mut Bank<S>, f: &mut Fields) {
    bank.define(reg::STATUS, 192)
        .with_tagged_flag(0)
        .with_tagged_flag(1)
        .with_tagged_flag(2)
        .with_tagged_flag(3)
        .with_flag(4, &mut f.idle_line_detected, FieldMode::READ)
        .with_flag(5, &mut f.read_fifo_not_empty, FieldMode::READ | FieldMode::WRITE_ZERO_TO_CLEAR)
        .with_flag(6, &mut f.transmission_complete, FieldMode::READ | FieldMode::WRITE_ZERO_TO_CLEAR)
        .with_tagged_flag(7)
        .with_tagged_flag(8)
        .with_tagged_flag(9)
        .with_reserved(10, 22)
        .done();

    bank.define(reg::DATA, 0)
        .with_tag(0, 9)
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
