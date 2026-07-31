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

/// Semantics the trace does not reach, taken from the C# rather than from
/// observed behaviour. Each of these exists because a mutation survived the
/// trace replay.
mod semantics_not_covered_by_the_trace {
    use renode_stm32::uart::Stm32Uart;

    const SR: u64 = 0x00;
    const DR: u64 = 0x04;
    const CR1: u64 = 0x0C;
    const UE_RE: u32 = (1 << 13) | (1 << 2); // usart + receiver enabled

    /// RXNE is WRITE_ZERO_TO_CLEAR in the C#, not W1C. Writing ones must NOT
    /// clear it. A W1C mutant survives the captured trace.
    #[test]
    fn rxne_is_write_zero_to_clear() {
        let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
        u.write(CR1, UE_RE);
        u.write_char(b'x');
        assert_ne!(u.read(SR) & (1 << 5), 0, "RXNE should set on receive");
        u.write(SR, 0xFFFF_FFFF);
        assert_ne!(u.read(SR) & (1 << 5), 0, "writing ones must not clear a W0C flag");
    }

    /// C#: reading DR dequeues, and clears RXNE once the FIFO drains.
    #[test]
    fn reading_data_drains_the_fifo() {
        let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
        u.write(CR1, UE_RE);
        u.write_char(b'a');
        u.write_char(b'b');
        assert_eq!(u.read(DR), b'a' as u32);
        assert_ne!(u.read(SR) & (1 << 5), 0, "RXNE still set with one byte left");
        assert_eq!(u.read(DR), b'b' as u32);
        assert_eq!(u.read(SR) & (1 << 5), 0, "RXNE clears when the FIFO empties");
    }

    /// C#: a character is dropped when neither UE nor RE is set.
    #[test]
    fn receive_is_dropped_when_disabled() {
        let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
        u.write_char(b'x');
        assert_eq!(u.read(SR) & (1 << 5), 0, "disabled UART must drop the character");
    }

    /// C#: TXE is assumed always empty, so TXEIE alone raises the IRQ.
    #[test]
    fn txe_interrupt_is_unconditional() {
        let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
        assert!(!u.irq());
        u.write(CR1, UE_RE | (1 << 7)); // TXEIE
        assert!(u.irq(), "TXEIE alone must raise IRQ, since TXE is assumed set");
    }

    /// C# computes BaudRate from BRR; OversamplingMode.By8 drops the oldest
    /// fraction bit. Used only for the idle-line timeout.
    #[test]
    fn baud_rate_follows_the_brr_formula() {
        let mut u = Stm32Uart::new(renode_stm32::uart::DEFAULT_FREQUENCY);
        u.write(0x08, (0x1A << 4) | 0x1); // mantissa 26, fraction 1
        // 8e6 / (8 * 2 * (26 + 1/16)) == 19184. (Written as 19230 first time:
        // the test was wrong, not the port.)
        assert_eq!(u.baud_rate(), 19184);
    }
}
