#[inline(never)] fn target() {}
#[inline(never)] fn recursive(n: u32) { if n == 0 { target(); } else { recursive(n - 1); } }
fn main() { recursive(std::hint::black_box(2)); }
