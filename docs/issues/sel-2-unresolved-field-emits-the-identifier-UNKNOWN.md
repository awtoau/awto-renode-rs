# An unresolved field handle emits the identifier `UNKNOWN`

Labels: `transpiler`, `bug`, `phase-3`

Two sites, both in the same shape:

    scripts/emitter/plugins/renode_expressions.py:37
        env["field"] = self.receiver_field(oid) or "UNKNOWN"
    scripts/emit.py:450
        field=self.receiver_field(target_id) or "UNKNOWN", value=value)

When `receiver_field` cannot name the field a `.Value` read refers to, the
emitter substitutes the literal string `UNKNOWN` and emits the line anyway.

## What comes out

`STM32F4_RCC`, whose `ClockControl` register binds five handles with
`out var` -- a LOCAL, not a field -- and reads them back from provider
callbacks:

    .WithFlag(0, out var hsion, name: "HSION")
    .WithFlag(1, FieldMode.Read, valueProviderCallback: _ => hsion.Value, ...)

emits

    .with_flag_anon(0, FieldMode::READ_WRITE)
    ...
    fn clock_control_1_provider(bank: &Bank<State>, st: &mut State, ...) -> u64 {
        return u64::from(bank.flag(st.f.UNKNOWN));
    }

Seven such functions in that one file. `Fields` has no member `UNKNOWN`, so
each is an E0609 -- which is the good case. The bad case is a corpus where
something IS called `UNKNOWN`.

Across everything `compile_check.py` emits: **73 occurrences in 12 modules**
(`stm32f4_rcc`, `stm32h7_rcc`, `stm32l0_rcc`, `stm32wba_rcc`, `stm32sdmmc`,
`arm_smmuv3`, `sam4s_dacc`, `sam_trng`, `nrf_clock`, `max32650_i2c`,
`litex_i2c_zephyr`, `opentitan_bignumberaccelerator`).

## Why it matters beyond the compile error

It is the failure the work protocol names: a path that could not do its job
emitted something that looks finished instead of saying why. There is no gap
line for it, so the file's `GAPS` header reads as though the callback was
translated. The rule that a withheld path must explain itself has a decorator
(`core.must_explain`) and these two sites predate it.

## The real gap underneath

`out var x` in a combinator is a register handle bound to a LOCAL. The emitter
models handles as fields of `Fields`, so a local-bound handle has nowhere to
live and the combinator degrades to its `_anon` form -- correctly, since no
field exists -- but every later read of `x.Value` then has nothing to name.

Two honest outcomes, either of which is better than `UNKNOWN`:

  * promote a local-bound handle to a `Fields` member (it is a handle with a
    known name; the C# local's scope is the map builder, which is exactly the
    scope of `define_registers`), or
  * withhold the callback and report `provider for bit N reads a handle bound
    to a local, which has no emitted storage`.

The first is a translation. The second is a gap. `UNKNOWN` is neither.

Found while fixing the register-owner selector; `STM32F4_RCC` had never been
emitted before, so these sites had never been reached on the target platform.
