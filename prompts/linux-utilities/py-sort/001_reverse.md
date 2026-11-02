# Task: Extend py_sort — checkpoint 001

Inherit only the previous validated implementation from this same lineage. Preserve all behavior established at earlier checkpoints.

Modify only `src/py_sort/py_sort.py`; executable: `build/py_sort.py`.

Read only standard input. Records are arbitrary byte strings separated by newline, including empty records, NUL bytes and invalid UTF-8. Empty input produces empty output. A final nonempty unterminated record is still a record. Emit every output record followed by newline. Sort records in unsigned bytewise lexicographic ascending order in LC_ALL=C, preserving duplicates. Successful output has status 0 and empty stderr. Do not modify record contents.

There are no file operands, including `-`. A bare `--` ends option parsing but does not permit operands. Unknown options or any operands produce empty stdout, a usage diagnostic on stderr and status 2. Once supported, short options may be clustered, repeated options are idempotent and their order does not affect results. Handle long records and input/output/allocation errors without crashes; operational errors return 2 with stderr. Exclude locale-specific ordering, keys, numeric ordering, stable-sort options, merge mode, random order, obsolete key syntax, POSIXLY_CORRECT compatibility, output files, zero-delimited records and all other flags.

## Cumulative checkpoint behavior

Add `-r` / `--reverse`. Reverse the entire ordering comparison; duplicates remain and each record retains its bytes.

## Implementation and validation

Use a standalone Python 3.12.8 program with a Python 3 shebang and main entry point, standard library only. Choose the internal architecture and algorithms independently. Do not copy implementations or delegate functionality through external utilities, subprocesses, shells, os.system, popen, exec/spawn or ctypes. Do not add flags or functionality beyond this checkpoint. Preserve arbitrary pathname and file bytes and handle ordinary errors without uncaught tracebacks. The controller verifies nonempty source and compiles it in memory without executing it; execution uses the pinned Python interpreter inside the isolated Linux case container, not a host launcher. Preserve the established Python semantic anchor `sort_lines`: core sorting/checking behavior must be reachable from main through it. Choose remaining structure freely.

The controller builds inside Linux Docker with:

    python3 "$HELDOUT_ROOT/scripts/docker_benchmark.py" build --utility py-sort

The visible checkpoint bundle is `tests/py-sort-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/py-sort-test-suite/judge_candidate.sh build/py_sort.py -r

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
