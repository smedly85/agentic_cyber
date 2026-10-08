// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target callback_target
int target(int value) {
    return value + 1;
}
// @end target
// @function recursive recursive_helper
int recursive(unsigned remaining) {
    if (remaining == 0) return target(10);
    return recursive(remaining - 1);
}
// @end recursive
// @function entry configured_source_entry
int entry(void) {
    return recursive(2);
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(void) {
    return entry() == 11 ? 0 : 1;
}
// @end main
