// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target_a callback_target
#[inline(never)]
fn target_a(value: i32) -> i32 {
    value + 1
}
// @end target_a
// @function target_b callback_target
#[inline(never)]
fn target_b(value: i32) -> i32 {
    value + 2
}
// @end target_b
// @function unrelated harness_only_decoy
#[inline(never)]
fn unrelated(value: i32) -> i32 {
    value + 3
}
// @end unrelated
// @function entry configured_source_entry
#[inline(never)]
fn entry(choose_b: bool) -> i32 {
    let callback: fn(i32) -> i32 = if choose_b { target_b } else { target_a };
    // @site entry.callback
    callback(10)
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    let decoy: fn(i32) -> i32 = unrelated;
    assert_eq!(decoy(10), 13);
    let choose_b = std::env::args().len() > 1;
    assert_eq!(entry(choose_b), if choose_b { 12 } else { 11 });
}
// @end main
