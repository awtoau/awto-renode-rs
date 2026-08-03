//! Register layout for `STM32_SYSCFG`, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! Source: STM32_SYSCFG.CreateRegisters
//!
//! GAPS the converter reports rather than guessing:
//!   - ExternalInterruptConfiguration1: DefineValueField bit 0: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration1: DefineValueField bit 12: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration1: DefineValueField bit 4: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration1: DefineValueField bit 8: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration2: DefineValueField bit 0: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration2: DefineValueField bit 12: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration2: DefineValueField bit 4: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration2: DefineValueField bit 8: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration3: DefineValueField bit 0: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration3: DefineValueField bit 12: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration3: DefineValueField bit 4: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration3: DefineValueField bit 8: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration4: DefineValueField bit 0: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration4: DefineValueField bit 12: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration4: DefineValueField bit 4: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - ExternalInterruptConfiguration4: DefineValueField bit 8: `changeCallback` is bound in the C# and no rule consumes it -- that behaviour is missing
//!   - GetLocalReceiver: withheld, return type `Antmicro.Renode.Core.IGPIOReceiver` has no Rust mapping
//!   - Reset: withheld, cannot emit expr:StaticInvocation:IGPIOExtensions.Unset
//!   - STM32_SYSCFG..ctor `STM32_SYSCFG()`: no statement could be translated, so no initialiser is emitted at all
//!   - STM32_SYSCFG..ctor `STM32_SYSCFG()`: statement 1 withheld -- not an assignment to the type's own storage, but VariableDeclarationGroup; an initialiser can only assign the struct it is building
//!   - STM32_SYSCFG..ctor `STM32_SYSCFG()`: statement 2 withheld -- not an assignment to the type's own storage, but Loop; an initialiser can only assign the struct it is building
//!   - STM32_SYSCFG..ctor `STM32_SYSCFG()`: statement 3 withheld -- assigns `Connections`, which the emitted struct has no storage for
//!   - STM32_SYSCFG..ctor `STM32_SYSCFG()`: statement 4 withheld -- assigns `internalReceiversCache`, which the emitted struct has no storage for
//!   - STM32_SYSCFG..ctor `STM32_SYSCFG()`: statement 5 withheld -- assigns `registers`, which the emitted struct has no storage for
//!   - state field `Connections`: needs trait `IGPIO` (D1 maps the field; the trait is issue #41). IGPIO declares 11 members, the corpus calls 5
//!   - state field `internalReceiversCache`: no Rust mapping for `System.Collections.Generic.Dictionary<int, Antmicro.Renode.Peripherals.Miscellaneous.STM32_SYSCFG.InternalReceiver>`
//!   - static call `IGPIOExtensions.Unset` has no Rust mapping

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets, from the C# `enum Register`.
pub mod reg {
    pub const EXTERNAL_INTERRUPT_CONFIGURATION1: u64 = 0x08;
    pub const EXTERNAL_INTERRUPT_CONFIGURATION2: u64 = 0x0C;
    pub const EXTERNAL_INTERRUPT_CONFIGURATION3: u64 = 0x10;
    pub const EXTERNAL_INTERRUPT_CONFIGURATION4: u64 = 0x14;
}

/// Field handles bound by `out` parameters in the C#.
#[derive(Default)]
pub struct Fields {
    pub exti_mappings: [ValueId; 16],
}

/// The peripheral's own state: every C# instance member that actually
/// stores something. Computed properties are excluded -- they hold
/// nothing, so a field here would invent storage the C# lacks.
#[derive(Default)]
pub struct State {
    /// Register field handles, bound by the C# `out` parameters.
    pub f: Fields,
}

// The peripheral's own methods. C# reaches its state through
// `this`; these receive it as (bank, st) instead, so a callback
// can call them -- a closure cannot borrow what it lives inside.
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
    bank.define(reg::EXTERNAL_INTERRUPT_CONFIGURATION1, 0)
        .with_value(0, 4, &mut f.exti_mappings[0], FieldMode::READ_WRITE)
        .with_value(4, 4, &mut f.exti_mappings[1], FieldMode::READ_WRITE)
        .with_value(8, 4, &mut f.exti_mappings[2], FieldMode::READ_WRITE)
        .with_value(12, 4, &mut f.exti_mappings[3], FieldMode::READ_WRITE)
        .done();

    bank.define(reg::EXTERNAL_INTERRUPT_CONFIGURATION2, 0)
        .with_value(0, 4, &mut f.exti_mappings[4], FieldMode::READ_WRITE)
        .with_value(4, 4, &mut f.exti_mappings[5], FieldMode::READ_WRITE)
        .with_value(8, 4, &mut f.exti_mappings[6], FieldMode::READ_WRITE)
        .with_value(12, 4, &mut f.exti_mappings[7], FieldMode::READ_WRITE)
        .done();

    bank.define(reg::EXTERNAL_INTERRUPT_CONFIGURATION3, 0)
        .with_value(0, 4, &mut f.exti_mappings[8], FieldMode::READ_WRITE)
        .with_value(4, 4, &mut f.exti_mappings[9], FieldMode::READ_WRITE)
        .with_value(8, 4, &mut f.exti_mappings[10], FieldMode::READ_WRITE)
        .with_value(12, 4, &mut f.exti_mappings[11], FieldMode::READ_WRITE)
        .done();

    bank.define(reg::EXTERNAL_INTERRUPT_CONFIGURATION4, 0)
        .with_value(0, 4, &mut f.exti_mappings[12], FieldMode::READ_WRITE)
        .with_value(4, 4, &mut f.exti_mappings[13], FieldMode::READ_WRITE)
        .with_value(8, 4, &mut f.exti_mappings[14], FieldMode::READ_WRITE)
        .with_value(12, 4, &mut f.exti_mappings[15], FieldMode::READ_WRITE)
        .done();

}
