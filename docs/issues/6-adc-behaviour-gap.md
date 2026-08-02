TITLE: adc1's 1,192 divergences are a behaviour gap, and one this oracle cannot reach

`adc1` was the largest unattributed block on the trace scorecard: 1,192
divergences over 11,415 reads, 89.6%. It is now attributed, and the attribution
is falsifiable rather than argued.

## The breakdown

Dumped in full — `TRACE_DUMP_DIR=... cargo test -p renode-stm32 --test
generated_trace`, then `python3 scripts/analyse_divergences.py adc1`. Both are
new; the harness previously printed five lines, which cannot separate a missing
register from a present one nobody writes.

| offset | register | reads | writes | diverge | first | expected → got | diff bits |
|---|---|---|---|---|---|---|---|
| 0x00 | Status | 1,858 | 1,192 | **596** | #63 | `0x2` → `0x0` (×596) | `0x2` |
| 0x4C | RegularData | 596 | 0 | **596** | #66 | `0x5DE`→`0` ×298, `0x800`→`0` ×297, `0x745`→`0` ×1 | `0xFDF` |

Nothing else diverges. Control1, Control2, SampleTime1/2, RegularSequence1/3 —
9,965 reads, zero divergences. The diff mask at 0x00 is one bit.

## Not a layout gap

Both registers are in the bank and both are wired to the state the C# reads.
`src/renode-stm32/tests/adc_semantics.rs` proves it directly: set
`f.end_of_conversion` and Status reads `0x2`; set `adc_data` and RegularData
reads it back and clears EOC and IRQ as the C# does. If the layout were the
cause those tests would fail.

The write path is live too — the firmware's own `0xFFFF_FFED` and `0xFFFF_FFDD`
clear EOC, which is why 1,262 of the 1,858 Status reads match at 0.

A line-by-line comparison of `adc_registers.rs` against `STM32_ADC.cs` found no
difference in any of the 13 defined registers: same offsets, same field
positions and widths, same modes, same tag/reserved split, and the two emitted
callbacks (`Control2` bit 30's `valueProviderCallback: _ => false`,
`RegularSequence1` bits 20–23's length writeback) are faithful.

## The C# chain, in full

    write Control2 bit 30  -> writeCallback -> StartConversion()
    StartConversion()      -> samplingTimer.Enabled = true       [LimitTimer]
    LimitTimer.LimitReached  -- VIRTUAL TIME, no bus access --
                           -> OnConversionFinished()
    OnConversionFinished() -> currentChannel.PrepareSample()     [ADCChannel]
                           -> adcData = currentChannel.GetSample()
                           -> endOfConversion.Value = scanModeActive
                                ? (endOfConversionSelect.Value || scanModeFinished)
                                : true

`OnConversionFinished` is the **only** writer of both diverging values.
`LimitTimer` and `ADCChannel` have no emitted Rust type; the ADC's `channels`,
`currentChannel`, `samplingTimer` and `machine` fields are all already reported
as gaps in the generated file's header, as is `OnConversionFinished` itself.

## ADON's dropped changeCallback is not the cause

`Control2` bit 0 binds `changeCallback: (_, val) => { if(val) EnableADC(); }`,
dropped for years and reported since the DSL-families work. `EnableADC`'s
entire body is

    currentChannel = channels[regularSequence[currentChannelIdx].Value];

It assigns a field no register reads. Wiring it moves **zero** divergences, and
`EnableADC` is itself withheld for reaching `channels`/`currentChannel`.

## Why no faithful port would move it either

This is the part worth keeping. The trace reads Status as `0`, then `0`, then
`0x2` — **three consecutive reads with no intervening bus access.** The flag is
set by a virtual-time event. `Replayable` is `read`/`write`/`reset` and has no
clock, so a complete translation of `OnConversionFinished` would still diverge
at 0x00 unless the sampling timer and the machine clock were modelled too.

0x4C is stronger still: `adcData` comes from `ADCChannel.GetSample()`, which
dequeues a `Queue<uint>` filled by `FeedSample` from the emulation script. The
expected values `0x5DE`, `0x800`, `0x745` are **external stimulus**, not a
function of any bus history. A bus-only replay cannot reproduce them in
principle, because the trace does not record where they came from.

So 1,192 is not a ratchet that will come down with register-map work, and
should not be treated as one.

## Acceptance

- [x] all 1,192 dumped and grouped, not five
- [x] layout claim falsified directly rather than inferred from the count
- [x] `adc_registers.rs` compared line by line against `STM32_ADC.cs`
- [x] the ADON hypothesis tested and rejected with the reason
- [ ] the scorecard distinguishes "reachable by this oracle" from "not"; adc1's
      596 at 0x4C belong in the second column and no ratchet should imply
      otherwise
