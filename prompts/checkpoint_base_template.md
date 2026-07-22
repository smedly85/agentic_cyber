# Task: Create the initial [PROGRAM] utility

Create a small [LANGUAGE] command-line program named:

    [PROGRAM]

The compiled executable must be:

    [EXECUTABLE_PATH]

Implement only the behavior described in this prompt.

Do not add options, file operands, or unrelated features beyond what is listed here.

## Program behavior

[PROGRAM_BEHAVIOR]

## Arguments

[ARGUMENTS_CONTRACT]

On invalid arguments:

    [INVALID_ARGUMENT_BEHAVIOR]

## Reference

[REFERENCE_NOTE]

Implement the behavior independently.

Do not copy source code, comments, algorithms, or implementation details from any
reference program.

## Error handling

[ERROR_CONTRACT]

## Implementation

[IMPLEMENTATION_CONSTRAINTS]

## Files

Create only:

    [FILES_TO_CREATE]

Do not create or modify any other file.

## Build

The build must support:

    [BUILD_COMMANDS]

Compile with:

    [COMPILER_SETTINGS]

Fix all compiler errors and warnings.

## Visible tests

The controller will evaluate this checkpoint using the following visible tests:

    [VISIBLE_TEST_PATHS]

These are the base tests for checkpoint 000. Later checkpoints must include
these tests as regression coverage together with each checkpoint's own visible
tests. Future-checkpoint tests are not part of this checkpoint's visible
population.

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

1. Files created or changed.
2. Program behavior implemented.
3. Build commands run.
4. Commands run.


