# Task: Extend c_mkdir — checkpoint 002

Inherit only the previous validated implementation from this same lineage. Preserve all behavior established at earlier checkpoints.

Modify only `src/c_mkdir/c_mkdir.c`; executable: `build/c_mkdir`.

Accept one or more directory operands. Create each named final directory; missing parents, existing entries (including directories), permission failures and incompatible path components are errors. Do not read stdin. Without -m, successful creation uses 0777 masked by the process umask. Exercise umasks 0000, 0022 and 0077. Process operands in order and continue after per-operand errors. Exit 0 only if all operands succeed, otherwise 1; stdout is empty, successful stderr is empty, and failures produce diagnostics identifying the operand. Diagnostics follow GNU 9.11 wording where the visible corpus asserts exact text, with program name `mkdir`.

Accept `--` as the option terminator; subsequent arguments, including dash-prefixed names, are literal operands. Bare `-` is an operand. Parse supported options before mutation, including options following operands. Unknown options and missing operands produce stderr and status 1. No other options are supported. Paths are byte strings, not necessarily UTF-8. Directory symlinks in parent components are traversed; do not replace symlinks or nondirectories. Permission, allocation and I/O failures must be diagnosed without crashing. Ownership, ACLs, SELinux, extended attributes and concurrent filesystem mutation are excluded.

## Cumulative checkpoint behavior

Add `-p` / `--parents`, idempotently. Create missing path components. Existing directories, including a symlink resolving to a directory, succeed without permission changes. Existing nondirectories still fail. New intermediate parents have permissions (0777 masked by umask) with owner write and search permission ensured, as GNU mkdir -p requires. Without -m, new final directories use the normal umask-derived mode. Repeated slashes, trailing slashes and dot components must retain normal pathname semantics.

Add `-m MODE`, `-mMODE`, `--mode MODE` and `--mode=MODE`. Last mode wins; reject invalid or empty mode arguments before creating operands, with `invalid mode` on stderr and status 1. An empty whole argument is distinct from a valid empty symbolic assignment such as `o=`.

Explicit modes override ordinary creation permissions. Numeric modes are octal (base eight), with or without a leading zero, in the range 0000..7777. Preserve requested special bits as well as ordinary permissions, independently of the process umask.

Symbolic modes use GNU Coreutils 9.11 directory semantics with `a=rwx` as the point of departure, not 0777 already reduced by umask. Accept u/g/o/a selectors, ASCII +, - and = operators, rwxXst permissions and permission-copy u/g/o, with comma-separated clauses and successive operations evaluated in order. The + operator adds permissions, - removes them, and = replaces the selected permissions, subject to the directory special-bit rules below. Each operation uses the mode resulting from preceding operations. Permission copying copies the source class's ordinary read/write/search bits to the selected classes. Conditional X supplies search permission for directories. Empty assignments clear selected ordinary permissions and are valid even at the end of an expression.

With explicit who (including a), ordinary symbolic permission changes are independent of umask. With omitted who, + and - affect only ordinary permission bits not protected by the process umask; = replaces ordinary permissions with the requested permissions filtered by that umask, clearing other ordinary permissions. This is symbolic evaluation, not a blanket umask applied again to the resulting mode. Support process umasks 0000, 0022 and 0077.

Preserve GNU special-bit semantics, including inherited directory set-user-ID/set-group-ID bits when the mode does not explicitly override them. Numeric modes of four or fewer octal digits preserve unspecified directory set-ID bits; five or more octal digits explicitly clear unspecified set-ID bits. s addresses set-user-ID for u and set-group-ID for g; t addresses sticky for o (including a or omitted who). Ordinary assignments preserve directory set-user-ID and set-group-ID bits unless explicitly addressed; sticky clearing follows the selected assignment. Retain GNU's special-bit-only behavior: `+t` and `a+t` have the same result with ordinary permissions 0755 for all three umasks above, whereas `a=rwx,+t` retains explicitly assigned ordinary permissions and is equivalent here to octal 1777. Do not generalize this sticky-only behavior into a masked starting mode for other symbolic expressions. Do not substitute host-native behavior.

With parents enabled, explicit modes apply only to newly created final directories. Newly created intermediate parents retain the parents-checkpoint umask rule with owner write and search ensured. Existing directories retain all permissions, including special bits; -m does not chmod existing final directories accepted by -p.

The behavioral requirements in this prompt are the complete specification for this checkpoint. Implement them using only the supplied source code, permitted read-only benchmark materials, and language-standard interfaces. The controller independently performs compilation and validation against the pinned GNU Coreutils 9.11 benchmark. No options outside this cumulative checkpoint are added.

## Implementation and validation

Use C11 and POSIX.1-2008 library interfaces. Choose the internal architecture and algorithms independently. Do not copy GNU or other implementations, delegate functionality to external utilities, launch subprocesses, or link third-party libraries. Do not add flags or functionality beyond this checkpoint. Handle resource failures without undefined behavior.

The controller builds inside Linux Docker with:

    cc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pedantic -O2 src/c_mkdir/c_mkdir.c -o build/c_mkdir

The visible checkpoint bundle is `tests/c-mkdir-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/c-mkdir-test-suite/judge_candidate.sh build/c_mkdir -p -m

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
