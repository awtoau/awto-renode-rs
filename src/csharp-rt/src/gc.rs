//! `Gc<T>` — the C# object graph, in safe Rust. Issue #57, phase 1.
//!
//! C# has one kind of object reference. Rust makes the translator pick one per
//! field — `T`, `&T`, `Box<T>`, `Rc<T>`, `Weak<T>`, an index — and the choice is
//! not local: it depends on who else holds the object and whether the graph
//! comes back round. The corpus measurement is 552 instance fields with 52
//! object-reference edges and 7 cycles in the cut; 15,216 fields, 1,278 edges
//! and 63+ cycles across the whole tree. At 1,278 edges, deciding a direction
//! per edge is not a mechanical translation, and a wrong direction is either a
//! leak or a dangling reference — neither of which a differential oracle sees.
//!
//! This module removes the decision: **every C# reference-typed field becomes
//! `Gc<T>`**, uniformly, and the graph may be as cyclic as the source is.
//!
//! # The API is the deliverable, not the collector
//!
//! If `Gc<T>` is harder to use than `Rc<RefCell<T>>` the argument for it
//! evaporates, so the design was driven backwards from the use sites — see
//! `docs/gc-use-sites.md`, which puts the two side by side on real shapes from
//! the corpus. The short version:
//!
//! | at the use site | `Rc<RefCell<T>>` | `Gc<T>` |
//! |---|---|---|
//! | back-reference to a parent | `Weak`, decided per field | `Gc<T>`, same as any other |
//! | reading through it | `.upgrade().unwrap().borrow()` | `heap[gc]` |
//! | re-entrant call parent → child → parent | **runtime panic** | compiles, cannot panic |
//! | getting the direction wrong | leak, or dangle | not representable |
//!
//! The third row is the one that matters. It is a real path in the corpus, not
//! a hypothetical: a child's transfer routine calls back into its parent's
//! interrupt update while the parent is already on the stack. Under
//! `Rc<RefCell<T>>` that is `already mutably borrowed`, at run time, on a path
//! no type check covers.
//!
//! # Why the heap is a parameter
//!
//! `Gc<T>` is an index, and an index needs its arena. There are two ways to
//! reach one: pass it, or find it ambiently in a thread-local. **Ambient access
//! is impossible without `unsafe`** — handing out `&T` from inside a
//! `thread_local!` needs either a raw pointer or a `RefCell` guard, and the
//! guard puts the borrow flag (and its panic) straight back. So the heap is
//! threaded, exactly as `safe-gc` threads it, and exactly as this project's
//! emitter already threads its field bank and state through every translated
//! method. The shape is not new; one more parameter joins two that are already
//! there.
//!
//! That parameter is also what makes re-entrancy safe: `&Heap` is a *shared*
//! borrow, and shared borrows nest. Mutation happens through `Cell`/`RefCell`
//! *inside* the object — decision D2's reasoning, applied to the object graph
//! rather than to fields: a `Cell` has no borrow flag, so re-entrant access
//! cannot panic.
//!
//! # Rooting, and the cost that was refused
//!
//! Every surveyed collector pays its cost in rooting discipline, and that is the
//! part that could make the port *less* mechanical. Two things keep it small
//! here:
//!
//! 1. **Roots are explicit and few.** `add_root` / `remove_root`, no RAII guard.
//!    An RAII `Root<T>` needs a back-pointer to the root set, which means `Rc`
//!    in the `Heap`, which makes `Heap: !Send` — and D3 wants a machine movable
//!    to a worker thread for N-instance test parallelism. A handful of roots
//!    that live for the process do not justify giving that up. The cost is that
//!    forgetting `remove_root` leaks; it is stated here rather than hidden.
//! 2. **Collection is explicit.** Nothing collects behind your back, so a `Gc`
//!    in a local cannot go stale between two statements. `collect()` needs
//!    `&mut Heap`, which the borrow checker only grants when no reference into
//!    the heap is outstanding.
//!
//! A `Gc` that *does* go stale — held across a `collect()` that freed it — is
//! caught: slots carry a generation counter, and a mismatched generation panics
//! with a message that says so. It is never a silent read of a recycled object.
//!
//! # `forbid(unsafe_code)`
//!
//! Inherited from the crate root. `safe-gc` (Fitzgerald) proved an
//! arena-plus-indices collector needs no `unsafe`, and its author is equally
//! plain that such a collector "is not a particularly high-performance garbage
//! collector". Both halves are taken at face value: this is the safe design, and
//! it is not fast. The measured budget it has to fit in is ~409 ns per bus
//! access, against which an indexed load and a `TypeId` lookup are noise — but
//! that is an argument for *this corpus*, not a general claim.
//!
//! # Determinism
//!
//! Arenas live in a `BTreeMap` keyed by `TypeId` so iteration order is fixed
//! within a run. `TypeId` values are not stable across compilations, so sweep
//! order is not either; nothing observable depends on it, because translated
//! objects have no `Drop` behaviour. If that ever changes, this is the note that
//! says why it broke.

