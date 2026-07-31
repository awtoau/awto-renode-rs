//! `STM32_GPIOPort`, translated from Renode's C#. Issue #14.
//!
//! The second peripheral, translated to test what the rule-leverage gate
//! predicted: 56% of its rule-able shapes also occur in `STM32_UART`, 90% of its
//! DSL combinator calls were already built.
//!
//! ## What transferred, and what did not
//!
//! The register file transferred almost entirely — same combinators, same
//! shapes. What did not is everything around it: pin state living outside the
//! register file, and the alternate-function routing. That matches the gate's
//! own caveat, and it is the expected split between the declarative half and the
//! behavioural half.
//!
//! ## Declared deviations
//!
//! 1. **Callbacks are dispatch arms, not combinator arguments.** The C# attaches
//!    `valueProviderCallback`/`writeCallback` to fields; those closures capture
//!    peripheral state, which Rust cannot express inside the struct they borrow.
//!    Behaviour lives in `read`/`write` instead. See `renode-regs` module docs.
//!
//! 2. **Alternate-function output routing is not modelled.** The C# maintains
//!    `GPIOAlternateFunction` objects per pin and connects/disconnects them as
//!    modes change. Nothing in the captured traces exercises it, and it needs
//!    the GPIO connection graph, which is not ported. `mode` is tracked
//!    faithfully; only the *routing consequence* is absent. Recorded rather than
//!    silently dropped, because a port that quietly omits behaviour is exactly
//!    what the oracle cannot catch.
//!
//! 3. **Constructor validation is not reproduced.** The C# raises
//!    `ConstructionException` for out-of-range pins and AF numbers. That is
//!    platform-construction-time behaviour and the platform here is compiled in.

use renode_regs::{Bank, FieldMode, ValueId};

pub const NUMBER_OF_PINS: usize = 16;

mod reg {
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
}

/// C# `enum Mode`.
#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub enum Mode {
    Input = 0,
    Output = 1,
    AlternateFunction = 2,
    Analog = 3,
}

impl Mode {
    fn from_bits(v: u64) -> Self {
        match v & 0b11 {
            0 => Mode::Input,
            1 => Mode::Output,
            2 => Mode::AlternateFunction,
            _ => Mode::Analog,
        }
    }
}

#[derive(Default)]
struct Fields {
    mode: ValueId,
    output_speed: ValueId,
    pull_up_pull_down: ValueId,
    input_data: ValueId,
    output_data: ValueId,
    alternate_function_low: ValueId,
    alternate_function_high: ValueId,
}

pub struct Stm32GpioPort {
    bank: Bank,
    f: Fields,
    /// Pin state. C# `BaseGPIOPort.State` — a bool per pin, held outside the
    /// register file because both IDR and ODR project it.
    state: [bool; NUMBER_OF_PINS],
    mode_reset: u32,
    output_speed_reset: u32,
    pull_up_pull_down_reset: u32,
}

impl Stm32GpioPort {
    pub fn new(mode_reset: u32, output_speed_reset: u32, pull_up_pull_down_reset: u32) -> Self {
        let mut bank = Bank::new();
        let mut f = Fields::default();
        create_registers(&mut bank, &mut f);
        let mut me = Self {
            bank,
            f,
            state: [false; NUMBER_OF_PINS],
            mode_reset,
            output_speed_reset,
            pull_up_pull_down_reset,
        };
        me.reset();
        me
    }

    pub fn reset(&mut self) {
        self.bank.reset();
        self.state = [false; NUMBER_OF_PINS];
        // C# Reset() seeds mode/speed/pull from the platform's reset values,
        // two bits per pin, rather than from the register reset value.
        for i in 0..NUMBER_OF_PINS as u16 {
            let sh = 2 * i as u32;
            self.bank
                .set_value(self.f.mode.offset(i), ((self.mode_reset >> sh) & 0b11) as u64);
            self.bank.set_value(
                self.f.output_speed.offset(i),
                ((self.output_speed_reset >> sh) & 0b11) as u64,
            );
            self.bank.set_value(
                self.f.pull_up_pull_down.offset(i),
                ((self.pull_up_pull_down_reset >> sh) & 0b11) as u64,
            );
        }
    }

    pub fn mode(&self, pin: usize) -> Mode {
        Mode::from_bits(self.bank.value(self.f.mode.offset(pin as u16)))
    }

