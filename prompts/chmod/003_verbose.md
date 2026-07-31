# Task: Add -v to new_chmod

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
are not accepted in symbolic clauses. `-R` / `--recursive` applies the mode to a
directory operand and then to its tree, pre-order, entries in ascending byte
order of name, skipping symbolic links found during traversal. `-c` /
`--changes` writes one line to standard output for each file whose mode actually
changed:

    mode of 'PATH' changed from 0644 (rw-r--r--) to 0755 (rwxr-xr-x)

A failed operand or tree entry is diagnosed on standard error and does not stop
the rest. Exit status is 0 when everything succeeded and 1 otherwise; an unknown
option, a missing operand and an invalid `MODE` are immediate failures with
status 1.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -v
    --verbose

With `-v`, new_chmod reports **every file it successfully processed**, whether
or not the mode changed.

- a file whose mode changed produces the same `changed from ... to ...` line
  `-c` already produces, byte for byte
- a file whose computed mode equals its current mode produces exactly one line
  on **standard output**:

      mode of 'PATH' retained as 0644 (rw-r--r--)

  using the same `PATH` rule and the same four-digit-octal and nine-character
  symbolic renderings defined for `-c`, followed by a newline

Report lines appear in processing order, which under `-R` is the pre-order,
name-sorted traversal order already specified.

Nothing is reported for a file that failed; a failure is still a diagnostic on
standard error.

## Interactions

`-c` and `-v` select how much is reported, and they are opposites in that
respect:

- **whichever appeared last on the command line wins**, whether it was written
  as a short option, inside a combined short-option cluster, or as a long
  option. `-c -v` reports everything; `-v -c` reports only changes.
- both are idempotent: repeating the winner changes nothing
- when neither is given, nothing is reported and standard output stays empty

So:

    build/new_chmod -c -v 755 f     # verbose: changed and retained lines
    build/new_chmod -v -c 755 f     # changes only
    build/new_chmod -cv 755 f       # verbose
    build/new_chmod -vc 755 f       # changes only

`-R` composes with either, and neither affects which files are visited, what
modes are applied, or the exit status.

## Reference

Use BusyBox chmod and GNU Coreutils chmod as behavioral inspiration for `-v`.
The line formats and the last-one-wins rule above are the contract for this
program; match them exactly.

Implement the feature independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Arguments

After this change, support:

    build/new_chmod [-R] [-c|-v] MODE FILE...
    build/new_chmod --verbose MODE FILE...

Short options may be combined:

    -Rv
    -cv
    -vc
    -Rcv

Repeated options are accepted and idempotent:

    -v -v
    --verbose --verbose

Options are recognized only before `MODE`; `--` still ends option processing.

Unknown options are still rejected with a usage message on standard error,
nothing on standard output, and exit status 1.

Do not add other options.

## Requirements

Preserve:

- octal and symbolic `MODE` parsing exactly as specified
- `-R` traversal order and its symlink rule
- the exact `changed from ... to ...` line format
- per-operand failure reporting on standard error and the "continue" rule
- exit status 0 on complete success, 1 when anything failed — reporting never
  changes the exit status
- the existing usage rejections and the `invalid mode` diagnostic

## Implementation

Use the existing C11 structure, compiler settings, and error handling. Modify
the existing implementation.

Represent the reporting level as one value derived from the command line rather
than two independent flags consulted at output time, so that last-one-wins
cannot disagree with itself. Render the two line kinds through the same
formatting helper, so `-c`'s output cannot drift from `-v`'s. Do not call an
external program. Do not make unrelated changes.

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

    tests/chmod-test-suite/judge_candidate.sh build/new_chmod -R -c -v

That command runs every frozen case whose required flags are all named on the
command line, so it covers the `-v` feature added here **and** the base, `-R`
and `-c` behavior from the earlier checkpoints as regression coverage. All of it
must pass. Every case runs against an isolated temporary fixture and checks the
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
3. How last-one-wins between `-c` and `-v` is resolved.
4. Commands run.
5. Whether the build passed.
