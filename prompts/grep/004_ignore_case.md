# Task: Add -i to new_grep

Modify:

    src/new_grep/new_grep.c

The executable must remain:

    build/new_grep

Add only the feature described here. Do not add unrelated behavior.

## Current program

Source:

    src/new_grep/new_grep.c

Executable:

    build/new_grep

Behavior already implemented:

new_grep takes a fixed byte-string `PATTERN` as its first operand and writes
every input line containing that string, case-sensitively, to standard output.
With no file operands it searches standard input; otherwise it searches each
operand in order. `-` is an ordinary name and `--` ends option processing.
`-H` / `--with-filename` forces the `NAME:` prefix on and `-h` / `--no-filename`
forces it off, the last of the two on the command line winning; with neither,
lines are prefixed when there are two or more file operands, or when `-r` is
given and an operand is a directory. Under a forced prefix, standard input is
named `(standard input)`. `-r` / `--recursive` searches directory operands in
pre-order with entries in ascending byte order of name, skipping symbolic links
found during traversal. Missing, unreadable, and (without `-r`) directory
operands are diagnosed errors that do not stop the remaining operands. Exit
status is 0 when a line was selected, 1 when none was, and 2 when any error
occurred.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -i
    --ignore-case

With `-i`, a line matches when `PATTERN` occurs in it as a contiguous run of
bytes **after case folding both the pattern and the line**.

### Folding rule

Folding is ASCII-only and locale-independent:

- the 26 bytes `A`–`Z` (`0x41`–`0x5A`) fold to `a`–`z`
- **every other byte is left exactly as it is**

In particular:

- bytes `>= 0x80` are never folded, so UTF-8 sequences are never altered and a
  pattern like `COLE` does not match `École` written in UTF-8
- non-letter ASCII is never folded. A fold written as `byte | 0x20` would map
  `[` to `{` and `]` to `}`; that is wrong. `-i [ABC]` must match the line
  `[abc]` and must **not** match the line `{abc}`
- NUL bytes and other control bytes pass through folding unchanged, and lines
  containing them are still matched normally

Do not use `tolower()` without ensuring locale independence, and do not assume
the input is valid UTF-8.

### What does not change

`-i` affects matching only. The **bytes written to standard output are the
original input bytes**, never the folded ones. Line order, prefixing, exit
status, and the diagnosed conditions are all unchanged.

An empty `PATTERN` still matches every line, with or without `-i`.

## Reference

Use BusyBox grep and GNU grep as behavioral inspiration for `-i`'s meaning, with
the ASCII-only folding rule above taking precedence where a locale-aware
implementation would differ.

Implement the feature independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Arguments

After this change, support:

    build/new_grep [-H|-h] [-r] [-i] PATTERN
    build/new_grep [-H|-h] [-r] [-i] PATTERN FILE_OR_DIR...
    build/new_grep --ignore-case PATTERN

Short options may be combined:

    -iH
    -ih
    -ri
    -rhi

Repeated options are accepted and idempotent:

    -i -i
    --ignore-case --ignore-case

Options may appear before or between operands, and `--` still ends option
processing. Option order does not change behavior, except for the existing
last-one-wins rule between `-H` and `-h`.

Unknown options are still rejected with a usage message on standard error,
nothing on standard output, and exit status 2.

Do not add other options.

## Requirements

Preserve:

- fixed-string matching: `PATTERN` is never a regular expression, with or
  without `-i`
- case-sensitive matching when `-i` is absent
- standard-input searching when there are no file operands
- byte-oriented line handling, including NUL bytes and invalid UTF-8
- a final line without a newline
- `-H` / `-h` last-one-wins, and the `-r` traversal and prefix rules
- per-operand error reporting and the 0 / 1 / 2 exit statuses

## Implementation

Use the existing C11 structure, compiler settings, and error handling. Modify
the existing implementation.

Fold the pattern once, not once per line. Do not call an external program. Do
not make unrelated changes.

## Build

Compile directly, without a Makefile:

    mkdir -p build
    cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_grep/new_grep.c -o build/new_grep

Fix all compiler errors and warnings.

## Visible tests

The command-specific test suite is copied into your working directory at:

    tests/grep-test-suite/

You may read anything in it while implementing the task.

The controller will judge this checkpoint by running exactly:

    tests/grep-test-suite/judge_candidate.sh build/new_grep -H -h -r -i

That command runs every frozen case whose required flags are all named on the
command line, so it covers the `-i` feature added here **and** the base, `-H`,
`-h` and `-r` behavior from the earlier checkpoints as regression coverage. All
of it must pass.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/grep-test-suite/`. Test tampering is detected and recorded.

The experiment controller owns validation and any repair iterations. Do not
perform an autonomous repair loop. If validation fails, the controller will
provide the failure output in a subsequent repair invocation. Any hidden,
comprehensive, or sanitizer evaluation is controller-only, is not exposed here,
and is never used as repair feedback.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. The folding rule and where it is applied.
4. Commands run.
5. Whether the build passed.
