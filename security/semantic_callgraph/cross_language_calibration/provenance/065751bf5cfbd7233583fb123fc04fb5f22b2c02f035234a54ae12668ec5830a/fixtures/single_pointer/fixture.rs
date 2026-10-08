// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target callback_target
#[inline(never)]
fn target(value: i32) -> i32 {
    value + 1
}
// @end target
// @function entry configured_source_entry
#[inline(never)]
fn entry() -> i32 {
    let callback: fn(i32) -> i32 = target;
    // @site entry.callback
    callback(10)
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    assert_eq!(entry(), 11);
}
// @end main
