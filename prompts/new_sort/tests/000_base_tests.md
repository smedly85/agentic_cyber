# Task: Create 000 base tests for new_sort

Create:

    tests/new_sort/test_new_sort.py

Also create an empty file if it does not exist:

    tests/new_sort/__init__.py

Test the complete base behavior of new_sort.

The executable is:

    build/new_sort

The base program accepts no command-line options or operands.

Do not modify:

    src/
    README.md
    src/new_sort/README.md
    prompts/
    Makefile

Do not change the implementation to make tests pass.

If a test exposes an implementation failure, leave the test unchanged and
report the failure.

## Required behavior

new_sort must:

- read newline-delimited records from standard input
- sort them in ascending bytewise lexicographic order
- use unsigned byte values for comparison
- write the sorted records to standard output
- preserve duplicate records
- add a newline to every output record
- treat a final input record without a newline as a complete record
- produce no output for empty input
- accept no options or operands

The newline delimiter is not part of a record's comparison value.

At the first differing byte, the record with the smaller unsigned byte value
must appear first.

When one record is a prefix of another, the shorter record must appear first.

The behavior must not depend on locale or valid UTF-8 input.

## Test rules

Use Python unittest.

Run new_sort through subprocess.

Use byte input and byte output.

Calculate expected output independently in Python.

Do not call other external utilities.

Do not copy comparison or input-processing logic from the C implementation.

Do not derive expected output from the program's output.

The test file must be self-contained.

## Required coverage

Test all of these:

1. Basic unordered input.
2. Already sorted input.
3. Reverse-ordered input.
4. Empty input.
5. One empty record.
6. One nonempty record.
7. Multiple empty records.
8. Empty records mixed with nonempty records.
9. Duplicate records.
10. Multiple duplicate groups.
11. Nonadjacent duplicates before sorting.
12. Records containing ordinary spaces.
13. Leading spaces.
14. Trailing spaces.
15. Records containing only spaces.
16. Tabs and other non-newline control bytes.
17. Punctuation.
18. Digits.
19. Uppercase and lowercase ASCII bytes.
20. Prefix relationships such as a, aa, aaa, and ab.
21. Records that differ only in the final byte.
22. Embedded NUL bytes.
23. Multiple embedded NUL bytes.
24. Bytes above ASCII, including 0x80 and 0xff.
25. Mixed ASCII and non-ASCII bytes.
26. Records containing every byte value except newline.
27. A final record without a terminating newline.
28. A one-byte final record without a newline.
29. An empty final input after a terminating newline.
30. A record longer than 4 KiB.
31. Records with different long common prefixes.
32. A large number of records.
33. A large number of duplicate records.
34. Input records are not truncated.
35. Input records are not modified.
36. Every input record appears exactly once in output, including duplicates.
37. Every successful output record ends with a newline.
38. Successful execution exits with status 0.
39. Successful execution writes nothing to standard error.
40. An unexpected short option is rejected.
41. An unexpected long option is rejected.
42. A non-option operand is rejected.
43. Multiple invalid arguments are rejected.
44. A single dash operand is rejected.
45. A double-dash argument is rejected.
46. Invalid arguments exit with status 2.
47. Invalid arguments produce no standard output.
48. Invalid arguments write a concise usage diagnostic to standard error.
49. Invalid arguments are rejected before standard input is processed.
50. Output failure produces a nonzero exit status when the platform provides
    /dev/full.
51. Output failure writes a diagnostic to standard error when supported.
52. The program handles repeated execution without relying on prior process
    state.

## Expected ordering

Use Python byte ordering to calculate normal expected output.

Expected output may be constructed with behavior equivalent to:

    sorted(records)

Each expected record must be followed by:

    b"\n"

Do not decode records as text.

Do not use locale-aware sorting.

## Invalid-argument checks

For every invalid invocation, verify:

- exit status is exactly 2
- standard output is empty
- standard error contains a usage diagnostic

Use input data that would produce visible output if it were read successfully.
This confirms that argument validation occurs before input processing.

## Platform-specific checks

Test output failure with:

    /dev/full

only when that device exists and can be opened.

Skip only that platform-specific test when the device is unavailable.

Do not skip ordinary behavioral tests.

Do not make tests depend on timing, random behavior, or system locale.

## Test quality

Use clear helper functions.

Use descriptive test names.

Keep expected-value calculations independent of the implementation.

Do not weaken assertions to match current implementation behavior.

Do not modify source code when tests fail.

Avoid excessive test data that makes the suite impractically slow.

## Validation

Run:

    make clean
    make
    python3 -m unittest discover -s tests/new_sort -p 'test_new_sort.py' -v
    make test

Report:

1. Files created.
2. Number of tests added.
3. Commands run.
4. Test results.
5. Any implementation failures found.
6. Any platform-specific test that was skipped and why.