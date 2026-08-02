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
//!     usart1 33,164 accesses      0 divergences   100.0%
//!     exti       25 accesses      0 divergences   100.0%
//!     syscfg      9 accesses      0 divergences   100.0%
//!     dma1      183 accesses      7 divergences    92.8%
//!     dma2   12,356 accesses    616 divergences    90.0%
//!     adc1   16,800 accesses  1,192 divergences    89.6%
//!     gpioPortA  62 accesses      3 divergences    82.4%
//!     can1      228 accesses     99 divergences    13.9%
//!
//! SYSCFG AND GPIO MOVED, and for one reason each.
//!
//! SYSCFG went 66.7% -> 100%. Its four EXTICR registers and their sixteen 4-bit
//! mux fields are built by a nested counted `for`, and the layout walker read
//! the SITE and never the loop around it: one register, one field whose bit
//! position was `4 * fieldNumber` and therefore not a constant, so the field
//! was dropped and the register emitted empty. `define_registers` was `{}` and
//! the file reported four gaps, none of them about registers. The loop bounds
//! are literals, so the iterations are known at conversion time and the map
//! unrolls to exactly what the C# builds.
//!
//! gpioPortA went 17.6% -> 82.4%. Five of its eleven registers are defined by
//! `WithEnumFields`/`WithValueFields` bound BY CALLBACK rather than by `out`,
//! and the rule table had only the `out` form -- so five registers matched no
//! rule at all, and their already-generated callbacks sat in the file as dead
//! code. The three divergences left are all first reads, of the platform reset
//! values that the untranslated constructor and `Reset()` would have seeded;
//! both are named gaps in the file's header.
//!
//! USART1 IS THE RESULT THAT MATTERS. 33,164 accesses, every read matching
//! the C#, from a module the converter produced. The hand-written uart.rs
//! passes the same trace -- so on the largest oracle this project has, the
//! generated register layout is indistinguishable from the file a person
//! wrote. That is the thing the whole pipeline exists to demonstrate.
//!
//! EXTI replays perfectly: 25 accesses, every read matching the C#. That is
//! the first evidence in this project that generated code BEHAVES correctly
//! rather than merely compiling.
//!
//! BOTH DMA ROWS MOVED, and how they moved is the point. They were 9.3% and
//! 0.2%; the C# `Stream` class defines its own six registers into the PARENT's
//! bank at `base + id * 0x18`, eight times over, and the register form only
//! ever matched a CONSTANT offset -- so those 48 registers were absent, every
//! read returned 0, and nothing reported a gap because nothing had matched.
//!
//! With offsets allowed to be expressions and the child emitted as a submodule,
//! 5,629 of the 6,252 divergences disappear. What is left is attributable to
//! ONE named gap: every remaining divergence is a read of LowInterruptStatus or
//! HighInterruptStatus, whose per-stream flags are bound by a `for` loop that
//! extends a register builder held in a local -- a shape the layout walker does
//! not emit, and which now reports itself rather than vanishing. 0x20 is bit 5,
//! TCIF0; 0x8000000 is bit 27, TCIF3. Exactly those flags, and nothing else.
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

generated_replay!(syscfg_generated, renode_stm32::syscfg_registers, "syscfg", 0);
generated_replay!(exti_generated, renode_stm32::exti_registers, "exti", 0);
generated_replay!(adc_generated, renode_stm32::adc_registers, "adc1", 1192);
generated_replay!(dma1_generated, renode_stm32::dma_registers, "dma1", 7);
generated_replay!(dma2_generated, renode_stm32::dma_registers, "dma2", 616);
generated_replay!(can1_generated, renode_stm32::can_registers, "can1", 99);

// GPIO and UART already have trace tests -- against the HAND-WRITTEN
// peripherals. Running the GENERATED modules on the same traces is the
// closest thing to a direct comparison this project has: same input, same
// oracle, one file written by a person and one by the converter.
generated_replay!(gpio_a_generated, renode_stm32::gpio_registers, "gpioPortA", 3);
// ZERO, and it must stay zero. 33,164 accesses, every read matching.
generated_replay!(usart1_generated, renode_stm32::uart_registers, "usart1", 0);