use std::any::{Any, TypeId};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::marker::PhantomData;
use std::ops::{Index, IndexMut};

/// An untyped edge: what the tracer collects and what the root set holds.
///
/// Ordered so the root set is a `BTreeSet` and iteration is deterministic.
#[derive(Copy, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Debug)]
pub struct GcRaw {
    ty: TypeId,
    slot: u32,
    gen: u32,
}

/// A reference to a garbage-collected `T`. The mapping for a C# reference-typed
/// field.
///
/// `Copy`, like the C# reference it stands for: assigning one does not move or
/// clone the object, and there is no refcount traffic on the write. It carries
/// no lifetime, so it can be stored in a struct that the object it points at
/// also points back at — which is the whole point.
///
/// Reaching the object needs the [`Heap`]: `heap[gc]`, or [`Heap::get`].
pub struct Gc<T: 'static> {
    slot: u32,
    gen: u32,
    /// `fn() -> T` rather than `T`: makes `Gc<T>` unconditionally `Send`/`Sync`
    /// and `Copy` regardless of `T`, which is right — it is an index, not a
    /// reference, and it grants no access to a `T` on its own.
    _t: PhantomData<fn() -> T>,
}

/// The null slot. `u32::MAX` rather than 0 so that a zeroed or `Default` handle
/// is null instead of pointing at the first object ever allocated.
const NULL_SLOT: u32 = u32::MAX;

impl<T: 'static> Gc<T> {
    /// C# `null`.
    ///
    /// C# reference fields start null and throw `NullReferenceException` on
    /// dereference; under D4 that is a panic. Representing null rather than
    /// forbidding it is deliberate: it keeps the translation faithful, and a
    /// `null` check in the source (`if(x != null)`) maps to [`Gc::is_null`]
    /// instead of needing nullability analysis the corpus does not yet carry.
    ///
    /// Where Roslyn's nullability annotation says a field cannot be null,
    /// `Option<Gc<T>>` is the stronger mapping and the rule records it as the
    /// refinement to make once that annotation is ingested.
    pub const fn null() -> Self {
        Self { slot: NULL_SLOT, gen: 0, _t: PhantomData }
    }

    pub const fn is_null(self) -> bool {
        self.slot == NULL_SLOT
    }

    fn raw(self) -> GcRaw {
        GcRaw { ty: TypeId::of::<T>(), slot: self.slot, gen: self.gen }
    }
}

