# Read the C# beside the Rust, one peripheral per session

**Taken 2026-08-02.**

A line-by-line comparison of generated Rust against its C# source is now routine
work, not a response to a symptom. One peripheral per session, prioritising
those never read.

## The evidence

The first such audit ran on 2026-08-02, over seven files, and found three
defects in an afternoon:

- **STM32_SYSCFG's register map was entirely empty.** `define_registers` was
  `{}`, an offset constant declared and never used, four gaps reported and none
  of them about registers.
- **Five of STM32_GPIOPort's eleven registers were absent.** Three reported
  "callback needs peer method", which is *documented* to mean the layout is
  still correct. It was not. Two reported nothing.
- **Two register-level write callbacks dropped in STM32_UART**, on flags that
  are WriteZeroToClear — so clearing them never recomputes the interrupt line.

All four automated checks passed on every one of these.

## Why the checks cannot replace it

| check | why it missed this |
|---|---|
| `check_generated` | proves byte-identity with converter output, which held |
| `check_refactor` | proves a change altered nothing, not that the output was right |
| `compile_check` | an empty register map is perfectly well-formed Rust |
| trace replay | syscfg is 9 accesses with a ratchet of 2; exti has zero writes; usart1 cannot observe an interrupt line |

Each answers a question that is cheap to ask. **None of them asks whether the
output is the same peripheral.**

Note the third finding especially: usart1 replays 33,164 accesses at 100% and
was still missing two callbacks. The strongest oracle in the project did not
see it, because the trace records register accesses and the defect moves an
interrupt line.

## The counter-argument, and why it lost

Reading is the most expensive check per run and does not scale — it is roughly
one agent-session per peripheral, against seconds for the automated ones.

It won because the automated checks are cheap *and* blind to the defect class
that matters most here: output that compiles, replays and reproduces, and is
wrong. That class has now produced seven known defects in this project. Nothing
else has found one.

## Scope

- One peripheral per session, unread ones first. Seven files have been read
  once; the rest of the cut never has.
- The finding must name the Rust line, the C# line, what differs, and **whether
  any existing check could have caught it** — that last part is what turns an
  audit into a new check rather than a one-off.
- A clean result is reported as such. "I looked at tag-versus-stored across five
  files and found one conflation" is worth as much as a defect, provided the
  looking actually happened.

## What would overturn this

Two or three consecutive audits finding nothing, which would suggest the defect
class has been closed by the checks that came out of earlier audits — the
intended outcome, and the point at which the cadence should drop rather than
continue out of habit.
