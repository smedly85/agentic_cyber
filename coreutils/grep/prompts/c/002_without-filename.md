# Task: Extend c_grep ? checkpoint 002

Modify the implementation validated at the previous checkpoint; preserve every earlier behavior.

Modify only `src/c_grep/c_grep.c`; executable: `build/c_grep`.

Implement exactly the cumulative bounded grep contract below. Do not add later options or unrestricted GNU grep behavior.

The first non-option operand is `PATTERN`; remaining operands are files. `PATTERN` is a fixed byte substring, never a regular expression. An empty pattern matches every line. Matching is case-sensitive. A bare `--` ends option parsing. With no file operands, search standard input; with operands, never read standard input. The filename `-` is deliberately an ordinary pathname, not standard input.

Input and files are arbitrary bytes. Newline byte `0x0A` delimits lines; NUL, carriage return, and invalid UTF-8 are ordinary data. A final unterminated line is a line, and every selected line is emitted once with a newline. Empty input emits nothing. Handle long lines and ordinary allocation/read/write failures without crashes.

Search file operands in command-line order. With one file, selected lines have no prefix; with two or more, prefix every selected line with the operand exactly as written plus `:`. This decision is made before searching and does not depend on matches or errors. Follow a symbolic link named directly as an operand. Missing, unreadable, or directory operands are diagnosed by name and later operands are still searched.

Exit 0 when at least one line was selected and no error occurred, 1 when no line was selected and no error occurred, and 2 when any usage, operand, allocation, or I/O error occurred, even if another operand matched. Successful stderr is empty; diagnostics go only to stderr. With no `PATTERN`, or with an unsupported option, reject before searching with empty stdout, a usage diagnostic, and status 2. Paths may contain arbitrary non-NUL bytes.

Add `-H` / `--with-filename`. It forces prefixes even for one file and for standard input; prefixed standard input is named `(standard input)`. Repetition is idempotent. Supported short options may be clustered, options may occur anywhere before `--`, and no later feature is accepted.

Add `-h` / `--no-filename`. It suppresses every filename prefix, including the default for multiple operands. `-H` and `-h` are independent overrides and the last occurrence wins across short, clustered, and long spellings. Repetition is idempotent.

## Implementation and validation

Use C11 and POSIX.1-2008 interfaces. The controller compiles with `cc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -pedantic -O2`. Handle size overflow and resource failures without undefined behavior. Preserve the semantic anchor `search_stream`: core line-selection behavior must be reachable from main through it. Choose all remaining structure and algorithms independently; do not add artificial helpers or target a call depth.

Do not copy GNU, BusyBox, legacy candidate, or other implementation source. Do not call or delegate to external utilities, subprocesses, shells, `system`, `popen`, exec/spawn APIs, or third-party libraries. Implement only this checkpoint's bounded surface.

The controller builds only inside pinned Linux Docker. The visible checkpoint bundle is `tests/c-grep-test-suite`; read only its supplied contents. It invokes `bash tests/c-grep-test-suite/judge_candidate.sh build/c_grep -H -h` inside Docker. Public tests are cumulative; independent held-out evaluation is controller-only and never repair feedback. Do not modify tests, prompts, or controller files. Do not compile or execute natively on the host.

Report files changed, behavior implemented, and unresolved constraints. Claim only validation actually performed by the controller.
