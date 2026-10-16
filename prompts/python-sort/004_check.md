# Task: python-sort checkpoint 004 (check)

Modify only `src/python-sort/new_sort.py`.
Inherit the preceding candidate from this same lineage; preserve all earlier behavior.
The controller launcher is `build/new_sort.py`.

## Complete cumulative behavior

Read newline-delimited records from standard input only. Sort ascending by
unsigned bytes, independently of locale. Exclude the newline delimiter from
comparisons. Preserve duplicate records and all other bytes, including NUL,
carriage returns and invalid UTF-8. Do not decode input as text or use Unicode
case folding. Support empty input, empty records, prefixes, spaces, long records
and a final record without a newline. Add a newline after each output record;
empty input produces no output. Use binary stdin/stdout. Exit 0 on success.

Support -r and --reverse: reverse the complete ordering comparison. Repetition
is idempotent; it never toggles the option off.

Support -f and --ignore-case: map ASCII a-z to A-Z for comparison only, leaving
all other bytes unchanged. If folded records compare equal, compare their
original bytes as a secondary key. Reverse applies to the complete comparison,
including this tie-break. Never modify the bytes written to stdout.

Support -u and --unique: output one representative per equal group. Without
ignore-case, equality means identical bytes. With ignore-case, equality uses
folded bytes and disables the original-byte tie-break. Retain the FIRST INPUT
record of each equal group, regardless of reverse. For input abc then ABC,
ignore-case plus unique retains abc; the opposite input order retains ABC.
Reverse changes group order, never the retained representative.

Support -c and --check: check adjacent input records without sorting or emitting
stdout. Use the ordering selected by the other options. Empty/single-record and
ordered input exit 0 with empty stderr. At the first disorder, exit 1 with a
concise stderr diagnostic identifying the input and offending record number.
Without unique, equal adjacent records are allowed; ignore-case still uses the
original-byte tie-break. With unique, require strict ordering under the unique
equality rule: duplicate groups (including case-folded equals) fail. Reverse
checks descending order. Check takes precedence over producing sorted output,
independent of option order. Do not implement additional check forms.

## Arguments and errors

Accept only the short options and exact long aliases stated above. Combine short
options in any order; repeated options are idempotent. Option order does not
change their interactions.
Reject every other argument, including file operands, a bare -, --, unknown
options, long-option abbreviations and attached option values. Parse arguments
before reading input. Invalid arguments require status 2, empty stdout and a
concise stderr usage diagnostic. This is the C ladder's bounded stdin-only
interface, not GNU's broader file/option interface.
Report input/output/resource failures on stderr with status 2 and no uncaught
traceback. Detect buffered output failures, including flush errors. Exact error
wording is not prescribed. Never print diagnostics on stdout.

## Implementation and reference

Use standalone Python 3.11+ with a Python 3 shebang and main entry point, standard
library only. GNU Coreutils 9.11 sort in LC_ALL=C is the functional oracle within
this bounded scope. Formal validation requires Darwin; BSD sort is not a substitute.
Implement independently. Python's built-in sorting is allowed. Do not delegate to
system sort, GNU sort, uniq, subprocesses, shells, os.system, popen, exec/spawn,
ctypes or external sorting implementations. Do not copy reference implementation code.
Require the canonical semantic anchor `sort_lines`: the core sorting/checking
behavior must be reachable from main through it. Choose other structure naturally.
Do not implement future features or options outside the current checkpoint.

## Files and validation

Edit only `src/python-sort/new_sort.py`. Do not provide or change any other file.
The controller checks nonempty source and Python syntax without executing it,
then creates an interpreter-pinned disposable launcher with the selected PYTHON_BIN.
Syntax failures enter the existing repair loop. The controller runs:

    tests/python-sort-test-suite/judge_candidate.sh build/new_sort.py -r -f -u -c

All applicable public cases are cumulative regression coverage. Do not change,
weaken, bypass or special-case tests. The controller owns validation and repair;
do not run an autonomous repair loop. Held-out evaluation runs separately after
repair and is never repair feedback. Report actual edits and implemented behavior;
do not claim validation you did not perform.
