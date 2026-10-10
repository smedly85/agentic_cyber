use std::sync::Once;
static A: Once = Once::new();
static B: Once = Once::new();
#[inline(never)] fn target_a() {}
#[inline(never)] fn target_b() {}
#[inline(never)] fn driver_a() { A.call_once(|| target_a()); }
#[inline(never)] fn driver_b() { B.call_once_force(|_| target_b()); }
fn main() { driver_a(); driver_b(); }