impl<T: 'static> Clone for Gc<T> {
    fn clone(&self) -> Self {
        *self
    }
}
impl<T: 'static> Copy for Gc<T> {}
impl<T: 'static> PartialEq for Gc<T> {
    /// C# reference equality: same object, or both null.
    fn eq(&self, other: &Self) -> bool {
        self.slot == other.slot && self.gen == other.gen
    }
}
impl<T: 'static> Eq for Gc<T> {}
impl<T: 'static> std::hash::Hash for Gc<T> {
    fn hash<H: std::hash::Hasher>(&self, h: &mut H) {
        self.slot.hash(h);
        self.gen.hash(h);
    }
}
impl<T: 'static> Default for Gc<T> {
    /// Null, so a `#[derive(Default)]` state struct holding one compiles and
    /// behaves as C# does before the constructor assigns it.
    fn default() -> Self {
        Self::null()
    }
}
impl<T: 'static> fmt::Debug for Gc<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.is_null() {
            write!(f, "Gc(null)")
        } else {
            write!(f, "Gc(#{}.{})", self.slot, self.gen)
        }
    }
}

/// Collects the outgoing edges of one object.
///
/// Handed to [`Trace::trace`]. Deliberately write-only: an implementation can
/// report edges and cannot read the heap, so `trace` cannot recurse and cannot
/// deadlock the borrow it was called under.
pub struct Tracer {
    out: Vec<GcRaw>,
}

impl Tracer {
    /// Report one outgoing reference. Null handles are skipped.
    pub fn edge<T: 'static>(&mut self, gc: Gc<T>) {
        if !gc.is_null() {
            self.out.push(gc.raw());
        }
    }
}

/// What a heap-allocated type must tell the collector.
///
/// One method, and the emitter can generate it from the field list alone: every
/// `Gc<_>` field becomes one `t.edge(...)`, every field of a type that itself
/// contains handles forwards to its own `trace`. There is no judgement in it,
/// which is what keeps it mechanical.
///
/// **Missing an edge is unsound in the memory-safety-adjacent sense**: the
/// object it pointed at can be collected while still referenced, and the next
/// access panics on the generation check. That is a loud failure rather than a
/// silent one, but it is still a failure, so the impl is generated rather than
/// written.
pub trait Trace: 'static {
    fn trace(&self, tracer: &mut Tracer);
}

/// `impl Trace` for types that contain no references — every primitive, and any
/// translated value type.
#[macro_export]
macro_rules! impl_trace_leaf {
    ($($t:ty),* $(,)?) => {$(
        impl $crate::Trace for $t {
            fn trace(&self, _: &mut $crate::Tracer) {}
        }
    )*};
}

impl_trace_leaf!(
    (), bool, char, String,
    i8, i16, i32, i64, i128, isize,
    u8, u16, u32, u64, u128, usize,
    f32, f64,
);

impl<T: 'static> Trace for Gc<T> {
    fn trace(&self, tracer: &mut Tracer) {
        tracer.edge(*self);
    }
}

impl<T: Trace> Trace for Option<T> {
    fn trace(&self, tracer: &mut Tracer) {
        if let Some(v) = self {
            v.trace(tracer);
        }
    }
}

impl<T: Trace> Trace for Vec<T> {
    fn trace(&self, tracer: &mut Tracer) {
        for v in self {
            v.trace(tracer);
        }
    }
}

impl<T: Trace> Trace for Box<T> {
    fn trace(&self, tracer: &mut Tracer) {
        (**self).trace(tracer);
    }
}

impl<T: Trace + Copy> Trace for std::cell::Cell<T> {
    /// A `Cell` field is how a translated object mutates through `&Heap` — the
    /// D2 pattern applied to the object graph. Tracing reads a copy, so no
    /// borrow is held.
    fn trace(&self, tracer: &mut Tracer) {
        self.get().trace(tracer);
    }
}

impl<T: Trace> Trace for std::cell::RefCell<T> {
    /// Cannot panic in practice: `collect` takes `&mut Heap`, so no `Ref` into
    /// any object can be outstanding when this runs.
    fn trace(&self, tracer: &mut Tracer) {
        self.borrow().trace(tracer);
    }
}

