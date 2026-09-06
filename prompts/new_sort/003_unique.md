# Task: Add unique output to new_sort

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

Ordering comparison and uniqueness equality/representative selection are
separate concepts.

Without ignore-case, lines are equal only when their bytes are identical.

Without `-u`, ordinary `-f` ordering is unchanged: compare ASCII case-folded
bytes first, then, when the folded values are equal, compare the original bytes
as a deterministic secondary comparison.

With both `-f` and `-u`, ASCII case-insensitive comparison determines which
lines belong to the same unique group. The original-byte secondary comparison
must not distinguish members of that group or choose the retained member.
Retain the first input record from each case-insensitive equal group and output
only that representative.

For example, this input:

    abc
    ABC

with `-f -u` must output:

    abc

For input order `abc` then `ABC`, retain `abc`.

Conversely, this input:

    ABC
    abc

with `-f -u` must output:

    ABC

For input order `ABC` then `abc`, retain `ABC`.

## Reference

Use GNU Coreutils sort 9.11 as behavioral inspiration.

Unique mode must use its uniqueness equality rule to form groups and retain the
first input record from each group.

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
- retain the first input record from each group and output one line per group

With -f -u:

- group lines using ASCII case-insensitive equality
- do not use the original-byte secondary comparison to distinguish group
  members or select a representative
- retain and output the first input record from each group

With -r -u:

- reverse the sorted order
- retain the first input record from each byte-identical group

With -r -f -u:

- use ASCII case-insensitive equality
- form the same unique groups as for `-f -u`
- retain the same first-input representative as for `-f -u`
- order the surviving groups in reverse; do not reverse or otherwise change
  representative selection

First determine the unique groups and their retained first-input
representatives. Reverse affects the ordering of the surviving groups, not
which representative survives. Thus `-r` does not change the retained
representative.

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
