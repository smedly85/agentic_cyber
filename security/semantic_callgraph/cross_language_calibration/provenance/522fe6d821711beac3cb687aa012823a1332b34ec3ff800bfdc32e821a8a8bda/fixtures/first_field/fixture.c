// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
typedef int (*Callback)(int);
struct Ops { Callback first; Callback second; };
// @function target callback_target
int target(int value) {
    return value + 1;
}
// @end target
// @function other callback_target
int other(int value) {
    return value + 2;
}
// @end other
// @function entry configured_source_entry
int entry(void) {
    struct Ops original = { target, other };
    // @site entry.callback
    return original.first(10);
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(void) {
    return entry() == 11 ? 0 : 1;
}
// @end main
