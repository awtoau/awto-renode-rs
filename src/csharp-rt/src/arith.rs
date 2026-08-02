//! C# integer arithmetic, where Rust's spelling of the same operator means
//! something else.
//!
//! Three of C#'s integer operators do NOT mean what the identically-spelled
//! Rust operator means, and in each case the difference is invisible at the
//! call site — which is the test in `docs/decisions/runtime-is-the-fourth-layer.md`
//! for a mapping that belongs here rather than in a template.
//!
//! | C# | what it does | what Rust's `+`/`<<` does |
//! |---|---|---|
//! | `a + b`, unchecked context (the DEFAULT) | wraps silently | panics in debug, wraps in release |
//! | `a + b`, `checked` context | throws `OverflowException` | panics in debug, wraps in release |
//! | `a << n` | shifts by `n` masked to the operand's width | panics in debug on `n >= BITS` |
//!
//! Sources, quoted rather than paraphrased because the masking rule is the one
//! people do not believe:
//!
//! * ECMA-334 §12.11 (shift operators): *"When the type of x is `int` or
//!   `uint`, the shift count is given by the low-order five bits of `count`.
//!   … When the type of x is `long` or `ulong`, the shift count is given by
//!   the low-order six bits of `count`."* So C# `1 << 32` is `1`, and
//!   C# `1 << -1` is `1 << 31`. Rust's `1i32 << 32` is a debug panic.
//! * ECMA-334 §12.8.20 (`checked`/`unchecked`): the default context for a
//!   non-constant expression is **unchecked**, so silent wrapping is the
//!   ordinary case and `checked` is the exception. The corpus agrees: the cut
//!   holds 2,602 unchecked binaries against 10 checked ones.
//!
//! ## Why the checked form panics
//!
//! C# throws `OverflowException`; this panics. Under D4 (exceptions, deferred)
//! there is no `Result` discipline to raise into yet, so the choice is recorded
//! in ONE place with the C# exception named in the message, rather than at each
//! of the several hundred arithmetic sites. When D4 lands, these functions are
//! what changes.
//!
//! ## Width promotion is the CALLER's job
//!
//! C# promotes any operand narrower than `int` before an arithmetic or shift
//! operator (ECMA-334 §12.4.7), so `(byte)0x80 << 1` is an `int` `0x100` and
//! not a `byte` `0`. Roslyn materialises that promotion as a conversion node,
//! and the converter's numeric-conversion rule emits the cast, so by the time
//! a value reaches here it already has its promoted type. These functions
//! therefore mask by `T::BITS - 1` for whatever `T` they are given: correct for
//! the promoted `i32`/`u32`/`i64`/`u64` that C# actually produces, and NOT a
//! model of what C# would do to a `u8` — because C# never shifts a `u8`.

/// The integer operations whose C# meaning differs from Rust's operator.
///
/// A trait rather than free generic functions over `std::ops` because the
/// wrapping and checked forms are inherent methods on the primitives, and
/// there is no std trait that names them.
pub trait CsInt: Copy + Sized {
    /// Bit width, for the shift-count mask.
    const BITS: u32;

    fn cs_wrapping_add(self, rhs: Self) -> Self;
    fn cs_wrapping_sub(self, rhs: Self) -> Self;
    fn cs_wrapping_mul(self, rhs: Self) -> Self;
    fn cs_wrapping_neg(self) -> Self;

    fn cs_checked_add(self, rhs: Self) -> Option<Self>;
    fn cs_checked_sub(self, rhs: Self) -> Option<Self>;
    fn cs_checked_mul(self, rhs: Self) -> Option<Self>;
    fn cs_checked_neg(self) -> Option<Self>;

    /// `<<` with the count masked to `BITS - 1`, as ECMA-334 §12.11 requires.
    fn cs_shl(self, count: u32) -> Self;
    /// `>>` with the count masked. Arithmetic for signed, logical for
    /// unsigned — which is what both languages do, so only the mask differs.
    fn cs_shr(self, count: u32) -> Self;
}

