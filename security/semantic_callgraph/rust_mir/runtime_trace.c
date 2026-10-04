/* Controlled Rust tracing support only; not part of the frozen C instrument. */
#include <stdint.h>
#include <unistd.h>
void mir_trace_record(uintptr_t callee, uintptr_t caller) {
    uintptr_t edge[2] = {callee, caller};
    /* Descriptor 3 is installed by the controlled runner. A failed write exits,
       so truncated/missing trace data can never be reported as a pass. */
    if (write(3, edge, sizeof edge) != sizeof edge) _exit(121);
}
