/* Post-hoc mechanism probe (not preregistered): heap slot from an allocator
 * that extapi.bc does not name.  mechanism_probe.py gives the declaration of
 * probe_alloc an LLVM allockind("alloc") attribute, like Rust's __rust_alloc. */
typedef int (*callback)(int);
extern void *probe_alloc(unsigned long size);

int target(int value) { return value + 1; }

int entry(void) {
    callback *slot = (callback *)probe_alloc(sizeof(callback));
    *slot = target;
    return (*slot)(10);
}

int main(void) { return entry(); }
