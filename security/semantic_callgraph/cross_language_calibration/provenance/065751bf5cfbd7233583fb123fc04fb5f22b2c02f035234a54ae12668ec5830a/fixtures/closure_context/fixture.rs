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
    let offset = 3;
    // @function entry::closure capturing_closure
    let callback = |value: i32| { target(value + offset) };
    // @end entry::closure
    // @site entry.callback
    callback(7)
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    assert_eq!(entry(), 11);
}
// @end main
