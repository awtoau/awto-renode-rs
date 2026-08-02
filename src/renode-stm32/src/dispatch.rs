//! Virtual dispatch as traits, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! DEVIATION -- the trait is derived from a base CLASS, not from the
//! interface dispatch actually goes through. The corpus does not hold those
//! interfaces: their members are unknown, so a trait declared from one would
//! have members chosen by hand rather than derived. A base class with virtual
//! members is a genuine dispatch contract and is what the corpus can supply --
//! but it is a DIFFERENT type with a different name, so a C# test of the form
//! `x is ISomething` is not served by this trait. If the ingest is never closed
//! over declared interfaces this stays a permanent approximation, so it is
//! written here, in the output, where it cannot be mistaken for a translation.
//!
//! WITHHELD, and each of these shrinks the contract for EVERY
//! implementor at once -- a trait method must be supplied by all:
//!   - BaseGPIOPort.on_gpio: not in the trait -- 1 of 1 implementor(s) cannot supply it (STM32_GPIOPort); their own override is not emitted, and forwarding to the base body instead would dispatch to the wrong method
//!   - BaseGPIOPort.reset: not in the trait -- 1 of 1 implementor(s) cannot supply it (STM32_GPIOPort); their own override is not emitted, and forwarding to the base body instead would dispatch to the wrong method
//!   - BaseGPIOPort: the whole trait is withheld -- no member survives, so it would be a name with no contract
//!   - BasicDoubleWordPeripheral.offset_to_string: not in the trait -- 4 of 4 implementor(s) cannot supply it (STM32DMA, STM32F4_EXTI, STM32_ADC, STM32_UART); no implementor emits it
//!   - BasicDoubleWordPeripheral.reset: not in the trait -- 3 of 4 implementor(s) cannot supply it (STM32DMA, STM32F4_EXTI, STM32_ADC); their own override is not emitted, and forwarding to the base body instead would dispatch to the wrong method

use renode_regs::Bank;
use crate::adc_registers;
use crate::dma_registers;
use crate::exti_registers;
use crate::uart_registers;

/// Dispatch contract of C# `BasicDoubleWordPeripheral`, member for member of
/// what all 4 in-corpus implementor(s) can supply.
pub trait BasicDoubleWordPeripheral {
    fn read_double_word(&mut self, offset: i64) -> u32;
    fn write_double_word(&mut self, offset: i64, value: u32) -> ();
}

/// C# `STM32DMA`, as something a trait can be implemented on: the
/// translated bodies are free functions, so the receiver is the
/// state they take, held together.
pub struct DmaRegisters {
    pub bank: Bank<dma_registers::State>,
    pub st: dma_registers::State,
}

impl DmaRegisters {
    pub fn new() -> Self {
        let mut bank: Bank<dma_registers::State> = Bank::new();
        let mut st = dma_registers::State::default();
        dma_registers::define_registers(&mut bank, &mut st.f);
        Self { bank, st }
    }
}

impl BasicDoubleWordPeripheral for DmaRegisters {
    fn read_double_word(&mut self, offset: i64) -> u32 {
        dma_registers::read_double_word(&self.bank, &mut self.st, offset)
    }
    fn write_double_word(&mut self, offset: i64, value: u32) -> () {
        dma_registers::write_double_word(&self.bank, &mut self.st, offset, value)
    }
}

/// C# `STM32F4_EXTI`, as something a trait can be implemented on: the
/// translated bodies are free functions, so the receiver is the
/// state they take, held together.
pub struct ExtiRegisters {
    pub bank: Bank<exti_registers::State>,
    pub st: exti_registers::State,
}

impl ExtiRegisters {
    pub fn new() -> Self {
        let mut bank: Bank<exti_registers::State> = Bank::new();
        let mut st = exti_registers::State::default();
        exti_registers::define_registers(&mut bank, &mut st.f);
        Self { bank, st }
    }
}

impl BasicDoubleWordPeripheral for ExtiRegisters {
    fn read_double_word(&mut self, offset: i64) -> u32 {
        exti_registers::read_double_word(&self.bank, &mut self.st, offset)
    }
    fn write_double_word(&mut self, offset: i64, value: u32) -> () {
        exti_registers::write_double_word(&self.bank, &mut self.st, offset, value)
    }
}

/// C# `STM32_ADC`, as something a trait can be implemented on: the
/// translated bodies are free functions, so the receiver is the
/// state they take, held together.
pub struct AdcRegisters {
    pub bank: Bank<adc_registers::State>,
    pub st: adc_registers::State,
}

impl AdcRegisters {
    pub fn new() -> Self {
        let mut bank: Bank<adc_registers::State> = Bank::new();
        let mut st = adc_registers::State::default();
        adc_registers::define_registers(&mut bank, &mut st.f);
        Self { bank, st }
    }
}

impl BasicDoubleWordPeripheral for AdcRegisters {
    fn read_double_word(&mut self, offset: i64) -> u32 {
        adc_registers::read_double_word(&self.bank, &mut self.st, offset)
    }
    fn write_double_word(&mut self, offset: i64, value: u32) -> () {
        adc_registers::write_double_word(&self.bank, &mut self.st, offset, value)
    }
}

/// C# `STM32_UART`, as something a trait can be implemented on: the
/// translated bodies are free functions, so the receiver is the
/// state they take, held together.
pub struct UartRegisters {
    pub bank: Bank<uart_registers::State>,
    pub st: uart_registers::State,
}

impl UartRegisters {
    pub fn new() -> Self {
        let mut bank: Bank<uart_registers::State> = Bank::new();
        let mut st = uart_registers::State::default();
        uart_registers::define_registers(&mut bank, &mut st.f);
        Self { bank, st }
    }
}

impl BasicDoubleWordPeripheral for UartRegisters {
    fn read_double_word(&mut self, offset: i64) -> u32 {
        uart_registers::read_double_word(&self.bank, &mut self.st, offset)
    }
    fn write_double_word(&mut self, offset: i64, value: u32) -> () {
        uart_registers::write_double_word(&self.bank, &mut self.st, offset, value)
    }
}
