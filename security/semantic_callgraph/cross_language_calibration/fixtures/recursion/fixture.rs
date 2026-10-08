// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target callback_target
#[inline(never)]
fn target(value: i32) -> i32 {
    value + 1
}
// @end target
// @function recursive recursive_helper
#[inline(never)]
fn recursive(remaining: u32) -> i32 {
    if remaining == 0 { return target(10); }
    recursive(remaining - 1)
}
// @end recursive
// @function entry configured_source_entry
#[inline(never)]
fn entry() -> i32 {
    recursive(2)
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    assert_eq!(entry(), 11);
}
// @end main
