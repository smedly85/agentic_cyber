# Task: python-cp checkpoint 003 (recursive)

Modify only `src/python-cp/new_cp.py`.
Inherit the previous checkpoint candidate and preserve all passing behavior.
The controller's executable is `build/new_cp.py`.

## Complete functionality required now

Implement ALL baseline behavior below plus every inherited and newly introduced
feature in this prompt. A minimal demonstration or a two-argument standard-library
wrapper is insufficient. Checkpoint 000 requires the complete baseline immediately.
Supported options now: -f/--force, -i/--interactive, -r/--recursive.

## Baseline behavior

Copy regular files, including empty files, arbitrary binary/NUL bytes and practical
large files, without changing source contents. Create a missing destination file
or overwrite an existing regular file. If DEST is an existing directory, copy
each source to DEST/source-basename; with multiple sources the final operand
must be an existing directory. Do not create missing destination parents.
Without `-r`, a directory source is an error. Diagnose missing/unreadable
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

## Inherited feature behavior

Add only `-f` and `--force`. These repeated options are idempotent.
Try opening the destination normally first. If that fails for an existing
nondirectory destination, remove that destination and retry creation, provided
directory permissions allow removal. This does not grant permissions on the
source or parent, suppress unrelated errors, or permit replacing a directory
with a regular file. A read-only regular destination in a writable parent is
the principal remove-and-recreate case. A normally writable destination is
overwritten in place, retaining its ordinary permission bits.

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

## New functionality at this checkpoint

Add only `-r` and `--recursive`; repetitions are idempotent.
Without this option, directory sources remain errors. With it, copy directories
and their descendants, including empty directories and files at every depth.
For a nonexistent DEST, create that directory as the root of the copied tree.
For an existing directory DEST, copy to DEST/source-basename; merge into an
existing directory there. Create nested directories as needed. Do not merge a
directory with a file or replace a directory with a file.

Do not follow source symlinks when this option is active, including source
operands: recreate the link with the same target bytes. Cycles in source links
therefore remain links and never drive traversal. Fixtures contain only targets
inside the case tree. Destination symlink collisions during tree copying are
outside scope. New directories use source ordinary rwx bits masked by umask;
existing directories keep their bits. Preserve earlier regular-file behavior.
Visit siblings in ascending raw filename-byte order so prompts are deterministic.

Apply `-f` to file opening failures as before. Apply `-i` before overwriting
existing files or links, but not when merging directories or creating new names.
These two options remain independent. A declined entry is skipped unchanged and
contributes status 1, with no additional error diagnostic beyond its prompt.
Diagnose a subtree failure, continue other reachable siblings and later source
operands, and return 1 if any error occurred; completed copies are not rolled back.

Reject a directory copy into itself or a descendant; do not traverse newly
created output. Detection may leave the initial empty target directory, but
must not copy any descendants there. Bound recursion or use an explicit work
list, diagnosing resource limits instead of crashing or looping. Do not add
any other options or aliases.

## Reserved for later

No later checkpoints in this ladder.
Do not implement future flags or any other options or aliases. Their absence
does not excuse omissions from the complete current contract.

## Arguments and errors

    build/new_cp.py SOURCE DEST or SOURCE... DIRECTORY

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
GNU Coreutils 9.11 cp is the functional reference only within this bounded
contract; BSD/macOS utilities are not substitutes. Implement independently.
Require the semantic anchor `copy_path`: core filesystem behavior must be reachable
from main through it. Choose the remaining architecture without artificial depth.

## Files and validation

Create or modify only `src/python-cp/new_cp.py`. Do not change tests, prompts,
configuration, controller files or any other repository file. The controller
verifies nonempty source, checks syntax without executing it, and creates an
interpreter-pinned disposable launcher. Syntax errors are repair feedback.
Selected read-only context is supplied through Aider; paths alone are not tool
access. The controller runs exactly:

    tests/python-cp-test-suite/judge_candidate.sh build/new_cp.py -f -i -r

This checks all applicable current and earlier cases, including status, stdout,
stderr and filesystem effects. Failed public validation is supplied in subsequent
controller-owned repair invocations. Hidden evaluation runs separately after
repair, never as feedback. Do not modify, weaken, disable or bypass tests, and do
not special-case individual test inputs. No autonomous validation/repair loop.

## Completion

Provide complete implementation instructions and actual edits now. Briefly report
files changed and behavior implemented; do not claim unperformed validation.
