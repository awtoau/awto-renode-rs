//! `STM32_UART`, translated from Renode's C#. Issue #13.
//!
//! Faithful translation, not an improvement. Where the C# is wrong or
//! simplified, this is wrong or simplified in the same way — the oracle
//! certifies equivalence, and an "improved" port makes the trace comparison
//! meaningless. Deviations are recorded here, never applied silently.
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

use renode_regs::{Bank, FieldMode, FlagId, ValueId};

/// Register offsets. C# `enum Register : long`.
mod reg {
    pub const STATUS: u64 = 0x00;
    pub const DATA: u64 = 0x04;
    pub const BAUD_RATE: u64 = 0x08;
    pub const CONTROL1: u64 = 0x0C;
    pub const CONTROL2: u64 = 0x10;
    pub const CONTROL3: u64 = 0x14;
    pub const GUARD_TIME_AND_PRESCALER: u64 = 0x18;
}

#[derive(Default)]
struct Fields {
    idle_line_detected: FlagId,
    read_fifo_not_empty: FlagId,
    transmission_complete: FlagId,
    receiver_enabled: FlagId,
    transmitter_enabled: FlagId,
    idle_line_irq_enabled: FlagId,
    rx_not_empty_irq_enabled: FlagId,
    tx_complete_irq_enabled: FlagId,
    tx_empty_irq_enabled: FlagId,
    parity_control_enabled: FlagId,
    usart_enabled: FlagId,
    dma_reception_request: FlagId,
    parity_selection: FlagId,
    oversampling_mode: FlagId,
    stop_bits: ValueId,
    divider_fraction: ValueId,
    divider_mantissa: ValueId,
}

/// C# `STM32_UART(IMachine machine, uint frequency = 8000000)`. This is the
/// SOURCE default, not platform configuration -- the .repl does not override it
/// for any UART on this board, so it is not derived from the platform.
/// It affects only `baud_rate()`, which Renode uses for nothing but the
/// idle-line timeout.
pub const DEFAULT_FREQUENCY: u32 = 8_000_000;

pub struct Stm32Uart {
    bank: Bank<()>,
    f: Fields,
    receive_fifo: std::collections::VecDeque<u8>,
    frequency: u32,
    /// Raised IRQ line state, so transitions can be compared against the C#.
    irq: bool,
    /// C# `event Action<byte> CharReceived`.
    pub char_received: Option<Box<dyn FnMut(u8)>>,
}

