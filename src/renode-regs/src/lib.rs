//! Renode's register DSL, in Rust. Issue #12.
//!
//! This is the single highest-leverage translation in the project: 2,538 lines
//! of C# implementing 20 combinators that the peripheral corpus calls 1,109
//! times. Getting it right makes most of every peripheral translate by rule.
//!
//! # Storage — decision D2
//!
//! Fields live in one contiguous `Vec<Cell<u64>>` per peripheral, and a field
//! handle is a typed index rather than a pointer. The C# maps naturally onto one
//! `Rc<RefCell<_>>` per field, and that was measured (`spike/field-layout`):
//! 1.1–1.7x slower depending on workload, roughly half of it the borrow-flag
//! read-modify-write.
//!
//! **That speed difference is not why this design was chosen.** A field read is
//! 0.34 ns against a ~409 ns per-MMIO-access budget — 0.08%, a rounding error.
//! The reasons are correctness: `Cell` has no borrow flag so re-entrant access
//! cannot panic (peripheral → bus → peripheral is a real path in Renode), and an
//! index-based bank is `Send`, which `Rc` blocks and which N-instance test
//! parallelism needs.
//!
//! # Faithfulness
//!
//! Field semantics — `FieldMode`, callback ordering, reset behaviour — mirror
//! the C# exactly. Where Rust forces a difference it is recorded on the rule,
//! never applied silently.

use std::cell::Cell;
use std::collections::BTreeMap;

/// How a field responds to reads and writes. Mirrors C# `FieldMode`, which is a
/// `[Flags]` enum, so the combinations matter as much as the members.
#[derive(Copy, Clone, PartialEq, Eq, Debug, Default)]
pub struct FieldMode(u16);

impl FieldMode {
    pub const READ: Self = Self(1 << 0);
    pub const WRITE: Self = Self(1 << 1);
    pub const SET: Self = Self(1 << 2);
    pub const TOGGLE: Self = Self(1 << 3);
    /// Writing 1 clears the bit. Common for interrupt-status flags.
    pub const WRITE_ONE_TO_CLEAR: Self = Self(1 << 4);
    /// Writing 0 clears the bit. Used by STM32 `USART_SR` RXNE/TC, which is why
    /// the C# comment there says the flags "cannot just be calculated".
    pub const WRITE_ZERO_TO_CLEAR: Self = Self(1 << 5);

    pub const READ_WRITE: Self = Self(Self::READ.0 | Self::WRITE.0);

    #[inline]
    pub const fn contains(self, other: Self) -> bool {
        self.0 & other.0 == other.0
    }
    #[inline]
    pub const fn is_empty(self) -> bool {
        self.0 == 0
    }
}

impl std::ops::BitOr for FieldMode {
    type Output = Self;
    #[inline]
    fn bitor(self, rhs: Self) -> Self {
        Self(self.0 | rhs.0)
    }
}

/// Typed handle to a boolean field. An index, not a pointer (D2).
#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub struct FlagId(u16);

/// Typed handle to a multi-bit field.
#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub struct ValueId(u16);

impl FlagId {
    #[inline]
    fn idx(self) -> usize {
        self.0 as usize
    }
}
impl ValueId {
    #[inline]
    fn idx(self) -> usize {
        self.0 as usize
    }
}

#[derive(Clone)]
struct FieldDef {
    offset: u32,
    width: u32,
    mode: FieldMode,
    reset: u64,
    slot: u16,
    /// Reserved and tagged fields hold no state and are never read back; they
    /// exist so the register knows which bits are accounted for. Renode warns
    /// about writes to bits no field covers, and reproducing that requires
    /// knowing the difference between "reserved" and "not modelled".
    reserved: bool,
}

/// One register: a bit layout over fields in the owning bank's arena.
pub struct Register {
    fields: Vec<FieldDef>,
    reset: u64,
    /// Bits covered by no field at all. Written values here are dropped, and
    /// Renode logs them — matching that behaviour is part of the trace oracle.
    unhandled_mask: u64,
    width_bits: u32,
}

impl Register {
    fn value(&self, bank: &Bank) -> u64 {
        let mut v = 0u64;
        for f in &self.fields {
            if f.reserved || !f.mode.contains(FieldMode::READ) {
                continue;
            }
            let raw = bank.slots[f.slot as usize].get();
            v |= (raw & mask(f.width)) << f.offset;
        }
        v
    }
}

