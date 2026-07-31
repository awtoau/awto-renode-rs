//! Replay the four captured GPIO port traces. Issue #14.
//!
//! Same caveat as the UART: a pass means indistinguishable ON THIS TRACE.

use renode_oracle::{load_trace, run, Replayable};
use renode_stm32::gpio_port::Stm32GpioPort;
use std::path::PathBuf;

struct Harness(Stm32GpioPort);
impl Replayable for Harness {
    fn read(&mut self, o: u64, _w: u32) -> u64 { self.0.read(o) as u64 }
    fn write(&mut self, o: u64, _w: u32, v: u64) { self.0.write(o, v as u32) }
    fn reset(&mut self) { self.0.reset() }
}

/// Reset values come from the platform description via
/// `scripts/parse_repl.py`. Retyping them here would create a second source of
/// truth that drifts silently: change the .repl and these tests would keep
/// asserting the old values while passing.
fn port(name: &str) -> Stm32GpioPort {
    let c = renode_stm32::platform::gpio_port(name)
        .unwrap_or_else(|| panic!("{name} is not in the platform description"));
    Stm32GpioPort::new(c.mode_reset, c.output_speed_reset, c.pull_up_pull_down_reset)
}

#[test]
fn gpio_traces_replay() {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../oracle/traces");
    let mut failures = Vec::new();
    for name in ["gpioPortA", "gpioPortB", "gpioPortC", "gpioPortE"] {
        let path = dir.join(format!("{name}.jsonl.gz"));
        let trace = load_trace(&path).unwrap_or_else(|e| panic!("{name}: {e}"));
        let mut h = Harness(port(name));
        let report = run(&mut h, &trace);
        println!("{name}: {} accesses ({} reads), {} divergences, {:.1}%",
                 report.total, report.reads, report.divergences.len(),
                 report.read_accuracy() * 100.0);
        for d in report.divergences.iter().take(5) { println!("    {d}"); }
        if !report.passed() { failures.push((name, report.divergences.len())); }
    }
    assert!(failures.is_empty(), "diverged: {failures:?}");
}
