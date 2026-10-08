// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
#include <stdlib.h>
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
    struct Ops *object = malloc(sizeof *object);
    if (object == NULL) return -1;
    object->first = other;
    object->second = target;
    // @site entry.callback
    int result = object->second(10);
    free(object);
    return result;
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(void) {
    return entry() == 11 ? 0 : 1;
}
// @end main