impl<T: Trace, const N: usize> Trace for [T; N] {
    fn trace(&self, tracer: &mut Tracer) {
        for v in self {
            v.trace(tracer);
        }
    }
}

impl<T: Trace + Clone + Default> Trace for crate::Array2D<T> {
    fn trace(&self, tracer: &mut Tracer) {
        for v in self.iter() {
            v.trace(tracer);
        }
    }
}

struct Slot<T> {
    value: Option<T>,
    /// Bumped when the slot is freed, so a handle kept across a collection
    /// fails loudly instead of reading whatever was allocated next.
    gen: u32,
    marked: bool,
}

struct Arena<T> {
    slots: Vec<Slot<T>>,
    free: Vec<u32>,
}

impl<T> Arena<T> {
    fn new() -> Self {
        Self { slots: Vec::new(), free: Vec::new() }
    }
}

/// The object-independent half of an arena, so `Heap` can hold arenas of
/// differing `T` in one map and still mark, trace and sweep them.
trait ArenaDyn: Any {
    fn as_any(&self) -> &dyn Any;
    fn as_any_mut(&mut self) -> &mut dyn Any;
    /// Mark one slot. `true` if it was live, matched the generation, and was not
    /// already marked — i.e. if its edges still need tracing.
    fn mark(&mut self, slot: u32, gen: u32) -> bool;
    fn trace_slot(&self, slot: u32, out: &mut Tracer);
    /// Free every unmarked slot and clear the marks. Returns how many it freed.
    fn sweep(&mut self) -> usize;
    fn live(&self) -> usize;
}

impl<T: Trace> ArenaDyn for Arena<T> {
    fn as_any(&self) -> &dyn Any {
        self
    }
    fn as_any_mut(&mut self) -> &mut dyn Any {
        self
    }
    fn mark(&mut self, slot: u32, gen: u32) -> bool {
        match self.slots.get_mut(slot as usize) {
            Some(s) if s.value.is_some() && s.gen == gen && !s.marked => {
                s.marked = true;
                true
            }
            _ => false,
        }
    }
    fn trace_slot(&self, slot: u32, out: &mut Tracer) {
        if let Some(Slot { value: Some(v), .. }) = self.slots.get(slot as usize) {
            v.trace(out);
        }
    }
    fn sweep(&mut self) -> usize {
        let mut freed = 0;
        for (i, s) in self.slots.iter_mut().enumerate() {
            if s.marked {
                s.marked = false;
            } else if s.value.is_some() {
                s.value = None;
                s.gen = s.gen.wrapping_add(1);
                self.free.push(i as u32);
                freed += 1;
            }
        }
        freed
    }
    fn live(&self) -> usize {
        self.slots.iter().filter(|s| s.value.is_some()).count()
    }
}

/// What one collection did. Returned so a caller — notably the phase-2 tracer —
/// can record it rather than infer it.
#[derive(Copy, Clone, PartialEq, Eq, Debug, Default)]
pub struct Collected {
    pub freed: usize,
    pub live: usize,
}

/// The arena every [`Gc`] indexes into.
///
/// One arena per concrete type, so slots are homogeneous and no `unsafe`
/// downcast is needed — only `Any`, at the arena granularity rather than per
/// object.
#[derive(Default)]
pub struct Heap {
    arenas: BTreeMap<TypeId, Box<dyn ArenaDyn>>,
    roots: BTreeSet<GcRaw>,
}

impl Heap {
    pub fn new() -> Self {
        Self { arenas: BTreeMap::new(), roots: BTreeSet::new() }
    }

    fn arena<T: Trace>(&self) -> Option<&Arena<T>> {
        self.arenas
            .get(&TypeId::of::<T>())
            .and_then(|a| a.as_any().downcast_ref::<Arena<T>>())
    }

