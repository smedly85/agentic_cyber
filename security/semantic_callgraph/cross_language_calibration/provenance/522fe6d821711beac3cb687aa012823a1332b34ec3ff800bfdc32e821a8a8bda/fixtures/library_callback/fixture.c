// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
#include <stdlib.h>
// @function target library_comparator
int target(const void *left, const void *right) {
    int a = *(const int *)left;
    int b = *(const int *)right;
    return (a > b) - (a < b);
}
// @end target
// @function entry configured_source_entry
int entry(void) {
    int values[3] = { 3, 1, 2 };
    // @site entry.library_callback
    qsort(values, 3, sizeof values[0], target);
    return values[0] == 1 && values[1] == 2 && values[2] == 3;
}
// @end entry
// @function main runtime_harness_outside_entry_root
int main(void) {
    return entry() ? 0 : 1;
}
// @end main