macro_rules! impl_cs_int {
    ($($t:ty),+ $(,)?) => { $(
        impl CsInt for $t {
            const BITS: u32 = <$t>::BITS;

            fn cs_wrapping_add(self, rhs: Self) -> Self { self.wrapping_add(rhs) }
            fn cs_wrapping_sub(self, rhs: Self) -> Self { self.wrapping_sub(rhs) }
            fn cs_wrapping_mul(self, rhs: Self) -> Self { self.wrapping_mul(rhs) }
            fn cs_wrapping_neg(self) -> Self { self.wrapping_neg() }

            fn cs_checked_add(self, rhs: Self) -> Option<Self> { self.checked_add(rhs) }
            fn cs_checked_sub(self, rhs: Self) -> Option<Self> { self.checked_sub(rhs) }
            fn cs_checked_mul(self, rhs: Self) -> Option<Self> { self.checked_mul(rhs) }
            fn cs_checked_neg(self) -> Option<Self> { self.checked_neg() }

            // `wrapping_shl` masks the count by `BITS - 1`, which IS the
            // ECMA-334 rule: & 0x1F for 32-bit, & 0x3F for 64-bit. A negative
            // C# count arrives here as its two's-complement `u32`, and the
            // low bits of that are the same low bits C# takes — so
            // `x << -1` is `x << 31` in both languages, with no special case.
            fn cs_shl(self, count: u32) -> Self { self.wrapping_shl(count) }
            fn cs_shr(self, count: u32) -> Self { self.wrapping_shr(count) }
        }
    )+ };
}

impl_cs_int!(i8, i16, i32, i64, i128, isize, u8, u16, u32, u64, u128, usize);

#[cold]
#[inline(never)]
fn overflowed(op: &str) -> ! {
    // The C# exception is named so that a stack trace from translated code
    // says which C# behaviour was being reproduced. See the module note on D4.
    panic!("System.OverflowException: arithmetic operation `{op}` overflowed \
            in a checked context")
}

/// C# `a + b` in the default (unchecked) context: wraps.
#[inline]
pub fn unchecked_add<T: CsInt>(a: T, b: T) -> T { a.cs_wrapping_add(b) }

/// C# `a - b` in the default (unchecked) context: wraps.
#[inline]
pub fn unchecked_sub<T: CsInt>(a: T, b: T) -> T { a.cs_wrapping_sub(b) }

/// C# `a * b` in the default (unchecked) context: wraps.
#[inline]
pub fn unchecked_mul<T: CsInt>(a: T, b: T) -> T { a.cs_wrapping_mul(b) }

/// C# `-a` in the default (unchecked) context: wraps, so `-int.MinValue` is
/// `int.MinValue`.
#[inline]
pub fn unchecked_neg<T: CsInt>(a: T) -> T { a.cs_wrapping_neg() }

/// C# `checked(a + b)`: throws `OverflowException`, so this panics.
#[inline]
pub fn checked_add<T: CsInt>(a: T, b: T) -> T {
    match a.cs_checked_add(b) { Some(v) => v, None => overflowed("+") }
}

/// C# `checked(a - b)`: throws `OverflowException`, so this panics.
#[inline]
pub fn checked_sub<T: CsInt>(a: T, b: T) -> T {
    match a.cs_checked_sub(b) { Some(v) => v, None => overflowed("-") }
}

/// C# `checked(a * b)`: throws `OverflowException`, so this panics.
#[inline]
pub fn checked_mul<T: CsInt>(a: T, b: T) -> T {
    match a.cs_checked_mul(b) { Some(v) => v, None => overflowed("*") }
}

/// C# `checked(-a)`: throws `OverflowException`, so this panics.
#[inline]
pub fn checked_neg<T: CsInt>(a: T) -> T {
    match a.cs_checked_neg() { Some(v) => v, None => overflowed("-") }
}

/// C# `a << count`. The count is masked to the width of `a`.
#[inline]
pub fn shl<T: CsInt>(a: T, count: u32) -> T { a.cs_shl(count) }

