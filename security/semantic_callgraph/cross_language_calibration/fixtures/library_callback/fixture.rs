// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target library_comparator
#[inline(never)]
fn target(left: &i32, right: &i32) -> std::cmp::Ordering {
    left.cmp(right)
}
// @end target
// @function entry configured_source_entry
#[inline(never)]
fn entry() -> bool {
    let mut values = [3, 1, 2];
    // @site entry.library_callback
    values.sort_by(target);
    values[0] == 1 && values[1] == 2 && values[2] == 3
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    assert!(entry());
}
// @end main
