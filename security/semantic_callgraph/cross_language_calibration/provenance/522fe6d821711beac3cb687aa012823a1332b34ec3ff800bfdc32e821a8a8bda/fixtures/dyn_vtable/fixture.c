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
struct Third { int value; };
// @function third_operation harness_only_decoy
int third_operation(const void *context) {
    const struct Third *object = context;
    return object->value + 3;
}
// @end third_operation
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
    struct Third third = { 10 };
    struct Object decoy = { &third, third_operation };
    if (decoy.operation(decoy.context) != 13) return 1;
    (void)argv;
    int choose_b = argc > 1;
    return entry(choose_b) == (choose_b ? 12 : 11) ? 0 : 1;
}
// @end main
