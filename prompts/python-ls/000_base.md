# Task: python-ls checkpoint 000 (base)

Create only `src/python-ls/new_ls.py`.
There is intentionally no starter implementation. Start from an empty candidate.
The controller's executable is `build/new_ls.py`.

## Complete functionality required now

Implement ALL baseline behavior below plus every inherited and newly introduced
feature in this prompt. A minimal demonstration or a two-argument standard-library
wrapper is insufficient. Checkpoint 000 requires the complete baseline immediately.
Supported options now: none.

## Baseline behavior

List the current directory when there are no operands. For file operands,
print their names. For directory operands, print their immediate entries,
excluding names beginning with dot. Output is a pipe, not a terminal: use one
literal name per line, no colors or column layout. Sort in ascending raw filename
byte order under LC_ALL=C. Sort file operands and directory operands as GNU does,
print files before directory contents, and use GNU directory headers and blank
line separation for multiple directory/mixed operands. Do not mutate any object.
List a command-line symlink to a file as a named operand; a command-line symlink
to a directory selects that directory in the base mode. A dangling symlink can
itself be listed. Symlinks encountered as directory entries remain entries.
Support empty directories, spaces, dash-prefixed operands after -- and a bare -
filename. Preserve filesystem path bytes using Python filesystem encoding and
surrogateescape. Diagnose missing operands and inaccessible directories, continue
other accessible operands, and preserve successful output. GNU ls statuses are
0 for success, 1 for minor traversal problems, and 2 for serious invocation or
operand errors. Diagnostics go to stderr; exact wording is not prescribed.
The bounded environment is POSIX Linux/Darwin, LC_ALL=C, TZ=UTC, pipe output and
QUOTING_STYLE=literal. Special files, embedded-newline/control-character names,
terminal formatting, ACL/security-context markers, other locales, concurrent
changes and options outside this ladder are not required.

## Inherited feature behavior

No earlier feature options beyond the baseline.

## New functionality at this checkpoint

The entire baseline contract is new and must be implemented now.

## Reserved for later

001 adds -a; 002 adds -l; 003 adds -R
Do not implement future flags or any other options or aliases. Their absence
does not excuse omissions from the complete current contract.

## Arguments and errors

    build/new_ls.py [FILE_OR_DIRECTORY...]

Recognize currently supported options anywhere before the first `--`, including
after operands. Consume that terminator; all subsequent arguments are operands,
including later `--` and dash-prefixed filenames. A bare `-` is a filename.
Combined short options are outside this bounded contract. Repeated supported
boolean options are accepted; preserve the utility-specific precedence above.
Zero operands means the current directory. Unknown options are invocation
errors with status 2, empty stdout and a diagnostic on stderr.
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
GNU Coreutils 9.11 ls is the functional reference only within this bounded
contract; BSD/macOS utilities are not substitutes. Implement independently.
Require the semantic anchor `list_path`: core filesystem behavior must be reachable
from main through it. Choose the remaining architecture without artificial depth.

## Files and validation

Create or modify only `src/python-ls/new_ls.py`. Do not change tests, prompts,
configuration, controller files or any other repository file. The controller
verifies nonempty source, checks syntax without executing it, and creates an
interpreter-pinned disposable launcher. Syntax errors are repair feedback.
Selected read-only context is supplied through Aider; paths alone are not tool
access. The controller runs exactly:

    tests/python-ls-test-suite/judge_candidate.sh build/new_ls.py 

This checks all applicable current and earlier cases, including status, stdout,
stderr and filesystem effects. Failed public validation is supplied in subsequent
controller-owned repair invocations. Hidden evaluation runs separately after
repair, never as feedback. Do not modify, weaken, disable or bypass tests, and do
not special-case individual test inputs. No autonomous validation/repair loop.

## Completion

Provide complete implementation instructions and actual edits now. Briefly report
files changed and behavior implemented; do not claim unperformed validation.
