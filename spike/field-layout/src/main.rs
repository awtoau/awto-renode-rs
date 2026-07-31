//! D2 layout comparison for issue #3 (P1). Throwaway measurement, not emulator code.
//!
//! PLAN.md claims register fields should be `Cell` in a contiguous arena rather
//! than one `Rc<RefCell<_>>` per field, on cache grounds. That claim is
//! unmeasured. This measures it.
//!
//! The workload is taken from the real bottleneck: `awto_rtc_measure_lsi()`
//! spins on `TIM5->SR` up to 500,000 times per edge across 130 edges -- order
//! 65M reads of ONE flag field. That is the hot pattern, so it is `poll_one`
//! below. `scan_all` covers ordinary register traffic across many fields, and
//! `poll_with_writes` covers a poll loop where a timer callback mutates other
//! fields in between (which is what actually happens).
//!
//! Fairness notes, because a rigged benchmark is worse than none:
//!   - The Rc variant allocates fields INTERLEAVED with decoy allocations, so
//!     they land scattered across the heap the way real peripheral construction
//!     leaves them. Allocating them back-to-back would hand Rc the arena's
//!     locality for free and understate the difference.
//!   - Both variants go through the same handle-indirection shape: peripheral
//!     holds a handle, reads through it.
//!   - Both use `black_box` on inputs and outputs so nothing is optimised away.
//!   - RCC defines ~240 fields, so FIELD_COUNT is 240.

use std::cell::{Cell, RefCell};
use std::hint::black_box;
use std::rc::Rc;
use std::time::Instant;

/// Fields defined by STM32F4_RCC -- the largest in the F427 corpus (240 `With*`
/// calls in 404 lines).
const FIELD_COUNT: usize = 240;

/// Reads per measurement. ~65M is the real LSI figure; 20M keeps each variant
/// under a few seconds while staying far above cache-warmup noise.
const READS: usize = 20_000_000;

// ---------------------------------------------------------------------------
// Variant A: one Rc<RefCell<u64>> per field, scattered across the heap.
// ---------------------------------------------------------------------------

struct RcFields {
    fields: Vec<Rc<RefCell<u64>>>,
    /// Kept alive so the decoys are not freed, which would let the allocator
    /// coalesce and accidentally give the fields locality they would not have.
    _decoys: Vec<Rc<RefCell<[u64; 4]>>>,
}

impl RcFields {
    fn new() -> Self {
        let mut fields = Vec::with_capacity(FIELD_COUNT);
        let mut decoys = Vec::with_capacity(FIELD_COUNT * 3);
        for i in 0..FIELD_COUNT {
            // Interleave decoys so field allocations are spread out, as they are
            // when a peripheral's constructor allocates fields amongst
            // registers, callbacks, closures and name strings.
            for _ in 0..3 {
                decoys.push(Rc::new(RefCell::new([i as u64; 4])));
            }
            fields.push(Rc::new(RefCell::new(i as u64)));
        }
        Self { fields, _decoys: decoys }
    }

    #[inline(always)]
    fn get(&self, id: usize) -> u64 {
        *self.fields[id].borrow()
    }

    #[inline(always)]
    fn set(&self, id: usize, v: u64) {
        *self.fields[id].borrow_mut() = v;
    }
}

// ---------------------------------------------------------------------------
// Variant B: contiguous Cell arena, handle is a typed index.
// ---------------------------------------------------------------------------

#[derive(Copy, Clone)]
struct FieldId(u16);

struct CellFields {
    fields: Vec<Cell<u64>>,
}

impl CellFields {
    fn new() -> Self {
        Self { fields: (0..FIELD_COUNT).map(|i| Cell::new(i as u64)).collect() }
    }

    #[inline(always)]
    fn get(&self, id: FieldId) -> u64 {
        self.fields[id.0 as usize].get()
    }

    #[inline(always)]
    fn set(&self, id: FieldId, v: u64) {
        self.fields[id.0 as usize].set(v);
    }
}

