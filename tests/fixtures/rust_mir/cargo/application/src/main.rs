fn main() {
    let guard = scopeguard::guard(1_u64, |value| { mir_controlled_first::entry(value); });
    mir_controlled_first::entry(2);
    drop(guard);
}
