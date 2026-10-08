// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target source_target
long long target(long long value) {
    return value + 1;
}
// @end target
// @function helper_i32 hand_specialized_helper
long long helper_i32(int value) {
    return target((long long)value);
}
// @end helper_i32
// @function entry configured_source_entry
long long entry(void) {
    return helper_i32(10);
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(void) {
    return entry() == 11 ? 0 : 1;
}
// @end main
