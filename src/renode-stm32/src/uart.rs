//! `STM32_UART`, translated from Renode's C#. Issue #13.
//!
//! Faithful translation, not an improvement. Where the C# is wrong or
//! simplified, this is wrong or simplified in the same way — the oracle
//! certifies equivalence, and an "improved" port makes the trace comparison
//! meaningless. Deviations are recorded here, never applied silently.
//!
//! ## Generated vs hand-written
//!
//! The register LAYOUT lives in `uart_registers.rs`, produced by the converter
//! from the corpus and enforced byte-for-byte by `scripts/check_generated.py`.
//! This file holds only behaviour, which the converter does not yet emit.
//!
//! Three hand edits were deleted when the layout became generated, all of which
//! had survived the trace oracle and mutation testing:
//!   - `.with_reserved(9, 23)` and `(16, 16)` on USART_DR: **not in the C# at
//!     all**, and behaviourally inert, so nothing could catch them
//!   - a dummy `ValueId::default()` where the C# has a computed field with no
//!     storage; the generated version reports the gap instead
//!   - four shortened field names, which made the file unreproducible
//!
//! ## Deviations from the C#, all forced and all recorded
//!
//! 1. **No idle-line timer.** The C# schedules a machine action one UART frame
//!    after each received character to raise IDLE. That needs the time
//!    framework, which is not ported yet, so `WriteChar` sets the flag
//!    immediately. Affects IDLE timing only; recorded rather than hidden, and it
//!    is why `report_idle_line` exists as a seam.
//! 2. **`CharReceived` is a callback slot** rather than a C# `event`. Same
//!    single-subscriber behaviour the platform actually uses.
//!
//! ## Faithfully reproduced quirks
//!
//! - `ORE` always reads 0 — the C# assumes no receive overruns.
//! - `TXE` always reads 1 — the C# assumes the transmit register is always
//!   empty. This is why `Update()` ORs in `transmitDataRegisterEmptyInterrupt`
//!   unconditionally.
//! - `BaudRate` is computed but used for nothing except the idle-line timeout.
//!   Renode models no transmission rate at all.

use crate::uart_registers::{define_registers, reg, Fields, State};
use renode_regs::Bank;

/// C# `STM32_UART(IMachine machine, uint frequency = 8000000)`. This is the
/// SOURCE default, not platform configuration -- the .repl does not override it
/// for any UART on this board, so it is not derived from the platform.
/// It affects only `baud_rate()`, which Renode uses for nothing but the
/// idle-line timeout.
pub const DEFAULT_FREQUENCY: u32 = 8_000_000;

pub struct Stm32Uart {
    bank: Bank<State>,
    /// Peripheral state, GENERATED from the C# instance members. Held here so
    /// the register callbacks can reach it.
    ///
    /// The field handles live INSIDE it, at `st.f`, because that is where the
    /// generated callbacks look for them — `why_handles_in_state` in the rules.
    /// Keeping a second `Fields` beside it left `st.f` default-initialised, so
    /// every handle in it was `u16::MAX`: harmless while no generated callback
    /// was reachable from this file, and an immediate out-of-bounds panic the
    /// moment the register-level write callback on STATUS became one.
    st: State,
    receive_fifo: std::collections::VecDeque<u8>,
    frequency: u32,
    /// Raised IRQ line state, so transitions can be compared against the C#.
    irq: bool,
    /// C# `event Action<byte> CharReceived`.
    pub char_received: Option<Box<dyn FnMut(u8)>>,
}

impl Stm32Uart {
    pub fn new(frequency: u32) -> Self {
        let mut bank: Bank<State> = Bank::new();
        let mut f = Fields::default();
        define_registers(&mut bank, &mut f);
        Self {
            bank,
            st: State { f, ..Default::default() },
            receive_fifo: Default::default(),
            frequency,
            irq: false,
            char_received: None,
        }
    }

    pub fn irq(&self) -> bool {
        self.irq
    }

    /// Status register without the read side effects, for assertions.
    /// `read(STATUS)` has none in the C# either -- only `read(DATA)` does --
    /// but the bank now threads `&mut State` for the generated callbacks, so
    /// this takes `&mut self` despite reading nothing.
    pub fn read_sr(&mut self) -> u32 {
        self.bank.read(reg::STATUS, &mut self.st).unwrap_or(0) as u32 | (1 << 7)
    }