/// Variant C: Rc<Cell<u64>> -- scattered heap allocation and pointer
/// indirection like variant A, but NO borrow flag. This discriminates between
/// the two candidate explanations for A being slow:
///   if C is close to B (Cell arena) -> the borrow flag is the cost
///   if C is close to A (Rc<RefCell>) -> the pointer chase / locality is
struct RcCellFields {
    fields: Vec<Rc<Cell<u64>>>,
    _decoys: Vec<Rc<RefCell<[u64; 4]>>>,
}

impl RcCellFields {
    fn new(n: usize) -> Self {
        let mut fields = Vec::with_capacity(n);
        let mut decoys = Vec::with_capacity(n * 3);
        for i in 0..n {
            for _ in 0..3 {
                decoys.push(Rc::new(RefCell::new([i as u64; 4])));
            }
            fields.push(Rc::new(Cell::new(i as u64)));
        }
        Self { fields, _decoys: decoys }
    }
    #[inline(always)]
    fn get(&self, id: usize) -> u64 {
        self.fields[id].get()
    }
}

/// Same two layouts, sized at construction, for the whole-system working set.
struct RcFieldsN {
    fields: Vec<Rc<RefCell<u64>>>,
    _decoys: Vec<Rc<RefCell<[u64; 4]>>>,
}

impl RcFieldsN {
    fn new(n: usize) -> Self {
        let mut fields = Vec::with_capacity(n);
        let mut decoys = Vec::with_capacity(n * 3);
        for i in 0..n {
            for _ in 0..3 {
                decoys.push(Rc::new(RefCell::new([i as u64; 4])));
            }
            fields.push(Rc::new(RefCell::new(i as u64)));
        }
        Self { fields, _decoys: decoys }
    }
    #[inline(always)]
    fn get(&self, id: usize) -> u64 {
        *self.fields[id].borrow()
    }
}

struct CellFieldsN {
    fields: Vec<Cell<u64>>,
}

impl CellFieldsN {
    fn new(n: usize) -> Self {
        Self { fields: (0..n).map(|i| Cell::new(i as u64)).collect() }
    }
    #[inline(always)]
    fn get(&self, id: usize) -> u64 {
        self.fields[id].get()
    }
}

// ---------------------------------------------------------------------------
// Workloads
// ---------------------------------------------------------------------------

fn time_it<F: FnMut() -> u64>(reads: usize, f: &mut F) -> f64 {
    let t0 = Instant::now();
    let mut acc = 0u64;
    for _ in 0..reads {
        acc = acc.wrapping_add(f());
    }
    let dt = t0.elapsed().as_secs_f64();
    black_box(acc);
    dt
}

/// A fixed ns/read threshold is the wrong hoisting detector -- an L1-resident
/// indexed load genuinely retires in ~2 cycles, so "too fast" is not evidence.
/// The real test is LINEARITY: if the loop body actually runs, doubling the
/// iteration count must roughly double the time. A hoisted loop does not.
fn bench<F: FnMut() -> u64>(name: &str, variant: &str, reads: usize, mut f: F) -> f64 {
    for _ in 0..(reads / 100).max(1000) {
        black_box(f());
    }
    let half = time_it(reads / 2, &mut f);
    let full = time_it(reads, &mut f);
    let linearity = if half > 0.0 { full / half } else { 0.0 };
    // Expect ~2.0. Below 1.6 means the body is not scaling with the loop.
    let flag = if linearity < 1.6 { "  <-- SUSPECT: not linear, likely hoisted" } else { "" };
    let per_sec = reads as f64 / full;
    println!("{name:<18} {variant:<12} {:>8.4} s  {:>10.1} M reads/s  {:>6.2} ns/read   x{:.2}{}",
             full, per_sec / 1e6, full * 1e9 / reads as f64, linearity, flag);
    per_sec
}

