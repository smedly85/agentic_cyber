// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
trait Action { fn operation(&self) -> i32; }
struct First { value: i32 }
struct Second { value: i32 }
impl Action for First {
// @function First::operation target_a
#[inline(never)]
fn operation(&self) -> i32 {
    self.value + 1
}
// @end First::operation
}
impl Action for Second {
// @function Second::operation target_b
#[inline(never)]
fn operation(&self) -> i32 {
    self.value + 2
}
// @end Second::operation
}
// @function entry configured_source_entry
#[inline(never)]
fn entry(choose_b: bool) -> i32 {
    let first = First { value: 10 };
    let second = Second { value: 10 };
    let receiver: &dyn Action = if choose_b { &second } else { &first };
    // @site entry.dispatch
    receiver.operation()
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    let choose_b = std::env::args().len() > 1;
    assert_eq!(entry(choose_b), if choose_b { 12 } else { 11 });
}
// @end main
