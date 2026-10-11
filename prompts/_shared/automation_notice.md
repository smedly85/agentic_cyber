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

This is a fully automated, non-interactive implementation task in Aider.
The editable source and selected read-only files are supplied through Aider.
Use the supplied contents; a path mentioned in the prompt does not mean you
can independently open it. Do not promise or claim to inspect files, search
the repository, or run commands using tools unavailable in this session.

No user is available to answer questions or approve work. Do not ask questions,
request approval, defer implementation, or finish with a proposed plan or an
offer to continue. Produce concrete implementation instructions and source
edits during the current invocation, within the allowed file scope.

If a requirement is ambiguous or underspecified, choose the most reasonable
interpretation consistent with the rest of this prompt and proceed. State the
interpretation you chose in your final response.

Every requirement in the supplied checkpoint prompt is mandatory within its
stated scope. "Base checkpoint" and "no options" do not mean illustrative or
minimal demonstration functionality: implement the complete specified baseline.
Later checkpoints add only their specified features; do not defer current
requirements to them or implement future checkpoint flags early.

In architect/editor mode, the architect must give the editor complete, concrete
implementation instructions covering all required behavior, argument handling,
filesystem semantics, safeguards, errors and exit status. The editor must apply
the corresponding source edits now. Do not substitute exploratory commentary,
repeated reconsideration, or a partial feature sketch for this handoff.

The controller handles compilation, validation, and subsequent repair
invocations. Build and validation commands in the task describe that controller
workflow; do not claim to have run them. Correct reported compiler errors and
warnings in the source. Do not wait for another invocation to implement known
requirements or run an autonomous validation/repair loop. Keep any completion
report brief and factual, describing actual edits and unresolved constraints
without conversational closing language. This session rule does not suppress
confirmation prompts that the implemented utility is explicitly required to emit.

Nothing in this section changes what the program must do. The task,
its scope, and the validation that follows are defined by the rest of this
prompt.
