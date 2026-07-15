# Task: Create 003 unique tests for sort

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
    tests/test_new_sort.py
    tests/new_sort/test_001_reverse.py
    tests/new_sort/test_002_ignore_case.py
    Makefile

Do not change the implementation to make tests pass.

If a test exposes an implementation failure, leave the test unchanged and
report the failure.

## Required behavior

Without -f:

- sort using bytewise ordering
- group only byte-identical lines
- output the first line from each group

With -f:

- group lines using ASCII case-insensitive equality
- use original bytes for deterministic secondary ordering
- output the first line from each completed sorted group

With -r:

- reverse the completed sorted order
- output the first line from each group in that order

Implement expected behavior independently in Python.

Keep ordering comparison separate from uniqueness equality.

## Test rules

Use Python unittest.

Run:

    build/new_sort

Use subprocess with byte input and byte output.

Do not call sort, uniq, or another external utility.

The test file must be self-contained.

## Required coverage

Test all of these:

1. -u removes byte-identical duplicates.
2. --unique produces the same output as -u.
3. No option still preserves duplicates.
4. Input with no duplicates.
5. Input containing only one repeated line.
6. Multiple duplicate groups.
7. Nonadjacent duplicates before sorting.
8. Empty input.
9. One line.
10. Multiple empty lines collapse to one empty line.
11. Empty lines mixed with nonempty lines.
12. Prefix-related lines remain distinct.
13. Leading and trailing spaces remain significant without -f.
14. Case variants remain distinct without -f.
15. -f -u groups ASCII case variants.
16. -u -f and -f -u are equivalent.
17. The deterministic representative is retained for case-equivalent groups.
18. -r -u reverses ordering and keeps one line per exact group.
19. -r -f -u follows the specified representative rule.
20. All supported option orders are equivalent where expected.
21. Combined forms including -fu, -uf, -ru, -urf, and -rfu.
22. Separate short forms.
23. Long forms.
24. Mixed short and long forms.
25. -uu is accepted and acts like -u.
26. Repeated long options are idempotent.
27. Repeated mixed options are idempotent.
28. Digits and punctuation.
29. Embedded NUL bytes.
30. Bytes above ASCII.
31. A final line without a newline.
32. Lines longer than 4 KiB.
33. A large number of duplicate groups.
34. Every successful output line ends in a newline.
35. Unknown short options fail.
36. Unknown long options fail.
37. Non-option operands fail.
38. --unique=value fails.
39. Invalid arguments exit with status 2.
40. Invalid arguments produce no standard output.
41. Invalid arguments write a usage diagnostic to standard error.
42. Successful commands exit with status 0.
43. Successful commands write nothing to standard error.

Include groups with three or more case variants.

Include groups where reverse mode changes which case variant appears first
under the checkpoint specification.

## Test quality

Create independent helpers for:

- ASCII folding
- expected ordering
- equality grouping
- unique representative selection

Do not derive expected output from the program output.

Do not copy implementation logic from the C source.

Do not weaken assertions to match current behavior.

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

Do not commit.
Do not create a branch.
Do not open a pull request.