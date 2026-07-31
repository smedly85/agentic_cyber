# Task: Add case-insensitive sorting to new_sort

Modify:

    src/new_sort/new_sort.c

The executable must remain:

    build/new_sort

Add only the feature described here. Do not add unrelated behavior.

Do not implement options or behavior outside this checkpoint's stated scope.

## Current program

Source:

    src/new_sort/new_sort.c

Executable:

    build/new_sort

Behavior already implemented:

new_sort reads newline-delimited lines from standard input, sorts them in
ascending locale-independent bytewise lexicographic order, and writes them to
standard output with a newline after every line. `-r`/`--reverse` reverses that
order. Duplicates are preserved, a final input line without a newline is still a
line, empty input produces empty output, and there are no file operands.
Unknown options and operands are rejected with a usage message on standard error
and exit status 2.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -f
    --ignore-case

When enabled, compare ASCII letters without regard to case.

For comparison:

- treat a through z as A through Z
- leave all other bytes unchanged
- do not use locale-dependent behavior

If two lines are equal after case folding, use their original bytes as a
deterministic secondary comparison.

The secondary comparison controls order only.

The no-option behavior must remain unchanged.

## Reference

Use GNU Coreutils sort 9.11 as behavioral inspiration.

Ignore-case sorting must compare lowercase and uppercase forms as equal.

Implement it independently.

Do not copy Coreutils source code, comments, algorithms, or implementation
details.

## Arguments

Support:

    -r
    --reverse
    -f
    --ignore-case

Short options may be combined:

    -rf
    -fr

Repeated options must be accepted and treated as idempotent:

    -ff
    -rrf
    --ignore-case --ignore-case

Unknown options and operands must:

- write a short usage message to standard error
- write nothing to standard output
- exit with status 2

Do not add file operands.

Do not add other options.

## Interaction with reverse

Apply case-insensitive comparison first.

Apply reverse ordering to the final comparison result.

These must be equivalent:

    -rf
    -fr

## Requirements

Preserve:

- empty input
- empty lines
- duplicates
- non-ASCII bytes
- long lines
- final lines without a newline
- existing error handling

Do not assume input is valid UTF-8.

## Implementation

Use the existing C11 structure and compiler settings.

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

    tests/sort-test-suite/judge_candidate.sh build/new_sort -r -f

That command runs every frozen case whose required flags are all named on the
command line, so it covers the ignore-case feature added here **and** the base
and reverse behavior from the earlier checkpoints as regression coverage. All of
it must pass.

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
3. Comparison approach.
4. Interaction with reverse.
5. Commands run.
6. Whether the build passed.
