//! An oracle tier that can observe INTERLEAVING. Issue #52.
//!
//! # Why this exists
//!
//! Tier-2 replay feeds recorded register accesses through a single-threaded
//! loop, so a threading difference cannot appear in it *by construction*. That
//! is not a gap in the traces; it is a property of the tier. For the lock sites
//! the converter emits, "the oracle passes" is therefore evidence of nothing,
//! and #52 asks for a tier that is not blind in that direction.
//!
//! This is that tier. It does one experiment:
//!
//! > Run the same workload with a lock and without it, over **every**
//! > interleaving, and compare the sets of observable outcomes.
//!
//! If the sets differ, the lock is load-bearing for that workload and deleting
//! it changes behaviour. If they are equal, the lock made no observable
//! difference *to that workload under this model* — a much weaker statement
//! than "the lock is unnecessary", and deliberately not phrased as one.
//!
//! # Deterministic, because a flaky concurrency test is worse than none
//!
//! There are no threads racing and no timing anywhere. Exactly one agent runs
//! at a time; it holds a baton passed over a channel, and the scheduler decides
//! who gets it next. Context switches happen only at declared preemption points
//! ([`Agent::step`]) and at lock acquisition. Exploration is a depth-first walk
//! over the schedule tree, so a run is reproducible from its decision vector
//! and the whole exploration is exhaustive up to the run cap.
//!
//! `sleep` appears nowhere and neither does any duration.
//!
//! # What it can see, and what it cannot
//!
//! It sees **atomicity violations**: a critical section observed or mutated
//! part-way through by another agent — lost updates, torn invariants, a state
//! machine caught between two consistent states. Those are what `lock` in the
//! corpus is defending against.
//!
//! It does **not** see memory-model effects: reordering, tearing, missing
//! fences. It cannot, because it never lets two agents run at once, and that is
//! also why it is free of both flakiness and undefined behaviour. A model that
//! serialises execution cannot report a data race that only a weak memory model
//! would produce. Say so rather than let the green tick imply otherwise.
//!
//! Its resolution is bounded by preemption points: **a critical section with no
//! preemption point inside it is unobservable**, and the harness reports that
//! case as [`Verdict::Vacuous`] rather than as agreement. A checker that
//! reports success while verifying nothing has already shipped in this project
//! once; the vacuity guard is the direct answer to it.
//!
//! # What safe Rust already decided
//!
//! `renode-regs` documents that an index-based bank is `Send`, "which `Rc`
//! blocks and which N-instance test parallelism needs". That is true, and it
//! compiles:
//!
//! ```
//! fn assert_send<T: Send>() {}
//! assert_send::<renode_regs::Bank<()>>();
//! ```
//!
//! `Send` moves a whole peripheral to a worker thread. It does **not** let two
//! threads touch one peripheral, and that is the case a lock exists for. The
//! bank's arena is `Vec<Cell<u64>>`, so the bank is not `Sync`, and the
//! compiler rejects the sharing outright:
//!
//! ```compile_fail,E0277
//! fn assert_sync<T: Sync>() {}
//! assert_sync::<renode_regs::Bank<()>>();
//! ```
//!
//! So today a missing lock inside a translated peripheral is not merely
//! untested — it is unrepresentable. Whether that stays true is a design
//! decision, not a fact: [`Shared`] asserts `Sync` under the scheduler's
//! discipline precisely so the experiment can be run anyway.

use std::cell::{RefCell, UnsafeCell};
use std::collections::BTreeSet;
use std::rc::Rc;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};

// ---------------------------------------------------------------------------
// Shared state primitives
// ---------------------------------------------------------------------------

/// A shared cell with no synchronisation at all — what a datum looks like once
/// its lock has been deleted.
///
/// # Safety
///
/// `Sync` is asserted, and the justification is the scheduler, not optimism:
/// exactly one agent ever runs at a time, and every handoff between agents goes
/// through an mpsc channel, which establishes happens-before in both
/// directions. Every access to a `Slot` is therefore totally ordered with every
/// other. What remains observable is the *interleaving* — which is the thing
/// under study — with no data race and no undefined behaviour.
pub struct Slot<T> {
    cell: UnsafeCell<T>,
}

