# Task: Create the initial new_cp

There is intentionally no starter implementation.

Create exactly:

    src/new_cp/new_cp.rs

Create the parent directory if necessary.
Do not create any other implementation file.

The executable must be:

    build/new_cp

Implement only the bounded behavior described here.

## Checkpoint scope

Complete functionality required now: ALL baseline behavior described below,
including argument validation, multiple sources, directory destinations, symlink
handling, permissions, self-copy protection, and per-source error/status rules.
Implement all of it immediately. A two-argument wrapper around `fs::copy` is
insufficient.

New in checkpoint 000: the entire option-free baseline, not a demonstration.
Reserved for later: 001 adds `-f` / `--force`; 002 adds `-i` /
`--interactive`; 003 adds `-r` / `--recursive`. Do not implement these
flags or their behavior early. Directory sources are errors at this checkpoint.


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

## Arguments

    build/new_cp SOURCE DEST
    build/new_cp SOURCE... DIRECTORY

Do not implement any options in this checkpoint.
Recognize options anywhere before `--`. The terminator ends option parsing;
after it every argument is an operand, including names starting with `-`.
A bare `-` is an ordinary filename. Missing operands, unknown short/long
options, or multiple sources without a directory target must fail before
mutating anything, with stderr diagnostic, empty stdout and status 1.
Combined short option spellings are outside the contract.

Read arguments with `std::env::args_os()`. Retain operands as OsString/PathBuf
(or borrowed OsStr/Path) through parsing, basename selection and filesystem
operations; never require UTF-8 or use lossy conversion to construct paths.
Parse the entire argument list and validate invocation-wide errors before any
mutation. Recognize only the options allowed here anywhere before the first
`--`, even after operands. Consume that terminator; all later arguments are
literal operands, including a later `--`. A bare `-` remains a filename.

For one source, select DEST itself unless it is an existing directory, in which
case select DEST/source-basename. For multiple sources, require an existing
directory as the final operand before processing any source, and select a
separate effective destination for each source. Apply the utility-specific
symlink and object-type rules above to these effective destinations. Check
self-operation safeguards before destructive changes. Process sources in order,
diagnose each per-source failure and continue later sources, accumulating
status 1 for any failure; return 0 only on complete success. Preserve completed
operations after later errors, with stdout/stderr behavior as specified above.

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

Require a function named `copy_path`.
The actual core filesystem operation must be reachable from `main` through
`copy_path`. This is a semantic anchor only: choose the remaining architecture
yourself. Do not add artificial helpers to increase call depth or target a
particular number of functions or levels.

## Files

Create only `src/new_cp/new_cp.rs`. Do not edit tests, configuration,
prompts, controller files, or other repository files.

## Build

The controller compiles the candidate with:

    mkdir -p build && rustc --edition=2021 -C opt-level=2 -D warnings src/new_cp/new_cp.rs -o build/new_cp

Fix compiler errors and warnings.

## Visible tests

The controller stages the checkpoint-visible bundle at `tests/cp-test-suite/`.
Use selected read-only contents supplied through Aider; the path alone does not
provide tool access. The controller will judge this checkpoint with exactly:

    tests/cp-test-suite/judge_candidate.sh build/new_cp

Selection is cumulative and includes applicable previous regression cases.
Each case checks final filesystem state, stdout, stderr and exit status.

The controller owns validation and repair. Do not run an autonomous repair
loop. Failed validation is supplied in a subsequent controller repair invocation.
Hidden evaluation is controller-only, occurs after repair, and is never repair
feedback. Test tampering is prohibited: do not modify, replace, weaken, disable,
bypass or delete any test file.

## Final response

Report files created, behavior implemented, error/status rules,
and any unresolved constraints. Compilation and validation are controller-owned;
do not claim unperformed commands or unverified results.
