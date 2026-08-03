TITLE: implementation/status record for #58 — C#/Rust semantic differences

Issue [#58](https://github.com/awtoau/awto-renode-rs/issues/58) has current
measurements and executable rules for its two explicit implementation items.
It is **not close-ready under the literal acceptance text**: finalizers,
disposal, events, shared ownership, and pinning all apply to the full corpus and
remain deferred, so they are neither handled nor not-applicable. This record
makes that remaining scope visible instead of weakening the acceptance test.

Counts below come from the canonical full-tree database (448,375 lines) via
`scripts/semantic_differences_census.py`.

| concern | current full-tree count | classification |
|---|---:|---|
| Finalizers are not `Drop` | **2 actual destructors** (five methods are named `Finalize`, but three are ordinary methods) | **deferred, visible**. `NativeBinder` and `TemporaryFilesManager` need a finalizer-safe ownership analysis. The old “non-issue” classification was wrong after removal of the cut. |
| `IDisposable` / `using` | **126** `Dispose` methods / **215** `Using` operations | **deferred, visible**. The existing refusal covers an `IDisposable` type in a signature, not `using` statement ordering. A general lowering needs `Drop` plus explicit early disposal and must preserve reverse-order cleanup during exceptional exit. |
| Mutable statics | **29 genuinely mutable**; classification below | **handled as faithful refusal**. A general emitter guard withholds any ordinary method accessing one until runtime-owned `OnceLock`/lock storage exists. It can no longer silently become per-instance `State`. |
| Events/delegates | **309** event declarations, **460** assignments, **802** references | **partly handled, documented deviation**. One `FnMut` subscriber is emitted; unsubscribe and multicast ordering remain a D4 runtime component. Every emitted site carries `WARN(multicast)`. |
| Shared mutable object state | **1,426 `SHARED` rows** in `ownership-tree.tsv` | **tracked by #57**. `Gc<T>` field typing is phase 1; target emission and tracing remain deferred there rather than duplicated here. |
| `ref` / `out` | **143 / 610** parameters | **handled for ordinary method emission**. Both become `&mut T`; body reads and writes dereference them, and in-corpus ref/out call arguments borrow mutably. Interface traits already used the same signature rule. More permissive C# aliasing that Rust rejects remains an explicit compile-time gap, never a by-value translation. |
| Interop pinning | **3** `AddressOf` operations | **deferred, visible**. The corpus records pointer expressions but not whether native code retains a managed object address after the call, so a required `Pin<Box<T>>` population cannot be derived yet. Current `renode-tlib` callbacks pass C function pointers and allocator-owned raw buffers, not movable managed object addresses. |

## Static-field classification

The issue's raw 34,886 was not a mutable-state count. The semantic split is:

| class | count |
|---|---:|
| const-valued fields (including enum members) | 34,600 |
| `static readonly`, non-const initialized values | 222 |
| non-readonly, written outside `.cctor` | **29** |
| non-readonly, `.cctor` write only | 2 |
| non-readonly, no recorded write | 33 |

The 29 process-wide mutable instances, enumerated rather than patched by name:

- `XLibHelper`: `DisplayHandle`, `EventListenerThread`
- `SimpleJson`: `currentJsonSerializerStrategy`, `pocoJsonSerializerStrategy`
- `EmulationManager.DisableEmulationFilesCleanup`
- `PseudorandomNumberGenerator.baseSeed`
- `Emulator`: `disposed`, `userDirectoryPath`, `userInterfaceProvider`
- `Logger`: `minLevel`, `nextEntryId`
- `LLVMAssembler.xtensaSupportWarningIssued`
- `LLVMDisassembler.xtensaSupportWarningIssued`
- `EFR32xG24_FlashUserData.count`, `EFR32xG2_DeviceInformation.count`
- `IPpacket.IPHeaderLength`
- `GStreamerWrapper`: `h264Encoder`, `h265Encoder`, `initialized`
- `InterferenceQueue.ForceBusyRssi`
- `SocketsManager.sockets`
- `Command.executingMethods`
- `Misc`: `LastBitmap`, `LastBitmapName`, `cachedRootDirectory`
- `VideoCapturer`: `bufferAllocated`, `fd`, `loggingParent`, `started`

This is a corpus-derived rule: `const_value IS NULL`, not readonly, and at
least one recorded write whose containing member is not `.cctor`. No Renode
type or field name occurs in the emitter.

## Verification

`scripts/check_semantic_differences.py` has positive controls for an ordinary
`ref int` method, an invocation with two `out` arguments, and a real mutable
static access, plus a negative control and a partition check over all statics.
