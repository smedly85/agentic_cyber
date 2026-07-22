# Task: Add [FEATURE] to [PROGRAM]

Modify the current implementation of [PROGRAM].

Add only the feature described here. Do not add unrelated behavior.

## Current program

Source:

    [SOURCE_PATH]

Program documentation:

    [README_PATH]

Executable:

    [EXECUTABLE_PATH]

Current behavior:

    [CURRENT_BEHAVIOR]

Preserve all current behavior unless this prompt explicitly changes it.

## New behavior

Add:

    [OPTION_OR_INTERFACE]

Required behavior:

    [FEATURE_BEHAVIOR]

## Reference

Use GNU Coreutils [UTILITY] 9.11 as behavioral inspiration.

Implement the feature independently.

Do not copy source code, comments, algorithms, or implementation details from
the reference program.

Only implement the behavior described in this prompt.

## Arguments

After this change, support:

    [SUPPORTED_ARGUMENTS]

Repeated options:

    [REPEATED_OPTION_RULE]

Combined short options:

    [COMBINED_OPTION_RULE]

Reject unknown options and unsupported operands.

On invalid arguments:

- write a short usage message to standard error
- write nothing to standard output
- exit with status 2

## Interactions

[FEATURE_INTERACTIONS]

## Limits

Keep these limits:

    [PROJECT_LIMITS]

Do not add:

    [UNSUPPORTED_BEHAVIOR]

## Implementation

Use the existing language, structure, compiler settings, and error handling.

Modify the existing implementation.

Do not call an external program to implement the feature.

Do not make unrelated changes.

## Build

Run:

    make clean
    make

Fix all compiler errors and warnings.

## Visible tests

The controller will evaluate this checkpoint using the following visible tests:

    [VISIBLE_TEST_PATHS]

These include the current checkpoint tests and the visible tests from every
earlier checkpoint, which are regression tests that must continue to pass.
Future-checkpoint tests are not part of this checkpoint's visible population.

You may inspect these visible tests while implementing the task.

Do not modify, replace, weaken, disable, bypass, or delete any visible test.

The controller will run:

    [VISIBLE_TEST_COMMAND]

after your implementation is returned.

Do not perform an autonomous repair loop. If validation fails, the experiment
controller will provide the failure output in a subsequent repair invocation.

Only the tests listed above are visible. Any hidden, comprehensive, or external
evaluation is controller-only, is not exposed here, and is not used as repair
feedback.

## Final response

Report:

1. Files changed.
2. Behavior added.
3. Implementation approach.
4. Commands run.
5. Whether the build passed.