// SAFETY: see the type-level comment. Serialised execution plus channel
// handoffs give a total order over all accesses.
unsafe impl<T: Send> Sync for Slot<T> {}

impl<T> Slot<T> {
    pub fn new(v: T) -> Self {
        Self { cell: UnsafeCell::new(v) }
    }
}

impl<T: Copy> Slot<T> {
    #[inline]
    pub fn get(&self) -> T {
        // SAFETY: no other agent is running; the read cannot overlap a write.
        unsafe { *self.cell.get() }
    }
    #[inline]
    pub fn set(&self, v: T) {
        // SAFETY: as above. The reference does not outlive this statement, so
        // no two `&mut` to the cell are ever live at once.
        unsafe { *self.cell.get() = v }
    }
}

/// Shares a `Send`-but-not-`Sync` value between agents.
///
/// This exists because of a finding rather than a convenience:
/// `renode_regs::Bank` is `Send` and **not** `Sync`, since its field arena is
/// `Vec<Cell<u64>>`. Safe Rust therefore refuses to let two threads touch one
/// peripheral's registers, and no amount of test-writing gets around it. Under
/// the scheduler that refusal is over-strict — one agent runs at a time — so
/// the assertion is made here, once, with the argument attached, instead of
/// being scattered through tests.
///
/// # Safety
///
/// Identical to [`Slot`]: serialised execution and channel handoffs give a
/// total order over accesses.
pub struct Shared<T>(T);

// SAFETY: see the type-level comment.
unsafe impl<T: Send> Sync for Shared<T> {}

impl<T> Shared<T> {
    pub fn new(v: T) -> Self {
        Self(v)
    }
}

impl<T> std::ops::Deref for Shared<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.0
    }
}

// ---------------------------------------------------------------------------
// Scheduler state
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Status {
    Runnable,
    /// Waiting for the lock with this id.
    Blocked(usize),
    Done,
}

#[derive(Default)]
struct SchedState {
    status: Vec<Status>,
    /// Holder of each registered lock, by lock id.
    holders: Vec<Option<usize>>,
    /// How deep each agent is inside a critical section.
    depth: Vec<usize>,
    /// Times the baton went to an agent while a *different* agent was inside a
    /// critical section. This is the anti-vacuity counter: at zero, the
    /// exploration never had the opportunity to observe anything, whatever the
    /// outcomes say.
    interleaved: usize,
}

impl SchedState {
    fn reset(&mut self, agents: usize) {
        self.status = vec![Status::Runnable; agents];
        self.depth = vec![0; agents];
        for h in &mut self.holders {
            *h = None;
        }
        self.interleaved = 0;
    }

    fn runnable(&self) -> Vec<usize> {
        (0..self.status.len())
            .filter(|&i| match self.status[i] {
                Status::Runnable => true,
                Status::Blocked(l) => self.holders[l].is_none(),
                Status::Done => false,
            })
            .collect()
    }

    fn all_done(&self) -> bool {
        self.status.iter().all(|s| *s == Status::Done)
    }
}

/// Registers locks and runs explorations. One per experiment.
pub struct Harness {
    state: Arc<Mutex<SchedState>>,
}

impl Default for Harness {
    fn default() -> Self {
        Self::new()
    }
}

impl Harness {
    pub fn new() -> Self {
        Self { state: Arc::new(Mutex::new(SchedState::default())) }
    }

    /// A scheduler-aware lock guarding nothing in particular — the shape C#
    /// `lock (obj)` actually has, where the association between the lock and
    /// the data it protects is a convention the compiler never checks.
    pub fn lock(&self) -> SyncLock {
        let mut st = self.state.lock().unwrap();
        st.holders.push(None);
        SyncLock { id: st.holders.len() - 1, state: self.state.clone() }
    }

