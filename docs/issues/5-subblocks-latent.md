TITLE: sub_blocks: three latent gaps, two of them silent

Found by audit immediately after `plugins/sub_blocks.py` landed. **None fires on
the current cut** -- recorded so they are not rediscovered later as a mystery.

The rule detects a child class that defines registers into its parent's bank and
is instantiated N times. It fires exactly once today, correctly, on
`STM32DMA.streams`, and both discriminators do the claimed work:
`STM32DMA.transferCompleteIrqStatus` is rejected by the back-reference test and
`STM32_ADC.channels` by the register-method test.

## 1. Only arrays are detected, and declining is silent

Detection requires `declared_type LIKE '%[]'`. A `List<Child>` or
`Dictionary<int, Child>` of register-bearing children is not detected and **no
gap is emitted** -- `gap_count` and `gap_identity` only fire once a field has
already passed the `[]` filter. So the container shape decides whether a miss is
visible, which is backwards.

## 2. `const_under` ignores the operator above the constant

It returns the first `Literal` or `FieldReference` in the subtree.
`Enumerable.Range(0, NrOfStreams / 2)` would yield **8, not 4** -- a silently
wrong instance count, hence a silently wrong register map, with no gap. The
existing `split_offset` shows the shape of the fix: recognise the operator, or
decline.

## 3. The range's start is discarded

`array_count` reads only `Range`'s `count`, and the emitted loop is always
`for id in 0..count`. For `Range(1, N).Select(id => new Child(this, id))` the C#
ids are `1..N` while the emitted ids are `0..N-1`, shifting every child's
register block by one step.

## Not a gap

`array_count` looks only at `SimpleAssignment` in the constructor, so a field
initialiser yields None -- but that path DOES report `gap_count`. Visible, and
therefore fine.

## Acceptance

- A register-bearing child in a non-array container is either handled or gapped
- A non-constant or computed count is gapped, never guessed
- A non-zero range start is honoured or gapped
- Each has a `rule_negative` entry so the rule cannot drift back
