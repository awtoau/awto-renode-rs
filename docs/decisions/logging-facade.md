# Logging: `Logger.*Log` maps to Rust's `log` crate facade

## Status

Landed (rule in `rulesdb/rules/register_dsl.json`, `"logging"` section;
dependency in `src/renode-stm32/Cargo.toml`), but bundled silently into commit
`018c5500` (31 Jul) alongside unrelated emitter changes and never written up as
its own decision. This backfills that record.

## Why this is a substitution decision, not a transpile gap

`Antmicro.Renode.Logging.Logger.LogAs` (and the `*Log` extension wrappers over
it) is not a self-contained algorithm. It reaches into:

```
Logger.LogAs -> EmulationManager.Instance.CurrentEmulation.CurrentLogger
             -> ActualLogger.ObjectInnerLog
```

`ActualLogger` fans a message out to every registered `ILoggerBackend`, checks
a per-machine, per-peripheral custom log level override, and holds locks over
backend registration. None of `EmulationManager`, `CurrentEmulation`, or the
backend abstraction is ported — they are core Renode infrastructure in the same
class as `sysbus`/`machine`/NVIC, which PLAN.md already defers to a later
phase. Transpiling `Logger.LogAs` faithfully would mean transpiling that whole
subsystem first. That makes this a D1–D4-style infrastructure substitution, not
a case of the converter failing to reach otherwise-transpilable logic (which is
what issue #63 is, for `BitHelper`/`Misc`/`DebugHelper`).

## What was decided

Every `this.DebugLog(...)` / `WarningLog` / `NoisyLog` / `ErrorLog` / `Log(level, ...)`
call maps to the matching `log` crate macro (`log::debug!`, `warn!`, `trace!`,
`error!`), added as a real Cargo dependency (`log = "0.4"`).

## What is lost

The `log` crate is a facade with no default sink — nothing is emitted unless the
embedding binary wires a subscriber (`env_logger`, etc.), which is out of scope
here. Additionally, none of the following on Renode's side carry over:

- Automatic peripheral-name prefixing (Renode's log line names the emitting
  object; `log`'s macros only carry the Rust module path, and only if a
  subscriber chooses to print it)
- Per-peripheral custom log level overrides (`BackendState.PeripheralsCustomLogLevel`)
- Multi-backend fanout (console, file, GUI backends simultaneously)

## Failure mode

A trace-replay divergence whose only difference is log output would be a false
positive under this decision (the oracle compares register/state effects, never
log lines) -- so this decision cannot itself break the oracle. It can make
debugging a real divergence harder: a message that should name the failing
peripheral instead shows only a Rust module path. That cost is accepted for now
because no divergence investigation to date has needed peripheral-name context
from a log line to find its cause.

## What would overturn it

The follow-up below, built once the Emulation/machine layer exists to host it --
or sooner, if a divergence investigation is ever blocked specifically by missing
peripheral-name context in log output, which would move this from "future work"
to "now."

## Follow-up

A faithful replacement — a small local logging facade that prefixes messages
with the peripheral name and supports per-peripheral level overrides, matching
what Renode's `ActualLogger` actually does — is plausible future work once
enough of the machine/emulation infrastructure exists to give it something to
plug into. Recorded here rather than assumed unnecessary. Until then, `log`
macros are the mapping in effect and every message compiles and routes
somewhere, faithful to level and message content, unfaithful to prefixing and
per-peripheral overrides.