impl Stm32Uart {
    pub fn new(frequency: u32) -> Self {
        let mut bank: Bank<()> = Bank::new();
        let mut f = Fields::default();
        define_registers(&mut bank, &mut f);
        Self {
            bank,
            f,
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
    /// but this takes `&self`, which tests want.
    pub fn read_sr(&self) -> u32 {
        self.bank.read(reg::STATUS, &mut ()).unwrap_or(0) as u32 | (1 << 7)
    }

    /// C# `BaudRate` property. Computed from BRR and used for exactly one thing:
    /// the idle-line timeout. There is no transmission-rate model.
    pub fn baud_rate(&self) -> u32 {
        // OversamplingMode.By8 ignores the oldest bit of dividerFraction.
        let over8 = self.bank.flag(self.f.oversampling_mode);
        let fraction = if over8 {
            self.bank.value(self.f.divider_fraction) & 0b111
        } else {
            self.bank.value(self.f.divider_fraction)
        };
        let mantissa = self.bank.value(self.f.divider_mantissa);
        let divisor = 8.0 * (2 - over8 as u32) as f64 * (mantissa as f64 + fraction as f64 / 16.0);
        if divisor == 0.0 {
            0
        } else {
            (self.frequency as f64 / divisor) as u32
        }
    }

    /// C# `WriteChar`. Deviation 1: the idle-line timer is not scheduled.
    pub fn write_char(&mut self, value: u8) {
        if !self.bank.flag(self.f.usart_enabled) && !self.bank.flag(self.f.receiver_enabled) {
            return; // C# logs a warning and drops the character
        }
        self.receive_fifo.push_back(value);
        self.bank.set_flag(self.f.read_fifo_not_empty, true);
        self.update();
    }

    /// The seam deviation 1 leaves behind: the time framework will call this.
    pub fn report_idle_line(&mut self) {
        self.bank.set_flag(self.f.idle_line_detected, true);
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
        self.irq = (b.flag(self.f.idle_line_irq_enabled) && b.flag(self.f.idle_line_detected))
            || (b.flag(self.f.rx_not_empty_irq_enabled) && b.flag(self.f.read_fifo_not_empty))
            || b.flag(self.f.tx_empty_irq_enabled)
            || (b.flag(self.f.tx_complete_irq_enabled) && b.flag(self.f.transmission_complete));
    }

    pub fn read(&mut self, offset: u64) -> u32 {
        match offset {
            reg::STATUS => {
                // ORE reads 0 and TXE reads 1, neither backed by a field.
                let mut v = self.bank.read(offset, &mut ()).unwrap_or(0);
                v |= 1 << 7; // TXE
                v as u32
            }
            reg::DATA => {
                // C#: "Cleared by a USART_SR read followed by a USART_DR read."
                // The model assumes SR was already read in the ISR.
                self.bank.set_flag(self.f.idle_line_detected, false);
                let value = self.receive_fifo.pop_front().unwrap_or(0);
                let not_empty = !self.receive_fifo.is_empty();
                self.bank.set_flag(self.f.read_fifo_not_empty, not_empty);
                self.update();
                value as u32
            }
            _ => self.bank.read(offset, &mut ()).unwrap_or(0) as u32,
        }
    }

    pub fn write(&mut self, offset: u64, value: u32) {
        match offset {
            reg::DATA => {
                if !self.bank.flag(self.f.usart_enabled)
                    && !self.bank.flag(self.f.transmitter_enabled)
                {
                    return; // C# logs and drops
                }
                if let Some(cb) = self.char_received.as_mut() {
                    cb(value as u8);
                }
                self.bank.set_flag(self.f.transmission_complete, true);
                self.update();
            }
            reg::STATUS | reg::CONTROL1 => {
                self.bank.write(offset, value as u64, &mut ());
                // Both registers carry a write callback that ends in Update().
                self.update();
            }
            _ => {
                self.bank.write(offset, value as u64, &mut ());
            }
        }
    }
}

/// C# `DefineRegisters()`. Field-for-field, in source order.
fn define_registers(bank: &mut Bank<()>, f: &mut Fields) {
    bank.define(reg::STATUS, 0xC0)
        .with_tagged_flag(0) // PE
        .with_tagged_flag(1) // FE
        .with_tagged_flag(2) // NF
        .with_tagged_flag(3) // ORE -- always reads false, handled in read()
        .with_flag(4, &mut f.idle_line_detected, FieldMode::READ)
        .with_flag(
            5,
            &mut f.read_fifo_not_empty,
            FieldMode::READ | FieldMode::WRITE_ZERO_TO_CLEAR,
        )
        .with_flag(
            6,
            &mut f.transmission_complete,
            FieldMode::READ | FieldMode::WRITE_ZERO_TO_CLEAR,
        )
        .with_tagged_flag(7) // TXE -- always reads true, handled in read()
        .with_tagged_flag(8) // LBD
        .with_tagged_flag(9) // CTS
        .with_reserved(10, 22)
        .done();

    bank.define(reg::DATA, 0)
        .with_value(0, 9, &mut ValueId::default(), FieldMode::READ_WRITE)
        .with_reserved(9, 23)
        .done();

    bank.define(reg::BAUD_RATE, 0)
        .with_value(0, 4, &mut f.divider_fraction, FieldMode::READ_WRITE)
        .with_value(4, 12, &mut f.divider_mantissa, FieldMode::READ_WRITE)
        .with_reserved(16, 16)
        .done();

    bank.define(reg::CONTROL1, 0)
        .with_tagged_flag(0) // SBK
        .with_tagged_flag(1) // RWU
        .with_flag(2, &mut f.receiver_enabled, FieldMode::READ_WRITE)
        .with_flag(3, &mut f.transmitter_enabled, FieldMode::READ_WRITE)
        .with_flag(4, &mut f.idle_line_irq_enabled, FieldMode::READ_WRITE)
        .with_flag(5, &mut f.rx_not_empty_irq_enabled, FieldMode::READ_WRITE)
        .with_flag(6, &mut f.tx_complete_irq_enabled, FieldMode::READ_WRITE)
        .with_flag(7, &mut f.tx_empty_irq_enabled, FieldMode::READ_WRITE)
        .with_tagged_flag(8) // PEIE
        .with_flag(9, &mut f.parity_selection, FieldMode::READ_WRITE)
        .with_flag(10, &mut f.parity_control_enabled, FieldMode::READ_WRITE)
        .with_tagged_flag(11) // WAKE
        .with_tagged_flag(12) // M
        .with_flag(13, &mut f.usart_enabled, FieldMode::READ_WRITE)
        .with_reserved(14, 1)
        .with_flag(15, &mut f.oversampling_mode, FieldMode::READ_WRITE)
        .with_reserved(16, 16)
        .done();

    bank.define(reg::CONTROL2, 0)
        .with_tag(0, 4) // ADD
        .with_reserved(5, 1)
        .with_tagged_flag(6) // LBDIE
        .with_reserved(7, 1)
        .with_tagged_flag(8) // LBCL
        .with_tagged_flag(9) // CPHA
        .with_tagged_flag(10) // CPOL
        .with_tagged_flag(11) // CLKEN
        .with_value(12, 2, &mut f.stop_bits, FieldMode::READ_WRITE)
        .with_tagged_flag(14) // LINEN
        .with_reserved(15, 17)
        .done();

    bank.define(reg::CONTROL3, 0)
        .with_tagged_flag(0) // EIE
        .with_tagged_flag(1) // IREN
        .with_tagged_flag(2) // IRLP
        .with_tagged_flag(3) // HDSEL
        .with_tagged_flag(4) // NACK
        .with_tagged_flag(5) // SCEN
        .with_flag(6, &mut f.dma_reception_request, FieldMode::READ_WRITE)
        .with_tagged_flag(7) // DMAT
        .with_tagged_flag(8) // RTSE
        .with_tagged_flag(9) // CTSE
        .with_tagged_flag(10) // CTSIE
        .with_reserved(11, 21)
        .done();

    // Present in the C# enum but never defined, so accesses fall through.
    let _ = reg::GUARD_TIME_AND_PRESCALER;
}
