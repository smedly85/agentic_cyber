fn parse_symbolic_mode(s: &str, umask: u32) -> Option<u32> {
    if s.is_empty() {
        return None;
    }
    // GNU special-bit-only behavior: when the expression involves special
    // bits (s/t) but no ordinary permission chars (r/w/x/X), ordinary bits
    // default to 0755 regardless of umask.
    let has_special = s.bytes().any(|b| b == b's' || b == b't');
    let has_rwx = s.bytes().any(|b| b == b'r' || b == b'w' || b == b'x' || b == b'X');
    let mut mode: u32 = if has_special && !has_rwx { 0o755 } else { 0o777 };
    for clause in s.split(',') {
        if clause.is_empty() {
            return None;
        }
        apply_symbolic_clause(&mut mode, clause, umask)?;
    }
    Some(mode & 0o7777)
}
