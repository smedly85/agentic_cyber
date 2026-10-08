// Controlled calibration source. Semantic labels are review metadata, not analyzer inputs.
#[derive(Clone, Copy)]
struct Ops { first: fn(i32) -> i32, second: fn(i32) -> i32 }
// @function target_a callback_target
#[inline(never)]
fn target_a(value: i32) -> i32 {
    value + 1
}
// @end target_a
// @function target_b callback_target
#[inline(never)]
fn target_b(value: i32) -> i32 {
    value + 2
}
// @end target_b
// @function unrelated callback_target
#[inline(never)]
fn unrelated(value: i32) -> i32 {
    value + 3
}
// @end unrelated
// @function invoke shared_indirect_caller
#[inline(never)]
fn invoke(object: &Ops) -> i32 {
    // @site invoke.callback
    (object.second)(10)
}
// @end invoke
// @function entry configured_source_entry
#[inline(never)]
fn entry() -> i32 {
    let stack = Ops { first: unrelated, second: target_a };
    let heap = Box::new(Ops { first: unrelated, second: target_b });
    let a = invoke(&stack);
    let b = invoke(&heap);
    a + b
}
// @end entry
// @function main runtime_harness_outside_entry_root
#[inline(never)]
fn main() {
    assert_eq!(entry(), 23);
}
// @end main
