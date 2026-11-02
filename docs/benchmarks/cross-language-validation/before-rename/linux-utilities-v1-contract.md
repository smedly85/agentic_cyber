# Canonical Linux utilities contract v1

Status: prepared; Linux oracle validation pending. Normative language-neutral behaviors follow. Checkpoints are cumulative; prompts contain only the current and earlier contracts.

## cp

Accept SOURCE DEST or SOURCE... DIRECTORY. With several sources the last operand must be an existing directory; with one source and a directory destination, the effective destination is DIRECTORY/source-basename. Do not create missing destination parents. Validate invocation-wide errors before any filesystem changes. Process sources in operand order, diagnose per-source failures and continue; do not roll back completed operations. Preserve source data on failure.

Options may appear anywhere before the first `--`; thereafter all arguments are literal operands. Bare `-` is a filename. Preserve arbitrary non-NUL pathname bytes, including invalid UTF-8. Combined short options are outside scope. Missing operands, unknown options and invalid multi-source destinations produce empty stdout, a diagnostic on stderr and status 1. Successful operations have status 0, empty stdout and empty stderr except interactive prompts. All per-source failures contribute status 1. Exact error wording is unconstrained, but diagnostics must identify the affected operand.

Use ordinary rwx permissions and umask 022. Files contain arbitrary bytes. Fixtures contain regular files, directories and symlinks whose targets stay in the case tree. Special files, ownership preservation, ACLs, extended attributes, timestamps, sparse allocation, special permission bits and cross-filesystem moves are excluded. Do not bypass operating-system permission errors. Handle ordinary allocation and I/O errors without crashing.

Copy regular file contents without altering the source. Overwrite existing regular destinations; retain existing destination rwx bits. New files have source rwx bits masked by umask. Reject directory sources. Follow source symlinks to regular files and existing destination symlinks to regular files; reject dangling destination links. Reject self-copy, including filesystem aliases, before destructive changes. Missing/unreadable sources, unwritable destinations and incompatible types are errors.


### force

Add `-f` / `--force`, idempotently. A normally writable existing destination is overwritten in place, retaining its permissions. When normal opening fails for an existing nondirectory destination, force permits removing that entry and creating its replacement if parent permissions allow. The replacement receives source rwx bits masked by umask. Force does not bypass source or parent permissions or replace a directory with a file.

### interactive

Add `-i` / `--interactive`. Before overwriting an existing effective destination, prompt on stderr naming it and consume one line from stdin. Only an initial ASCII y or Y affirms; leading whitespace, empty input, EOF and other initials decline. Decline preserves the destination, contributes status 1 under GNU 9.11, and processing continues without an additional error. Do not prompt for a missing destination. Force and interactive are independent in either order: confirmation is required before a force replacement can occur.

### recursive

Add `-r` / `--recursive`. Directory sources now copy their descendants and empty directories. A missing destination becomes the tree root; an existing directory destination receives source-basename, merging existing directories there. New directories receive source rwx bits masked by umask; existing directories keep their bits. In recursive mode all source symlinks, including operand symlinks and dangling or cyclic links, are recreated with identical target bytes and are not traversed. Without recursive mode preserve earlier symlink behavior. Destination symlink collisions within a copied tree are excluded. Preserve force and interactive behavior for regular files. Reject incompatible types and copying a directory into itself or a descendant; an initial empty output directory may remain, but no descendants may be copied into it. Traversal order is not prescribed; cases with multiple interactive collisions in a recursive tree are excluded because GNU traversal order is filesystem-dependent. Resource limits must produce a diagnostic rather than looping or crashing.

## mv

Accept SOURCE DEST or SOURCE... DIRECTORY. With several sources the last operand must be an existing directory; with one source and a directory destination, the effective destination is DIRECTORY/source-basename. Do not create missing destination parents. Validate invocation-wide errors before any filesystem changes. Process sources in operand order, diagnose per-source failures and continue; do not roll back completed operations. Preserve source data on failure.

Options may appear anywhere before the first `--`; thereafter all arguments are literal operands. Bare `-` is a filename. Preserve arbitrary non-NUL pathname bytes, including invalid UTF-8. Combined short options are outside scope. Missing operands, unknown options and invalid multi-source destinations produce empty stdout, a diagnostic on stderr and status 1. Successful operations have status 0, empty stdout and empty stderr except interactive prompts. All per-source failures contribute status 1. Exact error wording is unconstrained, but diagnostics must identify the affected operand.

Use ordinary rwx permissions and umask 022. Files contain arbitrary bytes. Fixtures contain regular files, directories and symlinks whose targets stay in the case tree. Special files, ownership preservation, ACLs, extended attributes, timestamps, sparse allocation, special permission bits and cross-filesystem moves are excluded. Do not bypass operating-system permission errors. Handle ordinary allocation and I/O errors without crashing.

Move regular files, symlinks and directory trees on one filesystem. Preserve moved contents and modes. A successful move removes the old source name. Move a source symlink itself; replace a nondirectory destination symlink itself, without changing its target. Existing directory destinations select a source basename; replace an empty directory at that effective destination when GNU permits, but never merge trees into a nonempty destination. Diagnose identical source/destination, incompatible types, a directory moved into itself or its descendants, missing sources and parent-permission errors. Input is non-terminal; the base checkpoint does not prompt for write-protected destinations.


### force

