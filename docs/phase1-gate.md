# Rule-leverage gate (#14)

**Verdict: PASS.**

The question: after translating one peripheral, how much of an *unseen* second
one is already covered? If file two costs what file one cost, the rule thesis
has failed and the project stops.

Measured on `STM32_GPIOPort` (376 lines, 48 DSL calls) with `STM32_UART` as the
only peripheral translated so far.

## Shape co-occurrence

| | subtrees | nodes | share |
|---|---:|---:|---:|
| GPIOPort rule-able subtrees | 294 | 2,647 | 100% |
| shape also occurs in **UART** | 129 | 1,502 | **56%** |
| shape occurs anywhere else in corpus | 262 | 2,425 | **91%** |
| GPIOPort-only | — | 222 | 9% |

**56% of the second peripheral's rule-able content is shapes the first already
contained.** Only 9% is unique to the file.

A first attempt measured 2% and was wrong: it asked whether a cluster's
*exemplar* sat in UART, but exemplars are chosen as the smallest cluster member
and so land wherever the shortest instance happens to be. The right question is
whether the shapes **co-occur**.

## DSL combinator reuse

| combinator | calls | already built for UART? |
|---|---:|---|
| `WithTaggedFlag` | 33 | yes |
| `WithValueField` | 5 | yes |
| `WithReservedBits` | 5 | yes |
| `WithEnumFields` | 3 | **new** (plural form) |
| `WithValueFields` | 2 | **new** (plural form) |

**43 of 48 calls (90%)** use combinators the UART work already established.

## What is genuinely new

Not the register definitions — the surrounding machinery:

- `BaseGPIOPort` base class (first inheritance case)
- `ILocalGPIOReceiver`, `GPIOAlternateFunction` — alternate-function routing
- Pin mode / output speed / pull-up-down state outside the register file
- Constructor validation raising `ConstructionException`

This is the expected shape: the *declarative* half transfers almost entirely,
the *behavioural* half is per-peripheral. It matches the density measurement
that motivated the project (RCC 240 `With*` calls in 404 lines vs STMCAN 1 in
1957).

## Caveat

This measures **shape coverage, not correctness**. Tier 2's limit applies: a
matching shape means a rule can be *applied*, not that the result is right. See
the mutation-testing result on `STM32_UART` — a real semantic change (RXNE
`W0C`→`W1C`) survived a 33,164-access trace because the firmware never exercises
that path.
