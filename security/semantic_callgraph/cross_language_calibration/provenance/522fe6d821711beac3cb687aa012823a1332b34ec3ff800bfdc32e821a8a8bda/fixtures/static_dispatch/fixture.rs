// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
trait Action { fn operation(&self, value: i32) -> i32; }
struct First;
// @function target callback_target
#[inline(never)]
fn target(value: i32) -> i32 {
    value + 1
}
// @end target
impl Action for First {
// @function First::operation concrete_operation
#[inline(never)]
fn operation(&self, value: i32) -> i32 {
    target(value)
}
// @end First::operation
}
struct Second;
impl Action for Second {
// @function Second::operation harness_only_decoy
#[inline(never)]
fn operation(&self, value: i32) -> i32 {
    value + 3
}
// @end Second::operation
}
// @function entry configured_source_entry
#[inline(never)]
fn entry() -> i32 {
    First.operation(10)
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    assert_eq!(Second.operation(10), 13);
    assert_eq!(entry(), 11);
}
// @end main
