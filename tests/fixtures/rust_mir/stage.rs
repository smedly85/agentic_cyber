extern crate stage_dependency;
#[inline(always)]
fn leaf(x: u64) -> u64 { std::hint::black_box(x) }
#[inline(always)]
fn direct(x: u64) -> u64 { leaf(x) }
#[inline(always)]
fn generic<T>(x: T) -> T { x }
struct Guard(u64);
impl Drop for Guard { fn drop(&mut self) { leaf(self.0); } }
fn main() {
    let x = std::hint::black_box(7);
    let _guard = Guard(x);
    let _ = direct(x);
    let _ = generic::<u64>(x);
    let closure = |v| leaf(v);
    let _ = closure(x);
    let _ = stage_dependency::dependency_direct(x);
    let _ = stage_dependency::dependency_generic(x);
    let _ = stage_dependency::dependency_non_generic(x);
}
