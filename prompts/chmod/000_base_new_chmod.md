# Task: Create the initial new_chmod utility

Create a small C command-line program named:

    new_chmod

The compiled executable must be:

    build/new_chmod

Implement only the behavior described in this prompt. Do not implement any
command-line option in this checkpoint — that happens in later checkpoints.

## Program behavior

new_chmod changes the permission bits of the files named by its operands.

    new_chmod MODE FILE...

The first argument is `MODE`. Every argument after it is an operand: a pathname
whose permission bits are to be changed.

new_chmod does not read standard input. It has no interaction with stdin at all.

### MODE parsing

`MODE` is accepted in two forms.

**1. Octal form.** One to four octal digits (`0`–`7777`), for example `755`,
`0644`, `2755`, `1777`. The value is the absolute permission-bits value,
including the setuid (`4000`), setgid (`2000`) and sticky (`1000`) bits when
present. It replaces the file's permission bits outright. The process umask
plays no part.

A string of octal digits is always read as the octal form. Five or more digits,
or any digit outside `0`–`7`, is an invalid mode.

**2. Symbolic form.** One or more clauses separated by commas. Each clause is:

    [ugoa...][+-=][rwxX...]

- the class letters are any combination of `u` (owner), `g` (group), `o`
  (other), `a` (all three). Repeats are allowed and mean nothing extra.
- an **empty class list means all three classes**, exactly as if `a` had been
  written. The process umask plays no part in this program.
- the operator is exactly one of `+` (add these permissions to the affected
  classes), `-` (remove them), `=` (set the affected classes to exactly these
  permissions, clearing the ones not listed)
- the permission letters are any combination of `r`, `w`, `x`, and `X`, and may
  be empty (`o=` clears every "other" bit, `u+` changes nothing)
- `X` means the execute bit, but only if the file is a directory, or if the
  file's mode **already** has at least one execute bit set at the moment the
  clause is applied. Otherwise `X` contributes nothing.
- clauses apply in order, left to right, each to the mode produced by the one
  before it

Symbolic clauses start from the file's **current** mode, so `u+x` adds owner
execute and leaves everything else alone. `=` clears bits only for the classes
it names: `u=rw` does not touch group or other bits.

To keep this program bounded, the permission letters `s` (setuid/setgid) and `t`
(sticky) are **not** accepted in the symbolic form, and no clause ever changes
the setuid, setgid, or sticky bits. Those bits are reachable only through the
four-digit octal form, which replaces them along with everything else. A
symbolic clause leaves them exactly as they were.

An empty `MODE`, a clause with no operator, an unknown class letter, an unknown
permission letter, or a trailing/empty clause (as in `u+x,`) is an invalid mode.

### Applying the mode

Attempt each operand in the order given.

- if the operand exists, compute its new mode and set it; that operand succeeds
- if the operand does not exist, or the mode cannot be changed, that operand
  fails

A symbolic link named as an operand is followed: the mode is applied to what it
resolves to, not to the link.

When an operand fails, report the failure for that operand and continue with the
remaining operands. The changes already made must remain in place.

A file whose computed mode equals its current mode is still a success; the
program simply has nothing to change.

### Output and exit status

If every operand succeeded, exit with status 0 and write nothing to standard
output or standard error.

If one or more operands failed, write one diagnostic line per failed operand to
standard error, naming that operand, and exit with status 1 after every operand
has been attempted.

Nothing is ever written to standard output in this checkpoint.

## Arguments

new_chmod in this checkpoint accepts:

    build/new_chmod MODE FILE...
    build/new_chmod -- MODE FILE...

new_chmod accepts no options in this checkpoint. Any argument that begins with
`-`, other than `--`, is an unknown option — including one that looks like a
symbolic mode. `--` ends option processing, so a mode beginning with `-` is
written as:

    build/new_chmod -- -w file

Reject, before any operand is attempted:

- an unknown option
- an invocation with no arguments, or with a `MODE` but no operand
- an invalid `MODE`

On an unknown option or a missing operand, write a short usage message to
standard error, write nothing to standard output, and exit with status 1.

On an invalid `MODE`, write a diagnostic to standard error containing the text
`invalid mode`, write nothing to standard output, and exit with status 1.

## Reference

Use BusyBox chmod and GNU Coreutils chmod as behavioral inspiration for mode
syntax, diagnostic classification, and the "attempt every operand, exit 1 if any
failed" rule. Where this prompt bounds the behavior — no `s`/`t` in symbolic
modes, no umask involvement — this prompt wins.

Implement the behavior independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Error handling

Detect and report, each as a per-operand failure (status 1, continue with the
remaining operands):

- the operand does not exist
- a path component of the operand is not a directory
- the process lacks permission to change the mode, or to reach the operand

Detect and report, each as an immediate failure before any operand is attempted
(status 1):

- no arguments at all
- no operands after `MODE`
- an unrecognized option
- an invalid `MODE`

For every failure, write a concise diagnostic to standard error naming what it
is about. Do not write diagnostics to standard output.

Also detect and report memory-allocation failures with a concise diagnostic and
a nonzero exit status.

## Implementation

Use C11 and POSIX-compatible behavior. Use `chmod()` / `stat()` (or their
equivalents) directly; do not shell out to an external `chmod` program.

Keep mode parsing, mode computation, and filesystem application separate where
practical: the parser should turn `MODE` into a value that can be applied to any
current mode, and the application step should not re-parse the string per
operand.

## Files

Create only:

    src/new_chmod/new_chmod.c

Do not create or modify any other file (no Makefile, no README, no .gitignore,
nothing else).

## Build

Compile directly, without a Makefile:

    mkdir -p build
    cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_chmod/new_chmod.c -o build/new_chmod

Fix all compiler errors and warnings.

## Visible tests

The command-specific test suite is copied into your working directory at:

    tests/chmod-test-suite/

You may read anything in it while implementing the task.

The controller will judge this checkpoint by running exactly:

    tests/chmod-test-suite/judge_candidate.sh build/new_chmod

That command runs every frozen case whose required flags are all named on the
command line. With no flags named, it runs the base-behavior cases this
checkpoint is responsible for; later checkpoints re-run them as regression
coverage. Every case runs against an isolated temporary fixture and checks the
resulting file modes as well as the output and exit status.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/chmod-test-suite/`. Test tampering is detected and recorded.

The experiment controller owns validation and any repair iterations. Do not
perform an autonomous repair loop. If validation fails, the controller will
provide the failure output in a subsequent repair invocation. Any hidden,
comprehensive, or sanitizer evaluation is controller-only, is not exposed here,
and is never used as repair feedback.

## Final response

Report:

1. File created.
2. Program behavior implemented.
3. Mode-parsing approach (octal and symbolic).
4. Build command run.
5. Commands run.
