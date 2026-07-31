//! FFI to tlib — the C CPU core. Issue #7.
//!
//! tlib is Renode's fork of QEMU's TCG: 227k lines of C, of which ~52k is the
//! ARM slice. It is **not translated and not replaced**. Two reasons:
//!
//! 1. The #3 profile put instruction dispatch at ~1.5% of runtime — it is not
//!    the bottleneck, so translating it buys nothing on speed.
//! 2. Keeping the CPU byte-identical on both sides is what makes the tier-3
//!    lockstep oracle exact: every state divergence is then a peripheral bug,
//!    never a CPU bug.
//!
//! ## Why this is easier from Rust than from C#
//!
//! Renode reaches tlib through `NativeBinder`, which emits IL at runtime to bind
//! 418 exports and 55 callback attach points. Rust needs neither: the attach
//! points take plain C function pointers, so a `extern "C" fn` goes straight in.
//!
//! ## Bring-up status
//!
//! **Mechanism proven, callback set incomplete.** Loading, symbol resolution and
//! callback attachment all work; `tlib_init` now proceeds through
//! `cpu_exec_init_all` into `cpu_init`/`cpu_reset` before hitting the next
//! unattached hook.
//!
//! The governing fact: **tlib calls its host callbacks unconditionally and does
//! not null-check them.** An unattached callback is not a graceful error, it is
//! a segfault inside `tlib_init` with a backtrace to address 0. Bring-up is
//! therefore: run, read the backtrace, attach the named callback, repeat.
//! Attached so far are the allocator trio and twelve infrastructure hooks;
//! roughly 39 remain, of which the important ones are the bus read/write
//! family (`Read*FromBus` / `Write*ToBus`) that carry MMIO.
//!
//! One trap already cost a cycle: an `attach!` macro using an inferred
//! `fn(_)` type compiled, resolved nothing, and left the crash unchanged —
//! which read as "this callback is not the problem". Attach points now name
//! their signature explicitly.
//!
//! ## Loading
//!
//! The library is `dlopen`ed rather than link-time bound, matching how Renode
//! selects a core per architecture at runtime, and keeping the path out of the
//! build (it comes from `RENODE_SRC`, never hardcoded).

use std::ffi::CString;
use std::path::Path;

pub use libloading::Error as LoadError;

/// Registers, as tlib numbers them for ARM.
pub mod reg {
    pub const R0: i32 = 0;
    pub const R1: i32 = 1;
    pub const R2: i32 = 2;
    pub const SP: i32 = 13;
    pub const LR: i32 = 14;
    pub const PC: i32 = 15;
    pub const CPSR: i32 = 25;
}

/// Why `execute` returned.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecResult {
    /// Ran the requested number of instructions.
    Ok,
    /// Returned early — an interrupt, a WFI, or a return request.
    Interrupted,
    /// tlib reported an abort.
    Aborted,
    Unknown(i32),
}

/// Bus callbacks the host must provide. tlib calls these for any access outside
/// a mapped RAM range, which is precisely the MMIO path.
pub trait Bus: Send {
    fn read_byte(&mut self, addr: u64) -> u8;
    fn read_word(&mut self, addr: u64) -> u16;
    fn read_double_word(&mut self, addr: u64) -> u32;
    fn write_byte(&mut self, addr: u64, value: u8);
    fn write_word(&mut self, addr: u64, value: u16);
    fn write_double_word(&mut self, addr: u64, value: u32);
}

type FnInit = unsafe extern "C" fn(*const std::os::raw::c_char) -> i32;
type FnAtomicInit = unsafe extern "C" fn(usize, i32) -> i32;
type FnExecute = unsafe extern "C" fn(u32) -> i32;
type FnMapRange = unsafe extern "C" fn(u64, u64);
type FnVoid = unsafe extern "C" fn();
type FnGetReg32 = unsafe extern "C" fn(i32) -> u32;
type FnSetReg32 = unsafe extern "C" fn(i32, u32);
type FnSetBlockSize = unsafe extern "C" fn(u32) -> u32;

// Attach points take a bare C function pointer. The `_ex` variants carry a CPU
// context for multi-core; single-core needs only the plain form.
type AttachAlloc = unsafe extern "C" fn(unsafe extern "C" fn(usize) -> *mut u8);
type AttachRealloc = unsafe extern "C" fn(unsafe extern "C" fn(*mut u8, usize) -> *mut u8);
type AttachFree = unsafe extern "C" fn(unsafe extern "C" fn(*mut u8));

// tlib delegates ALL allocation to the host: `init_tcg` attaches tlib's own
// wrapper, which then calls out through these. Without them `tlib_init`
// segfaults on a null function pointer inside `tlib_allocate` -- which is
// exactly how this was found, since nothing warns.
//
// Rust's allocator needs the layout back at free time, so the size is stored in
// a header word ahead of each block. That is the standard way to bridge a
// malloc/free ABI onto Rust's sized deallocation.
const HDR: usize = std::mem::size_of::<usize>();

