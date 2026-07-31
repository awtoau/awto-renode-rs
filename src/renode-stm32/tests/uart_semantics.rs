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
