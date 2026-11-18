# Task: Extend rust_mkdir — checkpoint 001

Inherit only the previous validated implementation from this same lineage. Preserve all behavior established at earlier checkpoints.

Modify only `src/rust_mkdir/rust_mkdir.rs`; executable: `build/rust_mkdir`.

Accept one or more directory operands. Create each named final directory; missing parents, existing entries (including directories), permission failures and incompatible path components are errors. Do not read stdin. Successful creation uses 0777 masked by the process umask. Exercise umasks 0000, 0022 and 0077. Process operands in order and continue after per-operand errors. Exit 0 only if all operands succeed, otherwise 1; stdout is empty, successful stderr is empty, and failures produce diagnostics identifying the operand. Diagnostics follow GNU 9.11 wording where the visible corpus asserts exact text, with program name `mkdir`.

Accept `--` as the option terminator; subsequent arguments, including dash-prefixed names, are literal operands. Bare `-` is an operand. Parse supported options before mutation, including options following operands. Unknown options and missing operands produce stderr and status 1. No other options are supported. Paths are byte strings, not necessarily UTF-8. Directory symlinks in parent components are traversed; do not replace symlinks or nondirectories. Permission, allocation and I/O failures must be diagnosed without crashing. Ownership, ACLs, SELinux, extended attributes and concurrent filesystem mutation are excluded.

## Cumulative checkpoint behavior

Add `-p` / `--parents`, idempotently. Create missing path components. Existing directories, including a symlink resolving to a directory, succeed without permission changes. Existing nondirectories still fail. New intermediate parents have permissions (0777 masked by umask) with owner write and search permission ensured, as GNU mkdir -p requires. New final directories use the normal umask-derived mode. Repeated slashes, trailing slashes and dot components must retain normal pathname semantics.

## Implementation and validation

Use one standalone Rust 2021 source file, Rust 1.85.1 and the standard library only, with applicable POSIX filesystem behavior. Choose the internal architecture and algorithms independently. No unsafe blocks, Cargo dependencies, external utilities, subprocess delegation or copied implementations. Do not add flags or functionality beyond this checkpoint. Handle ordinary errors without panics; preserve arbitrary pathname and file bytes.

The controller builds inside Linux Docker with:

    rustc --edition=2021 -C opt-level=2 -D warnings src/rust_mkdir/rust_mkdir.rs -o build/rust_mkdir

The visible checkpoint bundle is `tests/rust-mkdir-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/rust-mkdir-test-suite/judge_candidate.sh build/rust_mkdir -p

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
