# Task: Create 001 reverse tests for sort

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
    tests/test_new_sort.py
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

## Required coverage

Test all of these:

1. -r produces descending bytewise lexicographic order.
2. --reverse produces the same output as -r.
3. No option still produces ascending bytewise order.
4. Already ascending input.
5. Already descending input.
6. Unordered input.
7. Empty input.
8. One line.
9. Empty lines.
10. Duplicate lines.
11. Prefixes such as a, aa, aaa, and ab.
12. Leading spaces.
13. Trailing spaces.
14. Punctuation.
15. Uppercase and lowercase bytes.
16. Embedded NUL bytes.
17. Bytes above ASCII, including 0x80 and 0xff.
18. A final line without a newline.
19. Lines longer than 4 KiB.
20. A large number of lines.
21. -r -r is accepted and acts like -r.
22. -rr is accepted and acts like -r.
23. --reverse --reverse is accepted and acts like --reverse.
24. Unknown short options fail.
25. Unknown long options fail.
26. Non-option operands fail.
27. --reverse=value fails.
28. Invalid arguments exit with status 2.
29. Invalid arguments produce no standard output.
30. Invalid arguments write a usage diagnostic to standard error.
31. Successful commands exit with status 0.
32. Successful commands write nothing to standard error.

Expected reverse output must be computed independently using Python byte
ordering.

Do not hard-code only one example.

## Test quality

Use clear helper functions.

Use descriptive test names.

Do not depend on locale.

Do not depend on input being valid UTF-8.

Do not weaken assertions because of current implementation behavior.

Do not use timing-based checks.

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

Do not commit.
Do not create a branch.
Do not open a pull request.