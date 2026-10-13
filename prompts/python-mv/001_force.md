# Task: python-mv checkpoint 001 (force)

Modify only `src/python-mv/new_mv.py`.
Inherit the previous checkpoint candidate and preserve all passing behavior.
The controller's executable is `build/new_mv.py`.

## Complete functionality required now

Implement ALL baseline behavior below plus every inherited and newly introduced
feature in this prompt. A minimal demonstration or a two-argument standard-library
wrapper is insufficient. Checkpoint 000 requires the complete baseline immediately.
Supported options now: -f/--force.

## Baseline behavior

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

## Inherited feature behavior

No earlier feature options beyond the baseline.

## New functionality at this checkpoint

Accept -f and --force; repetitions are idempotent. Suppress overwrite
prompting, including for read-only destination files, without bypassing filesystem
permissions, type checks, self-operation safeguards or ordinary rename errors.
Do not remove destinations speculatively or implement copy/delete fallback.

## Reserved for later

002 adds -i
Do not implement future flags or any other options or aliases. Their absence
does not excuse omissions from the complete current contract.

## Arguments and errors

    build/new_mv.py SOURCE DEST or SOURCE... DIRECTORY

Recognize currently supported options anywhere before the first `--`, including
after operands. Consume that terminator; all subsequent arguments are operands,
including later `--` and dash-prefixed filenames. A bare `-` is a filename.
Combined short options are outside this bounded contract. Repeated supported
boolean options are accepted; preserve the utility-specific precedence above.
A single source uses DEST itself unless it resolves to an existing directory,
then uses DEST/source-basename. Multiple sources require an existing directory
as the final operand before any mutation. Missing operands, unknown options or
invalid destination arity fail before mutation with status 1 and empty stdout.
Check self-operation safeguards before destructive changes and process later
sources after per-source failures.
Use `sys.argv` with Python's filesystem encoding/surrogateescape behavior;
`os.fsencode`/`os.fsdecode` or byte paths may be used. Never lose path bytes through
replacement decoding. File contents may be arbitrary binary bytes. Handle ordinary
I/O, argument, permission and resource errors without uncaught tracebacks. Do not
lose source data because an operation failed.

## Implementation and reference

Use a standalone Python 3 program, with a Python 3 shebang and a main entry point.
The controller uses its selected supported Python interpreter, not an assumption
that `python` and `python3` are interchangeable. Standard-library modules including
os, sys, pathlib, stat and shutil are allowed; no third-party runtime dependencies.
Do not invoke external utilities through subprocess, os.system, popen, exec/spawn,
shells, ctypes or equivalent delegation. Do not copy reference implementation code.
GNU Coreutils 9.11 mv is the functional reference only within this bounded
contract; BSD/macOS utilities are not substitutes. Implement independently.
Require the semantic anchor `move_path`: core filesystem behavior must be reachable
from main through it. Choose the remaining architecture without artificial depth.

## Files and validation

Create or modify only `src/python-mv/new_mv.py`. Do not change tests, prompts,
configuration, controller files or any other repository file. The controller
verifies nonempty source, checks syntax without executing it, and creates an
interpreter-pinned disposable launcher. Syntax errors are repair feedback.
Selected read-only context is supplied through Aider; paths alone are not tool
access. The controller runs exactly:

    tests/python-mv-test-suite/judge_candidate.sh build/new_mv.py -f

This checks all applicable current and earlier cases, including status, stdout,
stderr and filesystem effects. Failed public validation is supplied in subsequent
controller-owned repair invocations. Hidden evaluation runs separately after
repair, never as feedback. Do not modify, weaken, disable or bypass tests, and do
not special-case individual test inputs. No autonomous validation/repair loop.

## Completion

Provide complete implementation instructions and actual edits now. Briefly report
files changed and behavior implemented; do not claim unperformed validation.
