# Task: Add -i to new_cp

Modify:

    src/new_cp/new_cp.rs

Modify only this implementation file.

The executable must remain:

    build/new_cp

Implement only the bounded behavior described here.

## Current program

Preserve the base contract below and the already implemented options `-f` unless explicitly changed.
Keep the canonical function `copy_path`: do not rename or remove it.
The core filesystem operation must remain reachable from `main` through it.
Preserve force's remove-and-recreate fallback.


## Program behavior

Copy regular files, including empty files, arbitrary binary/NUL bytes and practical
large files, without changing source contents. Create a missing destination file
or overwrite an existing regular file. If DEST is an existing directory, copy
each source to DEST/source-basename; with multiple sources the final operand
must be an existing directory. Do not create missing destination parents.
A directory source is an error in this checkpoint. Diagnose missing/unreadable
sources, unwritable destinations, missing parents and incompatible object types.
Detect copying a file onto itself (including aliases detectable with filesystem
identity) before truncating it; leave its contents unchanged.

A source symlink to a regular file is followed. An existing destination symlink
to a regular file is followed; a dangling destination link is an error. Special
files are outside this contract. Symlink targets in tests stay within the case
tree. With umask 022, new files use source ordinary rwx bits masked by umask;
overwriting an existing file retains its ordinary rwx bits. Ownership, ACLs,
extended attributes, timestamps, sparse allocation and special mode bits are
outside scope.

Process source operands in command-line order. A per-source failure is diagnosed
and does not stop later source operands; return 1 if any source failed.
Nothing goes to stdout. Successful operations have empty stderr except for
explicitly requested confirmation. Errors go to stderr and name the relevant
operand; exact diagnostic wording is not prescribed. Return 0 on complete
success, 1 on errors. Do not roll back completed
operations after a later source fails.

## New behavior

Add only `-i` and `--interactive`; repetitions are idempotent.
Before overwriting an existing destination, emit a prompt naming the destination
on stderr and read one line from stdin. In the C locale, a line whose FIRST
byte is ASCII y or Y is affirmative (including yes, Y, and y followed by other
bytes). Leading whitespace is not ignored. Empty input, EOF and all other first
bytes decline. Consume the entire line. Declining leaves that destination
unchanged and contributes status 1 for the invocation, as in GNU 9.11; continue
later sources and do not emit an additional error for the decline. Do not prompt for a nonexistent
destination.

The existing `-f` and new `-i` are independent: neither cancels the other,
regardless of order. When both are present, ask first; only after approval may
normal opening and the remove-and-recreate fallback proceed. Preserve this for
both `-f -i` and `-i -f`, including long forms.

## Arguments

    build/new_cp SOURCE DEST
    build/new_cp SOURCE... DIRECTORY

Accept only `-f` / `--force`, `-i` / `--interactive`.
Recognize options anywhere before `--`. The terminator ends option parsing;
after it every argument is an operand, including names starting with `-`.
A bare `-` is an ordinary filename. Missing operands, unknown short/long
options, or multiple sources without a directory target must fail before
mutating anything, with stderr diagnostic, empty stdout and status 1.
Combined short option spellings are outside the contract.

## Reference

GNU Coreutils 9.11 cp is the functional behavioral reference only within this
bounded contract; full GNU compatibility is not required. Implement independently.
Do not copy reference source code or implementation details.

## Error handling

Handle ordinary I/O, permission, allocation/resource and argument failures
without crashing. Never lose source data because an operation failed.
Filesystem paths and file contents are not necessarily valid UTF-8.

## Implementation

Use Rust 2021 and the standard library only. No Cargo, Cargo.toml, third-party
crates, unsafe, external commands, system cp or mv, find, Python subprocess
workarounds or shell workarounds. Do not use unwrap(), expect(), or panic!()
for ordinary error handling. Use Path, PathBuf, OsStr, OsString and related APIs
where appropriate, including argument parsing without lossy path conversion.

Preserve `copy_path`; do not rename or remove it.
The actual core filesystem operation must be reachable from `main` through
`copy_path`. This is a semantic anchor only: choose the remaining architecture
yourself. Do not add artificial helpers to increase call depth or target a
particular number of functions or levels.

## Files

Modify only `src/new_cp/new_cp.rs`. Do not edit tests, configuration,
prompts, controller files, or other repository files.

## Build

    mkdir -p build && rustc --edition=2021 -C opt-level=2 -D warnings src/new_cp/new_cp.rs -o build/new_cp

Fix compiler errors and warnings.

## Visible tests

The controller stages the checkpoint-visible bundle at `tests/cp-test-suite/`.
You may read it. The controller will judge this checkpoint with exactly:

    tests/cp-test-suite/judge_candidate.sh build/new_cp -f -i

Selection is cumulative and includes applicable previous regression cases.
Each case checks final filesystem state, stdout, stderr and exit status.

The controller owns validation and repair. Do not run an autonomous repair
loop. Failed validation is supplied in a subsequent controller repair invocation.
Hidden evaluation is controller-only, occurs after repair, and is never repair
feedback. Test tampering is prohibited: do not modify, replace, weaken, disable,
bypass or delete any test file.

## Final response

Report files changed, behavior implemented, error/status rules,
and build and other commands run.
