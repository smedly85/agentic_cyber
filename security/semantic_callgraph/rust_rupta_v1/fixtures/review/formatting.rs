use std::fmt;
struct Value;
#[inline(never)] fn display_target() {}
impl fmt::Display for Value {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        display_target(); f.write_str("value")
    }
}
fn main() { std::hint::black_box(format!("{}", Value)); }
