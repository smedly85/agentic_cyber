/* Post-hoc mechanism probe (not preregistered): the heap pointer of
 * heap_direct.c returned inside a 16-byte struct.  On x86-64 clang returns it
 * as { ptr, i64 } and the caller unpacks it with extractvalue, the same shape
 * as Rust's Global::alloc_impl -> exchange_malloc. */
typedef int (*callback)(int);
extern void *probe_alloc(unsigned long size);

struct allocation { void *ptr; long len; };

int target(int value) { return value + 1; }

struct allocation allocate(void) {
    struct allocation result = { probe_alloc(sizeof(callback)), (long)sizeof(callback) };
    return result;
}

int entry(void) {
    struct allocation memory = allocate();
    callback *slot = (callback *)memory.ptr;
    *slot = target;
    return (*slot)(10);
}

int main(void) { return entry(); }
