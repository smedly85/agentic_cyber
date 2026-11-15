## Session conditions

This is a fully automated, non-interactive implementation task in Aider.
The editable source and selected read-only files are supplied through Aider.
Use the supplied contents; a path mentioned in the prompt does not mean you
can independently open it. Do not promise or claim to inspect files, search
the repository, or run commands using tools unavailable in this session.

No user is available to answer questions or approve work. Do not ask questions,
request approval, defer implementation, or finish with a proposed plan or an
offer to continue. Produce concrete implementation instructions and source
edits during the current invocation, within the allowed file scope.

If a requirement is ambiguous or underspecified, choose the most reasonable
interpretation consistent with the rest of this prompt and proceed. State the
interpretation you chose in your final response.

Every requirement in the supplied checkpoint prompt is mandatory within its
stated scope. "Base checkpoint" and "no options" do not mean illustrative or
minimal demonstration functionality: implement the complete specified baseline.
Later checkpoints add only their specified features; do not defer current
requirements to them or implement future checkpoint flags early.

In architect/editor mode, the architect must give the editor complete, concrete
implementation instructions covering all required behavior, argument handling,
filesystem semantics, safeguards, errors and exit status. The editor must apply
the corresponding source edits now. Do not substitute exploratory commentary,
repeated reconsideration, or a partial feature sketch for this handoff.

The controller handles compilation, validation, and subsequent repair
invocations. Build and validation commands in the task describe that controller
workflow; do not claim to have run them. Correct reported compiler errors and
warnings in the source. Do not wait for another invocation to implement known
requirements or run an autonomous validation/repair loop. Keep any completion
report brief and factual, describing actual edits and unresolved constraints
without conversational closing language. This session rule does not suppress
confirmation prompts that the implemented utility is explicitly required to emit.

Nothing in this section changes what the program must do. The task,
its scope, and the validation that follows are defined by the rest of this
prompt.

# Task: Extend c_cp — checkpoint 003

Inherit only the previous validated implementation from this same lineage. Preserve all behavior established at earlier checkpoints.

Modify only `src/c_cp/c_cp.c`; executable: `build/c_cp`.

Accept SOURCE DEST or SOURCE... DIRECTORY. With several sources the last operand must be an existing directory; with one source and a directory destination, the effective destination is DIRECTORY/source-basename. Do not create missing destination parents. Validate invocation-wide errors before any filesystem changes. Process sources in operand order, diagnose per-source failures and continue; do not roll back completed operations. Preserve source data on failure.

Options may appear anywhere before the first `--`; thereafter all arguments are literal operands. Bare `-` is a filename. Preserve arbitrary non-NUL pathname bytes, including invalid UTF-8. Combined short options are outside scope. Missing operands, unknown options and invalid multi-source destinations produce empty stdout, a diagnostic on stderr and status 1. Successful operations have status 0, empty stdout and empty stderr except interactive prompts. All per-source failures contribute status 1. Exact error wording is unconstrained, but diagnostics must identify the affected operand.

Use ordinary rwx permissions and umask 022. Files contain arbitrary bytes. Fixtures contain regular files, directories and symlinks whose targets stay in the case tree. Special files, ownership preservation, ACLs, extended attributes, timestamps, sparse allocation, special permission bits and cross-filesystem moves are excluded. Do not bypass operating-system permission errors. Handle ordinary allocation and I/O errors without crashing.

Copy regular file contents without altering the source. Overwrite existing regular destinations; retain existing destination rwx bits. New files have source rwx bits masked by umask. Reject directory sources. Follow source symlinks to regular files and existing destination symlinks to regular files; reject dangling destination links. Reject self-copy, including filesystem aliases, before destructive changes. Missing/unreadable sources, unwritable destinations and incompatible types are errors.

## Cumulative checkpoint behavior

Add `-f` / `--force`, idempotently. A normally writable existing destination is overwritten in place, retaining its permissions. When normal opening fails for an existing nondirectory destination, force permits removing that entry and creating its replacement if parent permissions allow. The replacement receives source rwx bits masked by umask. Force does not bypass source or parent permissions or replace a directory with a file.

Add `-i` / `--interactive`. Before overwriting an existing effective destination, prompt on stderr naming it and consume one line from stdin. Only an initial ASCII y or Y affirms; leading whitespace, empty input, EOF and other initials decline. Decline preserves the destination, contributes status 1 under GNU 9.11, and processing continues without an additional error. Do not prompt for a missing destination. Force and interactive are independent in either order: confirmation is required before a force replacement can occur.

Add `-r` / `--recursive`. Directory sources now copy their descendants and empty directories. A missing destination becomes the tree root; an existing directory destination receives source-basename, merging existing directories there. New directories receive source rwx bits masked by umask; existing directories keep their bits. In recursive mode all source symlinks, including operand symlinks and dangling or cyclic links, are recreated with identical target bytes and are not traversed. Without recursive mode preserve earlier symlink behavior. Destination symlink collisions within a copied tree are excluded. Preserve force and interactive behavior for regular files. Reject incompatible types and copying a directory into itself or a descendant; an initial empty output directory may remain, but no descendants may be copied into it. Traversal order is not prescribed; cases with multiple interactive collisions in a recursive tree are excluded because GNU traversal order is filesystem-dependent. Resource limits must produce a diagnostic rather than looping or crashing.

## Implementation and validation

Use C11 and POSIX.1-2008 library interfaces. Choose the internal architecture and algorithms independently. Do not copy GNU or other implementations, delegate functionality to external utilities, launch subprocesses, or link third-party libraries. Do not add flags or functionality beyond this checkpoint. Handle resource failures without undefined behavior.

Preserve the established semantic anchor `copy_path`: the core filesystem operation must be reachable from main through it. Choose all remaining structure freely; do not add artificial helper functions or target a particular call depth.

The controller builds inside Linux Docker with:

    cc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pedantic -O2 src/c_cp/c_cp.c -o build/c_cp

The visible checkpoint bundle is `tests/c-cp-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/c-cp-test-suite/judge_candidate.sh build/c_cp -f -i -r

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
