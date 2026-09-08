## Session conditions

This session is fully automated and non-interactive.

No user is available to answer questions. A clarifying question ends the
session without an implementation, which is recorded as a failed attempt.

If a requirement is ambiguous or underspecified, choose the most reasonable
interpretation consistent with the rest of this prompt and proceed. State the
interpretation you chose in your final response.

Begin by inspecting the repository and then implement the change. Do not
produce an extended plan, a survey of alternatives, or exploratory commentary
before acting; any reasoning you need should be in service of an edit you are
about to make.

Nothing in this section changes what the program must do. The task,
its scope, and the validation that follows are defined by the rest of this
prompt.

# Task: Add -H to new_grep

Modify:

    src/new_grep/new_grep.c

The executable must remain:

    build/new_grep

Add only the feature described here. Do not add unrelated behavior.

Do not implement options or behavior outside this checkpoint's stated scope.

## Current program

Source:

    src/new_grep/new_grep.c

Executable:

    build/new_grep

Behavior already implemented:

new_grep takes a fixed byte-string `PATTERN` as its first operand and writes
every input line containing that string, case-sensitively, to standard output
with a terminating newline. An empty `PATTERN` matches every line. With no file
operands it searches standard input; otherwise it searches each operand in
order. `-` is an ordinary name and `--` ends option processing. A missing,
unreadable, or directory operand is a diagnosed error that does not stop the
remaining operands. Selected lines are prefixed with `NAME:` when there are two
or more file operands, and not otherwise. Exit status is 0 when a line was
selected, 1 when none was, and 2 when any error occurred. There are no options.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -H
    --with-filename

`-H` forces the filename prefix on, whatever the default rule would have
decided.

With `-H`:

- every selected line is written as `NAME:` followed by the line, where `NAME`
  is the file operand exactly as it was given on the command line
- when standard input is searched (no file operands), the name used is exactly:

      (standard input)

  so a selected line appears as `(standard input):alpha`
- a single file operand is prefixed, where without `-H` it would not have been
- two or more file operands are prefixed, exactly as they already were

`-H` changes only whether a prefix appears. It does not change which lines are
selected, the order of the output, the exit status, or which conditions are
diagnosed.

## Reference

Use BusyBox grep and GNU grep as behavioral inspiration for `-H`'s meaning and
for the `(standard input)` name.

Implement the feature independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Arguments

After this change, support:

    build/new_grep PATTERN
    build/new_grep PATTERN FILE...
    build/new_grep -H PATTERN
    build/new_grep -H PATTERN FILE...
    build/new_grep --with-filename PATTERN FILE...

Options may appear before or between operands, and `--` still ends option
processing.

Repeated options are accepted and idempotent:

    -H -H
    --with-filename --with-filename

Unknown options are still rejected with a usage message on standard error,
nothing on standard output, and exit status 2.

Do not add other options.

## Interactions

The prefix decision is still made once, before any output, from the command line
alone:

- `-H` given: prefix
- otherwise, two or more file operands: prefix
- otherwise: no prefix

## Requirements

Preserve:

- fixed-string, case-sensitive matching
- the empty-pattern rule
- byte-oriented line handling, including NUL bytes and invalid UTF-8
- a final line without a newline
- per-operand error reporting and the 0 / 1 / 2 exit statuses
- the existing usage rejections

## Implementation

Use the existing C11 structure, compiler settings, and error handling. Modify
the existing implementation. Do not call an external program. Do not make
unrelated changes.

## Build

Compile directly, without a Makefile:

    mkdir -p build
    cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_grep/new_grep.c -o build/new_grep

Fix all compiler errors and warnings.

## Visible tests

The command-specific test suite is copied into your working directory at:

    tests/grep-test-suite/

You may read anything in it while implementing the task.

The controller will judge this checkpoint by running exactly:

    tests/grep-test-suite/judge_candidate.sh build/new_grep -H

That command runs every frozen case whose required flags are all named on the
command line, so it covers the `-H` feature added here **and** the base behavior
from checkpoint 000 as regression coverage. Both must pass.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/grep-test-suite/`. Test tampering is detected and recorded.

The experiment controller owns validation and any repair iterations. Do not
perform an autonomous repair loop. If validation fails, the controller will
provide the failure output in a subsequent repair invocation. Any hidden,
comprehensive, or sanitizer evaluation is controller-only, is not exposed here,
and is never used as repair feedback.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. How the prefix decision is made.
4. Commands run.
5. Whether the build passed.
