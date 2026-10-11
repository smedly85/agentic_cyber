<!-- SHARED BLOCK — harness addition, not part of the task description.
     Expand [AUTOMATION_NOTICE] below from prompts/_shared/automation_notice.md,
     verbatim and identically in all three templates. Do not inline the text
     here: one source, no drift. -->

[AUTOMATION_NOTICE]

# Task: Continue [PROGRAM]

Your previous session returned an implementation that did not pass validation.

Continue the current implementation in this working directory.

Do not restart the task. Do not revert to an earlier version. Do not redesign
work that already passes.

## Repair attempt

    [LOOP_NUMBER] of [MAX_LOOPS]

## Current state

Your implementation so far:

    [SOURCE_PATH]

This file is your own previous work, already on disk in this directory. It is
not a baseline and not a reference solution.

Read its contents supplied through Aider before changing it.

Treat the supplied validation feedback as actionable implementation requirements
under the original task's bounded contract. Address every reported failing case
and compiler diagnostic, not just the first. Use both the structured failures
and raw output to identify underlying defects and make actual source edits in
this invocation. Restating the problem or proposing future fixes is insufficient.

Make the changes needed to fix those defects while preserving already passing
behavior and all original requirements. Do not return an unchanged candidate
while known failures remain unless repair is genuinely impossible under the
task's constraints; in that case, state the specific constraint and blocker.

## Original task

The following is the original task, quoted unchanged. It remains the
specification.

Its headings are shown demoted, and its own validation and reporting sections
describe the original session, not this one. Where it conflicts with this
document, this document wins.

===== BEGIN QUOTED ORIGINAL TASK =====

[ORIGINAL_PROMPT]

===== END QUOTED ORIGINAL TASK =====

## Validation that failed

The controller ran the validation below after your previous session returned.

Build:

    exit [BUILD_EXIT_CODE]

Base tests:

    exit [BASE_TEST_EXIT_CODE]

Checkpoint tests:

    exit [FEATURE_TEST_EXIT_CODE]

### Failing tests

[STRUCTURED_FAILURES]

### Raw output

[RAW_OUTPUT_TAILS]

## Visible tests

The failures above come from the following visible tests:

    [TEST_DIR_PATHS]

Use any visible test contents supplied as read-only context through Aider while
repairing the task. Do not assume the listed paths provide independent tool access.

Do not modify, replace, weaken, disable, bypass, or delete any test.

Do not special-case individual test inputs. Fix the underlying behavior.

## Files

Modify only:

    [SOURCE_PATH]

Do not create or modify any other file.

## Build

The controller runs:

    [BUILD_COMMAND]

Fix all compiler errors and warnings.

## Grading

After this session returns, the controller will run:

    [VALIDATION_COMMANDS]

Do not perform an autonomous repair loop beyond this session. If validation
still fails, the controller will provide the new failure output in a subsequent
repair invocation.

Only the tests listed above are visible. Any hidden, comprehensive, or external
evaluation is controller-only, is not exposed here, and is not used as repair
feedback.

## Final response

Report:

1. What was failing and why.
2. What you changed.
3. Compiler diagnostics addressed; compilation is performed by the controller.
4. How the edits address every reported failure, and any unresolved blocker.
   Expected outcomes must not be reported as verified passes.
