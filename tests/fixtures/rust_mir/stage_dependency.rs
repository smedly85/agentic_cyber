#[inline(always)]
pub fn dependency_leaf(x: u64) -> u64 { std::hint::black_box(x) }
#[inline(always)]
pub fn dependency_direct(x: u64) -> u64 { dependency_leaf(x) }
#[inline(always)]
pub fn dependency_generic<T>(x: T) -> T { x }
pub fn dependency_non_generic(x: u64) -> u64 { dependency_direct(x) }
