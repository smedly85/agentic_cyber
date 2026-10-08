// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
#[derive(Clone, Copy)]
struct Ops { first: fn(i32) -> i32, second: fn(i32) -> i32 }
// @function target callback_target
#[inline(never)]
fn target(value: i32) -> i32 {
    value + 1
}
// @end target
// @function other callback_target
#[inline(never)]
fn other(value: i32) -> i32 {
    value + 2
}
// @end other
// @function entry configured_source_entry
#[inline(never)]
fn entry() -> i32 {
    let object = Box::new(Ops { first: other, second: target });
    // @site entry.callback
    (object.second)(10)
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    assert_eq!(entry(), 11);
}
// @end main
