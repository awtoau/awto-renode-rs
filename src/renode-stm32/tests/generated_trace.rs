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
//!     can1      228 accesses     28 divergences    75.7%
//!
//! CAN1 MOVED FURTHEST, 13.9% -> 75.7%, and what moved it is a whole SHAPE the
//! converter could not see. `STMCAN` uses no register DSL: it hand-rolls a class
//! per register with `SetValue(uint)`/`GetValue()` over `bool` fields and
//! `const uint` masks, and dispatches with `switch((RegisterOffset)offset)` in
//! `ReadDoubleWord`. The DSL forms found nothing, `define_registers` was `{}`,
//! and NOT ONE of the forty gaps in the file said the type defines no registers.
//!
//! That is not one peripheral. 388 types serve a memory-mapped bus and 104 use
//! no DSL; 59 of those dispatch a constant-case switch on the offset, and 145
//! case bodies across 27 types read a plain field. The accessor-class half is
//! narrow -- 3 types -- and is a SEPARATE rule so it cannot borrow the broad
//! half's count. See rulesdb/rules/offset_switch.json.
//!
//! THE 28 THAT REMAIN ARE NOT LAYOUT, and each was traced to the C# statement
//! that produces the value the trace expects:
//!
//!   * 20 reads of CAN_TSR expecting 0x1C000003 against 0x1C000000. Bits 0 and
//!     1 are RQCP0/TXOK0, set by `TransmitStatusRegister.TxMailbox0Done()`,
//!     which `WriteDoubleWord` calls after a CAN_TI0R write with TXRQ set. That
//!     path runs `TransmitData`, and `CANMessage` has no Rust mapping -- an
//!     existing gap. No register-map work moves these.
//!   * 7 reads of CAN_MSR expecting 0xC01 (once 0xC00) against the reset 0xC02.
//!     `WriteDoubleWord`'s CAN_MCR case sets `MSR.InitAck` when INRQ is set and
//!     SLEEP clear, and clears both acks otherwise. Behaviour, and
//!     `WriteDoubleWord` is withheld.
//!   * 1 first read of CAN_MCR expecting 0x10000 against 0x10002. Neither side
//!     is wrong: 0x10002 is exactly what `DeviceRegisters.Reset()` produces
//!     (`CAN_MCR.SetValue(0x00010002)`), and it is also ST's documented reset
//!     value. The platform description writes `WriteDoubleWord 0x0 0x00010000`
//!     in can1's `init:` block -- before the CPU runs, so before the access log
//!     exists. Replay starts from a reset bank and never applies it. A harness
//!     that seeded the `.repl` init writes would close this one.
//!
//! Cross-checked against ST's own CMSIS header (`cmsis_device_f4`,
//! `stm32f427xx.h`) as a THIRD opinion, used to VERIFY and never to source:
//! every bit the C# declares individually lands on ST's position exactly -- all
//! 10 of MCR, all 9 of MSR, all 14 of IER, all 6 of ESR, FULL/FOVR of both
//! RFxR, TXRQ of TIxR, FINIT and CAN2SB of FMR, and FA1R's 28-bit FACT.
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
//! 5,629 of the 6,252 divergences disappear. Every remaining one is a read of
//! LowInterruptStatus or HighInterruptStatus: 0x20 is bit 5, TCIF0; 0x8000000
//! is bit 27, TCIF7. Exactly those flags, and nothing else.
//!
//! THAT REMAINDER WAS MISATTRIBUTED, and the correction is the useful part.
//! Those flags are bound by a `for` loop extending a register builder held in a
//! local -- a shape the layout walker did not emit, so the obvious reading was
//! that the missing LAYOUT was the cause. The shape is emitted now (all 24
//! combinator calls, the four TCIF flags in each status register at bits 5, 11,
//! 21, 27, bound to `f.transfer_complete_irq_status[0..7]`), and BOTH NUMBERS
//! ARE UNCHANGED. They had to be: a layout gives the register somewhere to put
//! a value, and nothing here computes one. `TCIF` is `FieldMode.Read`, no trace
//! write can set it, and its only C# writer is `Stream.PerformTransfer`, which
//! needs `DmaEngine.IssueCopy` -- a type with no Rust mapping, and a gap this
//! file has always reported.
//!
//! So these 623 are a BEHAVIOUR gap, not a layout one, and no register-map work
//! will move them. A layout claim is falsifiable directly -- set the handle and
//! read the register back -- and doing that is how the misattribution was
//! found; the trace count alone could not tell the two apart.
//!
//! Neither number would be visible from the gap count, which reports the same
//! kind of gap for both.
//!
//! ADC1 IS THE SAME STORY, AND WORSE. Its 1,192 land on exactly two offsets:
//! Status bit 1 (596 reads expecting 0x2, getting 0) and RegularData (all 596
//! of its reads, expecting a sample and getting 0). Both registers ARE in the
//! bank and both ARE wired to the state the C# reads -- tests/adc_semantics.rs
//! sets each by hand and reads it back, so the layout claim is falsified
//! directly rather than inferred. The sole C# writer of both is
//! `OnConversionFinished`, reached from `LimitTimer.LimitReached`.
//!
//! THIS RATCHET WILL NOT COME DOWN, and treating it as one would be a mistake.
//! The trace reads Status as 0, then 0, then 0x2 with NO INTERVENING BUS
//! ACCESS -- a virtual-time event set it, and `Replayable` has no clock. And
//! `adcData` comes from `ADCChannel.GetSample()`, a queue filled by
//! `FeedSample` from the emulation script: the expected 0x5DE / 0x800 / 0x745
//! are external stimulus, not a function of any bus history, so a bus-only
//! replay cannot reproduce them even from a complete port.
//! See docs/issues/6-adc-behaviour-gap.md.
//!
//! ADON's dropped `changeCallback` is NOT the cause: `EnableADC()` assigns
//! `currentChannel` and nothing reads it through a register.

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
            // Five lines cannot tell a missing register from a missing writer
            // -- that distinction needs every divergence, grouped. Set
            // TRACE_DUMP_DIR to write the full list; unset, nothing changes.
            if let Ok(dir) = std::env::var("TRACE_DUMP_DIR") {
                use std::io::Write;
                let dir = std::path::PathBuf::from(dir);
                std::fs::create_dir_all(&dir).expect("dump dir");
                let mut out = std::fs::File::create(
                    dir.join(concat!($trace, "-divergences.txt"))).expect("dump file");
                for d in report.divergences.iter() {
                    writeln!(out, "{d}").expect("dump write");
                }
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
generated_replay!(can1_generated, renode_stm32::can_registers, "can1", 28);

// GPIO and UART already have trace tests -- against the HAND-WRITTEN
// peripherals. Running the GENERATED modules on the same traces is the
// closest thing to a direct comparison this project has: same input, same
// oracle, one file written by a person and one by the converter.
generated_replay!(gpio_a_generated, renode_stm32::gpio_registers, "gpioPortA", 3);
// ZERO, and it must stay zero. 33,164 accesses, every read matching.
generated_replay!(usart1_generated, renode_stm32::uart_registers, "usart1", 0);
