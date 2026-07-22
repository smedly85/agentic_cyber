# Task: Add -m to new_mkdir

Modify:

    src/new_mkdir/new_mkdir.c

The executable must remain:

    build/new_mkdir

Add only the feature described here. Do not add unrelated behavior.

## Current program

Source:

    src/new_mkdir/new_mkdir.c

Program documentation:

    src/new_mkdir/README.md

Executable:

    build/new_mkdir

Current behavior:

new_mkdir creates each operand as a new directory, with `-p`/`--parents`
optionally creating missing intermediate directories and making an
already-existing final directory a success rather than a failure. Every
newly created directory currently gets mode `0777` masked by the process
umask. new_mkdir does not read standard input.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -m MODE
    --mode=MODE
    --mode MODE

`MODE` is accepted in two forms:

1. **Octal form**: a string of octal digits (e.g. `755`, `0700`, `1777`),
   interpreted as an absolute permission-bits value (including the setuid,
   setgid, and sticky bits when present), applied directly with no umask
   masking.
2. **Symbolic form**: one or more comma-separated clauses of the form
   `[ugoa...][+-=][rwxXst...]`, following POSIX/chmod symbolic-mode syntax:
   - the target-class letters are any combination of `u` (owner), `g`
     (group), `o` (other), `a` (all); if no class letters are given before
     the operator, the clause applies to all classes as if `a` were given
   - the operator is exactly one of `+` (add these permissions), `-` (remove
     these permissions), or `=` (set exactly these permissions, clearing any
     unmentioned bits for the affected classes)
   - the permission letters after the operator are any combination of `r`,
     `w`, `x` (or `X`, meaning `x` only if the entry is a directory — which
     it always is here), `s` (setuid/setgid, depending on class), and `t`
     (sticky), and may be empty (e.g. `o=` clears all "other" bits)
   - multiple comma-separated clauses apply in order, left to right
   - symbolic clauses start from an assumed base of full permissions
     (`0777`, i.e. `rwxrwxrwx`) before any clause is applied — not from the
     umask-derived default

When `-m`/`--mode` is given, the resulting mode of every directory it
applies to (see below) is exactly the computed value from `MODE` — the
process umask plays no role at all in that computation.

**Interaction with `-p`:** when `-p` and `-m` are both given, `-m`'s
computed mode applies **only to the final directory of each operand's
path** (the one actually named by the operand). Any intermediate
directories created along the way by `-p` still get the ordinary umask-based
default mode (`0777` masked by umask), exactly as `-p` alone would produce.
`-m` never affects intermediate directories, even when they are newly
created in the same invocation.

Without `-p`, `-m` applies to the (single, final) directory each operand
creates, as usual — there are no intermediates to consider.

If `MODE` is not a valid octal or symbolic mode string (including an empty
string), that is an immediate failure before any operand is attempted: write
a diagnostic to standard error containing the text `invalid mode`, write
nothing to standard output, and exit with status 1.

## Reference

Use GNU Coreutils mkdir 9.4 as behavioral inspiration for exit codes,
mode-string parsing conventions, and the `-p`+`-m` intermediate-directory
interaction described above.

Implement the feature independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Arguments

After this change, support:

    build/new_mkdir -m MODE DIR...
    build/new_mkdir --mode=MODE DIR...
    build/new_mkdir --mode MODE DIR...
    build/new_mkdir -p -m MODE DIR...

Repeated `-m`/`--mode` options are accepted; the last one given wins.

`-p`, `-v`-style combined short options are not required in this checkpoint
(no `-v` exists yet) — only `-p` and `-m` need to be usable together (in
either order) and independently.

Reject unknown options, an invalid `MODE` value, and an invocation with no
operands, exactly as before. All error exits remain status 1.

## Implementation

Use the existing language, structure, compiler settings, and error handling.
Modify the existing implementation. Do not call an external program (e.g.
`chmod`) to implement the feature. Do not make unrelated changes.

## Build

Compile directly, without a Makefile:

    mkdir -p build
    cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_mkdir/new_mkdir.c -o build/new_mkdir

Fix all compiler errors and warnings.

## Visible tests

No checkpoint-visible base, `-p`, or `-m` test files are currently available
for this checkpoint. Accordingly, there is no visible test path or visible test
command to inspect or run for this task.

Do not use or inspect any hidden, comprehensive, or external evaluator.
Do not modify, replace, weaken, disable, bypass, or delete any repository test.

The experiment controller owns validation and any repair iterations.
Do not perform an autonomous repair loop. If checkpoint-visible validation is
added later and fails, the controller may provide its failure output in a
subsequent repair invocation. Output from a hidden, comprehensive, or external
evaluator is never repair feedback.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. Mode-parsing approach (octal and symbolic).
4. Interaction with `-p`.
5. Commands run.
6. Whether the build passed.
