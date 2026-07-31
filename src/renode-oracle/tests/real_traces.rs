//! Verify the harness against the ACTUAL captured traces, not synthetic ones.
//! A parser that works on hand-written examples and fails on real data is the
//! failure mode that produced "22,713 accesses across 1 offset" during capture.

use renode_oracle::{load_trace, run, Replayable};
use std::path::PathBuf;

fn traces_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../oracle/traces")
}

struct AlwaysZero;
impl Replayable for AlwaysZero {
    fn read(&mut self, _o: u64, _w: u32) -> u64 { 0 }
    fn write(&mut self, _o: u64, _w: u32, _v: u64) {}
}

#[test]
fn every_committed_trace_loads_and_looks_like_a_trace() {
    let dir = traces_dir();
    assert!(dir.exists(), "no traces -- run scripts/capture_traces.py");
    let mut checked = 0;
    for entry in std::fs::read_dir(&dir).unwrap() {
        let path = entry.unwrap().path();
        if !path.to_string_lossy().ends_with(".jsonl.gz") { continue; }
        let trace = load_trace(&path).expect("trace should load");
        let name = path.file_name().unwrap().to_string_lossy().to_string();

        assert!(!trace.is_empty(), "{name} is empty");
        // The capture bug that nearly shipped: a wrong regex matched UART
        // character output and reported thousands of accesses at one offset.
        let offsets: std::collections::HashSet<_> = trace.iter().map(|a| a.offset).collect();
        assert!(trace.len() < 100 || offsets.len() > 1,
                "{name}: {} accesses across {} offset(s) -- parse error, not a trace",
                trace.len(), offsets.len());
        // Widths must be real bus widths.
        for a in &trace {
            assert!(matches!(a.width, 8 | 16 | 32 | 64), "{name}: bad width {}", a.width);
        }
        // Sequence numbers must be dense and ordered.
        for (i, a) in trace.iter().enumerate() {
            assert_eq!(a.seq as usize, i, "{name}: seq out of order at {i}");
        }
        checked += 1;
    }
    assert!(checked >= 15, "expected the full peripheral set, found {checked}");
}

#[test]
fn a_stub_fails_a_real_trace() {
    // The intended starting state: every peripheral is a stub and every trace
    // fails. If a stub ever passed, the oracle would be measuring nothing.
    let path = traces_dir().join("nvic.jsonl.gz");
    let trace = load_trace(&path).expect("nvic trace should load");
    let report = run(&mut AlwaysZero, &trace);
    assert!(!report.passed(), "an always-zero stub must not pass a real trace");
    assert!(report.reads > 1000, "nvic trace should be substantial");
    println!(
        "nvic: {} accesses ({} reads), stub read-accuracy {:.1}%",
        report.total, report.reads, report.read_accuracy() * 100.0
    );
}
