// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target callback_target
int target(int value) {
    return value + 1;
}
// @end target
// @function helper application_helper
int helper(int value) {
    return target(value);
}
// @end helper
// @function entry configured_source_entry
int entry(void) {
    return helper(10);
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(void) {
    return entry() == 11 ? 0 : 1;
}
// @end main
