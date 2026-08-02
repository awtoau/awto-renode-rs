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
//! # Callbacks
//!
//! The C# attaches `valueProviderCallback` / `writeCallback` closures to fields.
//! Those closures capture `this`, and a closure capturing `self` cannot be
//! stored inside `self` — reaching it needs `&self.bank` while calling it needs
//! `&mut self`.
//!
//! The closures capture `this` only because C# gives them no other way to reach
//! the peripheral. **Passing it as a parameter removes the cycle entirely**, so
//! callbacks live here in the DSL exactly as they do in the C#:
//!
//! - the bank needs only `&self`, because `Cell` provides interior mutability;
//! - peripheral state arrives as `&mut S`, a *disjoint* field borrow;
//! - the field index arrives as a parameter, covering the C# plural
//!   combinators' captured loop variable (`(idx, _) => mode[idx]`).
//!
//! An earlier version of this file claimed the callbacks could not be expressed
//! and moved them into the peripheral's `read`/`write` dispatch. That was wrong,
//! and it mattered: it would have made every callback-bearing field a hand-written
//! dispatch arm rather than a rule, which is most of the corpus.
//!
//! # Faithfulness
//!
//! Field semantics — `FieldMode`, callback ordering, reset behaviour — mirror
//! the C# exactly. Where Rust forces a difference it is recorded on the rule,
//! never applied silently.

use std::cell::Cell;
use std::collections::BTreeMap;

/// C# `valueProviderCallback`. Receives the bank (for sibling fields), the
/// peripheral's state, the field index within a plural group, and the field's
/// stored value. Returns the value to report.
pub type ValueProvider<S> = fn(&Bank<S>, &mut S, usize, u64) -> u64;

/// C# `writeCallback`, receiving the old and new values.
pub type WriteCallback<S> = fn(&Bank<S>, &mut S, usize, u64, u64);

/// C# `WithWriteCallback` — a callback on the REGISTER rather than on a field.
///
/// A different thing from `WriteCallback` despite C# giving both parameters the
/// same name: this one has no field to belong to, so it takes no field index,
/// and it fires once per write to the register rather than once per field.
/// `CallWriteHandlers` runs it after every field's own handler, unconditionally
/// — not only when something changed, which is what `changeCallback` is for.
pub type RegisterWriteCallback<S> = fn(&Bank<S>, &mut S, u64, u64);

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
    /// Reading clears the field. Readable: see [`FieldMode::is_readable`].
    pub const READ_TO_CLEAR: Self = Self(1 << 6);
    pub const WRITE_ZERO_TO_SET: Self = Self(1 << 7);
    pub const WRITE_ZERO_TO_TOGGLE: Self = Self(1 << 8);
    // 1 << 9 and 1 << 10 are unassigned in the C# enum. Left as holes rather
    // than renumbered: the values are what the corpus records, and a renumber
    // would silently change what every emitted mode means.
    /// Reading sets the field.
    pub const READ_TO_SET: Self = Self(1 << 11);
    /// Any write clears the field, whatever was written.
    pub const WRITE_TO_CLEAR: Self = Self(1 << 12);
    /// Any write sets the field, whatever was written.
    pub const WRITE_TO_SET: Self = Self(1 << 13);

    pub const READ_WRITE: Self = Self(Self::READ.0 | Self::WRITE.0);

    /// C# `FieldModeHelper.IsReadable`. THREE modes make a field readable, not
    /// one: a `ReadToClear`-only field answers reads and then clears itself.
    /// Testing `contains(READ)` instead made every such field read back zero.
    #[inline]
    pub const fn is_readable(self) -> bool {
        self.0 & (Self::READ.0 | Self::READ_TO_CLEAR.0 | Self::READ_TO_SET.0) != 0
    }

    /// C# `FieldModeHelper.WriteBits` — the mode with the read bits removed.
    /// The C# write path switches on this, relying on `IsValid`'s guarantee
    /// that at most one write bit is set.
    ///
    /// `IsWritable` and `ReadBits` are the other two helpers in that C# file
    /// and are deliberately absent: nothing here would call them, and an
    /// unused mirror of an upstream API is the dead configuration this file's
    /// own construction asserts exist to reject.
    #[inline]
    pub const fn write_bits(self) -> Self {
        Self(self.0 & !(Self::READ.0 | Self::READ_TO_CLEAR.0 | Self::READ_TO_SET.0))
    }

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
    /// Handle to the `n`th field of a `with_value_fields` group. Consecutive
    /// allocation is guaranteed, which is what makes indices better than
    /// pointers for the plural combinators.
    #[inline]
    pub const fn offset(self, n: u16) -> Self {
        Self(self.0 + n)
    }
}

struct FieldDef<S> {
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
    /// Index within a plural-combinator group; 0 for singular fields.
    group_index: usize,
    provider: Option<ValueProvider<S>>,
    on_write: Option<WriteCallback<S>>,
}

/// One register: a bit layout over fields in the owning bank's arena.
pub struct Register<S> {
    fields: Vec<FieldDef<S>>,
    reset: u64,
    /// Bits covered by no field at all. Written values here are dropped, and
    /// Renode logs them — matching that behaviour is part of the trace oracle.
    unhandled_mask: u64,
    width_bits: u32,
    /// C# `WithWriteCallback`. Register-level, fired once per write.
    on_write: Option<RegisterWriteCallback<S>>,
}

