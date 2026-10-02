//! Synthetic instrument validation only; not a historical specimen.
#![no_std]
extern crate semantic_dependency;

#[inline(never)]
pub fn target(x: u64) -> u64 { x.wrapping_add(1) }
#[inline(never)]
pub fn alternate(x: u64) -> u64 { x.wrapping_add(2) }
#[inline(never)]
pub fn a(x: u64) -> u64 { target(x) }
#[no_mangle]
pub fn entry_direct(x: u64) -> u64 { a(x) }

#[inline(never)]
pub fn recurse(x: u64) -> u64 {
    if x == 0 { target(x) } else { recurse(x - 1) }
}
#[no_mangle]
pub fn entry_recursion(x: u64) -> u64 { recurse(x) }

#[inline(never)]
pub fn invoke(f: fn(u64) -> u64, x: u64) -> u64 { f(x) }
#[no_mangle]
pub fn entry_function_pointer(x: u64) -> u64 { invoke(target, x) }
#[no_mangle]
pub fn entry_multi_target(x: u64) -> u64 {
    let f = if x == 0 { target } else { alternate };
    invoke(f, x)
}

pub struct Holder { pub operation: fn(u64) -> u64 }
#[inline(never)]
pub fn invoke_holder(h: Holder, x: u64) -> u64 { (h.operation)(x) }
#[no_mangle]
pub fn entry_struct_pointer(x: u64) -> u64 {
    invoke_holder(Holder { operation: target }, x)
}

#[no_mangle]
pub fn entry_closure(x: u64) -> u64 {
    let closure = |value| target(value);
    closure(x)
}

#[inline(never)]
pub fn generic<T>(x: u64, _value: T) -> u64 { target(x) }
#[no_mangle]
pub fn entry_generic(x: u64) -> u64 { generic(x, 1u8) }
#[no_mangle]
pub fn entry_multiple_instances(x: u64) -> u64 {
    generic(x, 1u8).wrapping_add(generic(x, 1u16))
}

pub trait Operation { fn operation(&self, x: u64) -> u64; }
pub struct First;
pub struct Second;
impl Operation for First {
    #[inline(never)]
    fn operation(&self, x: u64) -> u64 { target(x) }
}
impl Operation for Second {
    #[inline(never)]
    fn operation(&self, x: u64) -> u64 { alternate(x) }
}
#[inline(never)]
pub fn static_dispatch<T: Operation>(value: &T, x: u64) -> u64 {
    value.operation(x)
}
#[no_mangle]
pub fn entry_static_trait(x: u64) -> u64 { static_dispatch(&First, x) }
#[inline(never)]
pub fn dynamic_dispatch(value: &dyn Operation, x: u64) -> u64 {
    value.operation(x)
}
#[no_mangle]
pub fn entry_dynamic_trait(x: u64) -> u64 {
    if x == 0 { dynamic_dispatch(&First, x) }
    else { dynamic_dispatch(&Second, x) }
}

#[no_mangle]
pub fn entry_cross_crate_direct(x: u64) -> u64 {
    semantic_dependency::cross_direct(x)
}
#[no_mangle]
pub fn entry_cross_crate_indirect(x: u64) -> u64 {
    semantic_dependency::cross_indirect(semantic_dependency::cross_target, x)
}

pub mod left {
    #[inline(never)]
    pub fn duplicate(x: u64) -> u64 { super::target(x) }
}
pub mod right {
    #[inline(never)]
    pub fn duplicate(x: u64) -> u64 { super::alternate(x) }
}
#[no_mangle]
pub fn entry_duplicate_names(x: u64) -> u64 {
    left::duplicate(x).wrapping_add(right::duplicate(x))
}

// SVF's native entry is present; scientific entries are configured per case.
#[no_mangle]
pub fn main() -> i32 {
    // Every controlled entry is also reachable from the native root. This
    // prevents entry pruning from masquerading as a dispatch-resolution defect.
    let mut value = entry_direct(1);
    value = value.wrapping_add(entry_recursion(1));
    value = value.wrapping_add(entry_function_pointer(1));
    value = value.wrapping_add(entry_multi_target(1));
    value = value.wrapping_add(entry_struct_pointer(1));
    value = value.wrapping_add(entry_closure(1));
    value = value.wrapping_add(entry_generic(1));
    value = value.wrapping_add(entry_static_trait(1));
    value = value.wrapping_add(entry_dynamic_trait(1));
    value = value.wrapping_add(entry_cross_crate_direct(1));
    value = value.wrapping_add(entry_cross_crate_indirect(1));
    value = value.wrapping_add(entry_duplicate_names(1));
    value = value.wrapping_add(entry_multiple_instances(1));
    value as i32
}
