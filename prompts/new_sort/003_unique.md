# Task: Add unique output to new_sort

Modify:

    src/new_sort/new_sort.c

Update:

    src/new_sort/README.md

The executable must remain:

    build/new_sort

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

Run:

    make clean
    make

Fix all compiler errors and warnings.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. Equality rules.
4. Option interactions.
5. Commands run.
6. Whether the build passed.

Do not commit.
Do not create a branch.
Do not open a pull request.