    /// A scheduler-aware mutex that owns its data, shaped like
    /// `std::sync::Mutex` so that emitted `let _sync = x.lock().unwrap();`
    /// compiles against it unchanged.
    pub fn mutex<T>(&self, value: T) -> SyncMutex<T> {
        SyncMutex { lock: self.lock(), cell: UnsafeCell::new(value) }
    }

    /// The experiment's independent variable: the same workload, with the lock
    /// and without it. "Delete the lock" is a parameter, never an edit to
    /// generated code.
    pub fn policy(&self, locked: bool) -> Policy {
        if locked {
            Policy::Locked(self.lock())
        } else {
            Policy::Unlocked
        }
    }

    /// Walk every interleaving, depth-first, up to `max_runs`.
    ///
    /// Deterministic and exhaustive: each run is identified by the vector of
    /// scheduling choices that produced it, and the walk enumerates that tree.
    pub fn explore<W: Workload>(&self, w: &W, max_runs: usize) -> Exploration {
        let mut ex = Exploration::default();
        let mut prefix: Vec<usize> = Vec::new();
        loop {
            let (outcome, taken, interleaved) = self.run_once(w, &prefix);
            ex.runs += 1;
            ex.interleaved_into_critical_section += interleaved;
            match outcome {
                RunOutcome::Completed(o) => {
                    ex.outcomes.insert(o);
                }
                RunOutcome::Deadlocked => {
                    ex.deadlocks.push(taken.iter().map(|&(c, _)| c).collect());
                }
            }
            // Backtrack to the last decision with an unexplored alternative.
            match taken.iter().rposition(|&(c, n)| c + 1 < n) {
                None => break,
                Some(i) => {
                    prefix = taken[..=i].iter().map(|&(c, _)| c).collect();
                    prefix[i] += 1;
                }
            }
            if ex.runs >= max_runs {
                ex.truncated = true;
                break;
            }
        }
        ex
    }

    /// One run, with scheduling choices taken from `prefix` and defaulting to
    /// the lowest-numbered runnable agent once the prefix is exhausted.
    fn run_once<W: Workload>(
        &self,
        w: &W,
        prefix: &[usize],
    ) -> (RunOutcome, Vec<(usize, usize)>, usize) {
        w.reset();
        let n = w.agents();
        assert!(n >= 2, "an interleaving experiment needs at least two agents");
        self.state.lock().unwrap().reset(n);

        let (report_tx, report_rx) = channel::<()>();
        let mut go_txs: Vec<Sender<Baton>> = Vec::new();
        let mut go_rxs: Vec<Option<Receiver<Baton>>> = Vec::new();
        for _ in 0..n {
            let (tx, rx) = channel::<Baton>();
            go_txs.push(tx);
            go_rxs.push(Some(rx));
        }

        let mut taken: Vec<(usize, usize)> = Vec::new();
        let mut deadlocked = false;

        std::thread::scope(|scope| {
            for (i, rx) in go_rxs.iter_mut().enumerate() {
                let rx = rx.take().unwrap();
                let state = self.state.clone();
                let report = report_tx.clone();
                scope.spawn(move || {
                    let ctx = Rc::new(Ctx { id: i, state, report, go: rx });
                    CURRENT.with(|c| *c.borrow_mut() = Some(ctx.clone()));
                    ctx.wait();
                    // An aborted agent unwinds out of workload code; the panic
                    // is caught here so the exploration can still join.
                    let agent = Agent { ctx: ctx.clone() };
                    let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        w.run(&agent, i)
                    }));
                    CURRENT.with(|c| *c.borrow_mut() = None);
                    if r.is_ok() {
                        ctx.finish();
                    }
                });
            }

