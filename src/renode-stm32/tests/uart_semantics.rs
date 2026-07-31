//! Semantics the trace does not reach, taken from the C# rather than from
//! observed behaviour. Each of these exists because a mutation survived the
//! trace replay.
//!
//! Split out of the trace test so `--test *_trace` measures what the
//! CAPTURED TRACE can see, with nothing else propping it up. Keeping these
//! in the same file made 'trace-only' mutation scores identical to
//! 'trace + units', which is exactly the measurement error this avoids.

use renode_stm32::uart::Stm32Uart;

const SR: u64 = 0x00;
const DR: u64 = 0x04;
const CR1: u64 = 0x0C;
const UE_RE: u32 = (1 << 13) | (1 << 2); // usart + receiver enabled

/// RXNE is WRITE_ZERO_TO_CLEAR in the C#, not W1C. Writing ones must NOT
/// clear it. A W1C mutant survives the captured trace.
#[test]
fn rxne_is_write_zero_to_clear() {
    let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
    u.write(CR1, UE_RE);
    u.write_char(b'x');
    assert_ne!(u.read(SR) & (1 << 5), 0, "RXNE should set on receive");
    u.write(SR, 0xFFFF_FFFF);
    assert_ne!(u.read(SR) & (1 << 5), 0, "writing ones must not clear a W0C flag");
}

/// C#: reading DR dequeues, and clears RXNE once the FIFO drains.
#[test]
fn reading_data_drains_the_fifo() {
    let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
    u.write(CR1, UE_RE);
    u.write_char(b'a');
    u.write_char(b'b');
    assert_eq!(u.read(DR), b'a' as u32);
    assert_ne!(u.read(SR) & (1 << 5), 0, "RXNE still set with one byte left");
    assert_eq!(u.read(DR), b'b' as u32);
    assert_eq!(u.read(SR) & (1 << 5), 0, "RXNE clears when the FIFO empties");
}

/// C#: a character is dropped when neither UE nor RE is set.
#[test]
fn receive_is_dropped_when_disabled() {
    let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
    u.write_char(b'x');
    assert_eq!(u.read(SR) & (1 << 5), 0, "disabled UART must drop the character");
}

/// C#: TXE is assumed always empty, so TXEIE alone raises the IRQ.
#[test]
fn txe_interrupt_is_unconditional() {
    let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
    assert!(!u.irq());
    u.write(CR1, UE_RE | (1 << 7)); // TXEIE
    assert!(u.irq(), "TXEIE alone must raise IRQ, since TXE is assumed set");
}

/// C# computes BaudRate from BRR; OversamplingMode.By8 drops the oldest
/// fraction bit. Used only for the idle-line timeout.
#[test]
fn baud_rate_follows_the_brr_formula() {
    let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
    u.write(0x08, (0x1A << 4) | 0x1); // mantissa 26, fraction 1
    // 8e6 / (8 * 2 * (26 + 1/16)) == 19184. (Written as 19230 first time:
    // the test was wrong, not the port.)
    assert_eq!(u.baud_rate(), 19184);
}

/// The IRQ aggregation in C# `Update()`. Each term must be tested
/// INDEPENDENTLY: mutation testing showed that `&&`->`||` survived on every
/// term, because no test isolated one condition from the others.
mod irq_aggregation {
    use renode_stm32::uart::{Stm32Uart, DEFAULT_FREQUENCY};

    const SR: u64 = 0x00;
    const DR: u64 = 0x04;
    const CR1: u64 = 0x0C;
    const UE: u32 = 1 << 13;
    const RE: u32 = 1 << 2;
    const TE: u32 = 1 << 3;
    const IDLEIE: u32 = 1 << 4;
    const RXNEIE: u32 = 1 << 5;
    const TCIE: u32 = 1 << 6;
    const TXEIE: u32 = 1 << 7;

    fn uart() -> Stm32Uart {
        Stm32Uart::new(DEFAULT_FREQUENCY)
    }

    #[test]
    fn rxne_interrupt_needs_both_enable_and_flag() {
        let mut u = uart();
        u.write(CR1, UE | RE | RXNEIE);
        assert!(!u.irq(), "enable alone must not raise: RXNE is clear");
        u.write_char(b'x');
        assert!(u.irq(), "enable + flag raises");

        let mut v = uart();
        v.write(CR1, UE | RE); // flag set, interrupt disabled
        v.write_char(b'x');
        assert!(!v.irq(), "flag alone must not raise: RXNEIE is clear");
    }

    #[test]
    fn tc_is_set_at_reset() {
        // USART_SR resets to 0xC0, so TC (bit 6) and TXE (bit 7) start SET --
        // correct silicon behaviour, since no transmission is ongoing. Written
        // as its own test because it invalidated a first attempt at the TC
        // interrupt test below.
        let u = uart();
        assert_ne!(u.read_sr() & (1 << 6), 0, "TC is set out of reset");
    }

    #[test]
    fn tc_interrupt_needs_both_enable_and_flag() {
        let mut u = uart();
        u.write(SR, 0); // W0C: clear the reset-set TC first
        u.write(CR1, UE | TE | TCIE);
        assert!(!u.irq(), "TCIE with TC clear must not raise");
        u.write(DR, b'x' as u32);
        assert!(u.irq(), "transmitting sets TC, which raises with TCIE");

        let mut v = uart();
        v.write(SR, 0);
        v.write(CR1, UE | TE); // transmit with TCIE clear
        v.write(DR, b'x' as u32);
        assert!(!v.irq(), "TC flag alone must not raise");
    }

    #[test]
    fn idle_line_interrupt_needs_both_enable_and_flag() {
        let mut u = uart();
        u.write(CR1, UE | RE | IDLEIE);
        assert!(!u.irq(), "IDLEIE alone must not raise");
        u.report_idle_line();
        assert!(u.irq(), "idle line detected raises with IDLEIE");

        let mut v = uart();
        v.write(CR1, UE | RE);
        v.report_idle_line();
        assert!(!v.irq(), "idle flag alone must not raise");
    }

    #[test]
    fn reset_clears_the_irq_line() {
        let mut u = uart();
        u.write(CR1, UE | RE | TXEIE);
        assert!(u.irq());
        u.reset();
        assert!(!u.irq(), "reset must drop the IRQ line");
    }

    #[test]
    fn tc_is_write_zero_to_clear() {
        // Distinct from RXNE's W0C: mutation showed nothing covered this one.
        let mut u = uart();
        u.write(CR1, UE | TE);
        u.write(SR, 0);
        u.write(DR, b'x' as u32);
        assert_ne!(u.read(SR) & (1 << 6), 0, "TC sets on transmit");
        u.write(SR, 0xFFFF_FFFF);
        assert_ne!(u.read(SR) & (1 << 6), 0, "writing ones must not clear TC");
        u.write(SR, 0);
        assert_eq!(u.read(SR) & (1 << 6), 0, "writing zero clears TC");
    }

    #[test]
    fn control1_fields_are_writable_and_read_back() {
        // rw->read mutants survived on several CR1 flags because nothing read
        // the register back after writing it.
        let mut u = uart();
        let written = UE | RE | TE | RXNEIE | TCIE | IDLEIE | (1 << 9) | (1 << 10);
        u.write(CR1, written);
        assert_eq!(u.read(CR1), written, "CR1 must read back what was written");
    }
}
