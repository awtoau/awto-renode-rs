# Exceptions: mapping C# onto a language that has none

Research for issue #39. Nothing here is implemented; this document exists to
settle *which* mechanism the emitter should build before anyone builds it.

**It reopens declared deviation D4.** PLAN.md states:

> ### D4 — Exceptions → `Result`, panics for the fatal
>
> Renode's `RecoverableException` / `ConstructionException` become
> `Result<T, RenodeError>` threaded with `?`.

That was decided before the register DSL's callback types were committed. The
two are not compatible, and section 5 shows the exact call chain in the corpus
where the `?` chain has nowhere to go. Per CLAUDE.md a deviation is reopened,
never silently revisited — this is the reopening.

---

## 0. Recommendation in one paragraph

Translate `throw` to a **typed unwinding panic** (`panic_any` with a
`CsException` payload), and translate `catch` to `catch_unwind` +
`downcast` + `resume_unwind` for anything not matched. Do **not** thread
`Result` through translated method signatures. `finally` and `using` become
scope guards, which Rust's `Drop` implements faithfully for every corpus shape
present. This is the only option that leaves the DSL's
`ValueProvider`/`WriteCallback` signatures untouched, because it does not
colour signatures at all. Its failure mode is `panic = "abort"`: a profile
setting three lines long silently converts every translated `catch` into a
process abort, and no test in this repo would currently notice. That risk is
managed by pinning the profile and CI-checking it, not by hoping.

---

## 1. What the corpus actually contains

Query from the issue, against `rulesdb/patterns.db` (run 1, config `f427`,
Renode `dc52b24c`):

```
CatchClause|10
Throw|116
Try|10
Using|2
```

`Finally` returns nothing, and that is not an absence of finally blocks — **Roslyn
has no `Finally` operation kind**. `ITryOperation` exposes `.Finally` as a
`IBlockOperation`, so a finally block is ingested as an ordinary `Block` child.
One try in the cut has three children (`Block, CatchClause, Block`); the trailing
Block is its finally. See section 7 — this is the first ingest finding.

### Thrown types

Read from the `ObjectCreation` grandchild of each `Throw` (the `Throw` node
itself records nothing — second ingest finding):

| type | count | role |
|---|---:|---|
| `System.ArgumentException` | 46 | precondition / contract |
| `Antmicro.Renode.Exceptions.RecoverableException` | 22 | user error |
| `Antmicro.Renode.Exceptions.ConstructionException` | 19 | user error (subclass of the above) |
| `System.ArgumentNullException` | 7 | contract |
| `System.ArgumentOutOfRangeException` | 4 | contract |
| `System.InvalidOperationException` | 4 | contract |
| `CpuAbortException` | 3 | **control flow** |
| `System.IO.EndOfStreamException` | 2 | recoverable I/O |
| `System.IndexOutOfRangeException` | 2 | contract |
| `System.Diagnostics.UnreachableException` | 1 | assertion |
| `System.FormatException` | 1 | contract |
| `System.NotImplementedException` | 1 | assertion |
| (rethrow / `Argument` child) | 4 | — |

Contract violations are 64 of 116 (55%). `RecoverableException` and its
subclass are 41 (35%).

### Reach

This is the number that decides the design:

```sql
WITH RECURSIVE reach(mid) AS (
  SELECT DISTINCT o.method_id FROM operation o WHERE o.kind='Throw'
  UNION
  SELECT cs.caller_id FROM reach r JOIN call_site cs ON cs.callee_id = r.mid)
SELECT COUNT(*) FROM reach;              -- 366
SELECT COUNT(*) FROM method WHERE has_body=1;  -- 1277
```

**366 of 1,277 methods with a body — 28.7% — can transitively reach a `throw`**,
counting only in-corpus static call edges. Virtual dispatch and BCL calls are
excluded, so it is a lower bound. Any signature-colouring scheme has to recolour
at least a quarter of the deliverable.

Named examples in the peripherals already being translated:

```
BaseGPIOPort.SetConnectionStateBit     STM32F4_RTC.UpdateTimeState
STM32_GPIOPort.GetLocalReceiver        STM32F4_RTC.ReadDoubleWord
STM32_GPIOPort.Reset                   STM32_Timer.InputPrescalerDivider
STM32_UART.get_StopBits                STM32_UART.DefineRegisters
```

`src/renode-stm32/src/gpio_registers.rs` already carries the resulting gap:

```
//!   - SetConnectionStateBit: withheld, cannot emit stmt:Throw
```

### Implicit finally outnumbers explicit finally 110 to 1

The cut has **one** written `finally`. It also has 42 `lock` statements and 66
`foreach` loops, and in C# both lower to try/finally — `Monitor.Enter`/`Exit`
and `IEnumerator.Dispose` respectively. Plus 2 `using`. So the cleanup shapes
that must survive translation number ~111, of which exactly one is spelled
`finally`. That ratio matters: Rust's `Drop` handles the implicit 110 for free
(a `MutexGuard` drops, an iterator drops) and only the explicit one needs
emitter work.

### One thing the corpus rules out

```
$ grep -rn "catch.*) when (" --include=*.cs src/ | wc -l
0
```

**Zero exception filters in the entire Renode tree.** `catch (X) when (cond)`
needs no support. That is worth knowing, because filters are the one C#
exception feature with no clean Rust analogue at all — a filter runs *before*
unwinding, on top of the throwing frame, and `catch_unwind` runs strictly after.
IL2CPP hits exactly this and ships the divergence knowingly (section 2.1). Had
there been any filters here, the recommendation below would change. Ingest should
still record filter presence so a future corpus fails loudly rather than
silently dropping the condition — see section 7.

---

## 2. Prior art

### 2.1 IL2CPP — C# to C++ (Unity)

