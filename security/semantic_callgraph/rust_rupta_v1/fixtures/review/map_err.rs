#[inline(never)] fn callback_target() {}
#[inline(never)] fn returned_target() {}
#[inline(never)] fn driver() {
    let result: Result<(), fn()> = Err(returned_target);
    let mapped = result.map_err(|f| { callback_target(); f });
    if let Err(f) = mapped { f(); }
}
fn main() { driver(); }
