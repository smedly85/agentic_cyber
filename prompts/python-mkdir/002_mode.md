# Task: python-mkdir checkpoint 002 (mode)

Modify only `src/python-mkdir/new_mkdir.py`.
Inherit the previous checkpoint candidate and preserve all passing behavior.
The controller's executable is `build/new_mkdir.py`.

## Complete functionality required now

Implement ALL baseline behavior below plus every inherited and newly introduced
feature in this prompt. A minimal demonstration or a two-argument standard-library
wrapper is insufficient. Checkpoint 000 requires the complete baseline immediately.
Supported options now: -p/--parents, -m/--mode.

## Baseline behavior

Create every directory operand in command-line order. Without parents mode,
each parent must already exist; an existing final directory or any conflicting
file/link is an error. Follow symlinks in parent components. Do not read stdin.
New directories use 0777 masked by the process umask. Diagnose missing parents,
non-directory components, permission failures and existing targets. Continue
after per-operand errors, retain completed operations, and return 1 if any failed,
otherwise 0. Stdout is empty; stderr is empty on success and identifies relevant
operands on error. Exact diagnostic wording is not prescribed.
Paths with spaces, trailing slashes, dot components and non-UTF-8 bytes are in
scope. Symlink targets remain inside the working tree. Ownership changes,
inherited ACLs, extended attributes and concurrent filesystem changes are outside
scope. Do not roll back previously created directories after a later error.

## Inherited feature behavior

Accept -p and --parents; repetitions are idempotent. Create missing parent
components and succeed for an existing directory, including a symlink resolving
to a directory. Existing files and dangling symlink conflicts remain errors.
Do not change existing directories' modes. Newly created intermediate parents
use (0777 & ~umask) with owner write/search permissions added (u+wx), as GNU
requires, even with restrictive umasks. The final newly created directory still
uses the ordinary default unless an explicitly supported mode option changes it.
Handle repeated operands and dot/dot-dot components without discarding errors.

## New functionality at this checkpoint

Accept -m MODE, --mode MODE and --mode=MODE. The last mode option wins.
Support octal values 0000 through 7777 and symbolic chmod-style clauses, including
u/g/o/a classes, +, - and =, rwxXst, permission copying between u/g/o, empty
permission lists, and comma-separated clauses applied left to right. Evaluate
symbolic modes from a starting mode of 0777, treating X as execute for directories.
Follow GNU's omitted-who/umask rules; an explicit class such as a is not implicitly
masked. Explicit octal modes are not masked by umask. Preserve requested special
mode bits where supported on the POSIX host. Reject malformed or missing mode
arguments before creating any operand, with status 1 and stderr.
With parents mode, apply the requested mode only to newly created final operand
directories. Intermediate parents keep parents-mode permissions; existing final
directories are successful and unchanged. Mode parsing must not consume path
operands accidentally; validate all invocation-wide errors before mutation.

## Reserved for later

No later checkpoints in this ladder.
Do not implement future flags or any other options or aliases. Their absence
does not excuse omissions from the complete current contract.

## Arguments and errors

    build/new_mkdir.py DIR...

Recognize currently supported options anywhere before the first `--`, including
after operands. Consume that terminator; all subsequent arguments are operands,
including later `--` and dash-prefixed filenames. A bare `-` is a filename.
Combined short options are outside this bounded contract. Repeated supported
boolean options are accepted; preserve the utility-specific precedence above.
At least one directory operand is required. Validate option syntax and mode
arguments before mutation. Missing operands and unknown options return 1.
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
GNU Coreutils 9.11 mkdir is the functional reference only within this bounded
contract; BSD/macOS utilities are not substitutes. Implement independently.
This suite requires Linux: GNU 9.11 symbolic-mode behavior differs on Darwin.
Follow the Linux GNU contract, including its interaction with umask.
Require the semantic anchor `create_directory`: core filesystem behavior must be reachable
from main through it. Choose the remaining architecture without artificial depth.

## Files and validation

Create or modify only `src/python-mkdir/new_mkdir.py`. Do not change tests, prompts,
configuration, controller files or any other repository file. The controller
verifies nonempty source, checks syntax without executing it, and creates an
interpreter-pinned disposable launcher. Syntax errors are repair feedback.
Selected read-only context is supplied through Aider; paths alone are not tool
access. The controller runs exactly:

    tests/python-mkdir-test-suite/judge_candidate.sh build/new_mkdir.py -p -m

This checks all applicable current and earlier cases, including status, stdout,
stderr and filesystem effects. Failed public validation is supplied in subsequent
controller-owned repair invocations. Hidden evaluation runs separately after
repair, never as feedback. Do not modify, weaken, disable or bypass tests, and do
not special-case individual test inputs. No autonomous validation/repair loop.

## Completion

Provide complete implementation instructions and actual edits now. Briefly report
files changed and behavior implemented; do not claim unperformed validation.
