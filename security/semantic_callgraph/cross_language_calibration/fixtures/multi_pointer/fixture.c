// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
// @function target_a callback_target
int target_a(int value) {
    return value + 1;
}
// @end target_a
// @function target_b callback_target
int target_b(int value) {
    return value + 2;
}
// @end target_b
// @function unrelated harness_only_decoy
int unrelated(int value) {
    return value + 3;
}
// @end unrelated
// @function entry configured_source_entry
int entry(int choose_b) {
    int (*callback)(int) = choose_b ? target_b : target_a;
    // @site entry.callback
    return callback(10);
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(int argc, char **argv) {
    int (*decoy)(int) = unrelated;
    if (decoy(10) != 13) return 1;
    (void)argv;
    int choose_b = argc > 1;
    return entry(choose_b) == (choose_b ? 12 : 11) ? 0 : 1;
}
// @end main
