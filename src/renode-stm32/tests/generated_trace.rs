//! Replay captured traces against GENERATED modules.
//!
//! Every other trace test drives a HAND-WRITTEN peripheral. This one drives
//! converter output, which is the difference between "the generated code is
//! well-formed" and "the generated code behaves like the C# did".
//!
//! What it actually proves is narrower than it looks, and worth stating: these
//! modules carry register LAYOUT, and most of their behaviour is withheld
//! (the gaps are listed in each file's header). So a pass means the register
//! map is right -- offsets, widths, reset values, which bits are writable --
//! on this trace. It does not mean the peripheral works.
//!
//! That is still the strongest claim available for generated code today, and
//! it is a claim about the ACTUAL DELIVERABLE rather than about a file someone
//! wrote by hand.
//!
//! The harness is generic over the module: every generated file exposes the
//! same three things, so wiring a new one is a `mod` line and four lines here.

use renode_oracle::{load_trace, run, Replayable};
use renode_regs::Bank;
use std::path::PathBuf;

use renode_stm32::syscfg_registers as syscfg;

struct Generated {
    bank: Bank<syscfg::State>,
    state: syscfg::State,
}

impl Generated {
    fn new() -> Self {
        let mut bank: Bank<syscfg::State> = Bank::new();
        let mut fields = syscfg::Fields::default();
        syscfg::define_registers(&mut bank, &mut fields);
        let mut state = syscfg::State::default();
        state.f = fields;
        Self { bank, state }
    }
}

impl Replayable for Generated {
    fn read(&mut self, offset: u64, _w: u32) -> u64 {
        self.bank.read(offset, &mut self.state).unwrap_or(0)
    }
    fn write(&mut self, offset: u64, _w: u32, value: u64) {
        self.bank.write(offset, value, &mut self.state);
    }
    fn reset(&mut self) {
        self.bank.reset();
    }
}

#[test]
fn syscfg_trace_replays_against_generated_code() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../oracle/traces/syscfg.jsonl.gz");
    let trace = load_trace(&path).expect("syscfg trace");
    let mut h = Generated::new();
    let report = run(&mut h, &trace);

    println!(
        "syscfg (GENERATED): {} accesses ({} reads), {} divergences, {:.1}%",
        report.total, report.reads, report.divergences.len(),
        report.read_accuracy() * 100.0
    );
    for d in report.divergences.iter().take(8) {
        println!("    {d}");
    }
    // A RATCHET, not a pass/fail. Two divergences are KNOWN and understood:
    // both read EXTI configuration register 4, whose value comes from
    // behaviour this module withholds (see the GAPS header in
    // syscfg_registers.rs). The layout is right; the behaviour is absent, and
    // the converter says so.
    //
    // Asserting zero would mean deleting this test until the trait and
    // machine work lands, which is exactly when regressions would creep in.
    // Asserting "no worse than known" keeps the trace live and catches the
    // day a rule change breaks a register map that used to be correct.
    //
    // LOWER THIS as behaviour lands. That is the whole mechanism.
    const KNOWN_DIVERGENCES: usize = 2;
    assert!(
        report.divergences.len() <= KNOWN_DIVERGENCES,
        "generated SYSCFG diverged in {} places, {} are known -- a register \
         map that used to be right no longer is",
        report.divergences.len(),
        KNOWN_DIVERGENCES
    );
    assert!(
        report.total > 0,
        "trace replayed zero accesses -- the harness is not exercising anything"
    );
}
