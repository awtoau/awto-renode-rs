//! The interleaving oracle pointed at REAL code and REAL trace data.
//!
//! The unit tests in `lib.rs` prove the instrument can fail on a counter. That
//! is not enough to trust it: a harness that only ever sees its own toy is the
//! same category of thing as a checker that verifies nothing. These tests drive
//! `renode_regs::Bank` — the actual register DSL every translated peripheral is
//! built on — with values taken from a captured trace.
//!
//! WHAT THIS IS NOT
//! ----------------
//! It is not a translated peripheral under test, because **no translated
//! peripheral contains a lock site**. All 56 sites the census finds are in
//! `NVIC`, `BaseClockSource`, `GPIO`, `STM32F1_I2C`, `Logger` and `STM32SPI`,
//! none of which have been converted. So the subject here is a bank plus the
//! access sequence, which is the part that does exist, and the missing half is
//! stated rather than simulated.
//!
//! WHY THE PREEMPTION POINT IS WHERE IT IS
//! ---------------------------------------
//! `Bank::read` and `Bank::write` are each a single call with no preemption
//! point inside, so at bank granularity every access is atomic and the harness
//! would correctly report `Vacuous`. Interleaving becomes observable one level
//! up, where a peripheral method makes TWO bank calls that must not be split —
//! which is exactly the shape `lock (receiveBuffer)` guards in `STM32SPI`, and
//! the shape `lock (irqs)` guards around the read-modify-write of an IRQ state.

use renode_oracle::load_trace;
use renode_regs::{Bank, FieldMode, ValueId};
use renode_sync::{compare, Agent, Harness, Policy, Shared, Slot, Verdict, Workload};
use std::path::PathBuf;

const DATA: u64 = 0x00;
const STATUS: u64 = 0x04;

fn build_bank() -> (Bank<()>, ValueId, ValueId) {
    let mut bank: Bank<()> = Bank::new();
    let (mut data, mut status) = (ValueId::default(), ValueId::default());
    bank.define(DATA, 0).with_value(0, 32, &mut data, FieldMode::READ_WRITE).done();
    bank.define(STATUS, 0).with_value(0, 32, &mut status, FieldMode::READ_WRITE).done();
    (bank, data, status)
}

/// Write values lifted from a captured trace, so the workload is driven by what
/// the firmware actually did rather than by numbers chosen to make a point.
fn trace_writes(n: usize) -> Vec<u64> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../oracle/traces/usart1.jsonl.gz");
    let trace = load_trace(&path).expect("usart1 trace should load");
    let vs: Vec<u64> = trace
        .iter()
        .filter(|a| a.is_write && a.value != 0)
        .map(|a| a.value)
        .take(n)
        .collect();
    assert!(vs.len() == n, "trace should supply {n} non-zero writes, got {}", vs.len());
    vs
}

/// Read-modify-write of one register, split across two agents. The critical
/// section spans two bank calls with a preemption point between them.
struct Accumulate {
    bank: Shared<Bank<()>>,
    policy: Policy,
    values: Vec<u64>,
}

impl Workload for Accumulate {
    fn agents(&self) -> usize {
        2
    }
    fn reset(&self) {
        self.bank.reset();
    }
    fn run(&self, agent: &Agent, id: usize) {
        for (i, v) in self.values.iter().enumerate() {
            if i % 2 != id {
                continue;
            }
            let _section = self.policy.enter(agent);
            let cur = self.bank.read(DATA, &mut ()).expect("register exists");
            agent.step();
            self.bank.write(DATA, cur.wrapping_add(*v), &mut ());
        }
    }
    fn observe(&self) -> Vec<u64> {
        vec![self.bank.read(DATA, &mut ()).unwrap()]
    }
}

fn accumulate(locked: bool, values: Vec<u64>) -> (Harness, Accumulate) {
    let h = Harness::new();
    let policy = h.policy(locked);
    let (bank, _, _) = build_bank();
    (h, Accumulate { bank: Shared::new(bank), policy, values })
}

#[test]
fn deleting_the_lock_loses_a_real_write() {
    let values = trace_writes(2);
    let (h, w) = accumulate(true, values.clone());
    let with = h.explore(&w, 500);
    let (h2, w2) = accumulate(false, values.clone());
    let without = h2.explore(&w2, 500);

    let total = values.iter().fold(0u64, |a, b| a.wrapping_add(*b));
    assert_eq!(
        with.outcomes,
        std::collections::BTreeSet::from([vec![total]]),
        "with the lock, every write must land"
    );

    match compare(&with, &without) {
        Verdict::LoadBearing { extra, .. } => {
            // The lost update is one of the two values on its own.
            assert!(
                extra.iter().any(|o| values.contains(&o[0])),
                "expected a lost update among {extra:?}"
            );
        }
        other => panic!("the harness must catch this: {other:?}"),
    }
}

/// A lock over two registers, which is what "which lock protects which data"
/// means once a lock guards more than one field. The invariant is
/// `status == data`, and only interleaving can break it.
struct TwoRegisters {
    bank: Shared<Bank<()>>,
    policy: Policy,
    /// Set by any agent that observes the two registers disagreeing.
    torn: Slot<u64>,
    values: Vec<u64>,
}