impl<S> Register<S> {
    /// The register's backing value, WITHOUT consulting any value provider.
    ///
    /// C# keeps one `UnderlyingValue` per register and hands it to the
    /// register-level handlers as `baseValue`. That word is seeded with the
    /// reset value and only a REGISTER FIELD ever overwrites part of it, so
    /// this reconstructs it the same way: start from the reset value, then let
    /// each non-tag field's stored slot replace its own slice.
    ///
    /// Tags and bits belonging to no field therefore carry their reset value
    /// here, as they do in C#. They previously read back as zero, which was
    /// recorded as a deviation on REGISTER_WRITE_CALLBACK; reconstructing from
    /// the reset value costs one extra word and removes it.
    fn raw_value(&self, bank: &Bank<S>) -> u64 {
        let mut v = self.reset;
        for f in &self.fields {
            if f.reserved {
                continue;
            }
            let m = mask(f.width) << f.offset;
            v = (v & !m) | ((bank.slots[f.slot as usize].get() << f.offset) & m);
        }
        v
    }

    /// C# `PeripheralRegister.ReadInner`.
    ///
    /// The shape is the C#'s and not an optimisation of it, because the
    /// difference between the two IS the bug this method had. C# reads
    ///
    /// ```text
    /// var valueToRead = UnderlyingValue;
    /// foreach(var f in registerFields)
    ///     if(!f.FieldMode.IsReadable())
    ///         BitHelper.ClearBits(ref valueToRead, f.Position, f.Width);
    /// ```
    ///
    /// -- it starts from the whole backing word and SUBTRACTS what may not be
    /// read. Composing the answer out of the readable fields instead looks
    /// equivalent and is not: it silently drops every bit that belongs to a
    /// TAG or to no field at all, and those bits carry the reset value in C#
    /// for ever, because nothing in `WriteInner` or `ReadInner` touches them.
    ///
    /// Measured cost of the difference: `SPI_CRCPR` read 0x0 here against
    /// Renode's 0x7, and `FLASH_OPTCR` 0x0FFFAA01 against 0x0FFFAAED -- on the
    /// FIRST READ AFTER RESET, before any firmware ran. Firmware polling such
    /// a bit waits for ever.
    fn value(&self, bank: &Bank<S>, state: &mut S) -> u64 {
        // `UnderlyingValue`: the reset word, with each register field's stored
        // value (or its provider's answer) over its own slice. Tags are not
        // register fields, so they keep the reset value.
        let mut v = self.reset;
        for f in &self.fields {
            if f.reserved {
                continue;
            }
            let m = mask(f.width) << f.offset;
            let stored = bank.slots[f.slot as usize].get();
            // A field with a provider reports whatever the provider returns,
            // even without FieldMode::READ -- matching the C#, where supplying
            // a valueProviderCallback is what makes the field readable.
            // A provider only exists on readable fields (enforced at
            // construction), so consulting it needs no further mode check.
            let raw = match f.provider {
                Some(p) => p(bank, state, f.group_index, stored),
                None => stored,
            };
            v = (v & !m) | ((raw << f.offset) & m);
            // C# snapshots `valueToRead` BEFORE this pass, so a read-to-clear
            // field reports its old value and only then clears -- which is the
            // whole point of the mode.
            if f.mode.contains(FieldMode::READ_TO_CLEAR) && raw & mask(f.width) != 0 {
                bank.slots[f.slot as usize].set(0);
            }
            if f.mode.contains(FieldMode::READ_TO_SET) && raw & mask(f.width) != mask(f.width) {
                bank.slots[f.slot as usize].set(mask(f.width));
            }
        }
        // Now subtract the unreadable fields, as the C# loop does. A provider
        // makes a field readable in C# regardless of its mode, which is why
        // this asks about the provider and not only about the mode.
        for f in &self.fields {
            if !f.reserved && f.provider.is_none() && !f.mode.is_readable() {
                v &= !(mask(f.width) << f.offset);
            }
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
pub struct Bank<S> {
    slots: Vec<Cell<u64>>,
    resets: Vec<u64>,
    registers: BTreeMap<u64, Register<S>>,
}

impl<S> Default for Bank<S> {
    fn default() -> Self {
        Self::new()
    }
}

impl<S> Bank<S> {
    pub fn new() -> Self {
        Self { slots: Vec::new(), resets: Vec::new(), registers: BTreeMap::new() }
    }

    /// Begin defining the register at `offset`. Mirrors C# `Register.X.Define(this)`.
    pub fn define(&mut self, offset: u64, reset: u64) -> RegisterBuilder<'_, S> {
        RegisterBuilder {
            bank: self,
            offset,
            reset,
            fields: Vec::new(),
            next_bit: 0,
            width_bits: 32,
            on_write: None,
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

    pub fn read(&self, offset: u64, state: &mut S) -> Option<u64> {
        let reg = self.registers.get(&offset)?;
        Some(reg.value(self, state))
    }

    /// Returns the bits written that no field covers, so a caller can reproduce
    /// Renode's "unhandled write" warning.
    pub fn write(&self, offset: u64, value: u64, state: &mut S) -> Option<u64> {
        let reg = self.registers.get(&offset)?;
        // Captured BEFORE any field updates: C# takes `baseValue` first and
        // passes it to every handler, so a register-level callback sees the
        // register as it was, not as the field loop left it.
        let base = reg.on_write.map(|_| reg.raw_value(self));
        for f in &reg.fields {
            if f.reserved {
                continue;
            }
            let incoming = (value >> f.offset) & mask(f.width);
            let slot = &self.slots[f.slot as usize];
            let old = slot.get();
            let m = mask(f.width);
            // C# `WriteInner` switches on `FieldMode.WriteBits()` rather than
            // testing flags in an order of its own choosing, and the comment
            // there says why: "switch is OK, because write modes are
            // exclusive". Every arm below is that switch's arm restricted to
            // this field's bits, with the C# guards dropped where they only
            // decide whether to record a CHANGE (`x |= 0` is a no-op anyway).
            match f.mode.write_bits() {
                FieldMode::WRITE => slot.set(incoming),
                // `setRegisters = value & ~UnderlyingValue`, then OrWith.
                FieldMode::SET => slot.set(old | incoming),
                // XorWith(UnderlyingValue, value).
                FieldMode::TOGGLE => slot.set(old ^ incoming),
                // AndWithNot(UnderlyingValue, value) -- PER BIT. Setting the
                // whole field to 0 on any written 1 is right for a flag and
                // wrong for every wider W1C field.
                FieldMode::WRITE_ONE_TO_CLEAR => slot.set(old & !incoming & m),
                // AndWithNot(UnderlyingValue, ~value) == keep only where the
                // written bit is 1.
                FieldMode::WRITE_ZERO_TO_CLEAR => slot.set(old & incoming),
                // negSetRegisters = ~value & ~UnderlyingValue, then OrWith.
                FieldMode::WRITE_ZERO_TO_SET => slot.set(old | (!incoming & m)),
                // XorWith(UnderlyingValue, ~value).
                FieldMode::WRITE_ZERO_TO_TOGGLE => slot.set(old ^ (!incoming & m)),
                // Any write clears / sets, whatever the written value was.
                FieldMode::WRITE_TO_CLEAR => slot.set(0),
                FieldMode::WRITE_TO_SET => slot.set(m),
                // No write bits at all: the field is unwritable. The C# switch
                // falls through for the same reason.
                _ => {}
            }
            // C# order: the field is updated, then the write callback fires.
            // It fires on any write to the register, matching CallWriteHandler.
            if let Some(cb) = f.on_write {
                cb(self, state, f.group_index, old, incoming);
            }
        }
        // C# order: every field's write handler, THEN the register's. It fires
        // on any write, changed or not — `CallWriteHandlers` is unconditional.
        if let (Some(cb), Some(old)) = (reg.on_write, base) {
            cb(self, state, old, value & mask(reg.width_bits));
        }
        // C# `unhandledWrites = difference & ~definedFieldsMask`, where
        // `difference = UnderlyingValue ^ value` is taken before the field
        // loop. Every bit in `unhandled_mask` belongs to a tag or to no field,
        // and neither is ever written, so `UnderlyingValue` still holds the
        // reset value there -- writing a tag its own reset value is NOT
        // reported, exactly as in C#. `value & mask` reported it.
        Some((value ^ reg.reset) & reg.unhandled_mask)
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
pub struct RegisterBuilder<'a, S> {
    bank: &'a mut Bank<S>,
    offset: u64,
    reset: u64,
    fields: Vec<FieldDef<S>>,
    next_bit: u32,
    width_bits: u32,
    on_write: Option<RegisterWriteCallback<S>>,
}

impl<'a, S> RegisterBuilder<'a, S> {
    fn alloc(&mut self, reset: u64) -> u16 {
        let slot = self.bank.slots.len() as u16;
        self.bank.slots.push(Cell::new(reset));
        self.bank.resets.push(reset);
        slot
    }

    fn push(&mut self, offset: u32, width: u32, mode: FieldMode, reserved: bool) -> u16 {
        self.push_cb(offset, width, mode, reserved, 0, None, None)
    }

    #[allow(clippy::too_many_arguments)]
    fn push_cb(
        &mut self,
        offset: u32,
        width: u32,
        mode: FieldMode,
        reserved: bool,
        group_index: usize,
        provider: Option<ValueProvider<S>>,
        on_write: Option<WriteCallback<S>>,
    ) -> u16 {
        // C# RegisterField's constructor: "A write-only field cannot provide a
        // value callback." That invariant is enforced at construction there, so
        // enforcing it here is faithfulness, not extra strictness.
        //
        // Found by mutation testing: without it, mutating a provider-bearing
        // field's mode to write-only SURVIVED, because value() consulted the
        // provider regardless of the mode. The C# makes that unconstructable.
        assert!(
            !(provider.is_some() && !mode.is_readable()),
            "a write-only field cannot provide a value callback \
             (offset {offset}, width {width})"
        );
        // The mirror case: a callback that can never fire is dead configuration,
        // and silently accepting it is how dead code hides.
        assert!(
            !(on_write.is_some() && mode.is_empty()),
            "a field with no write mode cannot have a write callback \
             (offset {offset}, width {width})"
        );
        let reset = (self.reset >> offset) & mask(width);
        let slot = self.alloc(reset);
        self.fields.push(FieldDef {
            offset, width, mode, reset, slot, reserved, group_index, provider, on_write,
        });
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

    /// `WithValueField(pos, width, mode, name:)` — no `out`, no callbacks.
    ///
    /// **Stored, not tagged.** The C# overload without an `out` parameter still
    /// calls `DefineValueField`, so the field is a real `RegisterField` in
    /// `registerFields`: writes stick and reads return them. Only `Tag` /
    /// `TaggedFlag` go to the separate `tags` list that stores nothing.
    ///
    /// This exists because the two were conflated. An anonymous value field was
    /// emitted as `with_tag`, `Bank::write` skips reserved fields, and the
    /// register silently became write-ignored / read-as-zero — the C#
    /// `STM32F4_EXTI` EMR is a deliberate read-write scratch register and lost
    /// exactly that. Nothing observed it: its trace has no writes.
    ///
    /// No handle is returned because the C# binds none; the field is reachable
    /// only through the register it belongs to.
    pub fn with_value_anon(mut self, pos: u32, width: u32, mode: FieldMode) -> Self {
        self.push(pos, width, mode, false);
        self
    }

    /// `WithFlag(pos, mode, name:)` — no `out`, no callbacks. Stored, not
    /// tagged; see [`RegisterBuilder::with_value_anon`].
    pub fn with_flag_anon(mut self, pos: u32, mode: FieldMode) -> Self {
        self.push(pos, 1, mode, false);
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

    /// `WithFlag(pos, out field, mode, writeCallback:)` — bound AND computed.
    ///
    /// The C# `out` parameter and the callbacks are independent: a field can
    /// hand back a handle and carry behaviour, and 22 call sites in the cut do
    /// both. There was no combinator for that, so the bound rule matched, the
    /// callback fell off the end and nothing said so.
    pub fn with_flag_cb(
        mut self,
        pos: u32,
        out: &mut FlagId,
        mode: FieldMode,
        provider: Option<ValueProvider<S>>,
        on_write: Option<WriteCallback<S>>,
    ) -> Self {
        *out = FlagId(self.push_cb(pos, 1, mode, false, 0, provider, on_write));
        self
    }

    /// `WithValueField(pos, width, out field, mode, writeCallback:)` — the
    /// multi-bit form of `with_flag_cb`. Named for the C# `out` parameter that
    /// distinguishes it from `with_value_cb`, which binds nothing.
    pub fn with_value_out_cb(
        mut self,
        pos: u32,
        width: u32,
        out: &mut ValueId,
        mode: FieldMode,
        provider: Option<ValueProvider<S>>,
        on_write: Option<WriteCallback<S>>,
    ) -> Self {
        *out = ValueId(self.push_cb(pos, width, mode, false, 0, provider, on_write));
        self
    }

    /// `WithValueFields(pos, width, count, ...)` -- `count` consecutive fields
    /// of equal width. Returns the first handle; the rest are consecutive
    /// indices, which is exactly why field handles are indices and not pointers.
    pub fn with_value_fields(
        mut self,
        pos: u32,
        width: u32,
        count: u32,
        out: &mut ValueId,
        mode: FieldMode,
    ) -> Self {
        for i in 0..count {
            let slot = self.push(pos + i * width, width, mode, false);
            if i == 0 {
                *out = ValueId(slot);
            }
        }
        self
    }

    /// `WithEnumFields<E>(pos, width, count, ...)`. Enum fields are stored
    /// identically to value fields -- the C# distinction is type-level only, and
    /// the enum conversion happens where the peripheral reads the field.
    pub fn with_enum_fields(
        self,
        pos: u32,
        width: u32,
        count: u32,
        out: &mut ValueId,
        mode: FieldMode,
    ) -> Self {
        self.with_value_fields(pos, width, count, out, mode)
    }

    /// `WithValueField(pos, width, mode, valueProviderCallback:, writeCallback:)`.
    pub fn with_value_cb(
        mut self,
        pos: u32,
        width: u32,
        mode: FieldMode,
        provider: Option<ValueProvider<S>>,
        on_write: Option<WriteCallback<S>>,
    ) -> Self {
        self.push_cb(pos, width, mode, false, 0, provider, on_write);
        self
    }

    /// `WithEnumFields`/`WithValueFields` with per-index callbacks -- the C#
    /// `(idx, _) => ...` form. The captured loop variable becomes the
    /// `group_index` parameter.
    pub fn with_fields_cb(
        mut self,
        pos: u32,
        width: u32,
        count: u32,
        out: &mut ValueId,
        mode: FieldMode,
        provider: Option<ValueProvider<S>>,
        on_write: Option<WriteCallback<S>>,
    ) -> Self {
        for i in 0..count {
            let slot =
                self.push_cb(pos + i * width, width, mode, false, i as usize, provider, on_write);
            if i == 0 {
                *out = ValueId(slot);
            }
        }
        self
    }

    /// `WithValueFields`/`WithEnumFields` bound by CALLBACK and not by `out` —
    /// `(idx, val) => mode[idx]`, where the C# lambda closes over the group
    /// index and the peripheral keeps no field handle at all.
    ///
    /// Distinct from `with_fields_cb` only in binding nothing, which is why it
    /// exists: passing a scratch `ValueId` instead would invent a handle the
    /// C# does not have, and that is the same error class as the invented
    /// `.with_reserved(9, 23)`.
    pub fn with_values_cb(
        mut self,
        pos: u32,
        width: u32,
        count: u32,
        mode: FieldMode,
        provider: Option<ValueProvider<S>>,
        on_write: Option<WriteCallback<S>>,
    ) -> Self {
        for i in 0..count {
            self.push_cb(pos + i * width, width, mode, false, i as usize, provider, on_write);
        }
        self
    }

    /// C# `WithWriteCallback` — attaches to the REGISTER, so it takes no bit
    /// position and fires once per write rather than once per field.
    pub fn with_write_callback(mut self, cb: Option<RegisterWriteCallback<S>>) -> Self {
        self.on_write = cb;
        self
    }

    /// Finish the register and install it in the bank.
    pub fn done(self) {
        // C# `RecalculateFieldMask` sums `registerFields` ONLY, and `Tag()`
        // never calls it -- so `definedFieldsMask` excludes tags, and
        // `unhandledWrites = difference & ~definedFieldsMask` reports a write
        // to a tagged bit. `TagLogger` exists precisely to name which tags the
        // unhandled bits fell in. Folding reserved fields in here silenced
        // that, which is the one thing a tag is for.
        let mut covered = 0u64;
        for f in &self.fields {
            if f.reserved {
                continue;
            }
            covered |= mask(f.width) << f.offset;
        }
        let full = mask(self.width_bits);
        let reg: Register<S> = Register {
            fields: self.fields,
            reset: self.reset,
            unhandled_mask: full & !covered,
            width_bits: self.width_bits,
            on_write: self.on_write,
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
        let mut bank: Bank<()> = Bank::new();
        let (mut a, mut b) = (FlagId::default(), FlagId::default());
        bank.define(0x00, 0)
            .with_flag(2, &mut a, FieldMode::READ_WRITE)
            .with_flag(5, &mut b, FieldMode::READ_WRITE)
            .done();

        bank.write(0x00, 1 << 5, &mut ());
        assert!(!bank.flag(a));
        assert!(bank.flag(b));
        assert_eq!(bank.read(0x00, &mut ()), Some(1 << 5));
    }

    #[test]
    fn reset_value_is_applied_per_field() {
        // STM32 USART_SR resets to 0xC0: TC and TXE set.
        let mut bank: Bank<()> = Bank::new();
        let (mut tc, mut txe) = (FlagId::default(), FlagId::default());
        bank.define(0x00, 0xC0)
            .with_flag(6, &mut tc, FieldMode::READ)
            .with_flag(7, &mut txe, FieldMode::READ)
            .done();
        assert!(bank.flag(tc));
        assert!(bank.flag(txe));
        assert_eq!(bank.read(0x00, &mut ()), Some(0xC0));
    }

    #[test]
    fn write_one_to_clear_only_clears_on_one() {
        let mut bank: Bank<()> = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0)
            .with_flag(0, &mut f, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
            .done();
        bank.set_flag(f, true);
        bank.write(0, 0, &mut ());
        assert!(bank.flag(f), "writing 0 must not clear a W1C flag");
        bank.write(0, 1, &mut ());
        assert!(!bank.flag(f));
    }

    #[test]
    fn reserved_bits_absorb_writes_and_are_reported_unhandled() {
        let mut bank: Bank<()> = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0)
            .with_flag(0, &mut f, FieldMode::READ_WRITE)
            .with_reserved(1, 31)
            .done();
        // `Reserved()` wraps `Tag()`, and `RecalculateFieldMask` counts only
        // registerFields -- so bits 1..31 ARE unhandled writes in C#, which is
        // what `TagLogger` names them for. They still absorb the write, and
        // still read back their reset value, which here is zero.
        assert_eq!(bank.write(0, 0xFFFF_FFFF, &mut ()), Some(0xFFFF_FFFE));
        assert_eq!(bank.read(0, &mut ()), Some(1));
    }

    /// The divergence `check_reset_bits_reserved.py` was written for, at the
    /// measured `STM32SPI` SPI_CRCPR shape: reset 0x7 under a tag. C# reads
    /// 0x7 on the FIRST READ AFTER RESET; this read 0x0 until `value()`
    /// stopped skipping tags. Firmware polling such a bit waits forever.
    #[test]
    fn a_tag_reads_back_its_reset_value() {
        let mut bank: Bank<()> = Bank::new();
        bank.define(0x00, 0x7).with_tag(0, 16).with_reserved(16, 16).done();
        assert_eq!(bank.read(0x00, &mut ()), Some(0x7));

        // And `Reserved()` is a wrapper over `Tag()`, so it behaves the same.
        bank.define(0x04, 0x0FFF_AAED).with_reserved(0, 32).done();
        assert_eq!(bank.read(0x04, &mut ()), Some(0x0FFF_AAED));
    }

    /// The same mechanism one step further out: C# reads `UnderlyingValue` and
    /// subtracts the unreadable FIELDS, so a bit covered by nothing at all
    /// also reads back its reset value. Composing the answer from the fields
    /// dropped those bits, and no combinator has to be involved for the
    /// register to be wrong.
    #[test]
    fn bits_no_field_covers_read_back_their_reset_value() {
        let mut bank: Bank<()> = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0xF0F1).with_flag(0, &mut f, FieldMode::READ_WRITE).done();
        assert_eq!(bank.read(0, &mut ()), Some(0xF0F1));
        // And the reset value survives a write that misses them, as in C#:
        // WriteInner only ever updates registerFields.
        bank.write(0, 0, &mut ());
        assert_eq!(bank.read(0, &mut ()), Some(0xF0F0));
    }

    /// A write-only field is subtracted from the value being read even though
    /// its bit is set in the backing word. C# `IsReadable()` is the test, and
    /// starting from `UnderlyingValue` means forgetting the subtraction leaks
    /// the field instead of hiding it -- the opposite failure, so both
    /// directions are pinned.
    #[test]
    fn an_unreadable_field_is_subtracted_from_the_read() {
        let mut bank: Bank<()> = Bank::new();
        bank.define(0, 0xFF)
            .with_value_anon(0, 4, FieldMode::WRITE)
            .with_value_anon(4, 4, FieldMode::READ_WRITE)
            .done();
        assert_eq!(bank.read(0, &mut ()), Some(0xF0));
    }

    /// A tag is not a RegisterField, so `WriteInner` never touches it: it
    /// keeps its reset value for ever, through any number of writes.
    #[test]
    fn a_tag_keeps_its_reset_value_through_writes() {
        let mut bank: Bank<()> = Bank::new();
        bank.define(0, 0x7).with_tag(0, 16).with_reserved(16, 16).done();
        bank.write(0, 0xFFFF_FFFF, &mut ());
        assert_eq!(bank.read(0, &mut ()), Some(0x7));
        bank.write(0, 0x0000_0000, &mut ());
        assert_eq!(bank.read(0, &mut ()), Some(0x7));
    }

    /// C# takes `difference = UnderlyingValue ^ value`, so writing a tag the
    /// value it already holds is not an unhandled write. Reporting `value`
    /// rather than the difference made every write to a reset-set tag look
    /// like a change that went nowhere.
    #[test]
    fn writing_a_tag_its_own_reset_value_is_not_reported() {
        let mut bank: Bank<()> = Bank::new();
        bank.define(0, 0x7).with_tag(0, 32).done();
        assert_eq!(bank.write(0, 0x7, &mut ()), Some(0));
        assert_eq!(bank.write(0, 0x6, &mut ()), Some(1), "bit 0 differs");
    }

    #[test]
    fn writes_to_uncovered_bits_are_reported() {
        let mut bank: Bank<()> = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0).with_flag(0, &mut f, FieldMode::READ_WRITE).done();
        // Bits 1..31 are covered by no field: Renode warns about these, so the
        // mask is returned rather than silently dropped.
        assert_eq!(bank.write(0, 0b110, &mut ()), Some(0b110));
    }

    #[test]
    fn value_fields_allocate_consecutive_handles() {
        // GPIOPort's MODER is 16 two-bit fields; indexing pin N must be
        // first_handle + N, which is what makes index handles pay off.
        let mut bank: Bank<()> = Bank::new();
        let mut first = ValueId::default();
        bank.define(0, 0)
            .with_value_fields(0, 2, 16, &mut first, FieldMode::READ_WRITE)
            .done();
        bank.write(0, 0b11 << 4, &mut ()); // pin 2 = 0b11
        assert_eq!(bank.value(first.offset(2)), 0b11);
        assert_eq!(bank.value(first.offset(0)), 0);
        assert_eq!(bank.read(0, &mut ()), Some(0b11 << 4));
    }

    /// Callbacks live in the DSL, receiving the bank and peripheral state as
    /// parameters rather than capturing them. This is the C# `DR` shape:
    /// a read that mutates peripheral state AND sibling register fields.
    #[test]
    fn value_provider_reads_peripheral_state_and_mutates_siblings() {
        struct Fifo { bytes: Vec<u8> }
        fn provider(bank: &Bank<Fifo>, st: &mut Fifo, _i: usize, _cur: u64) -> u64 {
            // Mutates a sibling field through &Bank -- Cell makes this legal.
            bank.slots[0].set(0);
            st.bytes.pop().unwrap_or(0) as u64
        }
        let mut bank: Bank<Fifo> = Bank::new();
        let mut flag = FlagId::default();
        bank.define(0x00, 1).with_flag(0, &mut flag, FieldMode::READ).done();
        bank.define(0x04, 0)
            .with_value_cb(0, 9, FieldMode::READ, Some(provider), None)
            .with_reserved(9, 23)
            .done();

        let mut st = Fifo { bytes: vec![b'a', b'b'] };
        assert!(bank.flag(flag), "sibling starts set");
        assert_eq!(bank.read(0x04, &mut st), Some(b'b' as u64));
        assert!(!bank.flag(flag), "provider cleared the sibling field");
        assert_eq!(bank.read(0x04, &mut st), Some(b'a' as u64));
    }

    /// The C# plural form `(idx, _) => mode[idx]` captures a loop variable;
    /// here that arrives as the group index.
    #[test]
    fn plural_callbacks_receive_their_field_index() {
        struct Pins { seen: Vec<usize> }
        fn on_write(_b: &Bank<Pins>, st: &mut Pins, idx: usize, _old: u64, _new: u64) {
            st.seen.push(idx);
        }
        let mut bank: Bank<Pins> = Bank::new();
        let mut first = ValueId::default();
        bank.define(0, 0)
            .with_fields_cb(0, 2, 4, &mut first, FieldMode::READ_WRITE, None, Some(on_write))
            .done();
        let mut st = Pins { seen: vec![] };
        bank.write(0, 0, &mut st);
        assert_eq!(st.seen, vec![0, 1, 2, 3], "each field sees its own index");
    }

    /// C# throws ConstructionException for this exact case. Mutation testing
    /// found it: without the check, a provider-bearing field mutated to
    /// write-only survived, because value() used the provider regardless.
    #[test]
    #[should_panic(expected = "write-only field cannot provide a value callback")]
    fn write_only_field_cannot_have_a_value_provider() {
        fn provider(_b: &Bank<()>, _s: &mut (), _i: usize, _c: u64) -> u64 {
            0
        }
        let mut bank: Bank<()> = Bank::new();
        bank.define(0, 0)
            .with_value_cb(0, 8, FieldMode::WRITE, Some(provider), None)
            .done();
    }

    #[test]
    #[should_panic(expected = "no write mode cannot have a write callback")]
    fn unwritable_field_cannot_have_a_write_callback() {
        fn on_write(_b: &Bank<()>, _s: &mut (), _i: usize, _o: u64, _n: u64) {}
        let mut bank: Bank<()> = Bank::new();
        bank.define(0, 0)
            .with_value_cb(0, 8, FieldMode::default(), None, Some(on_write))
            .done();
    }

    /// The bug this pair of combinators exists for. C# `WithValueField(0, 32,
    /// name: "EMR")` binds no handle and is still a STORED field; `WithTag` is
    /// not. Emitting the first as the second made the register write-ignored and
    /// read-as-zero, which no trace in the cut could see.
    #[test]
    fn anonymous_value_field_stores_where_a_tag_drops() {
        let mut bank: Bank<()> = Bank::new();
        // 0x00 is the C# shape: an anonymous, handle-less, read-write field.
        bank.define(0x00, 0).with_value_anon(0, 32, FieldMode::READ_WRITE).done();
        // 0x04 is a genuine WithTag over the same bits, for contrast.
        bank.define(0x04, 0).with_tag(0, 32).done();

        assert_eq!(bank.write(0x00, 0xDEAD_BEEF, &mut ()), Some(0));
        assert_eq!(
            bank.read(0x00, &mut ()),
            Some(0xDEAD_BEEF),
            "an anonymous value field is stored: the write must survive"
        );

        assert_eq!(
            bank.write(0x04, 0xDEAD_BEEF, &mut ()),
            Some(0xDEAD_BEEF),
            "a tag is not in definedFieldsMask, so the write is unhandled"
        );
        assert_eq!(
            bank.read(0x04, &mut ()),
            Some(0),
            "a tag holds its reset value -- here 0 -- and the write did not \
             reach it, which is the difference"
        );
    }

    /// The mode was being discarded as well: every anonymous field became a
    /// READ_WRITE tag regardless of what the C# asked for. Five `STM32F4_RTC`
    /// flags are `Read | WriteZeroToClear` and one is write-only.
    #[test]
    fn anonymous_flag_honours_its_mode() {
        let mut bank: Bank<()> = Bank::new();
        bank.define(0, 0x1)
            .with_flag_anon(0, FieldMode::READ)
            .with_flag_anon(1, FieldMode::WRITE)
            .done();
        // Bit 0 is read-only: it reports its reset value and ignores the write.
        // Bit 1 is write-only: it stores the write and reports nothing.
        assert_eq!(bank.read(0, &mut ()), Some(0b01));
        bank.write(0, 0b10, &mut ());
        assert_eq!(bank.read(0, &mut ()), Some(0b01));
    }

    /// Anonymous fields allocate a slot, exactly as tags already did, so they
    /// neither create nor close a gap in the arena. `ValueId::offset(n)` still
    /// addresses a plural group consecutively with one in front of it.
    #[test]
    fn an_anonymous_field_does_not_break_consecutive_handles() {
        let mut bank: Bank<()> = Bank::new();
        let mut first = ValueId::default();
        bank.define(0, 0)
            .with_value_anon(0, 4, FieldMode::READ_WRITE)
            .with_value_fields(4, 2, 4, &mut first, FieldMode::READ_WRITE)
            .done();
        bank.write(0, 0b11 << 8, &mut ()); // group index 2
        assert_eq!(bank.value(first.offset(2)), 0b11);
        assert_eq!(bank.value(first.offset(0)), 0);
        assert_eq!(bank.read(0, &mut ()), Some(0b11 << 8));
    }

    /// C# `WithWriteCallback` fires ONCE per write to the register, after every
    /// field's own handler, and whether or not anything changed —
    /// `CallWriteHandlers` is unconditional. Dropping it is what left an
    /// interrupt line asserted after an ISR cleared the flag behind it.
    #[test]
    fn register_write_callback_fires_once_per_write_after_the_fields() {
        struct Log { seen: Vec<&'static str>, old: u64, new: u64 }
        fn field_cb(_b: &Bank<Log>, st: &mut Log, _i: usize, _o: u64, _n: u64) {
            st.seen.push("field");
        }
        fn reg_cb(_b: &Bank<Log>, st: &mut Log, old: u64, new: u64) {
            st.seen.push("register");
            st.old = old;
            st.new = new;
        }
        let mut bank: Bank<Log> = Bank::new();
        bank.define(0, 0)
            .with_value_cb(0, 4, FieldMode::READ_WRITE, None, Some(field_cb))
            .with_value_cb(4, 4, FieldMode::READ_WRITE, None, Some(field_cb))
            .with_write_callback(Some(reg_cb))
            .done();

        let mut st = Log { seen: vec![], old: 0xFF, new: 0xFF };
        bank.write(0, 0x21, &mut st);
        assert_eq!(st.seen, vec!["field", "field", "register"]);
        assert_eq!((st.old, st.new), (0, 0x21), "the register's values, not a field's");

        // Fires again with nothing changed: this is NOT changeCallback.
        st.seen.clear();
        bank.write(0, 0x21, &mut st);
        assert_eq!(st.seen, vec!["field", "field", "register"]);
        assert_eq!(st.old, 0x21, "old is the value BEFORE this write");
    }

    /// The plural combinators bound by CALLBACK rather than by `out`. Five
    /// registers of one peripheral use this and matched no rule at all, so the
    /// registers were located and emitted with no fields in them.
    #[test]
    fn computed_field_group_binds_no_handle_and_still_stores() {
        struct Pins { seen: Vec<usize> }
        fn on_write(_b: &Bank<Pins>, st: &mut Pins, idx: usize, _o: u64, _n: u64) {
            st.seen.push(idx);
        }
        let mut bank: Bank<Pins> = Bank::new();
        bank.define(0, 0)
            .with_values_cb(0, 2, 16, FieldMode::READ_WRITE, None, Some(on_write))
            .done();
        let mut st = Pins { seen: vec![] };
        bank.write(0, 0b11 << 4, &mut st);
        assert_eq!(bank.read(0, &mut st), Some(0b11 << 4), "stores without a handle");
        assert_eq!(st.seen.len(), 16, "every field in the group sees its own index");
    }

    /// `out` and a callback are independent in C#, and the combinator table had
    /// no shape for both: the handle was bound and the behaviour silently lost.
    #[test]
    fn a_bound_field_can_also_carry_a_callback() {
        struct S { writes: u32 }
        fn on_write(_b: &Bank<S>, st: &mut S, _i: usize, _o: u64, _n: u64) {
            st.writes += 1;
        }
        let mut bank: Bank<S> = Bank::new();
        let mut flag = FlagId::default();
        let mut val = ValueId::default();
        bank.define(0, 0)
            .with_flag_cb(0, &mut flag, FieldMode::READ_WRITE, None, Some(on_write))
            .with_value_out_cb(4, 4, &mut val, FieldMode::READ_WRITE, None, Some(on_write))
            .done();
        let mut st = S { writes: 0 };
        bank.write(0, 0x31, &mut st);
        assert!(bank.flag(flag), "the handle still binds");
        assert_eq!(bank.value(val), 3);
        assert_eq!(st.writes, 2, "and the callbacks still fire");
    }

    /// `FieldModeHelper.IsReadable` is `Read | ReadToClear | ReadToSet`, and
    /// only the first was tested. A `ReadToClear` field -- the C# mode of
    /// `SYS_TICK_CONTROL` bit 16, which the emitter rendered as
    /// `FieldMode::default()` -- answers reads, and clears itself afterwards.
    #[test]
    fn read_to_clear_reports_its_value_then_clears() {
        let mut bank: Bank<()> = Bank::new();
        bank.define(0, 0b101).with_value_anon(0, 3, FieldMode::READ_TO_CLEAR).done();
        assert_eq!(bank.read(0, &mut ()), Some(0b101), "the value BEFORE the clear");
        assert_eq!(bank.read(0, &mut ()), Some(0), "and it is gone afterwards");
    }

    #[test]
    fn read_to_set_reports_its_value_then_sets() {
        let mut bank: Bank<()> = Bank::new();
        bank.define(0, 0b001).with_value_anon(0, 3, FieldMode::READ_TO_SET).done();
        assert_eq!(bank.read(0, &mut ()), Some(0b001));
        assert_eq!(bank.read(0, &mut ()), Some(0b111));
    }

    /// The other four write modes the mode table had no bit for. Each arm is
    /// the C# `WriteInner` switch case restricted to the field's bits.
    #[test]
    fn the_remaining_write_modes_follow_the_csharp_switch() {
        let mut bank: Bank<()> = Bank::new();
        // READ is added throughout because `IsReadable()` is Read | ReadToClear
        // | ReadToSet: a write-only field reads back zero in C# as well.
        bank.define(0x00, 0b0101)
            .with_value_anon(0, 4, FieldMode::WRITE_ZERO_TO_SET | FieldMode::READ)
            .done();
        bank.define(0x04, 0b0101)
            .with_value_anon(0, 4, FieldMode::WRITE_ZERO_TO_TOGGLE | FieldMode::READ)
            .done();
        bank.define(0x08, 0b0101).with_value_anon(0, 4, FieldMode::WRITE_TO_CLEAR | FieldMode::READ).done();
        bank.define(0x0C, 0b0101).with_value_anon(0, 4, FieldMode::WRITE_TO_SET | FieldMode::READ).done();

        // negSetRegisters = ~value & ~old -> old | (!v & m): 0101 | 0010 = 0111
        bank.write(0x00, 0b1001, &mut ());
        assert_eq!(bank.read(0x00, &mut ()), Some(0b0111));
        // XorWith(old, ~value): 0101 ^ 0110 = 0011
        bank.write(0x04, 0b1001, &mut ());
        assert_eq!(bank.read(0x04, &mut ()), Some(0b0011));
        // Any write clears / sets the whole field, whatever was written.
        bank.write(0x08, 0b0000, &mut ());
        assert_eq!(bank.read(0x08, &mut ()), Some(0));
        bank.write(0x0C, 0b0000, &mut ());
        assert_eq!(bank.read(0x0C, &mut ()), Some(0b1111));
    }

    /// C# `AndWithNot(UnderlyingValue, value, position, width)` clears the
    /// written bits, not the field. Zeroing the whole field on any written 1
    /// is right for a flag and wrong for every wider W1C field -- and the
    /// mirror mistakes were in `Set` (set the field to 1) and `Toggle`
    /// (invert the whole field).
    #[test]
    fn the_bitwise_write_modes_act_per_bit_not_per_field() {
        let mut bank: Bank<()> = Bank::new();
        bank.define(0x00, 0b1111)
            .with_value_anon(0, 4, FieldMode::READ | FieldMode::WRITE_ONE_TO_CLEAR)
            .done();
        bank.define(0x04, 0b0000).with_value_anon(0, 4, FieldMode::SET | FieldMode::READ).done();
        bank.define(0x08, 0b1010)
            .with_value_anon(0, 4, FieldMode::TOGGLE | FieldMode::READ)
            .done();

        bank.write(0x00, 0b0011, &mut ());
        assert_eq!(bank.read(0x00, &mut ()), Some(0b1100), "only the written 1s clear");
        bank.write(0x04, 0b0110, &mut ());
        assert_eq!(bank.read(0x04, &mut ()), Some(0b0110), "Set ORs, it does not set to 1");
        bank.write(0x08, 0b0011, &mut ());
        assert_eq!(bank.read(0x08, &mut ()), Some(0b1001), "Toggle XORs the written bits");
    }

    /// C# hands a register-level write callback `baseValue = UnderlyingValue`,
    /// a word seeded with the reset value that only register FIELDS overwrite.
    /// Composing it from the stored slots alone dropped every tagged and
    /// uncovered bit to zero; this was a recorded deviation and no longer is.
    #[test]
    fn a_register_write_callback_sees_tag_and_uncovered_reset_bits() {
        struct Seen(u64);
        fn cb(_b: &Bank<Seen>, st: &mut Seen, old: u64, _new: u64) {
            st.0 = old;
        }
        let mut bank: Bank<Seen> = Bank::new();
        // bits 0..3 a real field, 4..7 a tag, 8..11 covered by nothing at all.
        bank.define(0, 0x0F0F)
            .with_value_anon(0, 4, FieldMode::READ_WRITE)
            .with_tag(4, 4)
            .with_write_callback(Some(cb))
            .done();
        let mut st = Seen(0);
        bank.write(0, 0, &mut st);
        assert_eq!(st.0, 0x0F0F, "the whole backing word, not just the fields");
    }

    #[test]
    fn reset_restores_every_field() {
        let mut bank: Bank<()> = Bank::new();
        let mut f = FlagId::default();
        bank.define(0, 0x1).with_flag(0, &mut f, FieldMode::READ_WRITE).done();
        bank.set_flag(f, false);
        bank.reset();
        assert!(bank.flag(f));
    }
}
