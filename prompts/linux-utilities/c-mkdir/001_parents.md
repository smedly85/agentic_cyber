# Task: Extend c_mkdir — checkpoint 001

Inherit only the previous validated implementation from this same lineage. Preserve all behavior established at earlier checkpoints.

Modify only `src/c_mkdir/c_mkdir.c`; executable: `build/c_mkdir`.

Accept one or more directory operands. Create each named final directory; missing parents, existing entries (including directories), permission failures and incompatible path components are errors. Do not read stdin. Successful creation uses 0777 masked by the process umask. Exercise umasks 0000, 0022 and 0077. Process operands in order and continue after per-operand errors. Exit 0 only if all operands succeed, otherwise 1; stdout is empty, successful stderr is empty, and failures produce diagnostics identifying the operand. Diagnostics follow GNU 9.11 wording where the visible corpus asserts exact text, with program name `mkdir`.

Accept `--` as the option terminator; subsequent arguments, including dash-prefixed names, are literal operands. Bare `-` is an operand. Parse supported options before mutation, including options following operands. Unknown options and missing operands produce stderr and status 1. No other options are supported. Paths are byte strings, not necessarily UTF-8. Directory symlinks in parent components are traversed; do not replace symlinks or nondirectories. Permission, allocation and I/O failures must be diagnosed without crashing. Ownership, ACLs, SELinux, extended attributes and concurrent filesystem mutation are excluded.

## Cumulative checkpoint behavior

Add `-p` / `--parents`, idempotently. Create missing path components. Existing directories, including a symlink resolving to a directory, succeed without permission changes. Existing nondirectories still fail. New intermediate parents have permissions (0777 masked by umask) with owner write and search permission ensured, as GNU mkdir -p requires. New final directories use the normal umask-derived mode. Repeated slashes, trailing slashes and dot components must retain normal pathname semantics.

## Implementation and validation

Use C11 and POSIX.1-2008 library interfaces. Choose the internal architecture and algorithms independently. Do not copy GNU or other implementations, delegate functionality to external utilities, launch subprocesses, or link third-party libraries. Do not add flags or functionality beyond this checkpoint. Handle resource failures without undefined behavior.

The controller builds inside Linux Docker with:

    cc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pedantic -O2 src/c_mkdir/c_mkdir.c -o build/c_mkdir

The visible checkpoint bundle is `tests/c-mkdir-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/c-mkdir-test-suite/judge_candidate.sh build/c_mkdir -p

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