#[inline]
const fn mask(width: u32) -> u64 {
    if width >= 64 {
        u64::MAX
    } else {
        (1u64 << width) - 1
    }
}

/// A peripheral's register file: one contiguous arena of field slots plus the
/// register layouts addressing into it.
pub struct Bank {
    slots: Vec<Cell<u64>>,
    resets: Vec<u64>,
    registers: BTreeMap<u64, Register>,
}

impl Default for Bank {
    fn default() -> Self {
        Self::new()
    }
}

impl Bank {
    pub fn new() -> Self {
        Self { slots: Vec::new(), resets: Vec::new(), registers: BTreeMap::new() }
    }

    /// Begin defining the register at `offset`. Mirrors C# `Register.X.Define(this)`.
    pub fn define(&mut self, offset: u64, reset: u64) -> RegisterBuilder<'_> {
        RegisterBuilder {
            bank: self,
            offset,
            reset,
            fields: Vec::new(),
            next_bit: 0,
            width_bits: 32,
        }
    }

    #[inline]
    pub fn flag(&self, id: FlagId) -> bool {
        self.slots[id.idx()].get() != 0
    }
    #[inline]
    pub fn set_flag(&self, id: FlagId, v: bool) {
        self.slots[id.idx()].set(v as u64);
    }
    #[inline]
    pub fn value(&self, id: ValueId) -> u64 {
        self.slots[id.idx()].get()
    }
    #[inline]
    pub fn set_value(&self, id: ValueId, v: u64) {
        self.slots[id.idx()].set(v);
    }

    /// Restore every field to its reset value. C# `RegistersCollection.Reset()`.
    pub fn reset(&self) {
        for (slot, r) in self.slots.iter().zip(&self.resets) {
            slot.set(*r);
        }
    }

    pub fn read(&self, offset: u64) -> Option<u64> {
        self.registers.get(&offset).map(|r| r.value(self))
    }

    /// Returns the bits written that no field covers, so a caller can reproduce
    /// Renode's "unhandled write" warning.
    pub fn write(&self, offset: u64, value: u64) -> Option<u64> {
        let reg = self.registers.get(&offset)?;
        for f in &reg.fields {
            if f.reserved {
                continue;
            }
            let incoming = (value >> f.offset) & mask(f.width);
            let slot = &self.slots[f.slot as usize];
            let mode = f.mode;
            if mode.contains(FieldMode::WRITE) {
                slot.set(incoming);
            } else if mode.contains(FieldMode::WRITE_ONE_TO_CLEAR) {
                if incoming != 0 {
                    slot.set(0);
                }
            } else if mode.contains(FieldMode::WRITE_ZERO_TO_CLEAR) {
                // Deliberately NOT `if incoming == 0 { clear }` for multi-bit
                // fields: the C# clears when the written bit is zero, per bit.
                if incoming & mask(f.width) != mask(f.width) {
                    slot.set(incoming & slot.get());
                }
            } else if mode.contains(FieldMode::SET) {
                if incoming != 0 {
                    slot.set(1);
                }
            } else if mode.contains(FieldMode::TOGGLE) {
                if incoming != 0 {
                    slot.set((slot.get() == 0) as u64);
                }
            }
        }
        Some(value & reg.unhandled_mask)
    }

    pub fn has_register(&self, offset: u64) -> bool {
        self.registers.contains_key(&offset)
    }
    pub fn register_offsets(&self) -> impl Iterator<Item = u64> + '_ {
        self.registers.keys().copied()
    }
}

/// Fluent register definition. Mirrors the C# combinator chain; each `with_*`
/// consumes and returns `self`, since Rust has no `out` parameters — the field
/// handle is returned through the `&mut` binding instead.
pub struct RegisterBuilder<'a> {
    bank: &'a mut Bank,
    offset: u64,
    reset: u64,
    fields: Vec<FieldDef>,
    next_bit: u32,
    width_bits: u32,
}

impl<'a> RegisterBuilder<'a> {
    fn alloc(&mut self, reset: u64) -> u16 {
        let slot = self.bank.slots.len() as u16;
        self.bank.slots.push(Cell::new(reset));
        self.bank.resets.push(reset);
        slot
    }

    fn push(&mut self, offset: u32, width: u32, mode: FieldMode, reserved: bool) -> u16 {
        let reset = (self.reset >> offset) & mask(width);
        let slot = self.alloc(reset);
        self.fields.push(FieldDef { offset, width, mode, reset, slot, reserved });
        self.next_bit = self.next_bit.max(offset + width);
        slot
    }

