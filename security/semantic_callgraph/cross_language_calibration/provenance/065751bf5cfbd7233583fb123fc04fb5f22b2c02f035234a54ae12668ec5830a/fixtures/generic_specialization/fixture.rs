// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target source_target
#[inline(never)]
fn target(value: i64) -> i64 {
    value + 1
}
// @end target
// @function helper generic_source_function
#[inline(never)]
fn helper<T: Into<i64>>(value: T) -> i64 {
    target(value.into())
}
// @end helper
// @function entry configured_source_entry
#[inline(never)]
fn entry() -> i64 {
    helper::<i32>(10)
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    assert_eq!(entry(), 11);
}
// @end main
