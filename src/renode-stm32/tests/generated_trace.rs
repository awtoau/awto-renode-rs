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
//! same four things, so wiring a new one is one macro line.
//!
//! THE NUMBERS ARE THE POINT, and they vary enormously:
//!
//!     exti      25 accesses      0 divergences   100.0%
//!     syscfg     9 accesses      2 divergences    66.7%
//!     adc1  16,800 accesses  1,788 divergences    84.3%
//!     dma1     183 accesses     88 divergences     9.3%
//!     dma2  12,356 accesses  6,164 divergences     0.2%
//!
//! EXTI replays perfectly: 25 accesses, every read matching the C#. That is
//! the first evidence in this project that generated code BEHAVES correctly
//! rather than merely compiling.
//!
//! DMA2 is at 0.2%, and that is equally informative. Its behaviour is almost
//! entirely withheld, so the module returns reset values while the C# returns
//! computed ones. The register map may well be right; the trace cannot say so
//! while the behaviour is missing.
//!
//! Neither number would be visible from the gap count, which reports the same
//! kind of gap for both.

use renode_oracle::{load_trace, run, Replayable};
use renode_regs::Bank;
use std::path::PathBuf;

/// Every generated module exposes the same four things, so the harness is
/// written once and each new trace costs a single macro line. If this stops
/// being true the converter has changed shape, and that is worth noticing.
macro_rules! generated_replay {
    ($name:ident, $module:path, $trace:literal, $known:expr) => {
        #[test]
        fn $name() {
            use $module as m;

            struct H {
                bank: Bank<m::State>,
                state: m::State,
            }
            impl Replayable for H {
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

            let mut bank: Bank<m::State> = Bank::new();
            let mut fields = m::Fields::default();
            m::define_registers(&mut bank, &mut fields);
            let mut state = m::State::default();
            state.f = fields;
            let mut h = H { bank, state };

            let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../oracle/traces")
                .join(concat!($trace, ".jsonl.gz"));
            let trace = load_trace(&path).expect($trace);
            let report = run(&mut h, &trace);

            println!(
                "{} (GENERATED): {} accesses ({} reads), {} divergences, {:.1}%",
                $trace, report.total, report.reads,
                report.divergences.len(), report.read_accuracy() * 100.0
            );
            for d in report.divergences.iter().take(5) {
                println!("    {d}");
            }
            assert!(report.total > 0, "{}: replayed zero accesses", $trace);
            // Ratchet, not pass/fail -- see the note above. LOWER as behaviour
            // lands; a rise means a register map that was right no longer is.
            assert!(
                report.divergences.len() <= $known,
                "{}: {} divergences, {} known -- a register map regressed",
                $trace, report.divergences.len(), $known
            );
        }
    };
}

generated_replay!(syscfg_generated, renode_stm32::syscfg_registers, "syscfg", 2);
generated_replay!(exti_generated, renode_stm32::exti_registers, "exti", 0);
generated_replay!(adc_generated, renode_stm32::adc_registers, "adc1", 1788);
generated_replay!(dma1_generated, renode_stm32::dma_registers, "dma1", 88);
generated_replay!(dma2_generated, renode_stm32::dma_registers, "dma2", 6164);