    /// `WithFlag(pos, out field, mode, name)`.
    pub fn with_flag(mut self, pos: u32, out: &mut FlagId, mode: FieldMode) -> Self {
        *out = FlagId(self.push(pos, 1, mode, false));
        self
    }

    /// `WithValueField(pos, width, out field, mode, name)`.
    pub fn with_value(mut self, pos: u32, width: u32, out: &mut ValueId, mode: FieldMode) -> Self {
        *out = ValueId(self.push(pos, width, mode, false));
        self
    }

    /// `WithTaggedFlag(name, pos)` — modelled but not backed by behaviour.
    pub fn with_tagged_flag(mut self, pos: u32) -> Self {
        self.push(pos, 1, FieldMode::READ_WRITE, true);
        self
    }

    /// `WithTag(name, pos, width)`.
    pub fn with_tag(mut self, pos: u32, width: u32) -> Self {
        self.push(pos, width, FieldMode::READ_WRITE, true);
        self
    }

    /// `WithReservedBits(pos, width)`.
    pub fn with_reserved(mut self, pos: u32, width: u32) -> Self {
        self.push(pos, width, FieldMode::default(), true);
        self
    }

    /// Finish the register and install it in the bank.
    pub fn done(self) {
        let mut covered = 0u64;
        for f in &self.fields {
            covered |= mask(f.width) << f.offset;
        }
        let full = mask(self.width_bits);
        let reg = Register {
            fields: self.fields,
            reset: self.reset,
            unhandled_mask: full & !covered,
            width_bits: self.width_bits,
        };
        self.bank.registers.insert(self.offset, reg);
    }
}

impl Default for FlagId {
    fn default() -> Self {
        Self(u16::MAX)
    }
}
impl Default for ValueId {
    fn default() -> Self {
        Self(u16::MAX)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flag_round_trips_through_the_register() {
        let mut bank = Bank::new();
        let (mut a, mut b) = (FlagId::default(), FlagId::default());
        bank.define(0x00, 0)
            .with_flag(2, &mut a, FieldMode::READ_WRITE)
            .with_flag(5, &mut b, FieldMode::READ_WRITE)
            .done();

        bank.write(0x00, 1 << 5);
        assert!(!bank.flag(a));
        assert!(bank.flag(b));
        assert_eq!(bank.read(0x00), Some(1 << 5));
    }

    #[test]
    fn reset_value_is_applied_per_field() {
        // STM32 USART_SR resets to 0xC0: TC and TXE set.
        let mut bank = Bank::new();
        let (mut tc, mut txe) = (FlagId::default(), FlagId::default());
        bank.define(0x00, 0xC0)
            .with_flag(6, &mut tc, FieldMode::READ)
            .with_flag(7, &mut txe, FieldMode::READ)
            .done();
        assert!(bank.flag(tc));
        assert!(bank.flag(txe));
        assert_eq!(bank.read(0x00), Some(0xC0));
    }

    #[test]
    fn write_one_to_clear_only_clears_on_one() {
        let mut bank = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0)
            .with_flag(0, &mut f, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
            .done();
        bank.set_flag(f, true);
        bank.write(0, 0);
        assert!(bank.flag(f), "writing 0 must not clear a W1C flag");
        bank.write(0, 1);
        assert!(!bank.flag(f));
    }

    #[test]
    fn reserved_bits_read_as_zero_and_absorb_writes() {
        let mut bank = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0)
            .with_flag(0, &mut f, FieldMode::READ_WRITE)
            .with_reserved(1, 31)
            .done();
        // Reserved bits are covered, so nothing is reported unhandled.
        assert_eq!(bank.write(0, 0xFFFF_FFFF), Some(0));
        assert_eq!(bank.read(0), Some(1));
    }

    #[test]
    fn writes_to_uncovered_bits_are_reported() {
        let mut bank = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0).with_flag(0, &mut f, FieldMode::READ_WRITE).done();
        // Bits 1..31 are covered by no field: Renode warns about these, so the
        // mask is returned rather than silently dropped.
        assert_eq!(bank.write(0, 0b110), Some(0b110));
    }

    #[test]
    fn reset_restores_every_field() {
        let mut bank = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0x1).with_flag(0, &mut f, FieldMode::READ_WRITE).done();
        bank.set_flag(f, false);
        bank.reset();
        assert!(bank.flag(f));
    }
}
