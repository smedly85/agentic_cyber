# Task: Create 002 ignore-case tests for new_sort

Create:

    tests/new_sort/test_002_ignore_case.py

Ensure this file exists:

    tests/new_sort/__init__.py

Do not modify existing tests.

Test the required behavior of:

    -f
    --ignore-case

Also test interaction with:

    -r
    --reverse

Do not modify:

    src/
    README.md
    src/new_sort/README.md
    prompts/
    tests/new_sort/test_new_sort.py
    tests/new_sort/test_001_reverse.py
    Makefile

Do not change the implementation to make tests pass.

If a test exposes an implementation failure, leave the test unchanged and
report the failure.

## Required comparison model

For the primary comparison:

- map ASCII a through z to A through Z
- leave every other byte unchanged

When primary values are equal:

- compare the original record bytes
- use that comparison as a deterministic secondary order

The secondary comparison affects ordering only.

With reverse enabled:

- perform the case-insensitive primary comparison
- perform the original-byte secondary comparison when needed
- reverse the complete comparison result

Implement expected behavior independently in Python.

Do not use locale-dependent case conversion.

Do not use:

    str.lower
    str.upper
    str.casefold
    Unicode decoding

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

Do not copy comparison logic from the C implementation.

The test file must be self-contained.

## Required coverage

Test all of these:

1. -f performs ASCII case-insensitive primary sorting.
2. --ignore-case produces the same output as -f.
3. No option remains normal bytewise sorting.
4. Lowercase input.
5. Uppercase input.
6. Mixed-case input.
7. Case variants with equal folded values.
8. Three or more variants of the same folded value.
9. Deterministic original-byte secondary ordering.
10. Records whose order changes because of ASCII folding.
11. Records whose order does not change because of ASCII folding.
12. Prefix relationships after case folding.
13. Empty input.
14. One empty record.
15. One nonempty record.
16. Multiple empty records.
17. Empty and nonempty records together.
18. Duplicate byte-identical records.
19. Case-equivalent but byte-different records.
20. Multiple case-equivalent groups.
21. Nonadjacent case-equivalent records before sorting.
22. Digits.
23. Punctuation.
24. Leading spaces.
25. Trailing spaces.
26. Tabs and non-newline control bytes.
27. Embedded NUL bytes.
28. Multiple embedded NUL bytes.
29. Non-ASCII bytes remain unchanged.
30. Bytes 0x80 and 0xff remain unchanged.
31. Mixed ASCII and non-ASCII bytes.
32. A final record without a newline.
33. A one-byte final record without a newline.
34. Records longer than 4 KiB.
35. Records with long common prefixes.
36. A large number of mixed-case records.
37. A large number of case-equivalent groups.
38. Input records are not truncated.
39. Input records are not modified.
40. Every input record appears exactly once.
41. Every successful output record ends with a newline.
42. -rf and -fr are equivalent.
43. -r -f and -f -r are equivalent.
44. Short and long option combinations are equivalent.
45. Mixed short and long option combinations are equivalent.
46. -ff is accepted and acts like -f.
47. -rrf is accepted and acts like -rf.
48. Repeated long options are idempotent.
49. Repeated mixed forms are idempotent.
50. Unknown short options fail.
51. Unknown long options fail.
52. Non-option operands fail.
53. A single dash is rejected.
54. A double-dash argument is rejected.
55. --ignore-case=value fails.
56. Multiple invalid arguments fail.
57. Invalid arguments exit with status 2.
58. Invalid arguments produce no standard output.
59. Invalid arguments write a usage diagnostic to standard error.
60. Invalid arguments are rejected before standard input is processed.
61. Successful commands exit with status 0.
62. Successful commands write nothing to standard error.
63. Repeated executions do not depend on prior process state.

## Expected output

Create an independent ASCII-fold helper that operates on bytes.

Calculate expected ordering using:

1. the ASCII-folded byte sequence
2. the original byte sequence as the secondary key

Reverse both comparison levels when reverse mode is active.

Do not derive expected output from the program output.

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

Do not import or reproduce C implementation internals.

Do not depend on locale.

Do not assume UTF-8 input.

Do not weaken assertions to match current output.

Do not use timing-based checks.

Avoid unnecessarily slow test data.

## Validation

Run:

    make clean
    make
    python3 -m unittest discover -s tests/new_sort -p 'test_002_ignore_case.py' -v
    make test

Report:

1. Files created or changed.
2. Number of tests added.
3. Commands run.
4. Test results.
5. Any implementation failures found.