# Task: Create 001 reverse tests for new_sort

Create:

    tests/new_sort/test_001_reverse.py

Also create an empty file if it does not exist:

    tests/new_sort/__init__.py

Test the required behavior of:

    -r
    --reverse

Do not modify:

    src/
    README.md
    src/new_sort/README.md
    prompts/
    tests/new_sort/test_new_sort.py
    Makefile

Do not change the implementation to make tests pass.

If a test exposes an implementation failure, leave the test unchanged and
report the failure.

## Test rules

Use Python unittest.

Run:

    build/new_sort

Use subprocess with byte input and byte output.

Calculate expected output independently in Python.

Do not call:

    sort
    uniq
    shuf
    another external utility

Do not copy comparison logic from the C implementation.

The test file must be self-contained.

## Required behavior

Without an option:

- sort records in ascending bytewise lexicographic order

With -r or --reverse:

- sort records in descending bytewise lexicographic order
- reverse the complete normal bytewise ordering
- preserve duplicate records

Use unsigned byte values.

When one record is a prefix of another, the longer record comes first in
reverse mode.

## Required coverage

Test all of these:

1. -r produces descending bytewise lexicographic order.
2. --reverse produces the same output as -r.
3. No option still produces ascending bytewise order.
4. Already ascending input.
5. Already descending input.
6. Unordered input.
7. Empty input.
8. One empty record.
9. One nonempty record.
10. Multiple empty records.
11. Empty records mixed with nonempty records.
12. Duplicate records.
13. Multiple duplicate groups.
14. Nonadjacent duplicates before sorting.
15. Prefixes such as a, aa, aaa, and ab.
16. Leading spaces.
17. Trailing spaces.
18. Records containing only spaces.
19. Tabs and other non-newline control bytes.
20. Punctuation.
21. Digits.
22. Uppercase and lowercase bytes.
23. Embedded NUL bytes.
24. Multiple embedded NUL bytes.
25. Bytes above ASCII, including 0x80 and 0xff.
26. Mixed ASCII and non-ASCII bytes.
27. A final record without a newline.
28. A one-byte final record without a newline.
29. Records longer than 4 KiB.
30. Records with long common prefixes.
31. A large number of records.
32. A large number of duplicate records.
33. Input records are not truncated.
34. Input records are not modified.
35. Every input record appears exactly once in output.
36. Every successful output record ends with a newline.
37. -r -r is accepted and acts like -r.
38. -rr is accepted and acts like -r.
39. --reverse --reverse is accepted and acts like --reverse.
40. Unknown short options fail.
41. Unknown long options fail.
42. Non-option operands fail.
43. A single dash is rejected.
44. A double-dash argument is rejected.
45. --reverse=value fails.
46. Multiple invalid arguments fail.
47. Invalid arguments exit with status 2.
48. Invalid arguments produce no standard output.
49. Invalid arguments write a usage diagnostic to standard error.
50. Invalid arguments are rejected before standard input is processed.
51. Successful commands exit with status 0.
52. Successful commands write nothing to standard error.
53. Repeated executions do not depend on prior process state.

Expected reverse output must be calculated independently using Python byte
ordering.

Do not hard-code only one example.

## Invalid-argument checks

For each invalid invocation:

- provide input that would normally produce visible output
- verify exit status is exactly 2
- verify standard output is empty
- verify standard error contains a usage diagnostic

## Test quality

Use clear helper functions.

Use descriptive test names.

Do not decode input as text.

Do not depend on locale.

Do not depend on valid UTF-8 input.

Do not weaken assertions because of current implementation behavior.

Do not use timing-based checks.

Avoid unnecessarily slow test data.

## Validation

Run:

    make clean
    make
    python3 -m unittest discover -s tests/new_sort -p 'test_001_reverse.py' -v
    make test

Report:

1. Files created.
2. Number of tests added.
3. Commands run.
4. Test results.
5. Any implementation failures found.