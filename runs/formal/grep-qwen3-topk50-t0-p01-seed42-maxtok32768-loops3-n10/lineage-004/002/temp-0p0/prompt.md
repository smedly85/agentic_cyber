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

# Task: Add -h to new_grep

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
every input line containing that string, case-sensitively, to standard output.
With no file operands it searches standard input; otherwise it searches each
operand in order. `-` is an ordinary name and `--` ends option processing. A
missing, unreadable, or directory operand is a diagnosed error that does not stop
the remaining operands. Selected lines are prefixed with `NAME:` when `-H` /
`--with-filename` is given, or when there are two or more file operands; under
`-H` the name used for standard input is `(standard input)`. Exit status is 0
when a line was selected, 1 when none was, and 2 when any error occurred.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -h
    --no-filename

`-h` forces the filename prefix off, whatever the default rule would have
decided.

With `-h`:

- no selected line carries a prefix, not even with two or more file operands
- the lines themselves, their order, the exit status, and which conditions are
  diagnosed are all unchanged

Note that `-h` is lowercase and `-H` is uppercase, and they are different
options.

## Interactions

`-H` and `-h` are opposites, and either may be repeated:

- **whichever appeared last on the command line wins**, whether it was written
  as a short option, inside a combined short-option cluster, or as a long option
- both are idempotent: repeating the winner changes nothing
- when neither is given, the default rule still applies: prefix when there are
  two or more file operands, otherwise no prefix

These are therefore all defined:

    build/new_grep -H -h PATTERN FILE      # -h wins: no prefix
    build/new_grep -h -H PATTERN FILE      # -H wins: prefix
    build/new_grep -Hh PATTERN FILE        # -h wins: no prefix
    build/new_grep -hH PATTERN FILE        # -H wins: prefix
    build/new_grep --with-filename -h PATTERN FILE FILE2   # -h wins: no prefix

The decision is still made once, before any output, from the command line alone.

## Reference

Use BusyBox grep and GNU grep as behavioral inspiration for `-h`'s meaning and
for the last-one-wins rule between `-H` and `-h`.

Implement the feature independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Arguments

After this change, support:

    build/new_grep [-H|-h] PATTERN
    build/new_grep [-H|-h] PATTERN FILE...
    build/new_grep --no-filename PATTERN FILE...

Short options may be combined in one argument:

    -Hh
    -hH

Options may appear before or between operands, and `--` still ends option
processing.

Unknown options are still rejected with a usage message on standard error,
nothing on standard output, and exit status 2.

Do not add other options.

## Requirements

Preserve:

- fixed-string, case-sensitive matching and the empty-pattern rule
- standard-input searching when there are no file operands
- byte-oriented line handling, including NUL bytes and invalid UTF-8
- a final line without a newline
- per-operand error reporting and the 0 / 1 / 2 exit statuses
- the existing usage rejections

## Implementation

Use the existing C11 structure, compiler settings, and error handling. Modify
the existing implementation. Represent the prefix decision as one value derived
from the command line rather than two independent flags consulted at output
time, so that last-one-wins cannot disagree with itself. Do not call an external
program. Do not make unrelated changes.

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

    tests/grep-test-suite/judge_candidate.sh build/new_grep -H -h

That command runs every frozen case whose required flags are all named on the
command line, so it covers the `-h` feature added here **and** the base and `-H`
behavior from the earlier checkpoints as regression coverage. All of it must
pass.

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
3. How last-one-wins between `-H` and `-h` is resolved.
4. Commands run.
5. Whether the build passed.
