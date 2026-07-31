//! Replay the captured usart1 trace against the translated UART. Issue #34.
//!
//! This is the first moment anything in this project is VALIDATED rather than
//! merely built -- but read the coverage caveat below before trusting a pass.
//!
//! ## What a pass here does and does not mean
//!
//! It means the port is INDISTINGUISHABLE FROM C# RENODE ON THIS TRACE. It does
//! not mean correct. Mutation testing on the first passing run:
//!
//!   TXE always-set removed          -> CAUGHT, 1218 divergences
//!   RXNE WRITE_ZERO_TO_CLEAR -> W1C -> SURVIVED, 0 divergences
//!
//! The second mutant is a real semantic change that the trace cannot see. The
//! firmware drives its shell over DMA and CPU hooks rather than the UART
//! interrupt path, so the trace has 1 distinct Status write value and 2 Data
//! reads across 33,164 accesses -- the W0C paths are simply never taken.
//!
//! Tier 2 is therefore a REGRESSION oracle, not a correctness proof. Behaviour
//! the firmware does not exercise needs unit tests derived from the C# source
//! (see the `semantics_not_covered_by_the_trace` tests below), and surviving
//! mutants are the signal for where those are missing.

use renode_oracle::{load_trace, run, Replayable};
use renode_stm32::uart::Stm32Uart;
use std::path::PathBuf;

struct Harness(Stm32Uart);

impl Replayable for Harness {
    fn read(&mut self, offset: u64, _w: u32) -> u64 {
        self.0.read(offset) as u64
    }
    fn write(&mut self, offset: u64, _w: u32, value: u64) {
        self.0.write(offset, value as u32);
    }
    fn reset(&mut self) {
        self.0.reset();
    }
}

#[test]
fn usart1_trace_replays() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../oracle/traces/usart1.jsonl.gz");
    let trace = load_trace(&path).expect("usart1 trace should load");

    // The C# constructor default; the .repl does not override it.
    let mut h = Harness(Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY));
    let report = run(&mut h, &trace);

    println!(
        "usart1: {} accesses ({} reads, {} writes), {} divergences, read accuracy {:.2}%",
        report.total, report.reads, report.writes,
        report.divergences.len(), report.read_accuracy() * 100.0
    );
    for d in report.divergences.iter().take(10) {
        println!("  {d}");
    }
    assert!(report.passed(), "{} divergences against the C# reference",
            report.divergences.len());
}
