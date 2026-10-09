#[inline(never)] fn target() {}
trait Action { fn act(&self); }
struct First;
impl Action for First { #[inline(never)] fn act(&self) { target(); } }
#[inline(never)] fn invoke(value: &dyn Action) { value.act(); }
fn main() { invoke(&First); }
