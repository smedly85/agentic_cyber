//! Supplemental controlled instrument fixture for rust_llvm_svf_v1.
//! Synthetic; not historical uutils source. It covers only constructs that the
//! existing instrument/expanded/calibration fixtures do not: mutual recursion,
//! a longer nested chain, a direct call to a body-unavailable external
//! function, and an indirect call through a pointer whose only origin is a
//! body-unavailable external function.

#[inline(never)]
pub fn target(x: u64) -> u64 { x.wrapping_add(1) }

#[inline(never)]
pub fn is_even(x: u64) -> u64 { if x == 0 { target(x) } else { is_odd(x - 1) } }
#[inline(never)]
pub fn is_odd(x: u64) -> u64 { if x == 0 { 0 } else { is_even(x - 1) } }
#[no_mangle]
pub fn entry_mutual_recursion(x: u64) -> u64 { is_even(x) }

#[inline(never)]
fn level3(x: u64) -> u64 { target(x) }
#[inline(never)]
fn level2(x: u64) -> u64 { level3(x) }
#[inline(never)]
fn level1(x: u64) -> u64 { level2(x) }
#[no_mangle]
pub fn entry_nested(x: u64) -> u64 { level1(x) }

extern "C" {
    fn external_work(x: u64) -> u64;
    fn external_callback() -> extern "C" fn(u64) -> u64;
}
#[no_mangle]
pub fn entry_external_body(x: u64) -> u64 { unsafe { external_work(x) } }

#[inline(never)]
pub fn call_unknown(x: u64) -> u64 {
    let callback = unsafe { external_callback() };
    callback(x)
}
#[no_mangle]
pub fn entry_unresolved_indirect(x: u64) -> u64 { call_unknown(x) }