    fn arena_mut<T: Trace>(&mut self) -> &mut Arena<T> {
        self.arenas
            .entry(TypeId::of::<T>())
            .or_insert_with(|| Box::new(Arena::<T>::new()))
            .as_any_mut()
            .downcast_mut::<Arena<T>>()
            .expect("arena is keyed by TypeId::of::<T>, so it holds Arena<T>")
    }

    /// C# `new T(...)`. Reuses a freed slot when there is one, which is what
    /// makes the generation counter necessary.
    pub fn alloc<T: Trace>(&mut self, value: T) -> Gc<T> {
        let arena = self.arena_mut::<T>();
        if let Some(slot) = arena.free.pop() {
            let s = &mut arena.slots[slot as usize];
            s.value = Some(value);
            s.marked = false;
            return Gc { slot, gen: s.gen, _t: PhantomData };
        }
        let slot = u32::try_from(arena.slots.len())
            .expect("more than u32::MAX live objects of one type");
        arena.slots.push(Slot { value: Some(value), gen: 0, marked: false });
        Gc { slot, gen: 0, _t: PhantomData }
    }

    /// Allocate and root in one step — the shape of the one object that is
    /// reachable from outside the heap.
    pub fn alloc_root<T: Trace>(&mut self, value: T) -> Gc<T> {
        let gc = self.alloc(value);
        self.add_root(gc);
        gc
    }

    /// Pin an object and everything it reaches. See the module note on why this
    /// is explicit rather than an RAII guard.
    pub fn add_root<T: 'static>(&mut self, gc: Gc<T>) {
        if !gc.is_null() {
            self.roots.insert(gc.raw());
        }
    }

    /// Unpin. Returns whether it was rooted, so a double-unroot is visible to a
    /// caller that cares rather than silent.
    pub fn remove_root<T: 'static>(&mut self, gc: Gc<T>) -> bool {
        !gc.is_null() && self.roots.remove(&gc.raw())
    }

    pub fn is_root<T: 'static>(&self, gc: Gc<T>) -> bool {
        !gc.is_null() && self.roots.contains(&gc.raw())
    }

    /// `None` for null and for a handle whose object has been collected. The
    /// non-panicking form, for a translated `x != null` test that must not
    /// throw.
    pub fn try_get<T: Trace>(&self, gc: Gc<T>) -> Option<&T> {
        if gc.is_null() {
            return None;
        }
        let s = self.arena::<T>()?.slots.get(gc.slot as usize)?;
        if s.gen != gc.gen {
            return None;
        }
        s.value.as_ref()
    }

    /// Dereference. Panics on null (C# `NullReferenceException`, D4) and on a
    /// handle left over from before a collection.
    pub fn get<T: Trace>(&self, gc: Gc<T>) -> &T {
        assert!(
            !gc.is_null(),
            "null reference: a `Gc<{}>` was dereferenced before it was assigned \
             (C# NullReferenceException)",
            std::any::type_name::<T>()
        );
        let slot = self
            .arena::<T>()
            .and_then(|a| a.slots.get(gc.slot as usize))
            .unwrap_or_else(|| {
                panic!("`Gc<{}>` #{} does not exist in this heap",
                       std::any::type_name::<T>(), gc.slot)
            });
        assert!(
            slot.gen == gc.gen && slot.value.is_some(),
            "`Gc<{}>` #{}.{} was collected; the slot is now generation {}. A \
             handle held across `collect()` must be rooted or re-read.",
            std::any::type_name::<T>(), gc.slot, gc.gen, slot.gen
        );
        slot.value.as_ref().expect("checked above")
    }

    /// Exclusive access, for a field the translated type does not hold in a
    /// `Cell`. Note that taking `&mut Heap` forbids re-entrancy *statically* —
    /// which is why the emitted mapping prefers interior mutability.
    pub fn get_mut<T: Trace>(&mut self, gc: Gc<T>) -> &mut T {
        // Validate through the shared path first so the diagnostics are shared.
        let _ = self.get(gc);
        self.arena_mut::<T>().slots[gc.slot as usize]
            .value
            .as_mut()
            .expect("checked by get")
    }

    /// How many objects of one type are live. The measurement the phase-2
    /// tracer builds on.
    pub fn live_of<T: Trace>(&self) -> usize {
        self.arena::<T>().map_or(0, |a| a.slots.iter().filter(|s| s.value.is_some()).count())
    }

    pub fn live(&self) -> usize {
        self.arenas.values().map(|a| a.live()).sum()
    }

    /// Mark and sweep from the roots.
    ///
    /// Nothing calls this implicitly. A machine that is built once and then
    /// exits never needs to, and that is the expected case; collection exists so
    /// that cycles *can* be reclaimed, and so phase 2 can ask what was
    /// reachable.
    pub fn collect(&mut self) -> Collected {
        let mut work: Vec<GcRaw> = self.roots.iter().copied().collect();
        let mut tracer = Tracer { out: Vec::new() };
        while let Some(r) = work.pop() {
            let Some(arena) = self.arenas.get_mut(&r.ty) else { continue };
            if !arena.mark(r.slot, r.gen) {
                continue; // null, stale, or already seen — the cycle stops here
            }
            // Separate statement, so the `&mut` above has ended: marking and
            // tracing never hold the arena at the same time, which is how this
            // is expressible without `unsafe`.
            let arena = self.arenas.get(&r.ty).expect("just borrowed it");
            arena.trace_slot(r.slot, &mut tracer);
            work.append(&mut tracer.out);
        }
        let freed = self.arenas.values_mut().map(|a| a.sweep()).sum();
        Collected { freed, live: self.live() }
    }
}