            loop {
                let (choices, done) = {
                    let st = self.state.lock().unwrap();
                    (st.runnable(), st.all_done())
                };
                if done {
                    break;
                }
                if choices.is_empty() {
                    // Every remaining agent is blocked on a lock some other
                    // blocked agent holds. Reporting it beats hanging, and a
                    // hang is what a naive baton scheduler does here.
                    deadlocked = true;
                    for tx in &go_txs {
                        let _ = tx.send(Baton::Abort);
                    }
                    break;
                }
                let idx = *prefix.get(taken.len()).unwrap_or(&0);
                let idx = idx.min(choices.len() - 1);
                taken.push((idx, choices.len()));
                let next = choices[idx];
                {
                    let mut st = self.state.lock().unwrap();
                    if st.depth.iter().enumerate().any(|(i, d)| i != next && *d > 0) {
                        st.interleaved += 1;
                    }
                }
                go_txs[next].send(Baton::Go).expect("agent gone");
                report_rx.recv().expect("agent dropped the baton");
            }

            if deadlocked {
                // Aborted agents are parked in `wait()`; the abort baton frees
                // them, but any that were mid-run must also be woken.
                for tx in &go_txs {
                    let _ = tx.send(Baton::Abort);
                }
            }
        });

        let interleaved = self.state.lock().unwrap().interleaved;
        let outcome = if deadlocked {
            RunOutcome::Deadlocked
        } else {
            RunOutcome::Completed(w.observe())
        };
        (outcome, taken, interleaved)
    }
}

enum Baton {
    Go,
    Abort,
}

enum RunOutcome {
    Completed(Vec<u64>),
    Deadlocked,
}

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------

struct Ctx {
    id: usize,
    state: Arc<Mutex<SchedState>>,
    report: Sender<()>,
    go: Receiver<Baton>,
}

impl Ctx {
    /// Hand the baton back and park until the scheduler returns it.
    fn wait(&self) {
        match self.go.recv() {
            Ok(Baton::Go) => {}
            // The scheduler declared this run deadlocked. Unwind out of
            // workload code so the run can be joined and reported.
            _ => std::panic::panic_any(Aborted),
        }
    }

    fn yield_now(&self) {
        self.report.send(()).expect("scheduler gone");
        self.wait();
    }

    fn finish(&self) {
        self.state.lock().unwrap().status[self.id] = Status::Done;
        self.report.send(()).expect("scheduler gone");
    }
}

/// Payload of the abort panic. Not an error the workload can meaningfully
/// handle, which is why it is a panic rather than a `Result`.
struct Aborted;

thread_local! {
    static CURRENT: RefCell<Option<Rc<Ctx>>> = const { RefCell::new(None) };
}

/// One logical thread of the workload.
pub struct Agent {
    ctx: Rc<Ctx>,
}

impl Agent {
    pub fn id(&self) -> usize {
        self.ctx.id
    }

    /// A preemption point. The scheduler may switch agents here and nowhere
    /// else, which is what makes the exploration finite and reproducible.
    ///
    /// Resolution comes entirely from where these are placed: a critical
    /// section without one inside it is atomic to this harness whether or not
    /// it is atomic in reality, and the vacuity guard exists to stop that being
    /// mistaken for a passing result.
    pub fn step(&self) {
        self.ctx.yield_now();
    }
}

// ---------------------------------------------------------------------------
// Locks
// ---------------------------------------------------------------------------

/// A lock the scheduler understands. Blocking on it is a scheduling event, not
/// a wait: the scheduler simply does not offer the baton to a blocked agent
/// until the lock is free.
pub struct SyncLock {
    id: usize,
    state: Arc<Mutex<SchedState>>,
}

impl SyncLock {
    /// Acquire, yielding to the scheduler for as long as another agent holds
    /// it. Returns a guard that releases on drop.
    pub fn acquire<'a>(&'a self, agent: &'a Agent) -> Held<'a> {
        loop {
            {
                let mut st = self.state.lock().unwrap();
                if st.holders[self.id].is_none() {
                    st.holders[self.id] = Some(agent.id());
                    st.depth[agent.id()] += 1;
                    return Held { lock: self, agent: agent.id() };
                }
                st.status[agent.id()] = Status::Blocked(self.id);
            }
            agent.ctx.yield_now();
            self.state.lock().unwrap().status[agent.id()] = Status::Runnable;
        }
    }
}

