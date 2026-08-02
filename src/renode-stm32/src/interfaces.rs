//! C# interfaces as Rust traits, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! A trait here is COMPLETE: every member the C# interface declares,
//! and every interface it inherits. One that cannot be complete is
//! withheld whole and listed below -- a trait missing members would
//! carry a name it does not live up to.
//!
//! WITHHELD, with the count of members that cannot be expressed:
//!   - Antmicro.Renode.Core.IGPIO: 3 of 8 member(s) and 0 of 0 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Core.IMachine: 62 of 92 member(s) and 3 of 3 inherited interface(s) blocked -- bcl_unmapped, generic_method, interface_withheld, property_without_accessor, type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Core.Structure.Registers.IRegisterCollection: 0 of 6 member(s) and 0 of 0 inherited interface(s) blocked -- name_collision
//!   - Antmicro.Renode.Core.Structure.Registers.IRegisterCollection<T>: 0 of 4 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.Bus.IBusController: 63 of 70 member(s) and 10 of 10 inherited interface(s) blocked -- bcl_unmapped, generic_method, interface_withheld, type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Peripherals.IPeripheral: 0 of 1 member(s) and 2 of 2 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.UART.IUART: 0 of 0 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.UART.IUART<T>: 2 of 5 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision, type_without_definition
//!
//! Per-member reasons: docs/status/interfaces.md, derived by
//! scripts/interface_census.py from this same analysis.

/// C# `Antmicro.Renode.Core.Structure.Registers.IEnumRegisterField<T>`, member for member.
pub trait IEnumRegisterField<T>: IRegisterField<T> {
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IFlagRegisterField`, member for member.
pub trait IFlagRegisterField: IRegisterField<bool> {
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IPeripheralRegister<T>`, member for member.
pub trait IPeripheralRegister<T> {
    fn dump(&mut self, allow_side_effects: bool) -> csharp_rt::Array2D<String>;
    fn read(&mut self) -> T;
    fn reset(&mut self) -> ();
    fn shadow_reload(&mut self) -> ();
    fn write(&mut self, offset: i64, value: T) -> ();
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IProvidesRegisterCollection<T>`, member for member.
pub trait IProvidesRegisterCollection<T> {
    fn registers_collection(&mut self) -> T;
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IRegisterField<T>`, member for member.
pub trait IRegisterField<T> {
    fn change_callback(&mut self) -> Option<Box<dyn FnMut(T, T)>>;
    fn read_callback(&mut self) -> Option<Box<dyn FnMut(T, T)>>;
    fn shadow_reload_callback(&mut self) -> Option<Box<dyn FnMut(T, T)>>;
    fn shadow_value(&mut self) -> T;
    fn value(&mut self) -> T;
    fn value_provider_callback(&mut self) -> Option<Box<dyn FnMut(T) -> T>>;
    fn width(&mut self) -> i32;
    fn write_callback(&mut self) -> Option<Box<dyn FnMut(T, T)>>;
    fn set_change_callback(&mut self, value: Option<Box<dyn FnMut(T, T)>>) -> ();
    fn set_read_callback(&mut self, value: Option<Box<dyn FnMut(T, T)>>) -> ();
    fn set_shadow_reload_callback(&mut self, value: Option<Box<dyn FnMut(T, T)>>) -> ();
    fn set_shadow_value(&mut self, value: T) -> ();
    fn set_value(&mut self, value: T) -> ();
    fn set_value_provider_callback(&mut self, value: Option<Box<dyn FnMut(T) -> T>>) -> ();
    fn set_write_callback(&mut self, value: Option<Box<dyn FnMut(T, T)>>) -> ();
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IValueRegisterField`, member for member.
pub trait IValueRegisterField: IRegisterField<u64> {
}