impl<T: Trace> Index<Gc<T>> for Heap {
    type Output = T;
    fn index(&self, gc: Gc<T>) -> &T {
        self.get(gc)
    }
}

impl<T: Trace> IndexMut<Gc<T>> for Heap {
    fn index_mut(&mut self, gc: Gc<T>) -> &mut T {
        self.get_mut(gc)
    }
}

impl fmt::Debug for Heap {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Heap({} live, {} root(s), {} arena(s))",
               self.live(), self.roots.len(), self.arenas.len())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    // ----------------------------------------------------------------- basics

    #[derive(Default)]
    struct Leaf {
        n: Cell<u64>,
    }
    impl Trace for Leaf {
        fn trace(&self, _: &mut Tracer) {}
    }

    #[test]
    fn alloc_read_write() {
        let mut h = Heap::new();
        let a = h.alloc_root(Leaf { n: Cell::new(7) });
        assert_eq!(h[a].n.get(), 7);
        h[a].n.set(9); // through `&Heap`: no exclusive borrow needed
        assert_eq!(h[a].n.get(), 9);
    }

    #[test]
    fn default_handle_is_null_like_an_unassigned_csharp_field() {
        let g: Gc<Leaf> = Gc::default();
        assert!(g.is_null());
        assert_eq!(format!("{g:?}"), "Gc(null)");
    }

    #[test]
    #[should_panic(expected = "NullReferenceException")]
    fn dereferencing_null_panics_as_csharp_throws() {
        let h = Heap::new();
        let _ = h.get(Gc::<Leaf>::null());
    }

    #[test]
    fn try_get_is_the_non_throwing_form() {
        let mut h = Heap::new();
        assert!(h.try_get(Gc::<Leaf>::null()).is_none());
        let a = h.alloc_root(Leaf::default());
        assert!(h.try_get(a).is_some());
    }

    #[test]
    fn reference_equality_is_csharp_reference_equality() {
        let mut h = Heap::new();
        let a = h.alloc_root(Leaf::default());
        let b = h.alloc_root(Leaf::default());
        assert_eq!(a, a);
        assert_ne!(a, b);
        assert_eq!(Gc::<Leaf>::null(), Gc::<Leaf>::null());
    }

    // ------------------------------------------------- the cycle Rc would leak

    /// Counts drops so "was it actually reclaimed" is an assertion rather than
    /// a belief.
    #[derive(Default)]
    struct DropCount(std::rc::Rc<Cell<usize>>);
    impl Drop for DropCount {
        fn drop(&mut self) {
            self.0.set(self.0.get() + 1);
        }
    }

    struct Parent {
        children: Vec<Gc<Child>>,
        _d: DropCount,
    }
    struct Child {
        parent: Gc<Parent>,
        _d: DropCount,
    }
    impl Trace for Parent {
        fn trace(&self, t: &mut Tracer) {
            self.children.trace(t);
        }
    }
    impl Trace for Child {
        fn trace(&self, t: &mut Tracer) {
            t.edge(self.parent);
        }
    }

    #[test]
    fn a_cycle_is_collected_once_unrooted() {
        let drops = std::rc::Rc::new(Cell::new(0));
        let mut h = Heap::new();

        let p = h.alloc_root(Parent { children: Vec::new(), _d: DropCount(drops.clone()) });
        for _ in 0..3 {
            let c = h.alloc(Child { parent: p, _d: DropCount(drops.clone()) });
            h[p].children.push(c); // needs &mut: Vec push is not a Cell write
        }
        // Parent -> children -> parent. Four objects, four edges, one cycle per
        // child. This is the corpus's most common object shape.
        assert_eq!(h.live(), 4);
        assert_eq!(h.collect(), Collected { freed: 0, live: 4 });
        assert_eq!(drops.get(), 0);

        h.remove_root(p);
        let c = h.collect();
        assert_eq!(c, Collected { freed: 4, live: 0 });
        assert_eq!(drops.get(), 4, "every object in the cycle was reclaimed");
    }

    #[test]
    fn the_same_shape_leaks_under_rc() {
        // The comparison the issue rests on. Same graph, `Rc<RefCell<_>>`, no
        // `Weak`: nothing is ever dropped, and nothing reports that.
        use std::cell::RefCell;
        use std::rc::Rc;

        struct RcParent {
            children: Vec<Rc<RefCell<RcChild>>>,
            _d: DropCount,
        }
        struct RcChild {
            _parent: Rc<RefCell<RcParent>>,
            _d: DropCount,
        }

        let drops = std::rc::Rc::new(Cell::new(0));
        {
            let p = Rc::new(RefCell::new(RcParent {
                children: Vec::new(),
                _d: DropCount(drops.clone()),
            }));
            for _ in 0..3 {
                let c = Rc::new(RefCell::new(RcChild {
                    _parent: p.clone(),
                    _d: DropCount(drops.clone()),
                }));
                p.borrow_mut().children.push(c);
            }
        } // every `Rc` binding is out of scope here
        assert_eq!(drops.get(), 0,
                   "the cycle keeps every strong count above zero -- this leak is \
                    what D1 accepted deliberately at 7 cycles and what 63+ makes \
                    untenable");
    }

    // --------------------------------------- re-entrancy: the corpus's hard shape

    /// The shape that panics under `Rc<RefCell<T>>`, translated from the
    /// corpus's transfer path: a parent signals a child, the child does its
    /// work, and the child calls back into the parent while the parent is still
    /// on the stack.
    struct Owner {
        parts: Vec<Gc<Part>>,
        interrupt_updates: Cell<u32>,
    }
    struct Part {
        owner: Gc<Owner>,
        id: usize,
        done: Cell<bool>,
    }
    impl Trace for Owner {
        fn trace(&self, t: &mut Tracer) {
            self.parts.trace(t);
        }
    }
    impl Trace for Part {
        fn trace(&self, t: &mut Tracer) {
            t.edge(self.owner);
        }
    }

    fn owner_signal(h: &Heap, this: Gc<Owner>, n: usize) {
        part_run(h, h[this].parts[n]);
    }
    fn part_run(h: &Heap, this: Gc<Part>) {
        h[this].done.set(true);
        // Re-entering the owner. `&Heap` is shared, so this nests.
        owner_update_interrupts(h, h[this].owner);
    }
    fn owner_update_interrupts(h: &Heap, this: Gc<Owner>) {
        let n = h[this].parts.iter().filter(|p| h[**p].done.get()).count();
        h[this].interrupt_updates.set(h[this].interrupt_updates.get() + n as u32);
    }

    #[test]
    fn parent_child_parent_reentrancy_does_not_panic() {
        let mut h = Heap::new();
        let o = h.alloc_root(Owner { parts: Vec::new(), interrupt_updates: Cell::new(0) });
        for id in 0..3 {
            let p = h.alloc(Part { owner: o, id, done: Cell::new(false) });
            h[o].parts.push(p);
        }
        owner_signal(&h, o, 1);
        assert!(h[h[o].parts[1]].done.get());
        assert_eq!(h[o].interrupt_updates.get(), 1);
        assert_eq!(h[h[o].parts[1]].id, 1);
        // Under `Rc<RefCell<_>>` the equivalent call chain is
        // `o.borrow_mut() -> p.borrow_mut() -> o.borrow_mut()`, which panics
        // here with "already mutably borrowed".
    }

    // --------------------------------------------------- stale handles are loud

    #[test]
    #[should_panic(expected = "was collected")]
    fn a_handle_held_across_a_collection_panics_rather_than_aliasing() {
        let mut h = Heap::new();
        let a = h.alloc(Leaf { n: Cell::new(1) });
        h.collect(); // `a` was never rooted
        let _ = h.get(a);
    }

    #[test]
    fn a_recycled_slot_does_not_answer_to_the_old_handle() {
        let mut h = Heap::new();
        let a = h.alloc(Leaf { n: Cell::new(1) });
        h.collect();
        let b = h.alloc_root(Leaf { n: Cell::new(2) }); // reuses a's slot
        assert_ne!(a, b);
        assert!(h.try_get(a).is_none(), "the generation counter separates them");
        assert_eq!(h[b].n.get(), 2);
    }

    // ------------------------------------------------------------- book-keeping

    #[test]
    fn roots_are_explicit_and_removable() {
        let mut h = Heap::new();
        let a = h.alloc(Leaf::default());
        assert!(!h.is_root(a));
        h.add_root(a);
        assert!(h.is_root(a));
        assert_eq!(h.collect().live, 1);
        assert!(h.remove_root(a));
        assert!(!h.remove_root(a), "removing twice is visible, not silent");
        assert_eq!(h.collect(), Collected { freed: 1, live: 0 });
    }

    #[test]
    fn arenas_are_per_type_so_handles_do_not_confuse() {
        let mut h = Heap::new();
        let l = h.alloc_root(Leaf { n: Cell::new(5) });
        let o = h.alloc_root(Owner { parts: Vec::new(), interrupt_updates: Cell::new(0) });
        // Same slot number, different arena, no confusion.
        assert_eq!(h.live_of::<Leaf>(), 1);
        assert_eq!(h.live_of::<Owner>(), 1);
        assert_eq!(h[l].n.get(), 5);
        assert_eq!(h[o].interrupt_updates.get(), 0);
        assert_eq!(h.live(), 2);
    }

    #[test]
    fn tracing_terminates_on_a_self_reference() {
        struct SelfRef {
            me: Cell<Gc<SelfRef>>,
        }
        impl Trace for SelfRef {
            fn trace(&self, t: &mut Tracer) {
                t.edge(self.me.get());
            }
        }
        let mut h = Heap::new();
        let a = h.alloc_root(SelfRef { me: Cell::new(Gc::null()) });
        h[a].me.set(a);
        assert_eq!(h.collect(), Collected { freed: 0, live: 1 });
    }
}
