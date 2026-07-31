# Known-equivalent mutants

Mutants that change source but cannot change observable behaviour. Excluded
from the mutation score **only with a reason that can be checked**, because an
exclusion list is otherwise just a place to hide real survivors.

Each entry must say *why* no test could distinguish the mutant — not that none
currently does.

## gpio

| operator | site | why no behaviour changes |
|---|---|---|
| `read->rw` | IDR `FieldMode::READ` → `READ_WRITE` | IDR has a `valueProvider`, which dominates reads, so the slot is never read. Adding WRITE lets the slot be written, and nothing ever reads it. |
| `rw->read` | ODR `READ_WRITE` → `READ` | ODR's writes go through its `writeCallback`, which fires on any register write (matching C# `CallWriteHandler`). Dropping WRITE stops the slot being updated, and the slot is never read because the provider dominates. |
| `write->read` | BSRR set half `WRITE` → `READ` | Same: the set is performed by `bsrr_set`, not by the slot. Becoming readable returns the slot, which stays 0 because `READ` does not write it — indistinguishable from the write-only read-as-zero it replaces. |
| `write->read` | BSRR reset half `WRITE` → `READ` | As above, for `bsrr_reset`. |

**Common cause:** on a field whose behaviour lives entirely in a callback, the
`FieldMode` governs only the backing slot, and the slot is unobservable. This is
faithful to the C#, where `CallWriteHandler` likewise fires regardless of whether
the field's mode caused a value update.

**It is not free.** It means field modes on callback-bearing fields are
documentation rather than behaviour, so an incorrect mode there will not be
caught by any test. Worth knowing when reading such a definition.