/// C# `a >> count`. The count is masked to the width of `a`.
#[inline]
pub fn shr<T: CsInt>(a: T, count: u32) -> T { a.cs_shr(count) }

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unchecked_add_wraps_where_rust_debug_panics() {
        // C#: `unchecked { int.MaxValue + 1 }` == int.MinValue. Rust's `+`
        // panics here under a debug profile, which is a behaviour change the
        // trace oracle would report as a crash rather than as a divergence.
        assert_eq!(unchecked_add(i32::MAX, 1), i32::MIN);
        assert_eq!(unchecked_add(u8::MAX, 1u8), 0);
        assert_eq!(unchecked_sub(0u32, 1), u32::MAX);
        assert_eq!(unchecked_mul(u16::MAX, 2u16), u16::MAX - 1);
    }

    #[test]
    fn unchecked_neg_of_min_is_min() {
        // The one negation C# and Rust disagree about.
        assert_eq!(unchecked_neg(i32::MIN), i32::MIN);
    }

    #[test]
    fn checked_add_in_range_is_the_ordinary_answer() {
        assert_eq!(checked_add(2i32, 3), 5);
        assert_eq!(checked_mul(1000u64, 1000), 1_000_000);
    }

    #[test]
    #[should_panic(expected = "System.OverflowException")]
    fn checked_add_overflow_names_the_csharp_exception() {
        // C# `checked { int.MaxValue + 1 }` throws OverflowException. The
        // panic message names it so translated code says which C# behaviour
        // it was reproducing.
        let _ = checked_add(i32::MAX, 1);
    }

    #[test]
    #[should_panic(expected = "System.OverflowException")]
    fn checked_sub_underflow_panics() {
        let _ = checked_sub(0u32, 1);
    }

    #[test]
    #[should_panic(expected = "System.OverflowException")]
    fn checked_mul_overflow_panics() {
        let _ = checked_mul(u16::MAX, 2u16);
    }

    #[test]
    #[should_panic(expected = "System.OverflowException")]
    fn checked_neg_of_min_panics() {
        let _ = checked_neg(i32::MIN);
    }

    #[test]
    fn shift_count_is_masked_to_five_bits_for_32_bit() {
        // ECMA-334 §12.11: the count is the low-order FIVE bits for int/uint.
        // So C# `1 << 32` is 1, not 0 -- and Rust's `1i32 << 32` is a debug
        // panic, so the plain operator is not a translation of this.
        assert_eq!(shl(1i32, 32), 1);
        assert_eq!(shl(1u32, 33), 2);
        assert_eq!(shr(0x8000_0000u32, 32), 0x8000_0000);
    }

    #[test]
    fn shift_count_is_masked_to_six_bits_for_64_bit() {
        assert_eq!(shl(1u64, 64), 1);
        assert_eq!(shl(1u64, 65), 2);
        assert_eq!(shr(1u64 << 63, 64), 1u64 << 63);
    }

    #[test]
    fn negative_shift_count_takes_the_same_low_bits_csharp_takes() {
        // C# `1 << -1` is `1 << 31`, because -1's low five bits are 11111.
        // A negative count reaches here as its two's-complement u32.
        assert_eq!(shl(1u32, (-1i32) as u32), 1u32 << 31);
        assert_eq!(shl(1u64, (-1i32) as u32), 1u64 << 63);
    }

    #[test]
    fn right_shift_keeps_the_sign_rule_both_languages_share() {
        // Arithmetic for signed, logical for unsigned -- the same in C# and
        // Rust, so only the mask needed a runtime function.
        assert_eq!(shr(-8i32, 1), -4);
        assert_eq!(shr(0x8000_0000u32, 1), 0x4000_0000);
    }

    #[test]
    fn ordinary_shifts_are_unchanged() {
        // The overwhelmingly common case must be identical to the operator,
        // or routing every shift through here would itself be a deviation.
        for n in 0..32u32 {
            assert_eq!(shl(1u32, n), 1u32 << n);
            assert_eq!(shr(0xDEAD_BEEFu32, n), 0xDEAD_BEEFu32 >> n);
        }
    }
}
