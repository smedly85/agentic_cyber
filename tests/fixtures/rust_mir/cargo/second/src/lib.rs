#[inline(never)]
pub fn target(value: u64) -> u64 { value }
#[inline(never)]
pub fn invoke(callback: fn(u64) -> u64, value: u64) -> u64 { callback(value) }