unsafe extern "C" fn host_alloc(size: usize) -> *mut u8 {
    let total = size + HDR;
    let layout = std::alloc::Layout::from_size_align(total, HDR).unwrap();
    let p = std::alloc::alloc_zeroed(layout);
    if p.is_null() {
        return p;
    }
    (p as *mut usize).write(total);
    p.add(HDR)
}

unsafe extern "C" fn host_realloc(ptr: *mut u8, size: usize) -> *mut u8 {
    if ptr.is_null() {
        return host_alloc(size);
    }
    let base = ptr.sub(HDR);
    let old_total = (base as *mut usize).read();
    let new_total = size + HDR;
    let layout = std::alloc::Layout::from_size_align(old_total, HDR).unwrap();
    let p = std::alloc::realloc(base, layout, new_total);
    if p.is_null() {
        return p;
    }
    (p as *mut usize).write(new_total);
    p.add(HDR)
}

// --- infrastructure callbacks tlib requires before init -------------------
//
// Discovered one segfault at a time: tlib calls these unconditionally and does
// not check for null, so an unattached one crashes inside tlib_init with a
// backtrace to address 0. Attaching the whole set up front is cheaper than
// finding them individually.

unsafe extern "C" fn on_translation_cache_size_change(_size: u64) {}
unsafe extern "C" fn log_as_cpu(_level: i32, _msg: *const std::os::raw::c_char) {}
unsafe extern "C" fn report_abort(msg: *const std::os::raw::c_char) {
    let text = if msg.is_null() {
        "<null>".to_string()
    } else {
        std::ffi::CStr::from_ptr(msg).to_string_lossy().into_owned()
    };
    panic!("tlib aborted: {text}");
}
unsafe extern "C" fn on_block_begin(_pc: u64, _size: u32) -> u32 {
    1 // continue executing
}
unsafe extern "C" fn on_block_finished(_pc: u64, _executed: u32) {}
unsafe extern "C" fn is_zero_u32() -> u32 {
    0
}
unsafe extern "C" fn get_total_elapsed_cycles() -> u64 {
    0
}
unsafe extern "C" fn invalidate_tb_in_other_cpus(_a: *mut u8, _b: *mut u8) {}
unsafe extern "C" fn touch_host_block(_addr: u64) {}
unsafe extern "C" fn mass_broadcast_dirty(_a: *mut u8, _n: i32) {}

unsafe extern "C" fn host_free(ptr: *mut u8) {
    if ptr.is_null() {
        return;
    }
    let base = ptr.sub(HDR);
    let total = (base as *mut usize).read();
    let layout = std::alloc::Layout::from_size_align(total, HDR).unwrap();
    std::alloc::dealloc(base, layout);
}

/// A loaded tlib instance.
///
/// tlib keeps its CPU state in a process-global (`env`), so exactly one may be
/// live at a time. That is a property of the C, not a choice made here, and it
/// is why this type is not `Clone` and construction is fallible.
pub struct Tlib {
    _lib: libloading::Library,
    execute: FnExecute,
    map_range: FnMapRange,
    reset: FnVoid,
    get_reg32: FnGetReg32,
    set_reg32: FnSetReg32,
}