pub struct Held<'a> {
    lock: &'a SyncLock,
    agent: usize,
}

impl Drop for Held<'_> {
    fn drop(&mut self) {
        let mut st = self.lock.state.lock().unwrap();
        st.holders[self.lock.id] = None;
        st.depth[self.agent] -= 1;
    }
}

/// A data-owning mutex shaped like `std::sync::Mutex`.
///
/// The emitted form of C# `lock (x)` is `let _sync = x.lock().unwrap();`, so a
/// field typed with this instead of `std::sync::Mutex` puts generated code
/// under the scheduler without the emitter knowing. That is the bridge from
/// this instrument to real translated peripherals — none of which contain a
/// lock site yet.
///
/// Outside an exploration there is no current agent and no scheduler; the lock
/// is then taken unconditionally, so the same code runs normally in production.
pub struct SyncMutex<T> {
    lock: SyncLock,
    cell: UnsafeCell<T>,
}

// SAFETY: mutual exclusion is enforced by the scheduler's holder table, so at
// most one `MutexGuard` exists at a time and the `&mut T` it hands out is
// unique. Serialised execution supplies the ordering.
unsafe impl<T: Send> Sync for SyncMutex<T> {}
unsafe impl<T: Send> Send for SyncMutex<T> {}

/// Mirrors `std::sync::PoisonError` only in shape: `lock()` returns a `Result`
/// so that `.unwrap()` in emitted code compiles. This harness never poisons.
#[derive(Debug)]
pub struct NeverPoisoned;

impl<T> SyncMutex<T> {
    pub fn lock(&self) -> Result<MutexGuard<'_, T>, NeverPoisoned> {
        let current = CURRENT.with(|c| c.borrow().clone());
        match current {
            Some(ctx) => {
                let agent = Agent { ctx };
                loop {
                    {
                        let mut st = self.lock.state.lock().unwrap();
                        if st.holders[self.lock.id].is_none() {
                            st.holders[self.lock.id] = Some(agent.id());
                            st.depth[agent.id()] += 1;
                            return Ok(MutexGuard { m: self, agent: Some(agent.id()) });
                        }
                        st.status[agent.id()] = Status::Blocked(self.lock.id);
                    }
                    agent.ctx.yield_now();
                    self.lock.state.lock().unwrap().status[agent.id()] = Status::Runnable;
                }
            }
            // No scheduler: ordinary single-threaded use.
            None => Ok(MutexGuard { m: self, agent: None }),
        }
    }
}

pub struct MutexGuard<'a, T> {
    m: &'a SyncMutex<T>,
    agent: Option<usize>,
}

impl<T> std::ops::Deref for MutexGuard<'_, T> {
    type Target = T;
    fn deref(&self) -> &T {
        // SAFETY: holding the guard means holding the lock.
        unsafe { &*self.m.cell.get() }
    }
}

impl<T> std::ops::DerefMut for MutexGuard<'_, T> {
    fn deref_mut(&mut self) -> &mut T {
        // SAFETY: the guard is unique, so this `&mut` is unique.
        unsafe { &mut *self.m.cell.get() }
    }
}

impl<T> Drop for MutexGuard<'_, T> {
    fn drop(&mut self) {
        if let Some(agent) = self.agent {
            let mut st = self.m.lock.state.lock().unwrap();
            st.holders[self.m.lock.id] = None;
            st.depth[agent] -= 1;
        }
    }
}

/// Whether a critical section is actually locked. Switching this is the
/// experiment; the workload code is identical either way, so nothing that
/// differs between the two arms can be attributed to the code having changed.
pub enum Policy {
    Locked(SyncLock),
    Unlocked,
}

