# Task: Extend c_cp — checkpoint 001

Inherit only the previous validated implementation from this same lineage. Preserve all behavior established at earlier checkpoints.

Modify only `src/c_cp/c_cp.c`; executable: `build/c_cp`.

Accept SOURCE DEST or SOURCE... DIRECTORY. With several sources the last operand must be an existing directory; with one source and a directory destination, the effective destination is DIRECTORY/source-basename. Do not create missing destination parents. Validate invocation-wide errors before any filesystem changes. Process sources in operand order, diagnose per-source failures and continue; do not roll back completed operations. Preserve source data on failure.

Options may appear anywhere before the first `--`; thereafter all arguments are literal operands. Bare `-` is a filename. Preserve arbitrary non-NUL pathname bytes, including invalid UTF-8. Combined short options are outside scope. Missing operands, unknown options and invalid multi-source destinations produce empty stdout, a diagnostic on stderr and status 1. Successful operations have status 0, empty stdout and empty stderr except interactive prompts. All per-source failures contribute status 1. Exact error wording is unconstrained, but diagnostics must identify the affected operand.

Use ordinary rwx permissions and umask 022. Files contain arbitrary bytes. Fixtures contain regular files, directories and symlinks whose targets stay in the case tree. Special files, ownership preservation, ACLs, extended attributes, timestamps, sparse allocation, special permission bits and cross-filesystem moves are excluded. Do not bypass operating-system permission errors. Handle ordinary allocation and I/O errors without crashing.

Copy regular file contents without altering the source. Overwrite existing regular destinations; retain existing destination rwx bits. New files have source rwx bits masked by umask. Reject directory sources. Follow source symlinks to regular files and existing destination symlinks to regular files; reject dangling destination links. Reject self-copy, including filesystem aliases, before destructive changes. Missing/unreadable sources, unwritable destinations and incompatible types are errors.

## Cumulative checkpoint behavior

Add `-f` / `--force`, idempotently. A normally writable existing destination is overwritten in place, retaining its permissions. When normal opening fails for an existing nondirectory destination, force permits removing that entry and creating its replacement if parent permissions allow. The replacement receives source rwx bits masked by umask. Force does not bypass source or parent permissions or replace a directory with a file.

## Implementation and validation

Use C11 and POSIX.1-2008 library interfaces. Choose the internal architecture and algorithms independently. Do not copy GNU or other implementations, delegate functionality to external utilities, launch subprocesses, or link third-party libraries. Do not add flags or functionality beyond this checkpoint. Handle resource failures without undefined behavior.

Preserve the established semantic anchor `copy_path`: the core filesystem operation must be reachable from main through it. Choose all remaining structure freely; do not add artificial helper functions or target a particular call depth.

The controller builds inside Linux Docker with:

    cc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pedantic -O2 src/c_cp/c_cp.c -o build/c_cp

The visible checkpoint bundle is `tests/c-cp-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/c-cp-test-suite/judge_candidate.sh build/c_cp -f

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