impl Tlib {
    /// Load and initialise a core. `model` is a tlib CPU name such as
    /// `"cortex-m4f"` — the same string the `.repl` supplies as `cpuType`.
    ///
    /// # Safety
    /// Loading an arbitrary shared library is inherently unsafe; the caller
    /// asserts `path` is a genuine tlib build for the intended architecture.
    pub unsafe fn load(path: &Path, model: &str) -> Result<Self, String> {
        let lib = libloading::Library::new(path).map_err(|e| format!("dlopen: {e}"))?;

        macro_rules! sym {
            ($t:ty, $name:literal) => {
                *lib.get::<$t>($name)
                    .map_err(|e| format!("{}: {e}", String::from_utf8_lossy($name)))?
            };
        }

        // MUST precede tlib_init: see the allocator comment above.
        let attach_alloc: AttachAlloc =
            sym!(AttachAlloc, b"renode_external_attach__FuncIntPtrIntPtr__Allocate\0");
        let attach_realloc: AttachRealloc = sym!(
            AttachRealloc,
            b"renode_external_attach__FuncIntPtrIntPtrIntPtr__Reallocate\0"
        );
        let attach_free: AttachFree =
            sym!(AttachFree, b"renode_external_attach__ActionIntPtr__Free\0");
        attach_alloc(host_alloc);
        attach_realloc(host_realloc);
        attach_free(host_free);

        // Attach by name where present; a core built without a given hook
        // simply has no attach point, so a miss is not an error.
        // Explicit attach-point type per callback signature. An inferred
        // `fn(_)` made this macro a silent no-op: it compiled, resolved nothing
        // useful, and the crash was unchanged -- which read as "the callback is
        // not the problem".
        macro_rules! attach {
            ($ty:ty, $sig:literal, $f:expr) => {{
                let attach_fn = lib
                    .get::<unsafe extern "C" fn($ty)>($sig)
                    .map_err(|e| format!("{}: {e}", String::from_utf8_lossy($sig)))?;
                (*attach_fn)($f);
            }};
        }
        attach!(unsafe extern "C" fn(u64),
            b"renode_external_attach__ActionUInt64__OnTranslationCacheSizeChange\0",
            on_translation_cache_size_change);
        attach!(unsafe extern "C" fn(i32, *const std::os::raw::c_char),
            b"renode_external_attach__ActionInt32String__LogAsCpu\0", log_as_cpu);
        attach!(unsafe extern "C" fn(*const std::os::raw::c_char),
            b"renode_external_attach__ActionString__ReportAbort\0", report_abort);
        attach!(unsafe extern "C" fn(u64, u32) -> u32,
            b"renode_external_attach__FuncUInt32UInt64UInt32__OnBlockBegin\0", on_block_begin);
        attach!(unsafe extern "C" fn(u64, u32),
            b"renode_external_attach__ActionUInt64UInt32__OnBlockFinished\0", on_block_finished);
        attach!(unsafe extern "C" fn() -> u32,
            b"renode_external_attach__FuncUInt32__IsInDebugMode\0", is_zero_u32);
        attach!(unsafe extern "C" fn() -> u32,
            b"renode_external_attach__FuncUInt32__IsWfiAsNop\0", is_zero_u32);
        attach!(unsafe extern "C" fn() -> u32,
            b"renode_external_attach__FuncUInt32__IsWfeAndSevAsNop\0", is_zero_u32);
        attach!(unsafe extern "C" fn() -> u64,
            b"renode_external_attach__FuncUInt64__GetTotalElapsedCycles\0", get_total_elapsed_cycles);
        attach!(unsafe extern "C" fn(*mut u8, *mut u8),
            b"renode_external_attach__ActionIntPtrIntPtr__$invalidate_tb_in_other_cpus\0",
            invalidate_tb_in_other_cpus);
        attach!(unsafe extern "C" fn(u64),
            b"renode_external_attach__ActionUInt64__$touch_host_block\0", touch_host_block);
        attach!(unsafe extern "C" fn(*mut u8, i32),
            b"renode_external_attach__ActionIntPtrInt32__OnMassBroadcastDirty\0",
            mass_broadcast_dirty);

        let init: FnInit = sym!(FnInit, b"tlib_init\0");
        let atomic_init: FnAtomicInit = sym!(FnAtomicInit, b"tlib_atomic_memory_state_init\0");
        let set_block: FnSetBlockSize = sym!(FnSetBlockSize, b"tlib_set_maximum_block_size\0");
        let execute: FnExecute = sym!(FnExecute, b"tlib_execute\0");
        let map_range: FnMapRange = sym!(FnMapRange, b"tlib_map_range\0");
        let reset: FnVoid = sym!(FnVoid, b"tlib_reset\0");
        let get_reg32: FnGetReg32 = sym!(FnGetReg32, b"tlib_get_register_value_32\0");
        let set_reg32: FnSetReg32 = sym!(FnSetReg32, b"tlib_set_register_value_32\0");

        let name = CString::new(model).map_err(|_| "model name has an interior NUL".to_string())?;
        let rc = init(name.as_ptr());
        if rc != 0 {
            return Err(format!("tlib_init(\"{model}\") returned {rc} -- unknown CPU model?"));
        }
        // -1 asks tlib to allocate the next free atomic id. Renode passes the
        // stored id only when restoring a deserialised state, which we do not do.
        atomic_init(0, -1);
        set_block(0x1000);

        Ok(Self { _lib: lib, execute, map_range, reset, get_reg32, set_reg32 })
    }

    /// Register a RAM range. Accesses inside it bypass the bus callbacks and go
    /// straight to tlib's own memory, which is what makes execution fast.
    pub fn map_range(&self, start: u64, length: u64) {
        unsafe { (self.map_range)(start, length) }
    }

    pub fn reset(&self) {
        unsafe { (self.reset)() }
    }

    pub fn register(&self, id: i32) -> u32 {
        unsafe { (self.get_reg32)(id) }
    }

    pub fn set_register(&self, id: i32, value: u32) {
        unsafe { (self.set_reg32)(id, value) }
    }

    pub fn pc(&self) -> u32 {
        self.register(reg::PC)
    }

    /// Execute up to `max_insns` instructions.
    pub fn execute(&self, max_insns: u32) -> ExecResult {
        match unsafe { (self.execute)(max_insns) } {
            0 => ExecResult::Ok,
            1 => ExecResult::Interrupted,
            n if n < 0 => ExecResult::Aborted,
            n => ExecResult::Unknown(n),
        }
    }
}

/// Locate the tlib build under a Renode source tree. Never hardcoded: the tree
/// location comes from `RENODE_SRC`.
pub fn core_path(renode_src: &Path, arch: &str) -> std::path::PathBuf {
    renode_src
        .join("output/bin/Release/platform-lib/linux-x64")
        .join(format!("translate-{arch}.so"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn core_path_is_built_from_the_tree_root() {
        let p = core_path(Path::new("/tree"), "arm-m-le");
        assert!(p.ends_with("translate-arm-m-le.so"));
    }
}
