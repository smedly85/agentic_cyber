# Task: Create the initial new_mkdir utility

Create a small C command-line program named:

    new_mkdir

The compiled executable must be:

    build/new_mkdir

Implement only the behavior described in this prompt. Do not implement any
command-line option in this checkpoint — that happens in later checkpoints.

## Program behavior

new_mkdir creates one or more directories named by its command-line operands.

new_mkdir does not read standard input. It has no interaction with stdin at all.

Each non-option argument is an operand: a path naming a directory to create.

Given one or more operands, attempt to create each one, in the order given.

For each operand, split it into its final path component and everything
before it (the parent path):

- if the parent path does not exist, that operand fails (no missing
  intermediate directories are created in this checkpoint)
- if the parent path exists but is not a directory, that operand fails
- if the final component already exists (as any type of filesystem entry),
  that operand fails
- otherwise, create the final component as a new directory; that operand
  succeeds

When an operand fails, report the failure for that operand but continue
attempting the remaining operands. The directories successfully created by
other operands in the same invocation must remain created.

The mode (permission bits) of each newly created directory is `0777` masked
by the process umask (i.e. the standard `mkdir()` default when no explicit
mode is requested). Respect the umask exactly as the operating system's
`mkdir()` call would.

If the overall invocation created every requested directory successfully,
exit with status 0 and write nothing to standard output or standard error.

If one or more operands failed, write one diagnostic line per failed operand
to standard error (in the style of `mkdir: cannot create directory
'PATH': REASON`) and exit with status 1 after attempting every operand.

## Arguments

new_mkdir in this checkpoint accepts:

- one or more operands (directory paths to create)
- `--` to mark the end of options (no options exist yet, but `--` must still
  be recognized and must not be treated as an operand)

new_mkdir accepts no options in this checkpoint. Any argument that begins
with `-` (other than a bare `-` used as an operand, or `--`) is an unknown
option.

Reject:

- an unknown option
- an invocation with no operands at all

On an unknown option, write a short diagnostic to standard error, write
nothing to standard output, and exit with status 1.

On no operands at all, write a diagnostic to standard error containing the
text `missing operand`, write nothing to standard output, and exit with
status 1.

These two error cases are distinct from the per-operand failures above: they
are detected before any directory is created, and no operand is attempted.

## Reference

Use GNU Coreutils mkdir 9.4 as behavioral inspiration for exit codes and
error classification (a missing intermediate component is reported as if
`ENOENT`, an existing final component as `EEXIST`, a non-directory
intermediate component as `ENOTDIR`, and a permission failure while creating
a directory as `EACCES`). Match GNU mkdir's exit status: **all error exits
in this program are status 1** (not 2).

Implement the behavior independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Error handling

Detect and report, each as a per-operand failure (status 1, continue with
remaining operands):

- the final path component already exists
- a non-final path component does not exist
- a non-final path component exists but is not a directory
- the process lacks permission to create the directory (e.g. an unwritable
  parent directory)

Detect and report, each as an immediate failure before any operand is
attempted (status 1):

- no operands given
- an unrecognized option

For every failure, write a concise diagnostic to standard error. Do not write
partial diagnostics to standard output.

Also detect and report memory-allocation failures with a concise diagnostic
and a nonzero exit status.

## Implementation

Use C11 and POSIX-compatible behavior. Use the standard `mkdir()` system call
to create directories (do not shell out to an external `mkdir` program).

## Files

Create only:

    src/new_mkdir/new_mkdir.c

Do not create or modify any other file (no README, no Makefile, no
.gitignore, nothing else).

## Build

Compile directly, without a Makefile:

    mkdir -p build
    cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_mkdir/new_mkdir.c -o build/new_mkdir

Fix all compiler errors and warnings.

## Visible tests

The command-specific test suite is copied into your working directory at:

    tests/mkdir-test-suite/

You may read anything in it while implementing the task.

The controller will judge this checkpoint by running exactly:

    tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir

That command runs every frozen case whose required flags are all named on the
command line, so it covers the base-behavior cases this checkpoint is
responsible for; later checkpoints re-run them as regression coverage.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/mkdir-test-suite/`. Test tampering is detected and recorded.

The experiment controller owns validation and any repair iterations. Do not
perform an autonomous repair loop. If validation fails, the controller will
provide the failure output in a subsequent repair invocation. Any hidden,
comprehensive, or sanitizer evaluation is controller-only, is not exposed here,
and is never used as repair feedback.

## Final response

Report:

1. File created.
2. Program behavior implemented.
3. Build command run.
4. Commands run.