fn main() {
    println!("D2 register-field layout comparison  (issue #3 / P1)");
    println!("{FIELD_COUNT} fields, {} M reads per measurement\n", READS / 1_000_000);
    println!("{:<18} {:<12} {:>10} {:>17} {:>13}", "workload", "variant", "time", "throughput", "latency");
    println!("{}", "-".repeat(74));

    let rc = RcFields::new();
    let cell = CellFields::new();

    // 1. poll_one -- the real LSI pattern: hammer a single flag field.
    let id = black_box(37usize);
    let a = bench("poll_one", "Rc<RefCell>", READS, || black_box(&rc).get(black_box(id)));
    let b = bench("poll_one", "Cell arena", READS, || black_box(&cell).get(FieldId(black_box(id) as u16)));
    let rc_cell = RcCellFields::new(FIELD_COUNT);
    let c = bench("poll_one", "Rc<Cell>", READS, || black_box(&rc_cell).get(black_box(id)));
    let poll_ratio = b / a;
    let nocell_ratio = c / a;
    println!();

    // 2. scan_all -- ordinary register traffic touching every field in turn.
    let mut i = 0usize;
    let a2 = bench("scan_all", "Rc<RefCell>", READS, || {
        i = (i + 1) % FIELD_COUNT;
        black_box(&rc).get(black_box(i))
    });
    let mut j = 0usize;
    let b2 = bench("scan_all", "Cell arena", READS, || {
        j = (j + 1) % FIELD_COUNT;
        black_box(&cell).get(FieldId(black_box(j) as u16))
    });
    let scan_ratio = b2 / a2;
    println!();

    // 3. poll_with_writes -- a poll loop with another field mutated every 16th
    //    iteration, which is what a timer callback does mid-poll.
    let mut k = 0usize;
    let a3 = bench("poll_with_writes", "Rc<RefCell>", READS, || {
        k += 1;
        if k % 16 == 0 {
            black_box(&rc).set(k % FIELD_COUNT, k as u64);
        }
        black_box(&rc).get(black_box(id))
    });
    let mut m = 0usize;
    let b3 = bench("poll_with_writes", "Cell arena", READS, || {
        m += 1;
        if m % 16 == 0 {
            black_box(&cell).set(FieldId((m % FIELD_COUNT) as u16), m as u64);
        }
        black_box(&cell).get(FieldId(black_box(id) as u16))
    });
    let mixed_ratio = b3 / a3;

    // 4. whole_system -- 22 peripherals' worth of fields, accessed in a
    //    scattered order. 240 fields fits L1 either way, so the cache argument
    //    can only be tested at a working set that does not.
    println!();
    const SYS_FIELDS: usize = 22 * 90;
    let rc_sys = RcFieldsN::new(SYS_FIELDS);
    let cell_sys = CellFieldsN::new(SYS_FIELDS);
    // Stride by a large odd number so accesses hop across cache lines.
    let mut p = 0usize;
    let a4 = bench("whole_system", "Rc<RefCell>", READS, || {
        p = (p + 1013) % SYS_FIELDS;
        black_box(&rc_sys).get(black_box(p))
    });
    let mut q = 0usize;
    let b4 = bench("whole_system", "Cell arena", READS, || {
        q = (q + 1013) % SYS_FIELDS;
        black_box(&cell_sys).get(black_box(q))
    });
    let sys_ratio = b4 / a4;

    println!("\n{}", "=".repeat(74));
    println!("Cell arena vs Rc<RefCell>, speedup (>1 means Cell is faster):");
    println!("  poll_one          {poll_ratio:>6.2}x   <- the LSI pattern, the one that matters");
    println!("    of which Rc<Cell> (scattered, no borrow flag) gets {nocell_ratio:>5.2}x");
    println!("  scan_all          {scan_ratio:>6.2}x");
    println!("  poll_with_writes  {mixed_ratio:>6.2}x");
    println!("  whole_system      {sys_ratio:>6.2}x   <- {SYS_FIELDS} fields, exceeds L1 for Rc");
    println!();
    println!("Memory: Rc  = {FIELD_COUNT} allocations, 16 B refcounts + 8 B borrow flag + 8 B payload each");
    println!("        Cell= 1 allocation, {} B contiguous ({} cache lines)",
             FIELD_COUNT * 8, (FIELD_COUNT * 8).div_ceil(64));
}
