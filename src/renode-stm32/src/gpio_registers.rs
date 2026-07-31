//! Register layout for `STM32_GPIOPort`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32_GPIOPort.CreateRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - BitReset: WithValueField: computed field: needs a dispatch arm
//!   - BitSet: WithValueField: computed field: needs a dispatch arm
//!   - InputData: WithValueField: computed field: needs a dispatch arm
//!   - OutputData: WithValueField: computed field: needs a dispatch arm

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

/// C# `DefineRegisters()`, field for field.
pub fn define_registers<S>(bank: &mut Bank<S>, f: &mut Fields) {
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
        .with_tag(0, 16)
        .with_reserved(16, 16)
        .done();

    bank.define(reg::OUTPUT_DATA, 0)
        .with_tag(0, 16)
        .with_reserved(16, 16)
        .done();

    bank.define(reg::BIT_SET, 0)
        .with_tag(0, 16)
        .with_tag(16, 16)
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
        .with_tag(0, 16)
        .with_reserved(16, 16)
        .done();

}
