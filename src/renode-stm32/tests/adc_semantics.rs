//! Why the GENERATED `STM32_ADC` map diverges 1,192 times, proved rather than
//! inferred.
//!
//! The adc1 trace is 16,800 accesses and 1,192 divergences, and they land on
//! exactly two offsets:
//!
//!     0x00 Status       596 of 1,858 reads   expected 0x2, got 0x0  (bit 1)
//!     0x4C RegularData  596 of   596 reads   expected the sample, got 0
//!
//! A trace count cannot tell a MISSING REGISTER from a PRESENT REGISTER THAT
//! NOTHING WRITES -- both read back 0. That mistake was already made once on
//! DMA, where the accepted explanation was a layout gap and the truth was a
//! behaviour gap. So the claim is made falsifiable here: set the state by hand
//! and read the register back. If the layout were the problem these tests
//! would fail.
//!
//! They pass. Both registers are in the bank, both are wired to the state the
//! C# reads, and the only thing absent is the code that produces a value.
//!
//! THE C# CHAIN, in full, because that is the deliverable of the diagnosis:
//!
//!     Control2 bit 30 write  -> writeCallback -> StartConversion()
//!     StartConversion()      -> samplingTimer.Enabled = true      [LimitTimer]
//!     LimitTimer.LimitReached (VIRTUAL TIME, no bus access)
//!                            -> OnConversionFinished()
//!     OnConversionFinished() -> currentChannel.PrepareSample()    [ADCChannel]
//!                            -> adcData = currentChannel.GetSample()
//!                            -> endOfConversion.Value = ...true
//!
//! `LimitTimer` and `ADCChannel` have no emitted Rust type, and the ADC's
//! `channels`, `currentChannel`, `samplingTimer` and `machine` fields are all
//! reported as gaps in the generated file's header. So the writer cannot be
//! emitted today.
//!
//! IT IS ALSO UNREACHABLE BY THIS ORACLE, which is the sharper point. The trace
//! shows Status read as 0, read as 0, then read as 0x2 with NO INTERVENING BUS
//! ACCESS -- the flag is set by a virtual-time event. `Replayable` is
//! read/write/reset and has no clock, so even a complete translation of
//! `OnConversionFinished` would still diverge here unless the sampling timer
//! and the machine clock were modelled too. No register-map work moves these
//! 1,192, and neither would a faithful port on its own.
//!
//! ADON's dropped `changeCallback` is NOT the cause. It calls `EnableADC()`,
//! whose whole body is `currentChannel = channels[regularSequence[
//! currentChannelIdx].Value]` -- it assigns a field that no register reads.
//! Wiring it would move zero divergences.

use renode_regs::Bank;
use renode_stm32::adc_registers as m;

fn adc() -> (Bank<m::State>, m::State) {
    let mut bank: Bank<m::State> = Bank::new();
    let mut fields = m::Fields::default();
    m::define_registers(&mut bank, &mut fields);
    let mut state = m::State::default();
    state.f = fields;
    (bank, state)
}

#[test]
fn status_bit_1_is_present_in_the_map_and_reads_back() {
    // The 596 divergences at 0x00 are all `expected 0x2, got 0x0`. If EOC were
    // missing from the layout this would return 0 and the DMA-style
    // misattribution would be correct.
    let (bank, mut st) = adc();
    assert_eq!(bank.read(m::reg::STATUS, &mut st), Some(0));
    bank.set_flag(st.f.end_of_conversion, true);
    assert_eq!(
        bank.read(m::reg::STATUS, &mut st),
        Some(0x2),
        "EOC is bit 1 of Status and is bound: the layout is not the gap"
    );
}

#[test]
fn the_traces_own_status_write_clears_eoc() {
    // The firmware clears EOC with 0xFFFF_FFED (and arms with 0xFFFF_FFDD);
    // both appear 596 times in adc1. The write path is honoured -- which is
    // why 1,262 of the 1,858 Status reads match at 0.
    let (bank, mut st) = adc();
    bank.set_flag(st.f.end_of_conversion, true);
    bank.write(m::reg::STATUS, 0xFFFF_FFED, &mut st);
    assert_eq!(bank.read(m::reg::STATUS, &mut st), Some(0));
    bank.set_flag(st.f.end_of_conversion, true);
    bank.write(m::reg::STATUS, 0xFFFF_FFDD, &mut st);
    assert_eq!(bank.read(m::reg::STATUS, &mut st), Some(0));
}

#[test]
fn regular_data_returns_adc_data_and_clears_eoc() {
    // 0x4C diverges on all 596 of its reads, expecting 0x5DE, 0x800 or 0x745 --
    // the samples. The provider callback IS emitted and IS wired to `adc_data`;
    // nothing ever assigns `adc_data`, because that is
    // `OnConversionFinished`'s line and it is withheld.
    let (bank, mut st) = adc();
    assert_eq!(bank.read(m::reg::REGULAR_DATA, &mut st), Some(0));

    st.adc_data = 0x5DE;
    bank.set_flag(st.f.end_of_conversion, true);
    st.irq = true;
    assert_eq!(
        bank.read(m::reg::REGULAR_DATA, &mut st),
        Some(0x5DE),
        "the value provider reads adc_data: the layout is not the gap"
    );
    // The C# side effects of that read, both faithful.
    assert!(!bank.flag(st.f.end_of_conversion), "reading DR clears EOC");
    assert!(!st.irq, "reading DR drops IRQ");
}

#[test]
fn no_bus_write_in_the_trace_can_produce_either_value() {
    // The load-bearing test. Replay every WRITE adc1 makes, in order, and then
    // check the two diverging registers. If any bus access could set EOC or
    // adc_data, this fails and the diagnosis is wrong.
    let (bank, mut st) = adc();
    for (offset, value) in [
        (m::reg::CONTROL1, 0x100u64),
        (m::reg::CONTROL2, 0x402),
        (m::reg::CONTROL2, 0x403),
        (m::reg::CONTROL2, 0x4000_0403), // SWSTART -- starts a conversion
        (m::reg::STATUS, 0xFFFF_FFDD),
        (m::reg::STATUS, 0xFFFF_FFED),
        (m::reg::SAMPLE_TIME1, 0x00E0_0000),
        (m::reg::SAMPLE_TIME2, 0x0000_0000),
        (m::reg::REGULAR_SEQUENCE1, 0x0010_0000),
        (m::reg::REGULAR_SEQUENCE3, 0x0000_0011),
    ] {
        bank.write(offset, value, &mut st);
    }
    assert!(
        !bank.flag(st.f.end_of_conversion),
        "no write sets EOC -- its only C# writer is OnConversionFinished"
    );
    assert_eq!(
        st.adc_data, 0,
        "no write produces a sample -- adcData is assigned only from \
         currentChannel.GetSample() in OnConversionFinished"
    );
    // And the register that DOES have a writer emitted proves the write path
    // is not simply dead: RegularSequence1 bits 20..23 drive the length.
    assert_eq!(
        st.regular_sequence_len, 2,
        "L = 1 in RQS1[23:20] means a two-conversion sequence; this callback \
         IS emitted, so a missing writer is a per-callback fact, not a \
         wholesale one"
    );
}
