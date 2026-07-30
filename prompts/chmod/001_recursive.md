# Task: Add -R to new_chmod

Modify:

    src/new_chmod/new_chmod.c

The executable must remain:

    build/new_chmod

Add only the feature described here. Do not add unrelated behavior.

## Current program

Source:

    src/new_chmod/new_chmod.c

Executable:

    build/new_chmod

Behavior already implemented:

new_chmod takes `MODE` as its first argument and applies it to each following
operand, in order. `MODE` is either one to four octal digits (an absolute value
including the setuid, setgid and sticky bits) or comma-separated symbolic
clauses `[ugoa...][+-=][rwxX...]`, applied to the file's current mode, with an
empty class list meaning all three classes and no umask involvement; `s` and `t`
are not accepted in symbolic clauses and no clause changes those bits. A
symbolic-link operand is followed. A failed operand is diagnosed on standard
error and does not stop the remaining operands. Nothing is written to standard
output. Exit status is 0 when every operand succeeded and 1 otherwise; an
unknown option, a missing operand and an invalid `MODE` are all immediate
failures with status 1. There are no options, and `--` ends option processing.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -R
    --recursive

With `-R`, an operand that is a directory is no longer just changed itself: the
mode is applied to the directory **and to everything beneath it**.

### Traversal

For a directory operand:

1. apply the mode to the directory itself first
2. then visit its immediate entries in **ascending byte order of entry name** (a
   plain byte comparison of the names, not a locale collation)
3. for each entry, apply the mode, and if it is a directory descend into it
   under the same rule

This is a pre-order walk with deterministic ordering, so the sequence of files
touched is fixed by the tree, not by the order the operating system happens to
return directory entries in.

A **symbolic link found during traversal is skipped**: it is neither followed
nor modified. A link cycle therefore cannot make the walk unbounded.

A symbolic link named *directly* as an operand is still followed, exactly as
before. The skip rule applies only to links discovered during traversal.

Apply the mode to the directory before descending. A symbolic clause that
removes the owner's search permission on a directory will then make that
directory's contents unreachable; the resulting failures are ordinary
per-operand failures, diagnosed and counted like any other.

### What does not change

- an operand that is a regular file behaves exactly as it always has, with or
  without `-R`
- **without** `-R`, a directory operand is still changed itself and not
  descended into; that was never an error and still is not
- a failure anywhere in a tree is diagnosed on standard error and the walk
  continues; the invocation exits 1
- nothing is written to standard output
- symbolic clauses are evaluated against each file's own current mode, so `X`
  and `+`/`-` can produce a different result for different files in the same
  tree

## Reference

Use BusyBox chmod and GNU Coreutils chmod as behavioral inspiration for `-R`.
Where this prompt pins the traversal order and the symlink rule, this prompt
wins.

Implement the feature independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Arguments

After this change, support:

    build/new_chmod MODE FILE...
    build/new_chmod -R MODE FILE...
    build/new_chmod --recursive MODE FILE...
    build/new_chmod -R -- -w DIR

Repeated options are accepted and idempotent:

    -R -R
    --recursive --recursive

`-R` is uppercase. Options are recognized only before `MODE`; `--` still ends
option processing, and everything after `MODE` is an operand.

Unknown options are still rejected with a usage message on standard error,
nothing on standard output, and exit status 1.

Do not add other options. In particular, do not add `-r`, `-L`, `-H`, `-P`, or
`--preserve-root`.

## Requirements

Preserve:

- octal and symbolic `MODE` parsing exactly as specified, including the
  exclusion of `s` and `t` from symbolic clauses
- per-operand failure reporting and the "continue with the remaining operands"
  rule
- exit status 0 on complete success, 1 when anything failed
- silence on standard output and on standard error when everything succeeded
- the existing usage rejections and the `invalid mode` diagnostic

## Implementation

Use the existing C11 structure, compiler settings, and error handling. Modify
the existing implementation.

Read a directory's entries, sort the names yourself, then act on them; do not
depend on the order `readdir` returns. Do not shell out to `find`, `chmod`, or
any other external program. Recursion depth must not be able to exhaust the
process: either bound it or use an explicit work list. Do not make unrelated
changes.

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

    tests/chmod-test-suite/judge_candidate.sh build/new_chmod -R

That command runs every frozen case whose required flags are all named on the
command line, so it covers the `-R` feature added here **and** the base behavior
from checkpoint 000 as regression coverage. Both must pass. Every case runs
against an isolated temporary fixture and checks the resulting file modes as
well as the output and exit status.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/chmod-test-suite/`. Test tampering is detected and recorded.

The experiment controller owns validation and any repair iterations. Do not
perform an autonomous repair loop. If validation fails, the controller will
provide the failure output in a subsequent repair invocation. Any hidden,
comprehensive, or sanitizer evaluation is controller-only, is not exposed here,
and is never used as repair feedback.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. Traversal order and symlink handling.
4. Commands run.
5. Whether the build passed.
