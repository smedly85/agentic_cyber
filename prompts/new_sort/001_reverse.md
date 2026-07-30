# Task: Add reverse sorting to new_sort

Modify:

    src/new_sort/new_sort.c

The executable must remain:

    build/new_sort

Add only the feature described here. Do not add unrelated behavior.

## Current program

Source:

    src/new_sort/new_sort.c

Executable:

    build/new_sort

Behavior already implemented:

new_sort reads newline-delimited lines from standard input until end of file,
sorts them in ascending locale-independent bytewise lexicographic order, and
writes them to standard output with a newline after every line. Duplicates are
preserved, a final input line without a newline is still a line, empty input
produces empty output, and there are no file operands. Any command-line
argument is currently rejected with a usage message on standard error and exit
status 2.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -r
    --reverse

Both options must produce reverse bytewise lexicographic order.

Example input:

    apple
    pear
    banana

Command:

    build/new_sort -r

Output:

    pear
    banana
    apple

The no-option behavior must remain ascending bytewise sorting.

## Reference

Use GNU Coreutils sort 9.11 as behavioral inspiration.

Reverse sorting must reverse the normal comparison order.

Implement it independently.

Do not copy Coreutils source code, comments, algorithms, or implementation
details.

## Arguments

Support:

    build/new_sort
    build/new_sort -r
    build/new_sort --reverse

Repeated reverse options must be accepted:

    -r -r
    -rr
    --reverse --reverse

Repeated options are idempotent.

Unknown options and operands must:

- write a short usage message to standard error
- write nothing to standard output
- exit with status 2

Do not add file operands.

Do not add other options.

## Requirements

Preserve:

- empty input
- empty lines
- duplicates
- long lines
- final lines without a newline
- existing error handling

## Implementation

Use the existing C11 structure and compiler settings.

Modify the existing comparator or sorting flow.

Do not call another sorting program.

Do not make unrelated changes.

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

    tests/sort-test-suite/judge_candidate.sh build/new_sort -r

That command runs every frozen case whose required flags are all named on the
command line, so it covers the reverse feature added here **and** the base
behavior from checkpoint 000 as regression coverage. Both must pass.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/sort-test-suite/`. Test tampering is detected and recorded.

The experiment controller owns validation and any repair iterations. Do not
perform an autonomous repair loop. If validation fails, the controller will
provide the failure output in a subsequent repair invocation. Any hidden,
comprehensive, or sanitizer evaluation is controller-only, is not exposed here,
and is never used as repair feedback.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. Implementation approach.
4. Commands run.
5. Whether the build passed.
