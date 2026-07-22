# Task: Add random sorting to new_sort

Modify:

    src/new_sort/new_sort.c

The executable must remain:

    build/new_sort

Add:

    -R
    --random-sort

Uppercase -R is different from lowercase -r.

Random sort must randomize the order of distinct comparison groups.

Equal lines must remain next to each other.

Randomize groups, not individual lines.

Without -f, groups are based on byte-identical lines.

With -f, groups are based on ASCII case-insensitive equality.

Inside each group, keep the deterministic order used without random sorting.

Every input line must appear once unless -u is active.

Separate program runs may produce different valid orders.

Cryptographically secure randomness is not required.

## Reference

Use GNU Coreutils sort 9.11 as behavioral inspiration.

Random sorting must randomize distinct keys while keeping equal keys together.

Implement it independently.

Do not copy Coreutils source code, comments, hashing code, random-number code,
algorithms, or implementation details.

Do not add:

    --sort=random
    --random-source
    --random-source=FILE

## Arguments

Support:

    -r
    --reverse
    -f
    --ignore-case
    -u
    --unique
    -R
    --random-sort

Short options may be combined:

    -Rf
    -fR
    -Ru
    -Rrfu

Repeated options must be accepted and treated as idempotent:

    -RR
    -RRfu
    --random-sort --random-sort

Unknown options and operands must:

- write a short usage message to standard error
- write nothing to standard output
- exit with status 2

Do not add file operands.

Do not add other options.

## Interactions

With -R:

- randomize bytewise equality groups
- preserve all lines

With -R -f:

- group lines using ASCII case-insensitive equality
- randomize the groups

With -R -u:

- randomize the groups
- output one line from each group

With -R -f -u:

- group using case-insensitive equality
- randomize the groups
- output one representative from each group

With -R -r:

- choose a random group order
- reverse that group order
- do not reverse lines inside a group

Option order must not change behavior.

## Requirements

Preserve:

- empty input
- empty lines
- duplicates unless -u is active
- long lines
- final lines without a newline
- existing error handling

Do not lose, duplicate, truncate, or modify records.

## Implementation

Use the existing C11 structure and compiler settings.

Check randomness initialization and allocation failures.

Avoid undefined behavior when creating or comparing random order values.

Do not call sort, shuf, or another external program.

Do not make unrelated changes.

## Build

Run:

    make clean
    make

Fix all compiler errors and warnings.

## Visible tests

The controller will evaluate this checkpoint using exactly these visible tests:

    tests/new_sort/test_new_sort.py
    tests/new_sort/test_001_reverse.py
    tests/new_sort/test_002_ignore_case.py
    tests/new_sort/test_003_unique.py
    tests/new_sort/test_004_random_sort.py

The base, reverse, ignore-case, and unique tests are regression coverage for
earlier checkpoints. `tests/new_sort/test_004_random_sort.py` covers the random
sort checkpoint added by this task. All five must pass.

You may inspect these visible tests while implementing the task.

Do not modify, replace, weaken, disable, bypass, or delete any visible test.

The controller will run exactly:

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
        tests/new_sort/test_new_sort.py \
        tests/new_sort/test_001_reverse.py \
        tests/new_sort/test_002_ignore_case.py \
        tests/new_sort/test_003_unique.py \
        tests/new_sort/test_004_random_sort.py \
        -v

after your implementation is returned.

Do not perform an autonomous repair loop. If validation fails, the experiment
controller will provide the failure output in a subsequent repair invocation.

Only the tests listed above are visible. Any hidden, comprehensive, or external
evaluation is controller-only, is not exposed here, and is not used as repair
feedback.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. Grouping rules.
4. Option interactions.
5. Randomness source.
6. Commands run.
7. Whether the build passed.

Do not commit.
Do not create a branch.
Do not open a pull request.
