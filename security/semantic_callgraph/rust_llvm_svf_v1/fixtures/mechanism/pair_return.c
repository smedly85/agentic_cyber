/* Post-hoc mechanism probe (not preregistered): a function pointer returned
 * inside a 16-byte struct, with no heap involved.  The caller receives it via
 * extractvalue of { ptr, i64 }, as Rust receives &dyn / &[T] / Option<&T>
 * scalar pairs. */
typedef int (*callback)(int);

struct pair { callback function; long tag; };

int target(int value) { return value + 1; }

struct pair choose(void) {
    struct pair result = { target, 1 };
    return result;
}

int entry(void) {
    struct pair chosen = choose();
    return chosen.function(10);
}

int main(void) { return entry(); }
