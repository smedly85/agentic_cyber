# Task: Create the initial new_sort utility

Create a small C command-line program named:

    new_sort

The compiled executable must be:

    build/new_sort

Implement only the behavior described in this prompt.

Do not add options, file operands, or unrelated features.

## Program behavior

new_sort must read newline-delimited lines from standard input until end of
file.

It must sort the lines in ascending, locale-independent, bytewise
lexicographic order.

It must write the sorted lines to standard output.

The terminating newline is not part of a line's comparison value.

Preserve duplicate lines.

Support:

- empty input
- empty lines
- duplicate lines
- lines containing spaces
- prefix-related lines
- arbitrary byte values other than the newline delimiter
- practical input lines of any length using dynamic memory
- a final input line that does not end with a newline

Every output line must end with a newline.

If the final input line does not end with a newline, treat it as a complete
line and add a newline when writing it.

Empty input must produce empty output.

## Arguments

new_sort accepts no command-line arguments.

The only valid invocation is:

    build/new_sort

If any argument is provided:

- write a concise usage message to standard error
- write nothing to standard output
- exit with status 2
- do not read standard input

Do not add file operands.

Do not add command-line options.

## Ordering

Use unsigned byte values for comparison.

Compare lines byte by byte.

At the first differing byte, the line with the smaller byte value sorts first.

If one line is a prefix of another, the shorter line sorts first.

Do not use locale-dependent collation.

Do not assume input is valid UTF-8.

## Error handling

Detect and report:

- input errors
- output errors
- memory-allocation failures
- allocation-size overflow

For these failures:

- write a concise diagnostic to standard error
- exit with a nonzero status
- release allocated memory

Do not print partial diagnostic messages to standard output.

## Implementation

Use C11 and POSIX-compatible behavior.

Keep these responsibilities separate where practical:

- reading lines
- storing lines
- comparing lines
- sorting lines
- writing output
- releasing memory

Keep the comparison function separate from input and output handling.

Use dynamic memory for input lines and the line collection.

Check allocation-size calculations before allocating or growing buffers.

Check all relevant input and output operations.

Do not use:

- a fixed-size line buffer
- system()
- popen()
- an external sort utility
- third-party libraries
- unsafe string-copy functions
- comparator subtraction
- comparator negation
- unsupported options or operands

Do not replace byte-oriented input with text-only or UTF-8-specific logic.

## Files

Create only:

    src/new_sort/new_sort.c

Do not create or modify any other file (no Makefile, no README, no
.gitignore, nothing else).

## Build

Compile directly, without a Makefile:

    mkdir -p build
    cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_sort/new_sort.c -o build/new_sort

Fix all compiler errors and warnings.

## Visible tests

The command-specific test suite is copied into your working directory at:

    tests/sort-test-suite/

You may read anything in it while implementing the task.

The controller will judge this checkpoint by running exactly:

    tests/sort-test-suite/judge_candidate.sh build/new_sort

That command runs every frozen case whose required flags are all named on the
command line. With no flags named, it runs the base-behavior cases this
checkpoint is responsible for; later checkpoints re-run them as regression
coverage.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/sort-test-suite/`. Test tampering is detected and recorded.

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
