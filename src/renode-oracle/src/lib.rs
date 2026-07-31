//! Tier-2 oracle: replay a captured C# Renode access trace against a Rust
//! peripheral and assert identical behaviour. Issue #34 (R5).
//!
//! This is the cheapest tier that says anything real, and it is what converts
//! "port a peripheral" from a research task into a test-driven one with an exact
//! pass/fail. Traces come from `scripts/capture_traces.py` (#6) and are committed
//! under `oracle/traces/` as the reference.
//!
//! A stub fails its trace by construction, which is the intended starting state:
//! 0% passing over 100% of the corpus is a truthful scoreboard.

use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

/// One recorded bus access.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Access {
    pub seq: u64,
    pub is_write: bool,
    pub width: u32,
    pub offset: u64,
    /// For a write, the value written. For a read, the value C# Renode
    /// **returned** — which is what a port must reproduce.
    pub value: u64,
    pub reg: Option<String>,
}

/// A divergence between the Rust peripheral and the reference.
#[derive(Debug)]
pub struct Divergence {
    pub access: Access,
    pub expected: u64,
    pub actual: u64,
}

impl std::fmt::Display for Divergence {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "access #{} read{} 0x{:X}{} -> expected 0x{:X}, got 0x{:X}",
            self.access.seq,
            self.access.width,
            self.access.offset,
            self.access
                .reg
                .as_deref()
                .map(|r| format!(" ({r})"))
                .unwrap_or_default(),
            self.expected,
            self.actual
        )
    }
}

/// Minimal JSON-line parsing. The trace format is written by our own capture
/// script with fixed keys and integer/string values only, so a dependency-free
/// reader is both sufficient and one less thing that can disagree with the
/// producer.
fn field<'a>(line: &'a str, key: &str) -> Option<&'a str> {
    let pat = format!("\"{key}\":");
    let start = line.find(&pat)? + pat.len();
    let rest = &line[start..];
    let end = rest.find(|c| c == ',' || c == '}')?;
    Some(rest[..end].trim())
}

fn num(line: &str, key: &str) -> Option<u64> {
    field(line, key)?.parse().ok()
}

pub fn parse_line(line: &str) -> Option<Access> {
    let dir = field(line, "dir")?.trim_matches('"');
    let reg = field(line, "reg").map(|r| r.trim_matches('"').to_string());
    Some(Access {
        seq: num(line, "seq")?,
        is_write: dir == "write",
        width: num(line, "width")? as u32,
        offset: num(line, "offset")?,
        value: num(line, "value")?,
        reg: reg.filter(|r| r != "null" && !r.is_empty()),
    })
}

/// Load a gzipped trace. Traces are stored compressed because polling traces are
/// ~95% redundant — `timer5` is 14,728 reads of one status register.
pub fn load_trace(path: &Path) -> std::io::Result<Vec<Access>> {
    let file = File::open(path)?;
    let reader: Box<dyn BufRead> = if path.extension().is_some_and(|e| e == "gz") {
        Box::new(BufReader::new(flate2::read::GzDecoder::new(file)))
    } else {
        Box::new(BufReader::new(file))
    };
    let mut out = Vec::new();
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        if let Some(a) = parse_line(&line) {
            out.push(a);
        }
    }
    Ok(out)
}

/// What a peripheral under test must provide.
pub trait Replayable {
    fn read(&mut self, offset: u64, width: u32) -> u64;
    fn write(&mut self, offset: u64, width: u32, value: u64);
    fn reset(&mut self) {}
}

/// Replay a trace, returning every divergence.
///
/// Writes are applied and reads are compared. Note this cannot prove the
/// peripheral correct — it proves it indistinguishable from the reference *on
/// this trace*, which is a weaker and more useful claim.
pub fn replay<P: Replayable>(peripheral: &mut P, trace: &[Access]) -> Vec<Divergence> {
    peripheral.reset();
    let mut out = Vec::new();
    for a in trace {
        if a.is_write {
            peripheral.write(a.offset, a.width, a.value);
        } else {
            let actual = peripheral.read(a.offset, a.width);
            if actual != a.value {
                out.push(Divergence { access: a.clone(), expected: a.value, actual });
            }
        }
    }
    out
}

/// Summary of one replay.
pub struct Report {
    pub total: usize,
    pub reads: usize,
    pub writes: usize,
    pub divergences: Vec<Divergence>,
}

impl Report {
    pub fn passed(&self) -> bool {
        self.divergences.is_empty()
    }
    /// Fraction of reads that matched. Reported because "12 divergences" means
    /// something very different at 20 reads than at 20,000.
    pub fn read_accuracy(&self) -> f64 {
        if self.reads == 0 {
            return 1.0;
        }
        (self.reads - self.divergences.len()) as f64 / self.reads as f64
    }
}

pub fn run<P: Replayable>(peripheral: &mut P, trace: &[Access]) -> Report {
    let divergences = replay(peripheral, trace);
    Report {
        total: trace.len(),
        reads: trace.iter().filter(|a| !a.is_write).count(),
        writes: trace.iter().filter(|a| a.is_write).count(),
        divergences,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_capture_line() {
        let line = r#"{"seq":3,"dir":"read","width":32,"offset":12,"value":8192,"reg":"Control1"}"#;
        let a = parse_line(line).expect("should parse");
        assert_eq!(a.seq, 3);
        assert!(!a.is_write);
        assert_eq!(a.width, 32);
        assert_eq!(a.offset, 12);
        assert_eq!(a.value, 8192);
        assert_eq!(a.reg.as_deref(), Some("Control1"));
    }

    #[test]
    fn parses_a_null_register_name() {
        let line = r#"{"seq":0,"dir":"write","width":32,"offset":0,"value":1,"reg":null}"#;
        let a = parse_line(line).expect("should parse");
        assert!(a.is_write);
        assert_eq!(a.reg, None);
    }

    /// A peripheral that always returns zero. Standing in for a `todo!()` stub,
    /// which must FAIL its trace — that is the point of the harness.
    struct AlwaysZero;
    impl Replayable for AlwaysZero {
        fn read(&mut self, _o: u64, _w: u32) -> u64 {
            0
        }
        fn write(&mut self, _o: u64, _w: u32, _v: u64) {}
    }

    #[test]
    fn a_stub_fails_its_trace() {
        let trace = vec![
            Access { seq: 0, is_write: false, width: 32, offset: 0, value: 0xC0, reg: None },
            Access { seq: 1, is_write: false, width: 32, offset: 4, value: 0, reg: None },
        ];
        let report = run(&mut AlwaysZero, &trace);
        assert!(!report.passed(), "a stub must not pass");
        assert_eq!(report.divergences.len(), 1, "only the non-zero read diverges");
        assert_eq!(report.reads, 2);
    }
}