impl Policy {
    pub fn enter<'a>(&'a self, agent: &'a Agent) -> Section<'a> {
        match self {
            #[cfg(not(feature = "prove-the-harness-can-fail"))]
            Policy::Locked(l) => Section { held: Some(l.acquire(agent)), marked: None },
            // THE DELIBERATE DEFECT. Under this feature the locked arm stops
            // locking, so both arms of every experiment are unlocked and every
            // test that depends on mutual exclusion must fail.
            //
            // A concurrency check that has never failed is worth nothing, and
            // this project has already shipped a checker that reported success
            // while verifying nothing. `scripts/check_sync_harness.py` builds
            // with this feature and fails if the tests still pass.
            #[cfg(feature = "prove-the-harness-can-fail")]
            Policy::Locked(_) => {
                agent.ctx.state.lock().unwrap().depth[agent.id()] += 1;
                Section { held: None, marked: Some(agent) }
            }
            // The region is still marked, so the vacuity counter sees the
            // unlocked arm exactly as it sees the locked one.
            Policy::Unlocked => {
                agent.ctx.state.lock().unwrap().depth[agent.id()] += 1;
                Section { held: None, marked: Some(agent) }
            }
        }
    }
}

pub struct Section<'a> {
    /// Held for its `Drop`, which is the whole point of a guard; nothing reads
    /// it, and that is not dead code.
    #[allow(dead_code)]
    held: Option<Held<'a>>,
    marked: Option<&'a Agent>,
}

impl Drop for Section<'_> {
    fn drop(&mut self) {
        if let Some(agent) = self.marked {
            agent.ctx.state.lock().unwrap().depth[agent.id()] -= 1;
        }
    }
}

// ---------------------------------------------------------------------------
// Workloads and verdicts
// ---------------------------------------------------------------------------

/// A workload the harness can replay under many schedules.
///
/// `reset` runs before every schedule, so the shared state must be rebuildable;
/// `observe` is read after every schedule and is the only thing compared. Put
/// into it whatever a divergence should be visible in — final state, the values
/// each agent read, or both.
pub trait Workload: Sync {
    fn agents(&self) -> usize;
    fn reset(&self);
    fn run(&self, agent: &Agent, id: usize);
    fn observe(&self) -> Vec<u64>;
}

/// The result of walking every schedule.
#[derive(Default, Debug)]
pub struct Exploration {
    pub runs: usize,
    pub outcomes: BTreeSet<Vec<u64>>,
    /// Decision vectors of runs that deadlocked, so each is reproducible.
    pub deadlocks: Vec<Vec<usize>>,
    pub interleaved_into_critical_section: usize,
    /// True if the run cap was hit, so the walk is no longer exhaustive.
    pub truncated: bool,
}

/// What the experiment concluded. `Vacuous` is first because it is the answer
/// that a careless harness silently reports as agreement.
#[derive(Debug, PartialEq, Eq)]
pub enum Verdict {
    /// The exploration never scheduled another agent while an agent was inside
    /// a critical section, so it could not have seen a difference. Not a pass.
    Vacuous { reason: String },
    /// Removing the lock produced outcomes the locked arm cannot produce.
    LoadBearing { extra: Vec<Vec<u64>>, locked: usize, unlocked: usize },
    /// Removing the lock deadlocked, or keeping it did.
    Deadlock { schedules: usize },
    /// Every outcome without the lock is one the locked arm also produces.
    /// Says nothing about workloads not explored.
    Indistinguishable { interleavings: usize, truncated: bool },
}

