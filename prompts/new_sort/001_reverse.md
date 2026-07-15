# Task: Add reverse sorting to new_sort

Modify:

    src/new_sort/new_sort.c

The executable must remain:

    build/new_sort

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

Run:

    make clean
    make

Fix all compiler errors and warnings.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. Implementation approach.
4. Commands run.
5. Whether the build passed.

Do not commit.
Do not create a branch.
Do not open a pull request.