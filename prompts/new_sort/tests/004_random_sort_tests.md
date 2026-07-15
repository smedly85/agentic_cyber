# Task: Create 004 random-sort tests for new_sort

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
    tests/new_sort/test_new_sort.py
    tests/new_sort/test_001_reverse.py
    tests/new_sort/test_002_ignore_case.py
    tests/new_sort/test_003_unique.py
    Makefile

Do not change the implementation to make tests pass.

If a test exposes an implementation failure, leave the test unchanged and
report the failure.

## Random-test rules

Do not require one exact distinct-group order.

Do not require two executions to produce different orders.

A valid random implementation may produce the same order more than once.

Do not use statistical thresholds.

Do not test randomness quality.

Do not fail because repeated executions produce the same valid order.

Validate required properties for every execution.

Run selected property cases multiple times.

## Required grouping behavior

Without -f:

- byte-identical records form one group
- every group appears in one contiguous output block

With -f:

- ASCII case-insensitive equal records form one group
- every group appears in one contiguous output block

Without -u:

- output contains exactly the same multiset of records as input

With -u:

- output contains exactly one representative per equality group
- representative selection follows checkpoint 003 rules

Inside each equality group:

- preserve normal deterministic internal order
- do not randomly shuffle group members
- reverse mode must not reverse group members

With -r:

- the selected random group order is reversed
- equality groups remain contiguous
- internal group order remains unchanged
- representative selection remains unchanged

## Representative rules

Without -f:

- exact duplicate records form one group
- the one retained record is byte-identical to every member

With -f and -u:

- determine equality using ASCII case-insensitive values
- choose the representative using normal deterministic original-byte order
- randomize the order of the surviving groups

With -R -r -f -u:

- choose the same representative as -R -f -u
- randomize the surviving groups
- reverse the chosen group order
- do not change any selected representative

## Test rules

Use Python unittest.

Run:

    build/new_sort

Use subprocess with byte input and byte output.

Use collections.Counter or an equivalent independent multiset check.

Do not call:

    sort
    uniq
    shuf
    another external utility

Do not import or reproduce C implementation internals.

The test file must be self-contained.

## Required coverage

Test all of these:

1. -R accepts ordinary input.
2. --random-sort satisfies the same properties as -R.
3. Uppercase -R is distinct from lowercase -r.
4. Empty input.
5. One empty record.
6. One nonempty record.
7. All records equal.
8. All records distinct.
9. Multiple duplicate groups.
10. Groups with different duplicate counts.
11. Equal records remain contiguous.
12. Every input record is preserved without -u.
13. No record is added.
14. No record is lost.
15. No record is modified.
16. Duplicate counts are preserved without -u.
17. Empty records.
18. Multiple empty records.
19. Empty records mixed with nonempty records.
20. Prefix-related records.
21. Leading spaces.
22. Trailing spaces.
23. Tabs and other non-newline control bytes.
24. Punctuation.
25. Digits.
26. Embedded NUL bytes.
27. Multiple embedded NUL bytes.
28. Bytes above ASCII.
29. Mixed ASCII and non-ASCII bytes.
30. A final record without a newline.
31. A one-byte final record without a newline.
32. Records longer than 4 KiB.
33. Records with long common prefixes.
34. A large number of distinct groups.
35. A large number of duplicate records.
36. -R -f uses case-insensitive groups.
37. Case-insensitive groups remain contiguous.
38. Group members use deterministic internal order.
39. -R -u outputs one representative per bytewise group.
40. -R -f -u outputs one representative per case-insensitive group.
41. -R -f -u uses the checkpoint 003 representative rule.
42. -R -r preserves all grouping properties.
43. -R -r does not reverse records inside groups.
44. -R -r -f -u does not change selected representatives.
45. Combined forms including -Rf, -fR, -Ru, -Rfu, and -Rrfu.
46. Separate short forms.
47. Long forms.
48. Mixed short and long forms.
49. Option order does not change grouping rules.
50. Option order does not change representative rules.
51. -RR is accepted.
52. Repeated long options are accepted.
53. --sort=random is rejected.
54. --random-source is rejected.
55. --random-source=value is rejected.
56. --random-sort=value is rejected.
57. Unknown short options fail.
58. Unknown long options fail.
59. Non-option operands fail.
60. A single dash is rejected.
61. A double-dash argument is rejected.
62. Multiple invalid arguments fail.
63. Invalid arguments exit with status 2.
64. Invalid arguments produce no standard output.
65. Invalid arguments write a usage diagnostic to standard error.
66. Invalid arguments are rejected before standard input is processed.
67. Successful commands exit with status 0.
68. Successful commands write nothing to standard error.
69. Repeated executions always satisfy all required properties.

## Random-output validation

For each execution:

- parse output as newline-delimited byte records
- verify every output record ends with a newline
- compare input and output multisets when -u is not active
- verify the expected number of groups
- verify equal groups are contiguous
- verify deterministic internal group order
- verify unique representatives when -u is active
- verify no record is modified

Do not compare two separate random executions and assume they began with the
same random group order.

Do not claim to verify exact reverse group order by comparing separate -R and
-R -r executions.

Verify that -R -r is accepted and that all observable grouping, preservation,
internal-order, and representative-selection requirements hold.

## Test helpers

Create independent helpers for:

- parsing newline-delimited byte output
- ASCII folding
- exact group keys
- case-insensitive group keys
- multiset comparison
- contiguous-group validation
- deterministic internal group ordering
- unique representative selection
- output record validation

Do not seed or control the program's random-number generator.

Do not make tests timing-dependent.

Do not weaken checks to match current behavior.

Avoid unnecessarily slow test data.

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
6. How randomized output was validated without requiring an exact group order.