/// Compare the two arms of the experiment.
pub fn compare(locked: &Exploration, unlocked: &Exploration) -> Verdict {
    if !locked.deadlocks.is_empty() {
        return Verdict::Deadlock { schedules: locked.deadlocks.len() };
    }
    if locked.interleaved_into_critical_section == 0
        || unlocked.interleaved_into_critical_section == 0
    {
        return Verdict::Vacuous {
            reason: "no agent was ever scheduled while another was inside a \
                     critical section -- the workload has no preemption point \
                     where the lock could matter, so agreement here means \
                     nothing was tested"
                .into(),
        };
    }
    let extra: Vec<Vec<u64>> =
        unlocked.outcomes.difference(&locked.outcomes).cloned().collect();
    if !extra.is_empty() {
        return Verdict::LoadBearing {
            extra,
            locked: locked.outcomes.len(),
            unlocked: unlocked.outcomes.len(),
        };
    }
    Verdict::Indistinguishable {
        interleavings: locked.runs + unlocked.runs,
        truncated: locked.truncated || unlocked.truncated,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Two agents doing read-modify-write on one counter, with a preemption
    /// point between the read and the write. This is the smallest shape the
    /// census reports for a guarded field: `lock (x) { n = f(n) }`.
    struct Rmw {
        counter: Slot<u64>,
        policy: Policy,
    }

    impl Workload for Rmw {
        fn agents(&self) -> usize {
            2
        }
        fn reset(&self) {
            self.counter.set(0);
        }
        fn run(&self, agent: &Agent, id: usize) {
            let _section = self.policy.enter(agent);
            let v = self.counter.get();
            agent.step();
            self.counter.set(v + 1 + id as u64);
        }
        fn observe(&self) -> Vec<u64> {
            vec![self.counter.get()]
        }
    }

    fn rmw(locked: bool) -> (Harness, Rmw) {
        let h = Harness::new();
        let policy = h.policy(locked);
        (h, Rmw { counter: Slot::new(0), policy })
    }

    #[test]
    fn a_deleted_lock_is_caught() {
        let (h, w) = rmw(true);
        let with = h.explore(&w, 200);
        let (h2, w2) = rmw(false);
        let without = h2.explore(&w2, 200);

        // With the lock, both increments land: 0 + 1 + 2.
        assert_eq!(with.outcomes, BTreeSet::from([vec![3]]));
        // Without it, either update can be lost.
        assert!(without.outcomes.contains(&vec![1]) || without.outcomes.contains(&vec![2]),
                "a lost update must be reachable, got {:?}", without.outcomes);

        match compare(&with, &without) {
            Verdict::LoadBearing { extra, .. } => {
                assert!(!extra.is_empty());
            }
            other => panic!("harness failed to catch a deleted lock: {other:?}"),
        }
    }

    /// The same experiment on a critical section with no preemption point
    /// inside it. The outcomes agree — and agreement here is worthless, so the
    /// verdict must say `Vacuous`, not `Indistinguishable`.
    struct Atomic {
        counter: Slot<u64>,
        policy: Policy,
    }

    impl Workload for Atomic {
        fn agents(&self) -> usize {
            2
        }
        fn reset(&self) {
            self.counter.set(0);
        }
        fn run(&self, agent: &Agent, id: usize) {
            let _section = self.policy.enter(agent);
            self.counter.set(self.counter.get() + 1 + id as u64);
        }
        fn observe(&self) -> Vec<u64> {
            vec![self.counter.get()]
        }
    }

    #[test]
    fn agreement_with_nothing_to_observe_is_reported_as_vacuous() {
        let h = Harness::new();
        let w = Atomic { counter: Slot::new(0), policy: h.policy(true) };
        let with = h.explore(&w, 200);
        let h2 = Harness::new();
        let w2 = Atomic { counter: Slot::new(0), policy: h2.policy(false) };
        let without = h2.explore(&w2, 200);

        assert_eq!(with.outcomes, without.outcomes, "no preemption point, so no difference");
        match compare(&with, &without) {
            Verdict::Vacuous { .. } => {}
            other => panic!("agreement with nothing observable must be vacuous, got {other:?}"),
        }
    }

    /// The locked arm must reproduce exactly the sequential results, no more:
    /// that is what "the lock made the section atomic" means operationally.
    #[test]
    fn locking_leaves_only_serial_outcomes() {
        let (h, w) = rmw(true);
        let ex = h.explore(&w, 200);
        assert!(ex.runs > 1, "more than one schedule must be explored");
        assert!(!ex.truncated);
        assert_eq!(ex.outcomes.len(), 1, "atomic sections have one outcome here");
    }

    /// Exploration must be reproducible, or every result is anecdotal.
    #[test]
    fn exploration_is_deterministic() {
        let (h, w) = rmw(false);
        let a = h.explore(&w, 200);
        let (h2, w2) = rmw(false);
        let b = h2.explore(&w2, 200);
        assert_eq!(a.runs, b.runs);
        assert_eq!(a.outcomes, b.outcomes);
        assert_eq!(
            a.interleaved_into_critical_section,
            b.interleaved_into_critical_section
        );
    }

    /// Lock ordering. The census finds a nested lock in `Logger`, so the
    /// harness has to survive the shape rather than hang on it.
    struct Ordered {
        a: SyncLock,
        b: SyncLock,
        done: Slot<u64>,
    }

    impl Workload for Ordered {
        fn agents(&self) -> usize {
            2
        }
        fn reset(&self) {
            self.done.set(0);
        }
        fn run(&self, agent: &Agent, id: usize) {
            let (first, second) = if id == 0 { (&self.a, &self.b) } else { (&self.b, &self.a) };
            let _f = first.acquire(agent);
            agent.step();
            let _s = second.acquire(agent);
            self.done.set(self.done.get() + 1);
        }
        fn observe(&self) -> Vec<u64> {
            vec![self.done.get()]
        }
    }

    #[test]
    fn a_lock_order_inversion_is_reported_not_hung() {
        let h = Harness::new();
        let w = Ordered { a: h.lock(), b: h.lock(), done: Slot::new(0) };
        let ex = h.explore(&w, 200);
        assert!(!ex.deadlocks.is_empty(), "the inversion must be found");
        // And it is reproducible: the decision vector names the schedule.
        assert!(ex.deadlocks.iter().all(|d| !d.is_empty()));
    }

    /// `SyncMutex` in the exact shape the emitter produces, so the bridge to
    /// generated code is exercised rather than assumed.
    struct Emitted {
        counter: SyncMutex<u64>,
        observed: Slot<u64>,
    }

    impl Workload for Emitted {
        fn agents(&self) -> usize {
            2
        }
        fn reset(&self) {
            *self.counter.lock().unwrap() = 0;
            self.observed.set(0);
        }
        fn run(&self, agent: &Agent, _id: usize) {
            // SYNC(measure): the emitted shape, verbatim.
            {
                let mut _sync = self.counter.lock().unwrap();
                let v = *_sync;
                agent.step();
                *_sync = v + 1;
            }
            self.observed.set(self.observed.get() + 1);
        }
        fn observe(&self) -> Vec<u64> {
            vec![*self.counter.lock().unwrap(), self.observed.get()]
        }
    }

    #[test]
    fn the_emitted_mutex_shape_runs_under_the_scheduler() {
        let h = Harness::new();
        let w = Emitted { counter: h.mutex(0), observed: Slot::new(0) };
        let ex = h.explore(&w, 200);
        assert!(ex.deadlocks.is_empty());
        assert_eq!(ex.outcomes, BTreeSet::from([vec![2, 2]]),
                   "mutual exclusion must hold across every schedule");
        assert!(ex.interleaved_into_critical_section > 0,
                "the mutex must be contended, or the test proves nothing");
    }

    /// Outside an exploration there is no scheduler, and the same type must
    /// behave as an ordinary mutex — otherwise it cannot ship in real code.
    #[test]
    fn the_emitted_mutex_works_without_a_scheduler() {
        let h = Harness::new();
        let m = h.mutex(7u64);
        *m.lock().unwrap() += 1;
        assert_eq!(*m.lock().unwrap(), 8);
    }
}