    /// C# `BaudRate` property. Computed from BRR and used for exactly one thing:
    /// the idle-line timeout. There is no transmission-rate model.
    pub fn baud_rate(&self) -> u32 {
        // OversamplingMode.By8 ignores the oldest bit of dividerFraction.
        let over8 = self.bank.value(self.st.f.oversampling_mode) != 0;
        let fraction = if over8 {
            self.bank.value(self.st.f.divider_fraction) & 0b111
        } else {
            self.bank.value(self.st.f.divider_fraction)
        };
        let mantissa = self.bank.value(self.st.f.divider_mantissa);
        let divisor = 8.0 * (2 - over8 as u32) as f64 * (mantissa as f64 + fraction as f64 / 16.0);
        if divisor == 0.0 {
            0
        } else {
            (self.frequency as f64 / divisor) as u32
        }
    }

    /// C# `WriteChar`. Deviation 1: the idle-line timer is not scheduled.
    pub fn write_char(&mut self, value: u8) {
        if !self.bank.flag(self.st.f.usart_enabled) && !self.bank.flag(self.st.f.receiver_enabled) {
            return; // C# logs a warning and drops the character
        }
        self.receive_fifo.push_back(value);
        self.bank.set_flag(self.st.f.read_fifo_not_empty, true);
        self.update();
    }

    /// The seam deviation 1 leaves behind: the time framework will call this.
    pub fn report_idle_line(&mut self) {
        self.bank.set_flag(self.st.f.idle_line_detected, true);
        self.update();
    }

    pub fn reset(&mut self) {
        self.bank.reset();
        self.receive_fifo.clear();
        self.irq = false;
    }

    /// C# `Update()` — IRQ is the OR of the enabled-and-asserted conditions.
    /// TXE is assumed always true, hence the unconditional term.
    fn update(&mut self) {
        let b = &self.bank;
        self.irq = (b.flag(self.st.f.idle_line_detected_interrupt_enabled) && b.flag(self.st.f.idle_line_detected))
            || (b.flag(self.st.f.receiver_not_empty_interrupt_enabled) && b.flag(self.st.f.read_fifo_not_empty))
            || b.flag(self.st.f.transmit_data_register_empty_interrupt_enabled)
            || (b.flag(self.st.f.transmission_complete_interrupt_enabled) && b.flag(self.st.f.transmission_complete));
    }

    pub fn read(&mut self, offset: u64) -> u32 {
        match offset {
            reg::STATUS => {
                // ORE reads 0 and TXE reads 1, neither backed by a field.
                let mut v = self.bank.read(offset, &mut self.st).unwrap_or(0);
                v |= 1 << 7; // TXE
                v as u32
            }
            reg::DATA => {
                // C#: "Cleared by a USART_SR read followed by a USART_DR read."
                // The model assumes SR was already read in the ISR.
                self.bank.set_flag(self.st.f.idle_line_detected, false);
                let value = self.receive_fifo.pop_front().unwrap_or(0);
                let not_empty = !self.receive_fifo.is_empty();
                self.bank.set_flag(self.st.f.read_fifo_not_empty, not_empty);
                self.update();
                value as u32
            }
            _ => self.bank.read(offset, &mut self.st).unwrap_or(0) as u32,
        }
    }

    pub fn write(&mut self, offset: u64, value: u32) {
        match offset {
            reg::DATA => {
                if !self.bank.flag(self.st.f.usart_enabled)
                    && !self.bank.flag(self.st.f.transmitter_enabled)
                {
                    return; // C# logs and drops
                }
                if let Some(cb) = self.char_received.as_mut() {
                    cb(value as u8);
                }
                self.bank.set_flag(self.st.f.transmission_complete, true);
                self.update();
            }
            reg::STATUS | reg::CONTROL1 => {
                self.bank.write(offset, value as u64, &mut self.st);
                // Both registers carry a write callback that ends in Update().
                self.update();
            }
            _ => {
                self.bank.write(offset, value as u64, &mut self.st);
            }
        }
    }
}
