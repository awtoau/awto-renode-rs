//! The dispatch trait, exercised rather than merely compiled.
//!
//! The claim the inheritance-layout decision turns on is that ONE trait object
//! spans peripherals whose `State` types differ, with the flattened state and
//! the free-fn bodies left exactly as they are. That is a language claim, and a
//! spike proved it in a scratch crate; this proves it against the committed
//! generated module, which is a different thing -- the spike patched the
//! declaration template in memory and no committed file had to change.
//!
//! The second test is the one that matters. "It compiles" is not evidence in
//! this project, and a vtable that reaches the WRONG body compiles perfectly:
//! that is exactly what the permissive resolver produced, giving three of four
//! peripherals a `reset` that ran the base's. So dispatch is checked against
//! calling the free function directly -- if the vtable ever forwards somewhere
//! else, the two disagree.

use std::cell::RefCell;
use std::rc::Rc;

use renode_stm32::dispatch::{
    AdcRegisters, BasicDoubleWordPeripheral, DmaRegisters, ExtiRegisters,
    UartRegisters,
};

#[test]
fn one_trait_object_over_four_state_types() {
    let bus: Vec<Rc<RefCell<dyn BasicDoubleWordPeripheral>>> = vec![
        Rc::new(RefCell::new(DmaRegisters::new())),
        Rc::new(RefCell::new(ExtiRegisters::new())),
        Rc::new(RefCell::new(AdcRegisters::new())),
        Rc::new(RefCell::new(UartRegisters::new())),
    ];
    assert_eq!(bus.len(), 4);
    for p in &bus {
        // Reached through `dyn`, so each element's own body runs even though
        // the four `State` types have nothing in common.
        let _ = p.borrow_mut().read_double_word(0);
    }
}

/// Every offset the four peripherals' reset values differ at is a place where
/// dispatching to the wrong body would be visible. Asserting they are not all
/// equal is what stops the test above passing on a vtable wired to one body.
#[test]
fn the_four_do_not_all_answer_alike() {
    let mut dma = DmaRegisters::new();
    let mut exti = ExtiRegisters::new();
    let mut adc = AdcRegisters::new();
    let mut uart = UartRegisters::new();
    let seen: Vec<u32> = (0..0x20u64)
        .map(|off| {
            let o = off as i64 * 4;
            dma.read_double_word(o)
                ^ exti.read_double_word(o)
                ^ adc.read_double_word(o)
                ^ uart.read_double_word(o)
        })
        .collect();
    assert!(seen.iter().any(|v| *v != 0),
            "all four peripherals answered identically at every offset -- a \
             vtable wired to one body would look exactly like this");
}

macro_rules! same_as_calling_it_directly {
    ($name:ident, $ty:ident, $module:ident) => {
        #[test]
        fn $name() {
            for off in (0..0x40i64).map(|i| i * 4) {
                let mut through: Box<dyn BasicDoubleWordPeripheral> =
                    Box::new($ty::new());
                let via_trait = through.read_double_word(off);
                let mut direct = $ty::new();
                let via_fn = renode_stm32::$module::read_double_word(
                    &direct.bank, &mut direct.st, off);
                assert_eq!(via_trait, via_fn,
                           "dispatch reached a different body at offset {off:#x}");
            }
        }
    };
}

same_as_calling_it_directly!(dma_dispatches_to_its_own_body, DmaRegisters,
                             dma_registers);
same_as_calling_it_directly!(exti_dispatches_to_its_own_body, ExtiRegisters,
                             exti_registers);
same_as_calling_it_directly!(adc_dispatches_to_its_own_body, AdcRegisters,
                             adc_registers);
same_as_calling_it_directly!(uart_dispatches_to_its_own_body, UartRegisters,
                             uart_registers);
