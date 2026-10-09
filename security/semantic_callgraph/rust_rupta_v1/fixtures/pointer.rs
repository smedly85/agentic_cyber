#[inline(never)] fn target() {}
#[inline(never)] fn invoke(f: fn()) { f(); }
fn main() { invoke(target); }