impl Workload for TwoRegisters {
    fn agents(&self) -> usize {
        2
    }
    fn reset(&self) {
        self.bank.reset();
        self.torn.set(0);
    }
    fn run(&self, agent: &Agent, id: usize) {
        let v = self.values[id];
        let _section = self.policy.enter(agent);
        self.bank.write(DATA, v, &mut ());
        agent.step();
        // Anyone entering the section must see the pair agree.
        let d = self.bank.read(DATA, &mut ()).unwrap();
        self.bank.write(STATUS, d, &mut ());
        agent.step();
        if self.bank.read(STATUS, &mut ()).unwrap() != self.bank.read(DATA, &mut ()).unwrap() {
            self.torn.set(1);
        }
    }
    fn observe(&self) -> Vec<u64> {
        vec![self.torn.get()]
    }
}

fn two_registers(locked: bool) -> (Harness, TwoRegisters) {
    let h = Harness::new();
    let policy = h.policy(locked);
    let (bank, _, _) = build_bank();
    let values = trace_writes(2);
    (h, TwoRegisters { bank: Shared::new(bank), policy, torn: Slot::new(0), values })
}

#[test]
fn deleting_the_lock_tears_an_invariant_across_two_registers() {
    let (h, w) = two_registers(true);
    let with = h.explore(&w, 500);
    assert_eq!(
        with.outcomes,
        std::collections::BTreeSet::from([vec![0]]),
        "under the lock the two registers never disagree"
    );

    let (h2, w2) = two_registers(false);
    let without = h2.explore(&w2, 500);
    assert!(
        without.outcomes.contains(&vec![1]),
        "without the lock some schedule must tear the pair, got {:?}",
        without.outcomes
    );
    assert!(matches!(compare(&with, &without), Verdict::LoadBearing { .. }));
}

/// The negative control. Same instrument, same bank, agents touching DIFFERENT
/// registers: there is nothing for a lock to protect, and the harness must not
/// invent a difference. A checker that flags everything is as useless as one
/// that flags nothing.
struct Disjoint {
    bank: Shared<Bank<()>>,
    policy: Policy,
    values: Vec<u64>,
}

impl Workload for Disjoint {
    fn agents(&self) -> usize {
        2
    }
    fn reset(&self) {
        self.bank.reset();
    }
    fn run(&self, agent: &Agent, id: usize) {
        let reg = if id == 0 { DATA } else { STATUS };
        let _section = self.policy.enter(agent);
        let cur = self.bank.read(reg, &mut ()).unwrap();
        agent.step();
        self.bank.write(reg, cur.wrapping_add(self.values[id]), &mut ());
    }
    fn observe(&self) -> Vec<u64> {
        vec![self.bank.read(DATA, &mut ()).unwrap(), self.bank.read(STATUS, &mut ()).unwrap()]
    }
}

#[test]
fn disjoint_data_needs_no_lock_and_the_harness_says_so() {
    let values = trace_writes(2);
    let h = Harness::new();
    let (bank, _, _) = build_bank();
    let w = Disjoint { bank: Shared::new(bank), policy: h.policy(true), values: values.clone() };
    let with = h.explore(&w, 500);

    let h2 = Harness::new();
    let (bank2, _, _) = build_bank();
    let w2 = Disjoint { bank: Shared::new(bank2), policy: h2.policy(false), values };
    let without = h2.explore(&w2, 500);

    match compare(&with, &without) {
        Verdict::Indistinguishable { truncated, .. } => assert!(!truncated),
        other => panic!("disjoint accesses must not be reported as a difference: {other:?}"),
    }
}

/// The instrument's own limit, asserted rather than described: at bank
/// granularity a single access is atomic, so the experiment can see nothing and
/// must report that instead of agreement.
struct SingleAccess {
    bank: Shared<Bank<()>>,
    policy: Policy,
    values: Vec<u64>,
}

impl Workload for SingleAccess {
    fn agents(&self) -> usize {
        2
    }
    fn reset(&self) {
        self.bank.reset();
    }
    fn run(&self, agent: &Agent, id: usize) {
        let _section = self.policy.enter(agent);
        self.bank.write(DATA, self.values[id], &mut ());
    }
    fn observe(&self) -> Vec<u64> {
        vec![self.bank.read(DATA, &mut ()).unwrap()]
    }
}

#[test]
fn one_bank_access_is_atomic_so_the_verdict_is_vacuous() {
    let values = trace_writes(2);
    let h = Harness::new();
    let (bank, _, _) = build_bank();
    let w = SingleAccess { bank: Shared::new(bank), policy: h.policy(true), values: values.clone() };
    let with = h.explore(&w, 500);

    let h2 = Harness::new();
    let (bank2, _, _) = build_bank();
    let w2 = SingleAccess { bank: Shared::new(bank2), policy: h2.policy(false), values };
    let without = h2.explore(&w2, 500);

    match compare(&with, &without) {
        Verdict::Vacuous { .. } => {}
        other => panic!("no preemption point inside the section, so nothing was tested: {other:?}"),
    }
}