    pub fn pin(&self, pin: usize) -> bool {
        self.state[pin]
    }

    pub fn set_pin(&mut self, pin: usize, value: bool) {
        self.state[pin] = value;
    }

    fn state_bits(&self) -> u64 {
        self.state
            .iter()
            .enumerate()
            .fold(0u64, |acc, (i, &b)| acc | ((b as u64) << i))
    }

    /// C# `WriteState(ushort)`.
    fn write_state(&mut self, value: u16) {
        for i in 0..NUMBER_OF_PINS {
            self.state[i] = value & (1 << i) != 0;
        }
    }

    pub fn read(&mut self, offset: u64) -> u32 {
        match offset {
            // Deviation 1: these are the C#'s valueProviderCallbacks.
            reg::INPUT_DATA | reg::OUTPUT_DATA => self.state_bits() as u32,
            // BSRR is write-only in the C# (FieldMode.Write), so it reads zero.
            reg::BIT_SET => 0,
            _ => self.bank.read(offset).unwrap_or(0) as u32,
        }
    }

    pub fn write(&mut self, offset: u64, value: u32) {
        match offset {
            reg::OUTPUT_DATA => {
                self.write_state(value as u16);
            }
            reg::BIT_SET => {
                // BSRR: low half sets, high half resets. C# applies set first,
                // then reset, and both are skipped when the half is zero.
                let set = (value & 0xFFFF) as u16;
                let reset = ((value >> 16) & 0xFFFF) as u16;
                if set != 0 {
                    self.write_state(self.state_bits() as u16 | set);
                }
                if reset != 0 {
                    self.write_state(self.state_bits() as u16 & !reset);
                }
            }
            reg::INPUT_DATA => {
                // IDR is read-only; the write is dropped.
            }
            _ => {
                self.bank.write(offset, value as u64);
            }
        }
    }
}

/// C# `CreateRegisters()`.
fn create_registers(bank: &mut Bank, f: &mut Fields) {
    bank.define(reg::MODE, 0)
        .with_enum_fields(0, 2, NUMBER_OF_PINS as u32, &mut f.mode, FieldMode::READ_WRITE)
        .done();

    let mut b = bank.define(reg::OUTPUT_TYPE, 0);
    for pin in 0..NUMBER_OF_PINS as u32 {
        b = b.with_tagged_flag(pin); // OT0..OT15
    }
    b.with_reserved(16, 16).done();

    bank.define(reg::OUTPUT_SPEED, 0)
        .with_enum_fields(0, 2, NUMBER_OF_PINS as u32, &mut f.output_speed, FieldMode::READ_WRITE)
        .done();

    bank.define(reg::PULL_UP_PULL_DOWN, 0)
        .with_enum_fields(
            0,
            2,
            NUMBER_OF_PINS as u32,
            &mut f.pull_up_pull_down,
            FieldMode::READ_WRITE,
        )
        .done();

    bank.define(reg::INPUT_DATA, 0)
        .with_value(0, 16, &mut f.input_data, FieldMode::READ)
        .with_reserved(16, 16)
        .done();

    bank.define(reg::OUTPUT_DATA, 0)
        .with_value(0, 16, &mut f.output_data, FieldMode::READ_WRITE)
        .with_reserved(16, 16)
        .done();

    // GPIOx_BS (set) and GPIOx_BR (reset), both write-only.
    bank.define(reg::BIT_SET, 0)
        .with_value(0, 16, &mut ValueId::default(), FieldMode::WRITE)
        .with_value(16, 16, &mut ValueId::default(), FieldMode::WRITE)
        .done();

    let mut b = bank.define(reg::CONFIGURATION_LOCK, 0);
    for pin in 0..NUMBER_OF_PINS as u32 {
        b = b.with_tagged_flag(pin); // LCK0..LCK15
    }
    b.with_tagged_flag(16) // LCKK
        .with_reserved(17, 15)
        .done();

    bank.define(reg::ALTERNATE_FUNCTION_LOW, 0)
        .with_value_fields(0, 4, 8, &mut f.alternate_function_low, FieldMode::READ_WRITE)
        .done();
    bank.define(reg::ALTERNATE_FUNCTION_HIGH, 0)
        .with_value_fields(0, 4, 8, &mut f.alternate_function_high, FieldMode::READ_WRITE)
        .done();
}
