<!-- ===================================================================
     SHARED PROMPT BLOCK — HARNESS OPERATING INSTRUCTIONS
     ===================================================================

     This file is the single source of the automation notice that every
     checkpoint and repair template carries. It is a DELIBERATE ADDITION by
     the experiment harness, not part of any utility's task description: it
     says nothing about what to implement, only about how the session is run.

     The experimental design holds the prompt constant across every
     checkpoint and every lineage. This block is part of that constant, so
     it lives in one file and is referenced by every template through the
     [AUTOMATION_NOTICE] placeholder. Do not paste its text into a template;
     three copies would drift and the "held constant" claim would quietly
     stop being true.

     Templates that must carry it:
       prompts/checkpoint_base_template.md
       prompts/checkpoint_feature_template.md
       prompts/repair_continuation_template.md

     Changing the wording below changes an experimental condition. Treat it
     the way a temperature change is treated: it is a new configuration, not
     a fix, and results produced under the old wording are not comparable to
     results produced under the new one.
     =================================================================== -->

## Session conditions

This session is fully automated and non-interactive.

No user is available to answer questions. A clarifying question ends the
session without an implementation, which is recorded as a failed attempt.

If a requirement is ambiguous or underspecified, choose the most reasonable
interpretation consistent with the rest of this prompt and proceed. State the
interpretation you chose in your final response.

Begin by inspecting the repository and then implement the change. Do not
produce an extended plan, a survey of alternatives, or exploratory commentary
before acting; any reasoning you need should be in service of an edit you are
about to make.

Nothing in this section changes what the program must do. The task,
its scope, and the validation that follows are defined by the rest of this
prompt.
