# Task: Create 003 unique tests for new_sort

Create:

    tests/new_sort/test_003_unique.py

Ensure this file exists:

    tests/new_sort/__init__.py

Do not modify existing tests.

Test the required behavior of:

    -u
    --unique

Also test interaction with:

    -r
    --reverse
    -f
    --ignore-case

Do not modify:

    src/
    README.md
    src/new_sort/README.md
    prompts/
    tests/new_sort/test_new_sort.py
    tests/new_sort/test_001_reverse.py
    tests/new_sort/test_002_ignore_case.py
    Makefile

Do not change the implementation to make tests pass.

If a test exposes an implementation failure, leave the test unchanged and
report the failure.

## Required behavior

Without -f:

- sort using bytewise ordering
- group only byte-identical records
- output one record from each group

With -f:

- determine equality using ASCII case-insensitive values
- order records within each equality group using original bytes
- choose the first record in that normal deterministic order
- remove the other records from the equality group

With -r but without -f:

- reverse the order of distinct bytewise groups
- output one record from each group

With -r and -f:

- determine case-insensitive equality groups
- choose each representative using the normal deterministic secondary order
- remove the other members of each group
- reverse the order of the surviving groups
- do not change the representative because reverse is enabled

Sorting and representative selection must be implemented independently in the
test oracle.

Keep ordering comparison separate from uniqueness equality.

## Test rules

Use Python unittest.

Run:

    build/new_sort

Use subprocess with byte input and byte output.

Do not call:

    sort
    uniq
    shuf
    another external utility

Do not copy implementation logic from the C source.

The test file must be self-contained.

## Required coverage

Test all of these:

1. -u removes byte-identical duplicates.
2. --unique produces the same output as -u.
3. No option still preserves duplicates.
4. Input with no duplicates.
5. Input containing only one repeated record.
6. Multiple duplicate groups.
7. Nonadjacent duplicates before sorting.
8. Duplicate groups of different sizes.
9. Empty input.
10. One empty record.
11. Multiple empty records collapse to one empty record.
12. Empty records mixed with nonempty records.
13. Prefix-related records remain distinct.
14. Records differing only in length remain distinct.
15. Leading spaces remain significant.
16. Trailing spaces remain significant.
17. Tabs and spaces remain distinct.
18. Case variants remain distinct without -f.
19. -f -u groups ASCII case variants.
20. -u -f and -f -u are equivalent.
21. Three or more case variants form one equality group.
22. The deterministic representative is retained.
23. Input order does not determine the representative.
24. -r -u reverses distinct exact-match groups.
25. -r -f -u retains the same representative as -f -u.
26. -r -f -u reverses the surviving group order.
27. Reverse does not change the selected case-insensitive representative.
28. All supported option orders are equivalent.
29. Combined forms including -fu, -uf, -ru, -urf, and -rfu.
30. Separate short forms.
31. Long forms.
32. Mixed short and long forms.
33. -uu is accepted and acts like -u.
34. Digits.
35. Punctuation.
36. Leading and trailing whitespace.
37. Embedded NUL bytes.
38. Multiple embedded NUL bytes.
39. Bytes above ASCII.
40. Mixed ASCII and non-ASCII bytes.
41. A final record without a newline.
42. A one-byte final record without a newline.
43. Records longer than 4 KiB.
44. Records with long common prefixes.
45. A large number of duplicate groups.
46. A large number of records in one group.
47. Input records are not truncated.
48. Selected representatives are not modified.
49. Every successful output record ends with a newline.
50. Unknown short options fail.
51. Unknown long options fail.
52. Non-option operands fail.
53. A single dash is rejected.
54. A double-dash argument is rejected.
55. --unique=value fails.
56. Multiple invalid arguments fail.
57. Invalid arguments exit with status 2.
58. Invalid arguments produce no standard output.
59. Invalid arguments write a usage diagnostic to standard error.
60. Invalid arguments are rejected before standard input is processed.
61. Successful commands exit with status 0.
62. Successful commands write nothing to standard error.
63. Repeated executions do not depend on prior process state.

## Expected-output helpers

Create independent helpers for:

- ASCII folding
- normal bytewise ordering
- ignore-case ordering
- exact equality
- case-insensitive equality
- equality-group construction
- deterministic representative selection
- reverse group ordering
- output serialization

For -f -u:

- choose the first member in normal deterministic case-insensitive order

For -r -f -u:

- choose the same member as -f -u
- reverse only the order of surviving groups

Do not derive expected output from program output.

## Invalid-argument checks

For each invalid invocation:

- provide input that would normally produce visible output
- verify exit status is exactly 2
- verify standard output is empty
- verify standard error contains a usage diagnostic

## Test quality

Use clear helper functions.

Use descriptive test names.

Do not import helpers from another test file.

Do not copy implementation internals.

Do not decode records as text.

Do not depend on locale.

Do not weaken assertions to match current behavior.

Do not use timing-based checks.

Avoid unnecessarily slow test data.

## Validation

Run:

    make clean
    make
    python3 -m unittest discover -s tests/new_sort -p 'test_003_unique.py' -v
    make test

Report:

1. Files created or changed.
2. Number of tests added.
3. Commands run.
4. Test results.
5. Any implementation failures found.