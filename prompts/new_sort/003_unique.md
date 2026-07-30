# Task: Add unique output to new_sort

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

new_sort reads newline-delimited lines from standard input, sorts them in
ascending locale-independent bytewise lexicographic order, and writes them to
standard output with a newline after every line. `-r`/`--reverse` reverses that
order. `-f`/`--ignore-case` compares ASCII letters without regard to case, with
the original bytes as a deterministic secondary comparison. Duplicates are
preserved, a final input line without a newline is still a line, empty input
produces empty output, and there are no file operands. Unknown options and
operands are rejected with a usage message on standard error and exit status 2.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -u
    --unique

When enabled, output one line from each group of equal sorted lines.

Sorting must happen before duplicate removal.

Keep the first line from each equal group in the completed sorted order.

Without ignore-case, lines are equal only when their bytes are identical.

With ignore-case, lines are equal when their ASCII case-folded values are
equal.

The original-byte secondary comparison used by ignore-case must not make case
variants separate unique groups.

Example with -f -u:

    Apple
    apple
    APPLE

These belong to one group. Output one of them: the first one in the completed
sorted order.

## Reference

Use GNU Coreutils sort 9.11 as behavioral inspiration.

Unique mode must output the first line from each group of lines that compare
equal.

Implement it independently.

Do not copy Coreutils source code, comments, algorithms, or implementation
details.

## Arguments

Support:

    -r
    --reverse
    -f
    --ignore-case
    -u
    --unique

Short options may be combined:

    -fu
    -uf
    -ru
    -rfu

Repeated options must be accepted and treated as idempotent:

    -uu
    -rfuu
    --unique --unique

Unknown options and operands must:

- write a short usage message to standard error
- write nothing to standard output
- exit with status 2

Do not add file operands.

Do not add other options.

## Interactions

With -u:

- group byte-identical lines
- output one line per group

With -f -u:

- group lines using ASCII case-insensitive equality
- output the first line from each group

With -r -u:

- reverse the sorted order
- keep the first line from each group in that order

With -r -f -u:

- use ASCII case-insensitive equality
- choose one representative using the normal deterministic secondary order
- remove the other members of the equal group
- apply reverse ordering after representative selection

Reverse sorting must not change which member of a case-insensitive equal group
is retained.

## Requirements

Preserve:

- empty input
- empty lines
- long lines
- prefix-related lines that are not equal
- final lines without a newline
- existing error handling

Do not modify input records.

## Implementation

Keep ordering comparison and uniqueness equality separate where needed.

Use the existing C11 structure and compiler settings.

Do not call sort, uniq, or another external program.

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

    tests/sort-test-suite/judge_candidate.sh build/new_sort -r -f -u

That command runs every frozen case whose required flags are all named on the
command line, so it covers the unique feature added here **and** the base,
reverse and ignore-case behavior from the earlier checkpoints as regression
coverage. All of it must pass.

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
3. Equality rules.
4. Option interactions.
5. Commands run.
6. Whether the build passed.
