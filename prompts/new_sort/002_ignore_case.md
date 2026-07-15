# Task: Add case-insensitive sorting to new_sort

Modify:

    src/new_sort/new_sort.c

Update:

    src/new_sort/README.md

The executable must remain:

    build/new_sort

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

## Documentation

Update:

    src/new_sort/README.md

Document:

    -f
    --ignore-case

State that the behavior is ASCII-only and locale-independent.

Document interaction with reverse sorting.

Do not modify the root README.

Do not modify files under prompts/.

## Build

Run:

    make clean
    make

Fix all compiler errors and warnings.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. Comparison approach.
4. Interaction with reverse.
5. Commands run.
6. Whether the build passed.

Do not commit.
Do not create a branch.
Do not open a pull request.