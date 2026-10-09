fn target() {}
fn third() {}
struct Ops { a: fn(), b: fn() }
fn main() {
    let ops = Ops { a: third, b: target };
    (ops.b)();
}