Add `-f` / `--force`. Force suppresses overwrite confirmation, including for a write-protected destination, but does not bypass parent permissions or type constraints. Repetitions are idempotent. Preserve all base error behavior.

### interactive

Add `-i` / `--interactive`. Prompt on stderr naming an existing effective destination before replacement, and consume a line from stdin. Initial ASCII y or Y affirms; all other initials, leading whitespace, blank input and EOF decline. Decline leaves source and destination unchanged and contributes status 1 under GNU 9.11; continue later sources. No prompt for a missing destination. The LAST occurrence among force and interactive selects the overwrite policy, including mixed short and long forms: `-i -f` does not prompt and `-f -i` prompts. This precedence differs from cp.

## mkdir

Accept one or more directory operands. Create each named final directory; missing parents, existing entries (including directories), permission failures and incompatible path components are errors. Do not read stdin. Successful creation uses 0777 masked by the process umask. Exercise umasks 0000, 0022 and 0077. Process operands in order and continue after per-operand errors. Exit 0 only if all operands succeed, otherwise 1; stdout is empty, successful stderr is empty, and failures produce diagnostics identifying the operand. Diagnostics follow GNU 9.11 wording where the visible corpus asserts exact text, with program name `mkdir`.

Accept `--` as the option terminator; subsequent arguments, including dash-prefixed names, are literal operands. Bare `-` is an operand. Parse supported options before mutation, including options following operands. Unknown options and missing operands produce stderr and status 1. No other options are supported. Paths are byte strings, not necessarily UTF-8. Directory symlinks in parent components are traversed; do not replace symlinks or nondirectories. Permission, allocation and I/O failures must be diagnosed without crashing. Ownership, ACLs, SELinux, extended attributes and concurrent filesystem mutation are excluded.


### parents

Add `-p` / `--parents`, idempotently. Create missing path components. Existing directories, including a symlink resolving to a directory, succeed without permission changes. Existing nondirectories still fail. New intermediate parents have permissions (0777 masked by umask) with owner write and search permission ensured, as GNU mkdir -p requires. New final directories use the normal umask-derived mode. Repeated slashes, trailing slashes and dot components must retain normal pathname semantics.

### mode

Add `-m MODE`, `-mMODE`, `--mode MODE` and `--mode=MODE`. Last mode wins; parse and reject invalid or empty modes before creating operands, with `invalid mode` on stderr and status 1. Accept octal modes in the range 0000..7777, including special bits, and GNU symbolic mode clauses using u/g/o/a, +/−/= (ASCII minus in actual arguments), rwxXst and permission-copy u/g/o, with comma-separated clauses evaluated in order. Omitted who and conditional X follow GNU directory-mode semantics. Numeric modes are not masked by umask. Symbolic modes follow GNU 9.11 on Linux; in particular `+t` and `a+t` produce 01755, whereas `a=rwx,+t` and octal 1777 produce 01777. These are Linux reference requirements, not the Darwin 0777 departure assumption. Do not hardcode host-native Darwin behavior.

With parents enabled, mode applies only to newly created final directories. Existing directories and intermediate parents retain the parents-checkpoint behavior. The mode option does not chmod existing final directories.

## sort

Read only standard input. Records are arbitrary byte strings separated by newline, including empty records, NUL bytes and invalid UTF-8. Empty input produces empty output. A final nonempty unterminated record is still a record. Emit every output record followed by newline. Sort records in unsigned bytewise lexicographic ascending order in LC_ALL=C, preserving duplicates. Successful output has status 0 and empty stderr. Do not modify record contents.

There are no file operands, including `-`. A bare `--` ends option parsing but does not permit operands. Unknown options or any operands produce empty stdout, a usage diagnostic on stderr and status 2. Once supported, short options may be clustered, repeated options are idempotent and their order does not affect results. Handle long records and input/output/allocation errors without crashes; operational errors return 2 with stderr. Exclude locale-specific ordering, keys, numeric ordering, stable-sort options, merge mode, random order, obsolete key syntax, POSIXLY_CORRECT compatibility, output files, zero-delimited records and all other flags.


### reverse

Add `-r` / `--reverse`. Reverse the entire ordering comparison; duplicates remain and each record retains its bytes.

### ignore-case

Add `-f` / `--ignore-case`. Compare ASCII letters without regard to case, leaving other bytes unchanged. Equal folded keys are ordered by original bytes as GNU's last-resort comparison. Reverse, if selected, reverses both comparisons. Output preserves the original bytes.

### unique

Add `-u` / `--unique`. Output one representative per equal comparison-key group: byte-identical equality normally, ASCII case-insensitive equality with ignore-case. The retained representative is the first record in input order, including in reverse mode. With uniqueness enabled the original-byte last-resort comparison does not split a folded-equal group or select its representative. No particular sorting or deduplication algorithm is required.

### check

Add `-c` / `--check`. Check input order without emitting output. Ordered input, empty input and a single record return 0 with empty stderr. At the first ordering violation return 1 and emit a diagnostic identifying the line; exact wording is not prescribed. Invalid arguments and operational failures still return 2. Compare using the same GNU ordering selected for ordinary output: reverse affects direction, ignore-case uses folded keys with the original-byte last-resort comparison unless unique disables it. With unique, equal adjacent keys are also a violation. Without unique, equal adjacent records are allowed. Do not implement other check aliases or `--check=WORD`.
