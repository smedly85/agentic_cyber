#[inline(never)] fn target() {}
#[inline(never)] fn second() { target(); }
#[inline(never)] fn first() { second(); }
fn main() { first(); }
