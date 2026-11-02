# Task: Extend rust_mv — checkpoint 002

Inherit only the previous validated implementation from this same lineage. Preserve all behavior established at earlier checkpoints.

Modify only `src/rust_mv/rust_mv.rs`; executable: `build/rust_mv`.

Accept SOURCE DEST or SOURCE... DIRECTORY. With several sources the last operand must be an existing directory; with one source and a directory destination, the effective destination is DIRECTORY/source-basename. Do not create missing destination parents. Validate invocation-wide errors before any filesystem changes. Process sources in operand order, diagnose per-source failures and continue; do not roll back completed operations. Preserve source data on failure.

Options may appear anywhere before the first `--`; thereafter all arguments are literal operands. Bare `-` is a filename. Preserve arbitrary non-NUL pathname bytes, including invalid UTF-8. Combined short options are outside scope. Missing operands, unknown options and invalid multi-source destinations produce empty stdout, a diagnostic on stderr and status 1. Successful operations have status 0, empty stdout and empty stderr except interactive prompts. All per-source failures contribute status 1. Exact error wording is unconstrained, but diagnostics must identify the affected operand.

Use ordinary rwx permissions and umask 022. Files contain arbitrary bytes. Fixtures contain regular files, directories and symlinks whose targets stay in the case tree. Special files, ownership preservation, ACLs, extended attributes, timestamps, sparse allocation, special permission bits and cross-filesystem moves are excluded. Do not bypass operating-system permission errors. Handle ordinary allocation and I/O errors without crashing.

Move regular files, symlinks and directory trees on one filesystem. Preserve moved contents and modes. A successful move removes the old source name. Move a source symlink itself; replace a nondirectory destination symlink itself, without changing its target. Existing directory destinations select a source basename; replace an empty directory at that effective destination when GNU permits, but never merge trees into a nonempty destination. Diagnose identical source/destination, incompatible types, a directory moved into itself or its descendants, missing sources and parent-permission errors. Input is non-terminal; the base checkpoint does not prompt for write-protected destinations.

## Cumulative checkpoint behavior

Add `-f` / `--force`. Force suppresses overwrite confirmation, including for a write-protected destination, but does not bypass parent permissions or type constraints. Repetitions are idempotent. Preserve all base error behavior.

Add `-i` / `--interactive`. Prompt on stderr naming an existing effective destination before replacement, and consume a line from stdin. Initial ASCII y or Y affirms; all other initials, leading whitespace, blank input and EOF decline. Decline leaves source and destination unchanged and contributes status 1 under GNU 9.11; continue later sources. No prompt for a missing destination. The LAST occurrence among force and interactive selects the overwrite policy, including mixed short and long forms: `-i -f` does not prompt and `-f -i` prompts. This precedence differs from cp.

## Implementation and validation

Use one standalone Rust 2021 source file, Rust 1.85.1 and the standard library only, with applicable POSIX filesystem behavior. Choose the internal architecture and algorithms independently. No unsafe blocks, Cargo dependencies, external utilities, subprocess delegation or copied implementations. Do not add flags or functionality beyond this checkpoint. Handle ordinary errors without panics; preserve arbitrary pathname and file bytes.

Preserve the established semantic anchor `move_path`: the core filesystem operation must be reachable from main through it. Choose all remaining structure freely; do not add artificial helper functions or target a particular call depth.

The controller builds inside Linux Docker with:

    rustc --edition=2021 -C opt-level=2 -D warnings src/rust_mv/rust_mv.rs -o build/rust_mv

The visible checkpoint bundle is `tests/rust-mv-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/rust-mv-test-suite/judge_candidate.sh build/rust_mv -f -i

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
