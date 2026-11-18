# Task: Extend c_sort — checkpoint 003

Inherit only the previous validated implementation from this same lineage. Preserve all behavior established at earlier checkpoints.

Modify only `src/c_sort/c_sort.c`; executable: `build/c_sort`.

Read only standard input. Records are arbitrary byte strings separated by newline, including empty records, NUL bytes and invalid UTF-8. Empty input produces empty output. A final nonempty unterminated record is still a record. Emit every output record followed by newline. Sort records in unsigned bytewise lexicographic ascending order in LC_ALL=C, preserving duplicates. Successful output has status 0 and empty stderr. Do not modify record contents.

There are no file operands, including `-`. A bare `--` ends option parsing but does not permit operands. Unknown options or any operands produce empty stdout, a usage diagnostic on stderr and status 2. Once supported, short options may be clustered, repeated options are idempotent and their order does not affect results. Handle long records and input/output/allocation errors without crashes; operational errors return 2 with stderr. Exclude locale-specific ordering, keys, numeric ordering, stable-sort options, merge mode, random order, obsolete key syntax, POSIXLY_CORRECT compatibility, output files, zero-delimited records and all other flags.

## Cumulative checkpoint behavior

Add `-r` / `--reverse`. Reverse the entire ordering comparison; duplicates remain and each record retains its bytes.

Add `-f` / `--ignore-case`. Compare ASCII letters without regard to case, leaving other bytes unchanged. Equal folded keys are ordered by original bytes as GNU's last-resort comparison. Reverse, if selected, reverses both comparisons. Output preserves the original bytes.

Add `-u` / `--unique`. Output one representative per equal comparison-key group: byte-identical equality normally, ASCII case-insensitive equality with ignore-case. The retained representative is the first record in input order, including in reverse mode. With uniqueness enabled the original-byte last-resort comparison does not split a folded-equal group or select its representative. No particular sorting or deduplication algorithm is required.

## Implementation and validation

Use C11 and POSIX.1-2008 library interfaces. Choose the internal architecture and algorithms independently. Do not copy GNU or other implementations, delegate functionality to external utilities, launch subprocesses, or link third-party libraries. Do not add flags or functionality beyond this checkpoint. Handle resource failures without undefined behavior.

The controller builds inside Linux Docker with:

    cc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pedantic -O2 src/c_sort/c_sort.c -o build/c_sort

The visible checkpoint bundle is `tests/c-sort-test-suite`. Read only its supplied contents. The controller invokes, inside Linux Docker:

    bash tests/c-sort-test-suite/judge_candidate.sh build/c_sort -r -f -u

All visible tests are cumulative. Do not modify, replace, weaken, disable or delete tests, prompts or controller files. Do not perform an autonomous repair loop; the controller owns compilation and validation. Hidden evaluation is separate, never available to you and never supplied as repair feedback. Do not compile or execute natively on the host.

Report files changed, behavior implemented and unresolved constraints. Claim only validation actually performed by the controller.
