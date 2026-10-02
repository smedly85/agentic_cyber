#![no_std]

#[inline(never)]
pub fn cross_target(x: u64) -> u64 { x.wrapping_add(7) }

#[inline(never)]
pub fn cross_direct(x: u64) -> u64 { cross_target(x) }

#[inline(never)]
pub fn cross_indirect(f: fn(u64) -> u64, x: u64) -> u64 { f(x) }
