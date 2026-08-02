# Audit: every path that can emit nothing

Issue #53. Six paths in one session produced no output and reported no reason,
and each was indistinguishable from a rule that correctly declined. Two were
reported as landed before anyone noticed; one survived two commits.

`core.must_explain` enforces the invariant where it applies:

> A path that produces no output MUST record why — a gap, an `unhandled`
> entry, or an exception.

It cannot be applied blindly. Some paths return empty **legitimately**, and
wrapping those would raise on correct behaviour. The distinction is whether
empty means *"I could not"* or *"there was nothing"*.

## Guarded — empty always means failure

| path | why empty is always a defect |
|---|---|
| `emit_peripheral_method` | a method with a body must produce lines; found the missing-method case |
| `emit_lambda` | a callback body that emits nothing cannot be a callback |
| `emit_switch` | a `Switch` node has arms by construction |
| `emit_loop` | a `Loop` node has a body by construction |

## Not guarded — empty is a valid answer

| path | why |
|---|---|
| `emit_stmt` | `Empty`, `Branch` and the mandatory C# `break` legitimately emit nothing |
| `emit_block` | an empty block is empty |
| `emit_call` | a combinator rule may declare `emit: null` deliberately — the register-level callback rule does exactly that, to avoid emitting guesswork |
| `emit_expr` | never returns empty; it returns a marker, which the withhold checks catch |
| `emit_registers` | a type with no registers is a fact, not a failure |

## Still to do

`emit_interface_trait`, `emit_assignment`, `emit_body`, `emit_method` and
`emit_file` are unaudited. Each needs the same question asked: when this
returns nothing, is that an answer or a failure?

## The rule for new code

If you write a path that can return empty, decide which kind it is **at the
time you write it**. If it is a failure, wrap it. If it is an answer, add a
row above saying why. Leaving it undecided is how all six got in.
