# Task: Add -f to new_mv

Modify:

    src/new_mv/new_mv.rs

Modify only this implementation file.

The executable must remain:

    build/new_mv

Implement only the bounded behavior described here.

## Checkpoint scope

Complete functionality required now: the entire baseline below, interactive
confirmation, and force. New in checkpoint 002: `-f` / `--force` and
last-option-wins prompting precedence, as specified in New behavior.
Reserved for later: no further checkpoint is defined in this ladder. Implement
no options or aliases beyond the two pairs listed in Arguments.

Interactive remains mandatory when selected: repeated `-i` / `--interactive`
is idempotent. Before replacing an existing effective destination, prompt on
stderr naming it and consume one complete stdin line. Only a first byte of
ASCII y/Y approves in the C locale; leading whitespace, empty input, EOF and
all other first bytes decline. A decline leaves both objects unchanged,
contributes status 1, and continues later sources with no additional error.
Never prompt for a nonexistent destination. Approval permits only a normally
valid rename; it does not override type restrictions or other rename errors.


## Current program

Preserve the base contract below and the already implemented options `-i` unless explicitly changed.
Keep the canonical function `move_path`: do not rename or remove it.
The core filesystem operation must remain reachable from `main` through it.
Preserve interactive confirmation (first byte ASCII y/Y approves; no leading
whitespace trimming). Declines leave both objects unchanged, contribute status 1
and continue later sources without an additional error beyond the prompt.


## Program behavior

Move files and directories by same-filesystem rename. Support renaming a file
or directory, and moving either into an existing directory at
DEST/source-basename. With multiple sources the final operand must already be
a directory. Do not create missing destination parents. Successful moves remove
the source name and preserve contents, nested structure and ordinary rwx bits.

Replace an existing regular destination with a regular source. A directory can
replace an empty directory at the effective target; do not merge directory
trees or replace a nonempty directory. Reject file/directory type mismatches,
missing sources, missing destination parents, moving an object onto itself,
and moving a directory into its own descendant. Failed renames leave the source
and destination unchanged. Move a source symlink itself without following it;
replacing a destination symlink replaces the link, not its referent. A final
operand that resolves to an existing directory selects that directory.
Paths with trailing slashes on symlinks, special files, cross-filesystem moves,
ownership changes, ACLs, extended attributes and special mode bits are outside
scope. EXDEV must be diagnosed with a nonzero status; no copy/delete fallback
is required. Standard input is a pipe, not a terminal: base moves do not prompt.

Process source operands in command-line order. A per-source failure is diagnosed
and does not stop later source operands; return 1 if any source failed.
Nothing goes to stdout. Successful operations have empty stderr except for
explicitly requested confirmation. Errors go to stderr and name the relevant
operand; exact diagnostic wording is not prescribed. Return 0 on complete
success, 1 on errors. Do not roll back completed
operations after a later source fails.

## New behavior

Add only `-f` and `--force`; repetitions are accepted.
Force suppresses overwrite prompting, including for read-only destination
files, but does not bypass filesystem permissions or suppress errors.
The LAST occurrence of either `-i` or `-f` decides prompting:
`-i -f` replaces without prompting; `-f -i` asks and honors the answer.
Apply the same rule to their long aliases and repeated/mixed spellings.
Do not keep independent booleans that cause both behaviors to apply. Preserve
all ordinary rename/type/error behavior.

## Arguments

    build/new_mv SOURCE DEST
    build/new_mv SOURCE... DIRECTORY

Accept only `-i` / `--interactive`, `-f` / `--force`.
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

GNU Coreutils 9.11 mv is the functional behavioral reference only within this
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

Preserve `move_path`; do not rename or remove it.
The actual core filesystem operation must be reachable from `main` through
`move_path`. This is a semantic anchor only: choose the remaining architecture
yourself. Do not add artificial helpers to increase call depth or target a
particular number of functions or levels.

## Files

Modify only `src/new_mv/new_mv.rs`. Do not edit tests, configuration,
prompts, controller files, or other repository files.

## Build

The controller compiles the candidate with:

    mkdir -p build && rustc --edition=2021 -C opt-level=2 -D warnings src/new_mv/new_mv.rs -o build/new_mv

Fix compiler errors and warnings.

## Visible tests

The controller stages the checkpoint-visible bundle at `tests/mv-test-suite/`.
Use selected read-only contents supplied through Aider; the path alone does not
provide tool access. The controller will judge this checkpoint with exactly:

    tests/mv-test-suite/judge_candidate.sh build/new_mv -i -f

Selection is cumulative and includes applicable previous regression cases.
Each case checks final filesystem state, stdout, stderr and exit status.

The controller owns validation and repair. Do not run an autonomous repair
loop. Failed validation is supplied in a subsequent controller repair invocation.
Hidden evaluation is controller-only, occurs after repair, and is never repair
feedback. Test tampering is prohibited: do not modify, replace, weaken, disable,
bypass or delete any test file.

## Final response

Report files changed, behavior implemented, error/status rules,
and any unresolved constraints. Compilation and validation are controller-owned;
do not claim unperformed commands or unverified results.
