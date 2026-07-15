# Task: Create 002 ignore-case tests for sort

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
    tests/test_new_sort.py
    tests/new_sort/test_001_reverse.py
    Makefile

Do not change the implementation to make tests pass.

If a test exposes an implementation failure, leave the test unchanged and
report the failure.

## Required comparison model

For the primary comparison:

- map ASCII a through z to A through Z
- leave every other byte unchanged

When primary values are equal, compare the original line bytes as the
deterministic secondary comparison.

With reverse enabled, reverse the completed comparison order.

Implement this expected behavior independently in Python.

Do not use locale-dependent case conversion.

Do not use str.lower, str.upper, casefold, or Unicode decoding for expected
byte comparisons.

## Test rules

Use Python unittest.

Run:

    build/new_sort

Use subprocess with byte input and byte output.

Do not call external sorting utilities.

The test file must be self-contained.

## Required coverage

Test all of these:

1. -f performs ASCII case-insensitive primary sorting.
2. --ignore-case produces the same output as -f.
3. No option remains normal bytewise sorting.
4. Lowercase and uppercase variants.
5. All-uppercase input.
6. All-lowercase input.
7. Mixed-case words.
8. Case variants with equal folded values.
9. Deterministic original-byte secondary ordering.
10. Prefix relationships after case folding.
11. Empty input.
12. One line.
13. Empty lines.
14. Duplicate byte-identical lines.
15. Case-equivalent but byte-different lines.
16. Digits and punctuation.
17. Leading and trailing spaces.
18. Non-ASCII bytes remain unchanged.
19. Embedded NUL bytes.
20. A final line without a newline.
21. Lines longer than 4 KiB.
22. A large number of mixed-case lines.
23. -rf and -fr are equivalent.
24. -r -f and -f -r are equivalent.
25. Long-option combinations are equivalent to short forms.
26. -ff is accepted and acts like -f.
27. -rrf is accepted and acts like -rf.
28. Repeated long options are idempotent.
29. Unknown short options fail.
30. Unknown long options fail.
31. Non-option operands fail.
32. --ignore-case=value fails.
33. Invalid arguments exit with status 2.
34. Invalid arguments produce no standard output.
35. Invalid arguments write a usage diagnostic to standard error.
36. Successful commands exit with status 0.
37. Successful commands write nothing to standard error.

Include cases where ASCII folding changes the primary order and cases where it
does not.

## Test quality

Use a small independent ASCII-fold helper.

Use descriptive test names.

Do not import helpers from the C implementation.

Do not depend on locale.

Do not assume UTF-8 input.

Do not weaken assertions to match current output.

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

Do not commit.
Do not create a branch.
Do not open a pull request.