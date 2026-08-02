# `.If(..).Then(..).Else(..)` drops its fields, and nothing says so

Labels: `transpiler`, `bug`, `phase-3`

`PeripheralRegisterExtensions` has a conditional family:

    new DoubleWordRegister(this)
        .WithReservedBits(0, 2)
        .WithFlag(2, out enable, ...)
        .If(series == STM32Series.L5)
            .Then(reg => reg.WithReservedBits(4, 1).WithTaggedFlag("CED", 5) ...)
            .Else(reg => reg.WithReservedBits(4, 28))

The fields inside `Then`/`Else` are installed through the LAMBDA's parameter, so
they share neither the chain's span start nor a chain-root local. They belong to
no chain the layout emitted, and they are not emitted.

## Why no gap appears

`emit_registers` collects unmatched calls in the chain into `skipped`, and
reports them -- but only those whose leaf name starts with `With` or `Define`:

    leaf = symbol.split("(")[0].split(".")[-1]
    if leaf.startswith(("With", "Define")) and leaf not in skipped:

`If`, `Then` and `Else` start with none of those, so they are dropped by the
filter that exists to stop unrelated nested calls being reported. The register
emits its unconditional fields, the conditional ones vanish, and the file's
`GAPS` header says nothing about it.

`register_preamble.emits_registers` does not catch it either: it walks TOP-LEVEL
statements, and these chains sit inside a `VariableDeclarationGroup` that the
preamble skips unless a register offset depends on one of its locals.

## Evidence

`STM32_RNG.Control` -- bits 4..31 are `.WithReservedBits(4, 28)` on this
platform's series and are simply absent from the emitted register. `STM32_CRC.Control`
loses bits 3..4 (`POLYSIZE`) and 5..7 (`REV_IN`, `REV_OUT`) the same way.

## Two separate defects

1. **The filter.** An unmatched call inside a located chain should be reported
   whatever it is called. The `With`/`Define` prefix was added to suppress noise
   from unrelated nested calls; the right discriminator is whether the call's
   RECEIVER is the register, not how the method is spelled.
2. **The family.** `If`/`Then`/`Else` selects between two field sets on a
   condition that is a constructor argument, i.e. constant per instance and NOT
   constant in the corpus. A faithful translation cannot pick a branch; it can
   emit both behind the condition, or withhold and say which condition it could
   not evaluate. Deciding which is the work; (1) is what makes the decision
   visible in the meantime.

Found while fixing the register-owner selector -- both peripherals above build
their maps in a constructor and had never been emitted.
