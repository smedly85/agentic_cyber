# Task: Add order checking to new_sort

Modify:

    src/new_sort/new_sort.c

The executable must remain:

    build/new_sort

Add only the feature described here. Do not add unrelated behavior.

Do not implement options or behavior outside this checkpoint's stated scope.

## Current program

Source:

    src/new_sort/new_sort.c

Executable:

    build/new_sort

Behavior already implemented:

new_sort reads newline-delimited lines from standard input, sorts them in
ascending locale-independent bytewise lexicographic order, and writes them to
standard output with a newline after every line. `-r`/`--reverse` reverses that
order. `-f`/`--ignore-case` compares ASCII letters without regard to case, with
the original bytes as a deterministic secondary comparison. `-u`/`--unique`
outputs one line from each group of lines that compare equal. Duplicates are
otherwise preserved, a final input line without a newline is still a line, empty
input produces empty output, and there are no file operands. Unknown options and
operands are rejected with a usage message on standard error and exit status 2.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -c
    --check

`-c` switches new_sort from *producing* sorted output to *checking* whether the
input is already sorted. It is a check-only mode.

In check mode:

- read the input lines exactly as before
- do **not** sort them
- do **not** write any line to standard output; standard output stays empty in
  every case, whether the input is ordered or not
- walk the input in order, comparing each line with the line before it using the
  **same comparison the other options select** (see interactions below)

If every adjacent pair is in order, exit with status 0 and write nothing to
standard error.

If some adjacent pair is out of order, stop at the first such pair, write a
diagnostic to standard error, and exit with status 1. Standard output must
remain empty.

The diagnostic must be a concise single line naming the offending input. Follow
GNU sort's shape, for example:

    new_sort: -:2: disorder: banana

Only the exit status, the empty standard output, and the presence of a
diagnostic on standard error are checked; the exact wording is yours.

Exit status 1 in check mode means "input is not sorted". It is distinct from
status 2, which continues to mean "the command line was invalid".

## Reference

Use GNU Coreutils sort 9.11 as behavioral inspiration for check mode: `-c`
verifies the ordering that the same invocation would otherwise produce, reports
the first violation, and produces no sorted output.

Implement it independently.

Do not copy Coreutils source code, comments, algorithms, or implementation
details.

Do not add:

    -C
    --check=WORD
    --check-chars

## Arguments

Support:

    -r
    --reverse
    -f
    --ignore-case
    -u
    --unique
    -c
    --check

Short options may be combined:

    -cu
    -rc
    -fc
    -rfuc

Repeated options must be accepted and treated as idempotent:

    -cc
    -rfcc
    --check --check

Unknown options and operands must:

- write a short usage message to standard error
- write nothing to standard output
- exit with status 2

Do not add file operands.

Do not add other options.

## Interactions

Check mode verifies the ordering the same invocation would otherwise produce, so
the other options change what counts as ordered:

With `-c` alone:

- adjacent lines must be in ascending bytewise order
- equal adjacent lines are in order

With `-c -r`:

- adjacent lines must be in descending bytewise order
- equal adjacent lines are in order

With `-c -f`:

- adjacency is judged by the ASCII case-insensitive comparison
- lines that differ only in case are equal, and therefore in order

With `-c -u`:

- the ordering must be **strict**: two adjacent lines that compare equal are a
  violation, reported exactly like any other out-of-order pair
- no line is written to standard output; `-u` does not re-enable output in
  check mode

`-c -f -u`, `-c -r -u` and `-c -r -f -u` combine these rules in the same way:
equality is decided by `-f` when present, strictness by `-u`, and direction by
`-r`.

Option order on the command line must not change behavior.

## Requirements

Preserve, in check mode:

- empty input: nothing to compare, so it is sorted (exit 0)
- a single line: sorted (exit 0)
- empty lines, which compare as ordinary zero-length lines
- arbitrary byte values other than the newline delimiter, including NUL bytes
  and invalid UTF-8
- a final line without a newline, which is still a line and still compared
- long lines
- existing error handling for input, output, and allocation failures

Do not modify input records.

Without `-c`, every existing behavior is unchanged.

## Implementation

Use the existing C11 structure and compiler settings.

Reuse the existing comparison function rather than writing a second ordering
rule for check mode; the two must not be able to disagree.

Do not call sort or another external program.

Do not make unrelated changes.

## Build

Compile directly, without a Makefile:

    mkdir -p build
    cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_sort/new_sort.c -o build/new_sort

Fix all compiler errors and warnings.

## Visible tests

The command-specific test suite is copied into your working directory at:

    tests/sort-test-suite/

You may read anything in it while implementing the task.

The controller will judge this checkpoint by running exactly:

    tests/sort-test-suite/judge_candidate.sh build/new_sort -r -f -u -c

That command runs every frozen case whose required flags are all named on the
command line, so it covers the check feature added here **and** the base,
reverse, ignore-case and unique behavior from the earlier checkpoints as
regression coverage. All of it must pass.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/sort-test-suite/`. Test tampering is detected and recorded.

The experiment controller owns validation and any repair iterations. Do not
perform an autonomous repair loop. If validation fails, the controller will
provide the failure output in a subsequent repair invocation. Any hidden,
comprehensive, or sanitizer evaluation is controller-only, is not exposed here,
and is never used as repair feedback.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. How check mode reuses the existing comparison.
4. Option interactions.
5. Commands run.
6. Whether the build passed.
