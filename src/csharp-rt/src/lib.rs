//! Runtime support for translated C#.
//!
//! Types that C# has and Rust does not, needed so a translation can be faithful
//! rather than approximate. Nothing here knows what is being translated: no
//! peripheral, no register, no emulator. It is the C#-to-Rust analogue of
//! IL2CPP's `libil2cpp` — the part of the source language that has to exist
//! somewhere once the syntax is gone.
//!
//! A type earns its place here only when the approximation is *observably*
//! different. `Queue<T>` does not: `VecDeque` matches it. `T[,]` does, and the
//! reason is below.

#![forbid(unsafe_code)]

use std::fmt;

/// A C# rectangular array, `T[,]`.
///
/// The obvious mapping is `Vec<Vec<T>>`, and it is wrong in three ways that
/// only one of which is cosmetic:
///
/// 1. **Raggedness becomes possible.** C# fixes every row at the same length
///    when the array is created and the type system enforces it. `Vec<Vec<T>>`
///    permits rows of differing length, so a translation bug can produce a
///    shape the source could not represent — and it is legal Rust, so nothing
///    catches it.
/// 2. **Initialisation differs.** `new string[3, 4]` yields twelve usable
///    slots immediately. `Vec<Vec<T>>` starts empty, so unless every emitted
///    construction remembers to fill it, the first index panics. That is a
///    correctness trap that depends on an emitter rule being remembered.
/// 3. **Layout differs** — one allocation versus N+1. Cosmetic here, since
///    nothing in this corpus depends on layout, but it is the reason the other
///    two follow.
///
/// So this is one flat `Vec` plus the row width (the *stride*), with indexing
/// computed the way C# computes it. Raggedness is unrepresentable, and the
/// constructor forces initialisation.
#[derive(Clone, PartialEq, Eq)]
pub struct Array2D<T> {
    data: Vec<T>,
    rows: usize,
    cols: usize,
}

impl<T: Clone + Default> Array2D<T> {
    /// `new T[rows, cols]` — every slot initialised, as C# does.
    pub fn new(rows: usize, cols: usize) -> Self {
        Self { data: vec![T::default(); rows * cols], rows, cols }
    }
}

impl<T> Array2D<T> {
    /// `a.GetLength(0)`.
    pub fn rows(&self) -> usize {
        self.rows
    }

    /// `a.GetLength(1)`. This is the stride: the distance between rows.
    pub fn cols(&self) -> usize {
        self.cols
    }

    /// `a.Length` — the TOTAL element count, which is what C# returns for a
    /// rectangular array, not the row count.
    pub fn len(&self) -> usize {
        self.data.len()
    }

    pub fn is_empty(&self) -> bool {
        self.data.is_empty()
    }

    fn offset(&self, row: usize, col: usize) -> usize {
        assert!(row < self.rows && col < self.cols,
                "index [{row}, {col}] out of bounds for {}x{}", self.rows, self.cols);
        row * self.cols + col
    }

    /// `a[row, col]`. Panics out of bounds, as C# throws.
    pub fn get(&self, row: usize, col: usize) -> &T {
        &self.data[self.offset(row, col)]
    }

    /// `a[row, col] = v`.
    pub fn set(&mut self, row: usize, col: usize, value: T) {
        let i = self.offset(row, col);
        self.data[i] = value;
    }

    pub fn get_mut(&mut self, row: usize, col: usize) -> &mut T {
        let i = self.offset(row, col);
        &mut self.data[i]
    }

    /// Row-major iteration, the order C# enumerates a rectangular array in.
    pub fn iter(&self) -> impl Iterator<Item = &T> {
        self.data.iter()
    }
}

impl<T: Clone + Default> Default for Array2D<T> {
    /// A zero-sized array, so a `#[derive(Default)]` state struct works.
    fn default() -> Self {
        Self { data: Vec::new(), rows: 0, cols: 0 }
    }
}

impl<T: fmt::Debug> fmt::Debug for Array2D<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Array2D({}x{}){:?}", self.rows, self.cols, self.data)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_initialises_every_slot_like_csharp() {
        // `new int[3, 4]` is immediately usable -- the trap Vec<Vec<T>> sets.
        let a: Array2D<i32> = Array2D::new(3, 4);
        assert_eq!(a.len(), 12);
        for r in 0..3 {
            for c in 0..4 {
                assert_eq!(*a.get(r, c), 0);
            }
        }
    }

    #[test]
    fn length_is_total_elements_not_rows() {
        // C# `a.Length` on a rectangular array is rows*cols, which is the one
        // most likely to be mistranslated from a jagged shape.
        let a: Array2D<u8> = Array2D::new(3, 4);
        assert_eq!(a.len(), 12);
        assert_eq!(a.rows(), 3);
        assert_eq!(a.cols(), 4);
    }

    #[test]
    fn indexing_matches_row_major_stride() {
        let mut a: Array2D<i32> = Array2D::new(2, 3);
        a.set(1, 2, 42);
        assert_eq!(*a.get(1, 2), 42);
        // row-major: [1,2] is the last element
        assert_eq!(a.iter().copied().collect::<Vec<_>>(), vec![0, 0, 0, 0, 0, 42]);
    }

    #[test]
    #[should_panic(expected = "out of bounds")]
    fn out_of_bounds_panics_as_csharp_throws() {
        let a: Array2D<i32> = Array2D::new(2, 2);
        let _ = a.get(2, 0);
    }

    #[test]
    fn default_is_empty_so_derived_state_structs_work() {
        let a: Array2D<i32> = Array2D::default();
        assert!(a.is_empty());
        assert_eq!(a.rows(), 0);
    }
}
