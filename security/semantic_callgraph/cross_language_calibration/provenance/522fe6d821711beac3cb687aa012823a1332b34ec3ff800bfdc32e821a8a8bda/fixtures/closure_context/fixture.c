// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
struct Environment { int offset; };
// @function target callback_target
int target(int value) {
    return value + 1;
}
// @end target
// @function callback environment_callback
int callback(const struct Environment *environment, int value) {
    return target(value + environment->offset);
}
// @end callback
// @function entry configured_source_entry
int entry(void) {
    struct Environment environment = { 3 };
    int (*function)(const struct Environment *, int) = callback;
    // @site entry.callback
    return function(&environment, 7);
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(void) {
    return entry() == 11 ? 0 : 1;
}
// @end main
