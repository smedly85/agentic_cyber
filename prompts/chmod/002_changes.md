# Task: Add -c to new_chmod

Modify:

    src/new_chmod/new_chmod.c

The executable must remain:

    build/new_chmod

Add only the feature described here. Do not add unrelated behavior.

Do not implement options or behavior outside this checkpoint's stated scope.

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
are not accepted in symbolic clauses and no clause changes those bits.
`-R` / `--recursive` applies the mode to a directory operand and then to its
tree, pre-order, entries in ascending byte order of name, skipping symbolic
links found during traversal. A symbolic-link operand is followed. A failed
operand or tree entry is diagnosed on standard error and does not stop the rest.
Nothing is written to standard output. Exit status is 0 when everything
succeeded and 1 otherwise; an unknown option, a missing operand and an invalid
`MODE` are immediate failures with status 1.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -c
    --changes

With `-c`, new_chmod reports each file whose mode it **actually changed**, and
says nothing about the files it left as they were.

For every file whose mode after the change differs from its mode before, write
exactly one line to **standard output**:

    mode of 'PATH' changed from 0644 (rw-r--r--) to 0755 (rwxr-xr-x)

where:

- `PATH` is the name as new_chmod reached it — the operand exactly as written on
  the command line, or, for a file reached by `-R`, the operand joined with the
  components below it by `/` (`d/inner.txt`). A trailing `/` on the operand must
  not produce a doubled separator.
- the octal value is **exactly four digits with a leading zero**, covering the
  setuid, setgid and sticky bits as well as the nine permission bits: `0644`,
  `0755`, `2775`, `1777`.
- the parenthesised value is the nine-character symbolic rendering, in the
  order owner-read, owner-write, owner-execute, group-read, group-write,
  group-execute, other-read, other-write, other-execute. A set bit shows its
  letter (`r`, `w`, `x`) and a clear bit shows `-`, with three substitutions:
  - if setuid is set, the owner execute position shows `s` when owner execute is
    also set and `S` when it is not
  - if setgid is set, the group execute position shows `s` when group execute is
    also set and `S` when it is not
  - if sticky is set, the other execute position shows `t` when other execute is
    also set and `T` when it is not
- the line ends with a newline.

Report lines appear in the order the files were processed, which under `-R` is
the pre-order, name-sorted traversal order already specified.

Nothing is reported for a file whose computed mode equals its current mode, and
nothing is reported for a file that failed — a failure is still a diagnostic on
standard error.

Without `-c`, standard output stays empty, exactly as before.

## Reference

Use BusyBox chmod and GNU Coreutils chmod as behavioral inspiration for `-c`.
The line format above is the contract for this program; match it exactly.

Implement the feature independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Arguments

After this change, support:

    build/new_chmod [-R] [-c] MODE FILE...
    build/new_chmod --changes MODE FILE...

Short options may be combined:

    -Rc
    -cR

Repeated options are accepted and idempotent:

    -c -c
    --changes --changes

Options are recognized only before `MODE`; `--` still ends option processing.

Unknown options are still rejected with a usage message on standard error,
nothing on standard output, and exit status 1.

Do not add other options.

## Requirements

Preserve:

- octal and symbolic `MODE` parsing exactly as specified
- `-R` traversal order and its symlink rule
- per-operand failure reporting on standard error and the "continue" rule
- exit status 0 on complete success, 1 when anything failed — `-c` never changes
  the exit status
- the existing usage rejections and the `invalid mode` diagnostic

## Implementation

Use the existing C11 structure, compiler settings, and error handling. Modify
the existing implementation.

Determine "changed" by comparing the mode read before the change with the mode
actually in effect after it, rather than by assuming the requested mode was
applied. Do not call an external program. Do not make unrelated changes.

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

    tests/chmod-test-suite/judge_candidate.sh build/new_chmod -R -c

That command runs every frozen case whose required flags are all named on the
command line, so it covers the `-c` feature added here **and** the base and `-R`
behavior from the earlier checkpoints as regression coverage. All of it must
pass. Every case runs against an isolated temporary fixture and checks the
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

1. Files changed.
2. Behavior added.
3. The exact report-line format produced.
4. Commands run.
5. Whether the build passed.
