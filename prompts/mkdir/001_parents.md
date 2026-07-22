# Task: Add -p to new_mkdir

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

new_mkdir creates each operand as a new directory. An operand fails if its
final component already exists, if a non-final path component is missing, or
if a non-final path component exists but is not a directory. A failed
operand does not stop the remaining operands from being attempted. Any
failure produces exit status 1; full success produces exit status 0 with no
output. new_mkdir does not read standard input.

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    -p
    --parents

Required behavior, when `-p`/`--parents` is given, for each operand:

- create every missing directory component of the operand's path, in order,
  including any missing intermediate components — not just the final one
- each newly created directory (intermediate or final) gets the same default
  mode as an operand created without `-p`: `0777` masked by the process
  umask
- if the operand's final component already exists as a directory, this is
  success (exit 0 contribution), not a failure — and its existing mode must
  not be changed
- if the operand's final component already exists but is not a directory
  (e.g. a regular file), that operand still fails
- if a non-final path component exists but is not a directory, that operand
  still fails

Without `-p`, behavior is unchanged from the current program.

## Reference

Use GNU Coreutils mkdir 9.4 as behavioral inspiration.

Implement the feature independently. Do not copy source code, comments,
algorithms, or implementation details from any reference program.

## Arguments

After this change, support:

    build/new_mkdir DIR...
    build/new_mkdir -p DIR...
    build/new_mkdir --parents DIR...

Repeated `-p`/`--parents` options are accepted and have the same effect as
one.

Reject unknown options and an invocation with no operands, exactly as
before. All error exits remain status 1.

## Interactions

`-p` only changes which directories get created and whether an
already-existing final directory is treated as success. It does not change
the default mode calculation (still umask-based in this checkpoint — `-m` is
not part of this checkpoint).

## Implementation

Use the existing language, structure, compiler settings, and error handling.
Modify the existing implementation. Do not call an external program to
implement the feature. Do not make unrelated changes.

## Build

Compile directly, without a Makefile:

    mkdir -p build
    cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_mkdir/new_mkdir.c -o build/new_mkdir

Fix all compiler errors and warnings.

## Visible tests

No checkpoint-visible base or `-p` test files are currently available for this
checkpoint. Accordingly, there is no visible test path or visible test command
to inspect or run for this task.

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
3. Implementation approach.
4. Commands run.
5. Whether the build passed.