IL2CPP is the closest shipping analogue of this project. It does **not** eliminate
exceptions — it maps managed exceptions onto native C++ exceptions. From
[*IL2CPP internals: A tour of generated code*](https://unity.com/blog/engine-platform/il2cpp-internals-a-tour-of-generated-code):

> "Managed exceptions are converted by il2cpp.exe to C++ exceptions. We have
> chosen this path to again avoid platform-specific solutions. When il2cpp.exe
> needs to emit code to raise a managed exception, it calls the
> il2cpp_codegen_raise_exception function."

`il2cpp_codegen_raise_exception` bottoms out in `vm/Exception.cpp` as a real
C++ throw of a wrapper:

```cpp
NORETURN void Exception::Raise(Il2CppException* ex, MethodInfo* lastManagedFrame)
{
    PrepareExceptionForThrow(ex, lastManagedFrame);
    throw Il2CppExceptionWrapper(ex);
}
```

`catch` is **not** C++ `catch (SpecificType&)`. Every handler catches the one
wrapper type and does a manual assignability test, rethrowing on no match:

```cpp
	catch(Il2CppExceptionWrapper& e)
	{
		__exception_local = (Exception_t7 *)e.ex;
		if (il2cpp_codegen_class_is_assignable_from (&InvalidOperationException_t7_il2cpp_TypeInfo, e.ex->object.klass))
			goto IL_0097;
		throw e;
	}
```

That is structurally identical to the `downcast` + `resume_unwind` in section 6,
and for the same reason: one payload type, dynamic test, rethrow if not ours.

**`finally` is the part IL2CPP has to build by hand**, because IL's `leave` and
C++'s scope-based cleanup do not line up. From
`libil2cpp/codegen/il2cpp-codegen-common.h`
([mirror](https://raw.githubusercontent.com/yimengfan/BDFramework.Core/master/HybridCLRData/il2cpp_plus_repo/libil2cpp/codegen/il2cpp-codegen-common.h)):

```c
// Exception support macros
#define IL2CPP_LEAVE(Offset, Target) \
    __leave_targets.push(Offset); \
    goto Target;

#define IL2CPP_END_FINALLY(Id) \
    goto __CLEANUP_ ## Id;

#define IL2CPP_JUMP_TBL(Offset, Target) \
    if(!__leave_targets.empty() && __leave_targets.top() == Offset) { \
        __leave_targets.pop(); \
        goto Target; \
        }

#define IL2CPP_RETHROW_IF_UNHANDLED(ExcType) \
    if(__last_unhandled_exception) { \
        ExcType _tmp_exception_local = __last_unhandled_exception; \
        __last_unhandled_exception = 0; \
        il2cpp_codegen_raise_exception(_tmp_exception_local); \
        }
```

Every EH-bearing method opens with a fixed prologue — an `alloca`-backed stack of
pending leave targets, sized to the method's nesting depth:

```cpp
	Exception_t * __last_unhandled_exception = 0;
	NO_UNUSED_WARNING (__last_unhandled_exception);
	Exception_t * __exception_local = 0;
	NO_UNUSED_WARNING (__exception_local);
	void* __leave_targets_storage = alloca(sizeof(int32_t) * 1);
	il2cpp::utils::LeaveTargetStack __leave_targets(__leave_targets_storage);
	NO_UNUSED_WARNING (__leave_targets);
```

and a `try`/`finally` (here, the implicit one a `foreach` lowers to) comes out as:

```cpp
IL_0053:
		{
			IL2CPP_LEAVE(0x6A, FINALLY_0055);
		}
	} // end try (depth: 1)
	catch(Il2CppExceptionWrapper& e)
	{
		__last_unhandled_exception = (Exception_t *)e.ex;
		goto FINALLY_0055;
	}

FINALLY_0055:
	{ // begin finally (depth: 1)
		... Dispose() ...
		IL2CPP_END_FINALLY(85)
	} // end finally (depth: 1)
	IL2CPP_CLEANUP(85)
	{
		IL2CPP_JUMP_TBL(0x6A, IL_006a)
		IL2CPP_RETHROW_IF_UNHANDLED(Exception_t *)
	}
```

Read as an algorithm: the finally is a labelled block reached by `goto` from both
the normal path and the exceptional path; the exceptional path first *swallows*
the C++ exception into `__last_unhandled_exception`; the cleanup block is a jump
table that pops the pending leave target and resumes, or re-raises if nothing
matched. Older IL2CPP used a single `int __leave_target`; it became a stack
because a single slot cannot represent two pending targets in nested try/finally.

**What it gets wrong / gives up.**

- Unity documents a **spec divergence on exception filters**
  ([IL2CPP limitations](https://docs.unity3d.com/6000.0/Documentation/Manual/scripting-restrictions.html)):
  > "IL2CPP supports exception filters. However, the execution order of filter
  > statements and catch blocks is different because IL2CPP uses C++ exceptions
  > to implement managed exceptions. This isn't noticeable unless a filter block
  > writes to a field."

  It falls straight out of the codegen: C++ `catch` unwinds before the handler
  runs, so the CLR's two-phase "run all filters, *then* unwind" cannot be
  expressed. This is the same reason section 1's zero-filters finding matters —
  `catch_unwind` has the identical limitation, and IL2CPP is the evidence that a
  production translator ships with it unfixed.
- Integer **divide-by-zero checks are off by default**
  ([runtime checks](https://docs.unity3d.com/6000.0/Documentation/Manual/il2cpp-runtime-checks.html)),
  so `x / 0` in a shipped build is C++-level UB rather than a managed exception.
  A silent, on-by-default divergence from the CLI spec.
- Generated code is unreadable, and every EH-bearing method pays the prologue
  whether or not anything throws.
- It presumes the target has exceptions. On one that does not, this scheme is
  necessary but not sufficient.

**What we take from it.** The leave-target stack exists for exactly one reason: a
`finally` sits between a `return` and the function exit. That is not hypothetical
here — **5 of the 10 `try` statements in the cut contain a `return` inside the
try body, and 3 of the 10 catch clauses do** (section 6 gives the Rust lowering).

### 2.2 Go — a language that genuinely has no exceptions

Go is the honest test case, and the Go FAQ is explicit that this is a design
position, not an omission ([go.dev/doc/faq](https://go.dev/doc/faq)):

> "We believe that coupling exceptions to a control structure, as in the
> `try-catch-finally` idiom, results in convoluted code. It also tends to
> encourage programmers to label too many ordinary errors, such as failing to
> open a file, as exceptional."

and

> "Go also has a couple of built-in functions to signal and recover from truly
> exceptional conditions. The recovery mechanism is executed only as part of a
> function's state being torn down after an error."

The blog states the convention that a mechanical translator cannot honour
([go.dev/blog/defer-panic-and-recover](https://go.dev/blog/defer-panic-and-recover)):

> "The convention in the Go libraries is that even when a package uses panic
> internally, its external API still presents explicit error return values."

**But the same page documents the escape hatch, and the reason for it:**

> "It encodes an interface with a set of recursive functions. If an error occurs
> when traversing the value, panic is called to unwind the stack to the top-level
> function call, which recovers from the panic and returns an appropriate error
> value."

That is `encoding/json`, in the Go standard library, and the reason is precisely
the constraint in section 5. Its worker is a **fixed-signature function pointer
that returns nothing**:

```go
type encoderFunc func(e *encodeState, v reflect.Value, opts encOpts)
```

so an error deep in the walk has no return channel. Go's answer, verbatim from
`src/encoding/json/encode.go`:

```go
// jsonError is an error wrapper type for internal use only.
// Panics with errors are wrapped in jsonError so that the top-level recover
// can distinguish intentional panics from this package.
type jsonError struct{ error }

func (e *encodeState) marshal(v any, opts encOpts) (err error) {
	defer func() {
		if r := recover(); r != nil {
			if je, ok := r.(jsonError); ok {
				err = je.error
			} else {
				panic(r)
			}
		}
	}()
	e.reflectValue(reflect.ValueOf(v), opts)
	return nil
}

// error aborts the encoding by panicking with err wrapped in jsonError.
func (e *encodeState) error(err error) {
	panic(jsonError{err})
}
```

Three things to copy exactly: the **private wrapper type** so foreign panics are
distinguishable, the **re-panic (`panic(r)`) when the payload is not ours**, and
the **recover sited at the API boundary**, not sprinkled.

**What it gets wrong / gives up**, from the Go spec
([Handling panics](https://go.dev/ref/spec#Handling_panics)) and the builtin docs:

> "The return value of `recover` is nil when the goroutine is not panicking or
> **recover was not called directly by a deferred function**."

> "Executing a call to recover inside a deferred function **(but not any function
> called by it)** stops the panicking sequence."

That single restriction is the reason no Java-to-Go translator has done this
properly: **you cannot factor the recovery into one runtime helper.** The
`recover()` call must be syntactically inlined in a deferred closure at every
single translated `try` site.

> "the state of functions called between G and the call to `panic` is discarded,
> and normal execution resumes. Any functions deferred by G before D are then
> run and G's execution terminates by returning to its caller."

So recovering *returns from the recovering function* — a Java
`try { a(); } catch (E e) { h(); } rest();` has no statement-level Go form,
because `rest()` is unreachable in that frame. Effective Go's `Compile` example
shows the workaround: hoist the try into its own function with **named return
values** set from inside the deferred closure. Whole-function restructuring, not
a statement rewrite. Also: panics do not cross goroutines, so a translated
`catch` cannot observe a `throw` on another thread; there is no resumption; and
typed catch is a manual type switch that must re-panic on the default arm
(`err = e.(Error) // Will re-panic if not a parse error.`).

**Both of these disadvantages are Go's, not Rust's**, and that is worth stating
explicitly because it is why the recommendation is viable here and would not be
in Go. `std::panic::catch_unwind` *is* an ordinary function — no
directly-deferred restriction — and it returns a `Result` to the calling frame,
which then continues normally. Rust gets Go's mechanism without Go's two worst
constraints.

**Java-to-Go transpilers: the category is evidence in itself.** There are two
real attempts and neither translates exceptions.

`NickyBoy89/java2go` maps `throw` to `panic` and **silently deletes `catch` and
`finally`** — the try block's statements are spliced inline. From
[`tree_sitter.go`](https://github.com/NickyBoy89/java2go/blob/master/tree_sitter.go):

```go
	case "try_with_resources_statement":
		// Ignore try with resources statements as well
		// NOTE: This will also ignore the catch clause
		stmts := []ast.Stmt{ParseStmt(node.NamedChild(0), source, ctx)}
		return append(stmts, ParseStmt(node.NamedChild(1), source, ctx).(*ast.BlockStmt).List...)
	case "try_statement":
		// We ignore try statements
		return ParseStmt(node.NamedChild(0), source, ctx).(*ast.BlockStmt).List
```

Its README lists what is unimplemented and **does not mention exceptions at all**.
A Java method that throws and recovers locally becomes a Go function that panics
and kills the process — output that compiles, looks finished, and is wrong. This
is precisely the failure the work protocol's "never emit something that merely
looks finished" rule exists to prevent, found in the wild.

`dglo/java2go` models try/catch/finally in its IR but emits calls to functions
that do not exist (`try()`, `catch_<Type>(e)`, `finally()`, `throw()`), and its
README says so: "if you're lucky that converted code may even be compilable."
Loud failure, which is the better of the two.

The serious Java translations (GWT, TeaVM, J2ObjC) all target languages that
have exceptions. **There is no production Java-to-Go translator, and the
exception model is why.**

### 2.3 CodePorting Translator Cs2Cpp — C# to C++, and the `return`-inside-`try` problem

The commercial C#-to-C++ translator (formerly the Aspose C# to C++ Porter). Two
things in its design transfer directly.

**Exceptions are the one thing it does *not* put behind a smart pointer.**
Ordinary translated objects are `System::SharedPtr<T>` from `System::MakeObject<T>()`;
exceptions are split into a heap "body" and a stack "wrapper"
([docs](https://github.com/codeporting-translator/Docs/blob/main/en/translator/cs2cpp/developer-guide/cpp-user-defined-exception-classes.md)):

> "Instances of ExceptionWrapper must be stack-allocated only. Also, only
> instances of ExceptionWrapper template can be used for throw syntax
> constructions."

> "To throw exception, ExceptionWrapper::Throw() method must be called. Throwing
> ExceptionWrapper instances directly is not recommended, as the exception type
> will be trimmed to the one being thrown. Using ExceptionWrapper::Throw
> guarantees, that the type of contained exception body will be rethrown, even if
> the ExceptionWrapper instance was type-trimmed."

with a virtual `DoThrow` per exception class doing the type-preserving rethrow.
Rust's `Box<dyn Any>` payload gives this for free — the payload's concrete type
survives `resume_unwind` — so the whole `Details_`/`ExceptionWrapper` apparatus
has no analogue to build. Worth knowing the problem exists, and that we do not
have it.

**`finally` becomes a runtime helper taking two lambdas**, and the `return`
inside a `try` is handled with an `optional` return plus a sentinel out-param
([docs](https://github.com/codeporting-translator/Docs/blob/main/en/translator/cs2cpp/developer-guide/what-converts-to-what/try-finally-statements.md)):

```cpp
int32_t TryFinallyStatements::ValueReturnTry()
{
    auto optionalReturnValue__73 = System::DoTryFinally(
    [&](bool& isReturned__73) -> int32_t /* try-catch block */
    {
        return 1;
        isReturned__73 = false;
        return System::Details::initialized_value;
    }
    , [&] /* finally block */
    {
        System::Console::WriteLine(u"finally");
    });
    if (optionalReturnValue__73) return *optionalReturnValue__73;

}
```

This is IL2CPP's leave-target problem solved without `goto`, and it is
essentially the `Flow<T, R>` lowering proposed in section 6 — a body closure that
reports whether it returned, and a caller that forwards the return. Note the
shape it is forced into: dead code after `return 1;`, "did we return" encoded by
*not* running a statement, and warning suppression pragmas to make it build. A
Rust `enum Flow<T, R>` expresses the same thing without any of that.

For `using` it threads the in-flight exception into the disposal explicitly,
which is the honest version of the problem section 4 raises:

```cpp
    catch(...)
    {
        dispose_guard_1.SetCurrentException(std::current_exception());
    }
```

**What it gets wrong / gives up.** The vendor documents `finally` as a *known
unsafe translation* and pushes the fix back onto the input
([limitations](https://github.com/codeporting-translator/Docs/blob/main/en/translator/cs2cpp/developer-guide/limitations-and-bugs/translator-limitations-and-bugs.md)):

> "Translator translates C# code in **finally** block into equivalent C++ code,
> which is put into a destructor of a special service object. This means that in
> code in C# **finally** block may throws an execpion, this same excetpion may
> potentially be thrown in destructor of a service object in generated C++ code,
> which can be disasterous for the C++ application. Thus the following C# code
> will be translated into unsafe C++ code and should be rewritten so that its
> finally block does not throw before passing the code to translator for
> translation" *(sic)*

That is the same divergence as Rust's double-panic abort (section 4), reached by
the same route — cleanup running in a destructor — and answered with "change your
C#". It also documents a silent behaviour change with exception consequences:

> "A C# null-reference of type **string** is always translated into an instance
> of System::String class that behaves as an empty string, rather than as a
> null-reference. In C# when a method is invoked on a null String object
> reference, a NullReferenceException is thrown. **Correspoding C++ code does not
> throw.**"

An exception that simply stops existing. This is the class of failure the oracle
must reject, and it is the reason section 6 rejects untyped `panic!`.

### 2.4 .NET's own runtimes — the cost of EH dispatch, and Mono's set-pending-exception

Two data points from the runtime that hosts the corpus.

**CoreCLR replaced its EH implementation in .NET 9** with NativeAOT's, which is
managed code walking its own funclet tables rather than the OS unwinder
([What's new in .NET 9](https://github.com/dotnet/docs/blob/main/docs/core/whats-new/dotnet-9/runtime.md)):

> "The CoreCLR runtime has adopted a new exception handling approach that improves
> the performance of exception handling. The new implementation is based on the
> NativeAOT runtime's exception-handling model. **The change removes support for
> Windows structured exception handling (SEH) and its emulation on Unix.** … The
> new exception handling implementation is 2-4 times faster, per some exception
> handling micro-benchmarks."

Two takeaways: EH *dispatch* is expensive enough that a 2–4x win was worth
rebuilding it, and the cost of leaving the platform mechanism is paid in
debugger fidelity — the release notes list WinDbg no longer breaking on first-chance
managed exceptions, and exception interception not working on Arm64 or Unix.
Both are relevant to the "Rust panics do not give C# stack traces" deviation.

**Mono documents the exact alternative this document rejects**, and rejects it
for the same reason. Its own unwinder pays to save an LMF frame on every
managed→native transition
([Mono exception handling](https://github.com/dotnet/runtime/blob/main/docs/design/mono/web/exception-handling.md)):

> "To allow mono_raise_exception () to unwind through native code, we need to save
> the LMF structures which can add a lot of overhead even in the common case when
> no exception is thrown. **So this is not zero-cost exception handling.**"

> "An alternative might be to use a JNI style set-pending-exception API. Runtime
> code could call mono_set_pending_exception (), then return to its caller with an
> error indication allowing the caller to clean up. When execution returns to
> managed code, then managed->native wrapper could check whenever there is a
> pending exception and throw it if necessary."

That second quote is the "out-of-band error slot" option in section 6's rejection
table, proposed by people who ship a runtime. It works for Mono because there is
a single choke point — the managed→native wrapper — that can check on the way
back. Section 6 explains why the same trick changes behaviour here: our choke
point would be `Bank::write`'s field loop, and checking between fields does not
reproduce what an in-flight exception does to the remaining fields.

### 2.5 c2rust — C to Rust, and what it refuses

The closest existing translator *targeting Rust*
([c2rust.com/manual/docs/known-limitations.html](https://c2rust.com/manual/docs/known-limitations.html))
lists non-local control flow under features it will "likely never support":

> `longjmp`/`setjmp` — "it is unclear how these interact with Rust (esp.
> idiomatic Rust)."

**What it gives up.** Any C program using `setjmp` for error recovery is simply
untranslatable. That is a defensible answer for c2rust — such programs are rare —
and an indefensible one here, because 28.7% of the corpus reaches a throw. It is
worth stating plainly that the reference implementation of "translate to Rust"
declined this problem rather than solving it.

### 2.6 Emscripten — C++ to Wasm, the cost of emulating EH

Wasm originally had no exceptions, so Emscripten had to emulate them
([emscripten.org/docs/porting/exceptions.html](https://emscripten.org/docs/porting/exceptions.html)):

> "By default, exception catching is disabled in Emscripten." … "Exception
> thrown, but exception catching is not enabled."

> `-fexceptions` (JavaScript-based): "This option has relatively high overhead,
> but it will work on all JavaScript engines with WebAssembly support."

> `-fwasm-exceptions`: "leverages a new feature that brings built-in instructions
> for throwing and catching exceptions to WebAssembly. As a result, it can reduce
> code size and performance overhead compared to the JavaScript-based
> implementation."

> "Currently `std::set_terminate` is NOT supported when a thrown exception does
> not have a matching handler" — "that functionality requires two-phase exception
> handling, which neither supports."

**What it gets wrong / gives up.** The default is to turn every `throw` into an
abort, which is exactly the silent-behaviour-change hazard called out in
section 6. Two-phase EH is lost, so anything that must observe the exception
*before* unwinding (C# `when` filters; the corpus has none) is unsupportable. And
the emulated path is measurably slow, which is why the native Wasm feature was
added at all.

### 2.7 Rust's own rules for the boundary

Two normative sources bound what is legal.

RFC 2945, the `"C-unwind"` ABI
([rust-lang.github.io/rfcs/2945-c-unwind-abi.html](https://rust-lang.github.io/rfcs/2945-c-unwind-abi.html)):

> "with the `panic=unwind` runtime, `panic!` will cause an `abort` if it would
> otherwise 'escape' from a function defined with `extern "C"`."

> "If a non-forced foreign unwind would enter a Rust frame via an
> `extern "C-unwind"` ABI boundary, but the Rust code is compiled with
> `panic=abort`, the unwind will be caught and the process aborted."

`std::panic::catch_unwind`
([doc.rust-lang.org](https://doc.rust-lang.org/std/panic/fn.catch_unwind.html)):

> "It is **not** recommended to use this function for a general try/catch
> mechanism. The `Result` type is more appropriate to use for functions that can
> fail on a regular basis."

> "This function **might not catch all Rust panics**. A Rust panic is not always
> implemented via unwinding, but can be implemented by aborting the process as
> well. This function *only* catches unwinding panics, not those that abort the
> process."

> "The closure provided is required to adhere to the `UnwindSafe` trait to ensure
> that all captured variables are safe to cross this boundary."

> "Finally, be **careful in how you drop the result of this function**. If it is
> `Err`, it contains the panic payload, and dropping that may in turn panic!"

The first quote is a direct argument against the recommendation and is answered
in section 6, not ignored. It is advice for hand-written Rust that *has* the
option of `Result`; section 5 shows this translation does not.

---

## 3. Does the `RecoverableException` distinction survive translation?

**Yes, and it must — but as a payload type, not as a return type.**

Renode's own hierarchy, confirmed from the corpus `type` table:

```
ConstructionException  ->  RecoverableException  ->  System.Exception
```

and outside the cut, `RegisterValueUnavailableException` and
`InvalidRegisterAccessException` are also `: RecoverableException`. The
distinction is real and load-bearing: there are **24 `catch(RecoverableException)`
sites** across the Renode tree, and they are the boundary at which a user error
stops being an error and becomes a message. They sit at the Monitor, the GDB
stub, the plugin loader, `Emulator.cs`, and — critically for us —
`TranslationCPU.TryTranslateAddress`.

The distinction that *does not* survive is C#'s: Renode uses
`ArgumentException` for contract violations and `RecoverableException` for user
errors, but the two are not separated by any mechanism, only by convention and
by which handler happens to be installed. A translation that promoted
`ArgumentException` to a Rust `panic!` with no payload and `RecoverableException`
to `Result` would be *choosing* which of Renode's exceptions are catchable, and
that choice is not in the C#. Reproducing Renode's actual behaviour means
reproducing "any of these is catchable by whoever installed a handler".

**Exceptions used for control flow.** Three shapes are present, and they are not
the same problem:

1. **`Try*` methods** — `throw` then immediately `catch` to return a bool.
   `TranslationCPU.TryTranslateAddress` is the clean case:

   ```csharp
   public bool TryTranslateAddress(ulong logicalAddress, MpuAccess accessType, out ulong physicalAddress)
   {
       try { physicalAddress = TranslateAddress(logicalAddress, accessType); return true; }
       catch(RecoverableException) { physicalAddress = logicalAddress; return false; }
   }
   ```

   Also `Misc.TryCopyToTemporaryFile`, `Misc.TryCreateEmptyFile`,
   `IPeripheral.TryGetMachine`, `NVIC.IsCurrentCPUInSecureState`. The throw site
   and the catch site are both inside the translation unit.

2. **`CpuAbortException`** — genuine long-range control flow, thrown from a
   callback the CPU core invokes and caught around the execution loop. Detailed
   in section 5.

3. **Wrapping** — `catch(IOException e) { throw new InvalidOperationException($"...{e.Message}"); }`
   in `Misc.CopyToFile`. Requires the caught payload's message, so the payload
   must carry the message string, not just a discriminant.

Shape 1 is the tempting one to special-case into `Result`, and it should **not**
be, at least not as the general mechanism. The rule "collapse a throw whose only
catcher is in the same method into a `Result`" is sound and worth having as an
*optimisation* on top of the general mechanism, but as the general mechanism it
fails on shape 2 and cannot be applied at all when the throw is four frames down
through code that other callers also reach — which is the `Try*` case in
`TryTranslateAddress`, where `TranslateAddress` is also a public method others
call directly.

---

## 4. `finally` and `using`: is `Drop` enough?

Mostly yes, and the residue is small and enumerable.

### Where `Drop` is exactly right

Rust runs destructors on scope exit, early `return`, `break`, `continue`, `?`,
and during panic unwinding. C# runs `finally` on all of the same. For the 110
implicit finallys (`lock`, `foreach`) the mapping is free: a `MutexGuard` drops,
an iterator drops. For `using`, whose entire purpose is "call `Dispose` on scope
exit", `Drop` is the same construct with a different spelling — and both `Using`
operations in the cut are the plain `using(var x = ...) { }` statement form.

### Where it differs — precisely

| case | C# `finally` | Rust `Drop` | verdict |
|---|---|---|---|
| early `return` from the try body | runs | runs | same |
| `break`/`continue` out of the try | runs | runs | same |
| exception propagating through | runs | runs (unwind) | same **only if `panic = "unwind"`** |
| `panic = "abort"` / `std::process::abort` | n/a | **does not run** | see section 6 |
| `Environment.FailFast` / `process::exit` | does not run | does not run | same |
| `finally` throws while an exception is in flight | the new exception **replaces** the in-flight one | second panic during unwind **aborts the process** | **divergence** |
| `finally` mutates a local read after the try | legal | fights the borrow checker | **needs restructuring** |
| `Dispose()` throws | propagates | `Drop::drop` cannot fail | **divergence** |
| ordering with several guards | textual order of nested finallys | reverse declaration order | same for nested scopes; must emit nesting, not siblings |
| `return` *inside* `finally` | **illegal in C#** (CS0157) | n/a | nothing to map |

The last row is a genuine relief: because C# forbids leaving a `finally` via
`return`/`goto`/`break`, a translated finally is always straight-line cleanup.

The two divergences are both low-exposure in this corpus and both must be
recorded as deviations rather than assumed away. Neither is peculiar to Rust:
CodePorting's C#-to-C++ translator hits the identical "finally may throw, and
cleanup runs in a destructor" hole (section 2.3) and documents it as an unsafe
translation whose remedy is to rewrite the C# first. We should record it as a
deviation and report a gap, not silently emit the unsafe form.

The only written `finally` in the cut is:

```csharp
finally
{
    if(libraryStream != null) { libraryStream.Close(); }
}
```

— cleanup of a *parameter*, no local mutation, no throw. A scope guard handles it.

### Nested scopes

C# `finally` runs at the end of the `try` block, whereas `Drop` runs at the end
of the lexical block holding the guard. These coincide only if the emitter
introduces a block scope for the try and places the guard inside it. That is one
line of emitter discipline and is called out here because getting it wrong moves
cleanup later without changing any test result — the class of bug the work
protocol lists under "it compiles is not evidence".

### The residue

A `finally` that mutates a local the code after the try also reads cannot be a
`Drop` guard, because the guard would have to hold `&mut` to that local for its
whole lifetime. The general answer is IL2CPP's: lower the try/finally to explicit
control flow rather than to a destructor. There is no such site in the cut, so
the correct action is to **report a gap** for that shape, not to build the
machinery speculatively.

---

## 5. The hard one: callbacks whose signature is fixed

### The constraint, stated exactly

`src/renode-regs/src/lib.rs`:

```rust
pub type ValueProvider<S> = fn(&Bank<S>, &mut S, usize, u64) -> u64;
pub type WriteCallback<S> = fn(&Bank<S>, &mut S, usize, u64, u64);
```

and `rulesdb/rules/register_dsl.json` under `callback_signatures` pins them,
`"ret": "u64"` and `"ret": "()"`. They are called from `Register::value` and
`Bank::write`, both of which are hand-written DSL code mirroring C#
`PeripheralRegister`.

### It is not hypothetical — here is the chain

`STM32F4_RTC.cs`:

```csharp
valueProviderCallback: _ => mainTimer.Read(DateTimeSelect.Second, Rank.Units))
```

`TimerConfig.Read` calls `GetTimeSelect`, and `GetTimeSelect` ends:

```csharp
default:
    throw new ArgumentException($"Unexpected date time select: {what}");
```

So: **a `valueProviderCallback` reaches a `throw`, three frames down, in a
peripheral already in scope for translation.** The same shape recurs — the
corpus lists `STM32F4_RTC.UpdateTimeState`, `STM32_Timer.InputPrescalerDivider`,
`BaseGPIOPort.SetConnectionStateBit` (reached from a `value => ...` lambda in
`NXP_IMX_GPIO`), and `STM32_UART.get_StopBits`.

### What this does to `Result`

Colouring `GetTimeSelect` as `-> Result<i32, E>` forces `Read` to
`-> Result<u32, E>`, forces the lambda to `-> Result<u64, E>`, and therefore
forces `ValueProvider` to `fn(...) -> Result<u64, E>`. That in turn forces
`Register::value`, `Bank::read`, `Bank::write` and every caller of them. The
recolouring does not stop there, and this is the decisive part: **it stops dead
at boundaries Rust does not let us widen.**

- `Drop::drop` cannot return anything. `finally`/`using` translations live here.
- `Iterator::next` cannot return `Result` without changing the item type, which
  changes every consumer.
- `extern "C"` callbacks have a signature dictated by the C caller.

The third is already live in this workspace. `src/renode-tlib/src/lib.rs`:

```rust
unsafe extern "C" fn report_abort(msg: *const std::os::raw::c_char) {
    ...
    panic!("tlib aborted: {text}");
}
```

This is the direct counterpart of Renode's:

```csharp
[Export]
private void ReportAbort(string message)
{
    ...
    throw new CpuAbortException(message);
}
```

caught back in managed code around the tlib call:

```csharp
lastTlibResult = (TlibExecutionResult)TlibExecute(checked((int)numberOfInstructionsToExecute));
...
catch(CpuAbortException)
{
    this.NoisyLog("CPU abort detected, halting.");
    InvokeHalted(new HaltArguments(HaltReason.Abort, this));
    return ExecutionResult.Aborted;
}
```

Renode's own comment on that throw is worth reading, because it shows the
authors know they are unwinding through native frames:

```csharp
/* If the trace writer runs asynchronyously, we need to disable it.
 * Otherwise it might catch the CpuAbortException when we cross the tlib boundary
 * since the tracer can read emulated CPU registers (tlib callbacks)
 * and catch the exception there, before the CPU thread does.
 */
```

**The C# had no `Result` option either.** `[Export] private void ReportAbort(string)`
returns `void` because tlib's function-pointer table says so. Throwing is the
only channel. A translation that requires a return channel cannot reproduce this
at all; it is not a matter of inconvenience.

### The two things this means

1. **`Result` is not merely awkward here, it is incomplete.** There exist throw
   sites in this corpus whose nearest legal return channel is on the far side of
   a signature nobody involved controls. Any design that says "use `Result`, and
   panic where you cannot" has to answer *where* the panic gets caught, at which
   point it has built the panic mechanism anyway — and now has two.

2. **`report_abort` is currently wrong and should be filed.** Per RFC 2945, a
   panic escaping an `extern "C"` function aborts the process. So today the
   CpuAbort path terminates the emulator instead of unwinding to the executor.
   The fix is `extern "C-unwind"` plus a `catch_unwind` at the `TlibExecute` call
   site. That crate is outside this issue's module; per the work protocol it is
   **filed, not fixed**.

### And the reason it costs nothing under the recommendation

A panic does not appear in a signature. `ValueProvider` stays
`fn(&Bank<S>, &mut S, usize, u64) -> u64`; `callback_signatures` in
`register_dsl.json` is not edited; `peripheral_methods.decl`
(`fn {name}(bank: &Bank<State>, st: &mut State{extra}) -> {ret}`) is not edited.
A throw inside a provider unwinds through `Register::value` and `Bank::read` to
whatever frame the C# would have unwound to. That is the whole argument.

---

## 6. Recommendation, and its failure mode

### The mechanism

A small runtime, sited in the DSL crate or a new `renode-rt`:

```rust
/// One C# exception, as a panic payload. Private type, so a foreign panic
/// is distinguishable — this is `encoding/json`'s `jsonError`.
pub struct CsException {
    pub class: ExceptionClass,
    pub message: String,
}

/// One variant per C# exception type the corpus throws or catches. The
/// subtype test comes from the corpus `type` table's base chain, so
/// `catch(RecoverableException)` catches `ConstructionException`.
pub enum ExceptionClass { Argument, ArgumentNull, ArgumentOutOfRange,
                          IndexOutOfRange, InvalidOperation, Format,
                          EndOfStream, Recoverable, Construction, CpuAbort,
                          NotImplemented, Unreachable }

#[cold]
#[inline(never)]
pub fn throw(class: ExceptionClass, message: String) -> ! {
    std::panic::panic_any(CsException { class, message })
}

pub fn try_catch<R>(body: impl FnOnce() -> R) -> Result<R, CsException> {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(body)) {
        Ok(v)  => Ok(v),
        Err(p) => match p.downcast::<CsException>() {
            Ok(e)     => Err(*e),
            Err(other) => std::panic::resume_unwind(other),  // not ours
        },
    }
}
```

- `throw new X(msg)` → `rt::throw(rt::ExceptionClass::X, format!(...))`
- `try/catch` → `rt::try_catch(|| { .. })` + a `match` whose arms test
  `class.is_a(..)` in source order, with a final `Err(e) => rt::rethrow(e)`
- `throw;` (rethrow) → `rt::rethrow(e)`
- `finally` / `using` → a scope guard struct nested inside a synthesised block
- `NotImplementedException` / `UnreachableException` → `unimplemented!()` /
  `unreachable!()`, which is more faithful, not less: both are assertions with
  no catcher anywhere in the tree.

`AssertUnwindSafe` is required and is *not* a fudge here: C# offers no unwind
safety guarantee whatsoever, and Renode's code routinely leaves objects
half-updated after an exception. Asserting it reproduces C#. It should be
recorded as a deviation anyway, since it discards a check Rust would otherwise
give us.

**`return` inside a `try`.** 5 of 10 try statements and 3 of 10 catch clauses in
the cut contain a `return`, and a `return` inside the closure returns from the
closure. The general lowering is IL2CPP's leave-target stack, reduced to what
Rust can express:

```rust
enum Flow<T, R> { Value(T), Return(R) }
```

the try body yields `Flow`, and the caller does
`match .. { Flow::Return(r) => return r, Flow::Value(v) => v }`. Mechanical, and
it covers `break`/`continue` by extension. CodePorting's `DoTryFinally` does the
same thing in C++ with an `optional` return and a `bool&` sentinel (section 2.3);
a Rust enum expresses it without their dead code and warning pragmas.

Two properties of `catch_unwind` make this workable in Rust where it is not in
Go: it is an ordinary function, so the recovery logic can live in one runtime
helper rather than being inlined at every site, and it returns to the calling
frame, so execution continues after the `try` instead of terminating the
enclosing function. Section 2.2 gives the Go spec text for both restrictions.

### The failure mode

**`panic = "abort"`.** Three lines in a `Cargo.toml` profile turn every
translated `catch` into a process abort, and `std` says so plainly:

> "This function **might not catch all Rust panics**. … This function *only*
> catches unwinding panics, not those that abort the process."

The workspace `[profile.release]` currently sets `debug`, `lto` and
`codegen-units` and says nothing about `panic`, so it defaults to `unwind` and
happens to be correct today. Nothing enforces it. Someone adding
`panic = "abort"` for binary size would silently delete Renode's entire
`RecoverableException` handling, and — this is the part that matters — no test in
this repo would fail, because the oracle traces exercise register access, not
error paths. This is the same class as the invented `.with_reserved(9, 23)`:
behaviourally wrong code that no test can see.

Mitigation, and it must be built with the feature, not after:
`scripts/check_profile.py` (or an addition to an existing gate) asserting
`panic = "unwind"` in every profile, plus one oracle case that actually throws
and expects a caught result.

Secondary failure modes, all to be recorded as deviations:

- **Double panic aborts.** A panic while unwinding aborts the process; C# lets a
  `finally`'s exception replace the in-flight one. One `finally` in the cut, and
  it cannot throw, so exposure is nil today — but the deviation is real.
- **Unwinding through `extern "C"` is an abort (RFC 2945).** Every FFI entry
  point that a translated throw can reach must be `extern "C-unwind"` with a
  `catch_unwind`. This is enumerable — the tlib callback table is a fixed list —
  but a missed one is an abort, not a test failure.
- **The panic hook is global process state.** Default behaviour prints to stderr;
  a translated `throw` that Renode catches and logs would print an unwanted
  message. Installing a hook is process-wide, which interacts with the
  N-instance parallel testing D3 anticipates.
- **No C# stack traces.** A `CsException` payload carries class and message, not
  a managed call stack. Renode logs exception text, not stack traces, on the
  paths in the cut, so the oracle can compare log output — but this is a real
  loss and both prior-art runtimes paid it too: IL2CPP's release builds "might
  produce a call stack that's missing one or more managed methods", and CoreCLR's
  .NET 9 EH rewrite cost first-chance-exception breaks in WinDbg.
- **Cost.** Unwinding is slow, and it is slow everywhere: CoreCLR rebuilt its EH
  in .NET 9 for a documented "2-4 times faster", and Mono records that its own
  scheme "is not zero-cost exception handling" (section 2.4). Irrelevant on the
  throw paths in this corpus — all are error paths — but it would matter if a
  `Try*` method were called in a hot loop. The same-method collapse optimisation
  in section 3 addresses that if it ever shows up in a profile.

### What was rejected, and why

| option | why not |
|---|---|
| **`Result` everywhere (D4 as written)** | Requires recolouring ≥28.7% of bodied methods, and the recolouring must cross `ValueProvider`, `WriteCallback`, `Drop::drop` and `extern "C"` — signatures that cannot be widened. Section 5 gives a concrete chain where it has nowhere to go. Also the sole remaining failure mode of the recommendation (`panic=abort`) does not go away, because you still need panics for the uncolourable frames — so you get two mechanisms, not one. |
| **`Result` where possible, panic where not** | A method's colour then depends on its callers, so it needs whole-program analysis, it changes when a new caller appears, and the same C# method translates two ways. Directly contradicts "a rule is not a rule until it has three validated instances". |
| **Untyped `panic!` for everything** | Loses the catchable/fatal distinction that 24 `catch(RecoverableException)` sites depend on, and loses the message that `Misc.CopyToFile`'s wrapping catch reads. Not equivalent; the oracle should reject it. Cs2Cpp's null-string divergence (section 2.3) is what this class of shortcut looks like once shipped: an exception that stops existing. |
| **Delete `catch`, keep `throw`** | What `NickyBoy89/java2go` does (section 2.2). Compiles, looks finished, converts local recovery into process death. Named here only so it is on the record as rejected. |
| **Out-of-band error slot on `State`** | Mono proposes exactly this as its own alternative — "a JNI style set-pending-exception API" (section 2.4) — and it works there because the managed→native wrapper is a single choke point that checks on the way back. Here the choke point is `Bank::write`'s field loop, and checking between fields does not reproduce an in-flight exception: the remaining fields still get written. A behaviour change *invisible in the signature*, which is the worst kind. |
| **Widen the DSL callback types to `Result`** | Possible — we own that file — but it makes the DSL stop mirroring the C# it is a translation of, it does not solve `Drop`/`extern "C"`, and `callback_signatures` is a committed rule that other issues build on. |
| **Refuse, as c2rust refuses `setjmp`** | Defensible at 0.1% of a corpus. Not at 28.7%. |

---

## 7. Cost

### Ingest — four findings, all properties Roslyn already exposes

Per the work protocol these are **reported, not implemented**, and they batch.

1. **`IThrowOperation` records nothing.** The thrown type is currently only
   recoverable by walking to the `ObjectCreation` grandchild through a
   `Conversion`, and a bare `throw;` (rethrow) is distinguishable only by having
   no children. Ask: record `exception_type` and `rethrow` in `detail`.

2. **`ICatchClauseOperation` records nothing, and the caught type is lost.**
   7 of 10 catch clauses in the cut have no exception variable, so the corpus
   cannot distinguish `catch(RecoverableException)` from `catch(Exception)` from
   `catch`. `NVIC.IsCurrentCPUInSecureState` catches `RecoverableException` and
   the database holds only `CatchClause -> Block`. **This is a hard blocker** —
   the construct cannot be emitted correctly without it. Ask: record
   `ExceptionType`, and `Filter` presence (there are none in Renode today, but a
   silently-dropped filter would be a wrong translation, not a gap).

3. **The base chain of an exception type is not always in the cut.** The `type`
   table has `ConstructionException -> RecoverableException -> System.Exception`,
   but `CpuAbortException` is thrown three times and never declared in the cut,
   and BCL chains (`ArgumentNullException : ArgumentException`) are absent
   entirely. Since `catch(ArgumentException)` must catch `ArgumentNullException`,
   ask: record the full base chain of thrown/caught types as `detail`, walking
   `ITypeSymbol.BaseType`, which works for BCL types too.

4. **Minor:** `ITryOperation.Finally` is a plain `Block` sibling. Positionally
   derivable (the Block after the catches), but tag it.

### Rules

| file | change |
|---|---|
| `rulesdb/rules/lang/exceptions.json` | **new.** Generic templates: throw, try/catch, rethrow, scope guard, `Flow` lowering, plus the BCL exception-type → `ExceptionClass` table and the two recorded deviations (double-panic, `AssertUnwindSafe`). Must not name Renode. |
| `rulesdb/rules/plugins/renode_exceptions.json` | **new.** `RecoverableException` / `ConstructionException` / `CpuAbortException` classification and the catch-boundary list. This is corpus knowledge and `check_layering.py` will (correctly) reject it in the lang file. |
| `rulesdb/rules/register_dsl.json` | **unchanged.** Specifically `callback_signatures` is untouched — that is the point of the recommendation. |
| `rulesdb/rules/csharp_core.json` | unchanged; the new deviations belong in the new lang file. |

### Emitter

| file | change | rough size |
|---|---|---|
| `scripts/emitter/lang/exceptions.py` | **new.** Handlers for `Throw`, `Try`, `Using`, the finally-block-as-guard, and the `Flow` lowering for `return` inside a try. | ~250–320 lines |
| `scripts/emitter/plugins/renode_exceptions.py` | **new.** Exception-class classification from the corpus type hierarchy. | ~60–90 lines |
| `src/renode-regs/src/lib.rs` or a new `renode-rt` | the ~40-line runtime in section 6. Hand-written infrastructure, not generated output. | ~40 lines + tests |
| `scripts/check_profile.py` | **new** gate: `panic = "unwind"` in every profile. | ~30 lines |

### One blocker for the parallel-work protocol

`scripts/emitter/core.py` declares a dispatch registry (`stmt()`, `expr()`,
`stmt_handlers()`), and **nothing calls it**. Modules are composed as mixins in
`scripts/emit.py`:

```python
class Emitter(RenodeExpressions, Expressions, Statements, Types):
```

and `emit_stmt` in `scripts/emitter/lang/statements.py` is a hardcoded `if`
chain. So adding `lang/exceptions.py` requires editing `scripts/emit.py` (import
+ base class) and `statements.py` (dispatch) — **both of which the work protocol
puts off limits**, and both of which every other transpiler issue also needs to
touch for the same reason.

The clean fix is a one-line fallback in `emit_stmt`, just before it records the
kind as unhandled, consulting `core.stmt_handlers(kind)`. That is a maintainer
change to `core.py`/`statements.py`/`emit.py` and should be requested in the
issue thread rather than done by an issue agent. Until it exists, "one module per
agent" is not actually achievable for any new statement kind.

### What lands, and how it is measured

The protocol asks for a corpus count, not a site. On merge:

- 116 `Throw` operations emit rather than withhold.
- 10 `Try` + 10 `CatchClause` emit — **conditional on ingest finding 2**;
  without the caught type they must stay withheld, and saying otherwise would be
  emitting something that merely looks finished.
- 2 `Using` emit; the 1 `finally` emits.
- `SetConnectionStateBit: withheld, cannot emit stmt:Throw` disappears from
  `src/renode-stm32/src/gpio_registers.rs`, and the methods listed in section 1
  become emittable subject to their other gaps.

---

## 8. Open questions for the maintainer

1. **D4 is reopened.** Does the recommendation replace it, or is there a reason
   for `Result` that section 5 misses? This needs a written verdict before any
   emitter work starts; it is a whole-program decision.
2. **Ingest finding 2 is a blocker**, not an optimisation. Try/catch cannot be
   emitted at all without the caught type. Should #39 land throw-only first and
   try/catch after the next re-ingest?
3. **`report_abort` in `src/renode-tlib/src/lib.rs` panics out of an
   `extern "C"` fn.** Filed, not fixed, per the protocol — but it is on the
   CpuAbort path and should not wait for #39.
4. **The dispatch registry is unwired.** Either wire it or accept that new
   statement kinds need maintainer edits.
