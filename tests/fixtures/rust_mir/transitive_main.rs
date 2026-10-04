use transitive_dependency::Action;
#[inline(never)]
fn dynamic(value:&dyn Action)->usize {value.operation(2,3)}
fn main(){
    for second in [false,true] {
        let value=transitive_bridge::route(7,transitive_dependency::make(second),9);
        // Authenticated crates.io dependency transports the same dyn object.
        let guard=scopeguard::guard(value, |_| {});
        let value=scopeguard::ScopeGuard::into_inner(guard);
        std::hint::black_box(dynamic(&*value));
    }
}
