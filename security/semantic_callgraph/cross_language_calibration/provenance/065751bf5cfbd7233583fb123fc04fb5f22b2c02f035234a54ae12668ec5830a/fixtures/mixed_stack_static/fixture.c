// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
typedef int (*Callback)(int);
struct Ops { Callback first; Callback second; };
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
// @function unrelated callback_target
int unrelated(int value) {
    return value + 3;
}
// @end unrelated
static const struct Ops STATIC_OPS = { unrelated, target_b };
// @function invoke shared_indirect_caller
int invoke(const struct Ops *object) {
    // @site invoke.callback
    return object->second(10);
}
// @end invoke
// @function entry configured_source_entry
int entry(void) {
    struct Ops stack = { unrelated, target_a };
    int a = invoke(&stack);
    int b = invoke(&STATIC_OPS);
    return a + b;
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(void) {
    return entry() == 23 ? 0 : 1;
}
// @end main
