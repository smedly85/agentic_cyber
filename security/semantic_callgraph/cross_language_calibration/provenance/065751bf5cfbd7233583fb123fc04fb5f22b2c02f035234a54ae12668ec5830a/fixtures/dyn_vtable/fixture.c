// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
struct First { int value; };
struct Second { int value; };
struct Object { const void *context; int (*operation)(const void *); };
// @function first_operation target_a
int first_operation(const void *context) {
    const struct First *object = context;
    return object->value + 1;
}
// @end first_operation
// @function second_operation target_b
int second_operation(const void *context) {
    const struct Second *object = context;
    return object->value + 2;
}
// @end second_operation
// @function entry configured_source_entry
int entry(int choose_b) {
    struct First first = { 10 };
    struct Second second = { 10 };
    struct Object a = { &first, first_operation };
    struct Object b = { &second, second_operation };
    const struct Object *receiver = choose_b ? &b : &a;
    // @site entry.dispatch
    return receiver->operation(receiver->context);
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(int argc, char **argv) {
    (void)argv;
    int choose_b = argc > 1;
    return entry(choose_b) == (choose_b ? 12 : 11) ? 0 : 1;
}
// @end main
