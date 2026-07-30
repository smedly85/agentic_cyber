# Task: Create the initial new_grep utility

Create a small C command-line program named:

    new_grep

The compiled executable must be:

    build/new_grep

Implement only the behavior described in this prompt. Do not implement any
command-line option in this checkpoint — that happens in later checkpoints.

## Program behavior

new_grep selects the lines of its input that contain a pattern, and writes them
to standard output.

### Pattern matching

The first operand is `PATTERN`. **`PATTERN` is a fixed byte string, not a
regular expression.** A line matches when `PATTERN` occurs in it as a contiguous
run of bytes. Characters such as `.`, `*`, `[`, `]`, `^` and `$` have no special
meaning: they match themselves and nothing else.

An empty `PATTERN` matches every line.

Matching is case-sensitive in this checkpoint.

A line that contains `PATTERN` more than once is still selected exactly once and
written exactly once.

### Lines

Input is a byte stream delimited by newline (`0x0A`) bytes. A line is the bytes
between delimiters, not including the delimiter.

- A trailing newline at the end of the input does not create an extra empty
  line.
- A final line that is not terminated by a newline is still a line.
- Every line written to standard output ends with a newline, including a final
  line that had none in the input.
- Carriage returns are ordinary data: `needle\r` is a line whose bytes include
  the `\r`, and the `\r` is written back out.
- Any byte other than the newline delimiter is ordinary data, including NUL
  bytes and byte sequences that are not valid UTF-8. There is no "binary file"
  detection and no suppression of matches in binary input.

Lines may be of any practical length; use dynamic memory rather than a
fixed-size line buffer.

### Standard input

If there are no file operands after `PATTERN`, new_grep searches standard input.

If there is at least one file operand, standard input is not read at all.

### File operands

Every operand after `PATTERN` is a pathname to search, in the order given.

- `-` is **not** special. It names a file called `-`, and is an error if no such
  file exists.
- `--` ends option processing. Every argument after it is an operand, even one
  that begins with `-`.

For each operand, in order:

- if it names a readable regular file (or a symbolic link that resolves to one —
  an operand naming a symlink is opened through it), search it
- if it does not exist, or cannot be opened or read, that operand is an error:
  write a diagnostic to standard error naming the operand, and continue with the
  remaining operands
- if it names a directory, that operand is an error in this checkpoint (there is
  no recursive search yet): write a diagnostic to standard error naming the
  operand, and continue with the remaining operands

An error on one operand never abandons the operands that follow it, and never
discards the lines already written.

### Filename prefixes

When a line is written with a filename prefix, the output for that line is the
name **exactly as given on the command line**, then a single `:` byte, then the
line's bytes, then a newline:

    a.txt:alpha

Whether prefixes are written is decided once, before any output, from the
command line alone:

- with **two or more** file operands, every selected line is prefixed
- with exactly one file operand, no line is prefixed
- when standard input is searched, no line is prefixed

The decision does not depend on which operands turn out to match, or even on
whether they exist.

A line whose own bytes contain a `:` is not treated specially; the prefix is
simply prepended.

### Exit status

new_grep exits with:

- `0` — at least one line was selected and no error occurred
- `1` — no line was selected and no error occurred
- `2` — an error occurred, **regardless of whether any line was selected**

Error status wins over match status: a run that selected lines from one operand
and failed to open another exits `2`.

### Standard output and standard error

Selected lines go to standard output and nothing else does. Diagnostics go to
standard error and nothing else does. A diagnostic must name the operand it is
about; its exact wording is yours.

## Arguments

new_grep in this checkpoint accepts:

    build/new_grep PATTERN
    build/new_grep PATTERN FILE...
    build/new_grep -- PATTERN FILE...

new_grep accepts no options in this checkpoint. Any argument that begins with
`-`, other than a bare `-` (an operand) and `--` (the terminator), is an unknown
option.

Reject, before anything is searched:

- an unknown option, short or long
- an invocation with no arguments at all (no `PATTERN`)

On either, write a short usage message to standard error, write nothing to
standard output, and exit with status `2`.

## Reference

Use BusyBox grep and GNU grep as behavioral inspiration for exit-status
semantics and diagnostic classification only. This program is deliberately much
smaller than either: fixed-string matching, no regular expressions, and only the
options listed above.

Implement the behavior independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Error handling

Detect and report, each as a per-operand error (status 2, continue with the
remaining operands):

- an operand that does not exist
- an operand that cannot be opened or read (for example, no read permission)
- an operand that is a directory

Detect and report, each as an immediate failure before anything is searched
(status 2):

- an unrecognized option
- no `PATTERN`

Also detect and report memory-allocation failures, allocation-size overflow, and
write errors on standard output, each with a concise diagnostic on standard
error and a nonzero exit status.

Do not write partial diagnostics to standard output.

## Implementation

Use C11 and POSIX-compatible behavior.

Keep these responsibilities separate where practical: argument parsing, reading
a line, deciding whether a line matches, and writing a selected line.

Do not use:

- a fixed-size line buffer
- `system()` or `popen()`
- an external grep, or any other external program
- third-party libraries
- functions that assume the data is a NUL-terminated string when it may contain
  NUL bytes

Do not replace byte-oriented input with text-only or UTF-8-specific logic.

## Files

Create only:

    src/new_grep/new_grep.c

Do not create or modify any other file (no Makefile, no README, no .gitignore,
nothing else).

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

    tests/grep-test-suite/judge_candidate.sh build/new_grep

That command runs every frozen case whose required flags are all named on the
command line. With no flags named, it runs the base-behavior cases this
checkpoint is responsible for; later checkpoints re-run them as regression
coverage.

Do not modify, replace, weaken, disable, bypass, or delete any file under
`tests/grep-test-suite/`. Test tampering is detected and recorded.

The experiment controller owns validation and any repair iterations. Do not
perform an autonomous repair loop. If validation fails, the controller will
provide the failure output in a subsequent repair invocation. Any hidden,
comprehensive, or sanitizer evaluation is controller-only, is not exposed here,
and is never used as repair feedback.

## Final response

Report:

1. File created.
2. Program behavior implemented.
3. Exit-status rules.
4. Build command run.
5. Commands run.
