//! Semantics the traces cannot see. Every test here exists because a mutation
//! SURVIVED the trace replay:
//!
//!   BSRR reset-half ignored  -> survived all four traces
//!   IDR/ODR always read 0    -> survived all four traces
//!   mode reset dropped       -> caught only on ports A and B
//!
//! A peripheral returning zero for every pin read passes every captured GPIO
//! trace. Four green ticks, no information. These are derived from the C#
//! source, not from observed behaviour.
//!
//! Split out of the trace test so `--test *_trace` measures what the
//! CAPTURED TRACE can see, with nothing else propping it up. Keeping these
//! in the same file made 'trace-only' mutation scores identical to
//! 'trace + units', which is exactly the measurement error this avoids.

use renode_stm32::gpio_port::{Mode, Stm32GpioPort, NUMBER_OF_PINS};

const ODR: u64 = 0x14;
const IDR: u64 = 0x10;
const BSRR: u64 = 0x18;
const MODER: u64 = 0x00;

#[test]
fn odr_write_sets_pin_state_and_idr_reflects_it() {
    let mut g = Stm32GpioPort::new(0, 0, 0);
    g.write(ODR, 0b1010);
    assert_eq!(g.read(IDR), 0b1010, "IDR must project pin state");
    assert_eq!(g.read(ODR), 0b1010);
    assert!(g.pin(1) && g.pin(3) && !g.pin(0));
}

#[test]
fn bsrr_low_half_sets_high_half_resets() {
    let mut g = Stm32GpioPort::new(0, 0, 0);
    g.write(BSRR, 0xFF); // set pins 0..7
    assert_eq!(g.read(IDR), 0xFF);
    g.write(BSRR, 0x0F << 16); // reset pins 0..3
    assert_eq!(g.read(IDR), 0xF0, "high half must clear the named pins");
}

#[test]
fn bsrr_reset_half_is_applied_after_the_set_half() {
    // C# applies set then reset, so a pin named in both ends up cleared.
    let mut g = Stm32GpioPort::new(0, 0, 0);
    g.write(BSRR, 0b1 | (0b1 << 16));
    assert_eq!(g.read(IDR), 0, "reset wins when a pin is in both halves");
}

#[test]
fn bsrr_is_write_only() {
    let mut g = Stm32GpioPort::new(0, 0, 0);
    g.write(BSRR, 0xFF);
    assert_eq!(g.read(BSRR), 0, "BSRR is FieldMode.Write in the C#");
}

#[test]
fn idr_is_read_only() {
    let mut g = Stm32GpioPort::new(0, 0, 0);
    g.write(IDR, 0xFFFF);
    assert_eq!(g.read(IDR), 0, "writes to IDR must be dropped");
}

#[test]
fn mode_reset_value_is_applied_two_bits_per_pin() {
    let c = renode_stm32::platform::gpio_port("gpioPortA").unwrap();
    let g = Stm32GpioPort::new(c.mode_reset, 0, 0);
    assert_eq!(g.mode(13), Mode::AlternateFunction);
    assert_eq!(g.mode(14), Mode::AlternateFunction);
    assert_eq!(g.mode(15), Mode::AlternateFunction);
    assert_eq!(g.mode(0), Mode::Input);
}

#[test]
fn moder_write_changes_pin_mode() {
    let mut g = Stm32GpioPort::new(0, 0, 0);
    g.write(MODER, 0b01 << (2 * 5)); // pin 5 = Output
    assert_eq!(g.mode(5), Mode::Output);
    assert_eq!(g.mode(4), Mode::Input);
    assert_eq!(g.read(MODER), 0b01 << 10);
}

#[test]
fn every_pin_is_addressable() {
    let mut g = Stm32GpioPort::new(0, 0, 0);
    for p in 0..NUMBER_OF_PINS {
        g.set_pin(p, true);
        assert!(g.pin(p));
    }
    assert_eq!(g.read(IDR), 0xFFFF);
}
