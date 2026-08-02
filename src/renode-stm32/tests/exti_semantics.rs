//! Semantics of the GENERATED `STM32F4_EXTI` register map that its trace
//! cannot see.
//!
//! The exti trace is 25 accesses with ZERO writes, so it scores 100% against a
//! peripheral that ignores every write ever made to it. It did: EMR was emitted
//! as `.with_tag(0, 32)`, which `Bank::write` skips because tags are reserved,
//! so the register was write-ignored and read-as-zero. The C# is
//!
//!     // Blank implementation to preserve backwards compatibility ...
//!     Registers.EventMask.Define(this)
//!         .WithValueField(0, 32, name: "EMR");
//!
//! -- a deliberate read-write scratch register. `WithValueField` with no `out`
//! calls `DefineValueField` exactly as the bound overload does; the only thing
//! the missing `out` costs is a handle. `name:` is documented in the C# as an
//! ignored parameter, "treat it as a comment".
//!
//! This file exists because the oracle structurally cannot catch that class of
//! bug: an over-match that produces behaviourally inert code is invisible to a
//! trace with no writes. Same reason as gpio_semantics.rs.

use renode_regs::Bank;
use renode_stm32::exti_registers as m;

fn exti() -> (Bank<m::State>, m::State) {
    let mut bank: Bank<m::State> = Bank::new();
    let mut fields = m::Fields::default();
    m::define_registers(&mut bank, &mut fields);
    let mut state = m::State::default();
    state.f = fields;
    (bank, state)
}

#[test]
fn event_mask_is_a_read_write_scratch_register() {
    let (bank, mut st) = exti();
    bank.write(m::reg::EVENT_MASK, 0xDEAD_BEEF, &mut st);
    assert_eq!(
        bank.read(m::reg::EVENT_MASK, &mut st),
        Some(0xDEAD_BEEF),
        "EMR is an anonymous WithValueField: stored, not tagged"
    );
}

#[test]
fn event_mask_returns_to_zero_on_reset() {
    // The C# register has no reset value, so the field resets to 0 -- which is
    // also what the broken tag form returned, and is why a read-only trace
    // could not tell the two apart.
    let (bank, mut st) = exti();
    bank.write(m::reg::EVENT_MASK, 0xFFFF_FFFF, &mut st);
    bank.reset();
    assert_eq!(bank.read(m::reg::EVENT_MASK, &mut st), Some(0));
}

#[test]
fn event_mask_covers_all_32_bits() {
    // `write` returns the bits no field covered. A 32-bit field covers them
    // all, so nothing is reported unhandled -- the tag form covered them too,
    // which is the other reason this was invisible.
    let (bank, mut st) = exti();
    assert_eq!(bank.write(m::reg::EVENT_MASK, 0xFFFF_FFFF, &mut st), Some(0));
}

#[test]
fn interrupt_mask_still_round_trips() {
    // The bound sibling, unchanged by the fix: if field indices had shifted,
    // this is where it would show.
    let (bank, mut st) = exti();
    bank.write(m::reg::INTERRUPT_MASK, 0x0000_FFFF, &mut st);
    assert_eq!(bank.read(m::reg::INTERRUPT_MASK, &mut st), Some(0x0000_FFFF));
    assert_eq!(bank.value(st.f.interrupt_mask), 0x0000_FFFF);
    assert_eq!(
        bank.read(m::reg::EVENT_MASK, &mut st),
        Some(0),
        "writing IMR must not touch EMR"
    );
}
