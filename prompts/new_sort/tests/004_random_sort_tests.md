# Task: Create 004 random-sort tests for sort

Create:

    tests/new_sort/test_004_random_sort.py

Ensure this file exists:

    tests/new_sort/__init__.py

Do not modify existing tests.

Test the required behavior of:

    -R
    --random-sort

Also test interaction with:

    -r
    --reverse
    -f
    --ignore-case
    -u
    --unique

Do not modify:

    src/
    README.md
    src/new_sort/README.md
    prompts/
    tests/test_new_sort.py
    tests/new_sort/test_001_reverse.py
    tests/new_sort/test_002_ignore_case.py
    tests/new_sort/test_003_unique.py
    Makefile

Do not change the implementation to make tests pass.

If a test exposes an implementation failure, leave the test unchanged and
report the failure.

## Random-test rules

Do not require one exact group order.

Do not require two runs to produce different orders.

A valid random implementation may produce the same order more than once.

Do not use statistical randomness thresholds.

Do not test randomness quality.

Validate required properties for every run.

Run selected property cases several times, but never fail only because two
runs match.

## Required properties

Without -f:

- byte-identical lines form one group
- every group appears in one contiguous block

With -f:

- ASCII case-insensitive equal lines form one group
- every group appears in one contiguous block

Without -u:

- output must contain exactly the same multiset of lines as input

With -u:

- output must contain exactly one representative per equality group
- the representative must follow the deterministic internal ordering rule

Inside an equality group:

- preserve the deterministic internal order used without random sorting
- do not randomly shuffle members of the group

With -r:

- group-order reversal must not break grouping
- internal group ordering must remain valid

## Test rules

Use Python unittest.

Run:

    build/new_sort

Use subprocess with byte input and byte output.

Use collections.Counter or an equivalent independent multiset check.

Do not call sort, uniq, shuf, or another external utility.

The test file must be self-contained.

## Required coverage

Test all of these:

1. -R accepts ordinary input.
2. --random-sort has the same required properties as -R.
3. Uppercase -R is distinct from lowercase -r.
4. Empty input.
5. One line.
6. All input lines equal.
7. All input lines distinct.
8. Multiple duplicate groups.
9. Equal lines remain contiguous.
10. Every input record is preserved without -u.
11. No record is added.
12. No record is lost.
13. No record is modified.
14. Duplicate counts are preserved without -u.
15. Empty lines.
16. Multiple empty lines.
17. Prefix-related lines.
18. Leading and trailing spaces.
19. Punctuation and digits.
20. Embedded NUL bytes.
21. Bytes above ASCII.
22. A final line without a newline.
23. Lines longer than 4 KiB.
24. A large number of groups.
25. A large number of duplicate records.
26. -R -f uses case-insensitive groups.
27. Case-insensitive groups remain contiguous.
28. Members inside case-insensitive groups have deterministic internal order.
29. -R -u outputs one representative per bytewise group.
30. -R -f -u outputs one representative per case-insensitive group.
31. -R -r preserves all grouping properties.
32. -R -r does not reverse members inside equal groups.
33. -Rrfu and other valid combined forms are accepted.
34. Option order does not change grouping or representative rules.
35. -RR is accepted.
36. Repeated long options are accepted.
37. Mixed repeated options are idempotent.
38. --sort=random is rejected.
39. --random-source is rejected.
40. --random-source=value is rejected.
41. Unknown short options fail.
42. Unknown long options fail.
43. Non-option operands fail.
44. Invalid arguments exit with status 2.
45. Invalid arguments produce no standard output.
46. Invalid arguments write a usage diagnostic to standard error.
47. Successful commands exit with status 0.
48. Successful commands write nothing to standard error.

For randomized output, assert properties instead of exact distinct-group order.

Do not compare a -R run with a separate -R -r run and assume they used the
same random order.

## Test helpers

Create independent helpers for:

- parsing newline-delimited byte output
- ASCII folding
- equality-group keys
- multiset comparison
- contiguous-group validation
- deterministic internal group ordering
- unique representative validation

Do not import or reproduce implementation internals.

Do not seed or control the program's random-number generator.

Do not make tests timing-dependent.

Do not weaken checks to match current behavior.

## Validation

Run:

    make clean
    make
    python3 -m unittest discover -s tests/new_sort -p 'test_004_random_sort.py' -v
    make test

Report:

1. Files created or changed.
2. Number of tests added.
3. Commands run.
4. Test results.
5. Any implementation failures found.
6. How randomized outputs were validated without requiring an exact order.

Do not commit.
Do not create a branch.
Do not open a pull request.