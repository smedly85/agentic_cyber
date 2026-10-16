# Task: python-sort checkpoint 000 (base)

Create only `src/python-sort/new_sort.py`.
There is intentionally no starter candidate; begin with an absent source file.
The controller launcher is `build/new_sort.py`.

## Complete cumulative behavior

Read newline-delimited records from standard input only. Sort ascending by
unsigned bytes, independently of locale. Exclude the newline delimiter from
comparisons. Preserve duplicate records and all other bytes, including NUL,
carriage returns and invalid UTF-8. Do not decode input as text or use Unicode
case folding. Support empty input, empty records, prefixes, spaces, long records
and a final record without a newline. Add a newline after each output record;
empty input produces no output. Use binary stdin/stdout. Exit 0 on success.

No feature options are supported at this checkpoint.

## Arguments and errors

Accept no arguments at checkpoint 000.
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

    tests/python-sort-test-suite/judge_candidate.sh build/new_sort.py 

All applicable public cases are cumulative regression coverage. Do not change,
weaken, bypass or special-case tests. The controller owns validation and repair;
do not run an autonomous repair loop. Held-out evaluation runs separately after
repair and is never repair feedback. Report actual edits and implemented behavior;
do not claim validation you did not perform.
