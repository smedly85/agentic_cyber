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

Create:

    Makefile
    README.md
    src/new_sort.c

Create or update:

    .gitignore

The .gitignore file must include:

    build/
    __pycache__/
    *.pyc
    .pytest_cache/

## Build

The Makefile must support:

    make
    make test
    make clean

The normal build must produce:

    build/new_sort

Compile with strict settings equivalent to:

    -std=c11 -Wall -Wextra -Werror -pedantic -O2

The build must create the build directory when needed.

The clean target must remove generated build files and test caches.

The controller will build with:

    make clean
    make

## Documentation

Document:

- what new_sort does
- that it reads from standard input
- that it writes to standard output
- that it accepts no arguments
- the bytewise sorting behavior
- how to build it
- how to run it
- how to run the tests
- how to clean generated files

Do not describe unsupported features.

## Visible tests

The controller will evaluate this checkpoint using the following visible base
test:

    tests/new_sort/test_new_sort.py

This test covers the checkpoint 000 base behavior and becomes regression
coverage for every later checkpoint.

You may inspect this visible test while implementing the task.

Do not modify, replace, weaken, disable, bypass, or delete this visible test.

The controller will run exactly:

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/new_sort/test_new_sort.py -v

after your implementation is returned.

Do not perform an autonomous repair loop. If validation fails, the experiment
controller will provide the failure output in a subsequent repair invocation.

Only the test listed above is visible. Any hidden, comprehensive, or external
evaluation is controller-only, is not exposed here, and is not used as repair
feedback.

## Final response

Report:

1. Files created or changed.
2. Program behavior implemented.
3. Build commands run.
4. Test results.
