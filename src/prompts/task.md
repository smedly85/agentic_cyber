Diversify one {{ language_name }} function while keeping the program's behaviour identical.

## Target
- Function: `{{ target_name }}` (defined in `{{ target_file }}`, line {{ target_line }})
- Call-graph depth from `main`: {{ target_depth }}
- The program (read-only) is in `/work/project`. Read anything you need there.

## What to do
Rewrite `{{ target_name }}` so it is **semantically equivalent** but **implemented differently**:
use a different algorithm, control flow, data representation, statement order or idioms.
Renaming locals or reformatting is not enough.

## The only file you may edit
`{{ function_file }}` — it currently contains the function's definition.
Everything you write in it replaces the original definition in `{{ target_file }}`.
Edits anywhere else are discarded.

## Rules
- Keep the signature **exactly** the same: name, parameter names and types, return type,
  qualifiers{% if language == "rust" %}, visibility, generics, lifetimes, where-clauses{% endif %} and attributes.
{% if allow_new_helpers %}- You MAY add new helper functions in the same file.{% else %}- Do NOT add new helper functions.{% endif %}
{% if allow_new_includes %}- You MAY add new {% if language == "rust" %}`use` declarations{% else %}`#include` directives{% endif %} in the same file (they are moved to the top of the source file).{% else %}- Do NOT add {% if language == "rust" %}`use` declarations{% else %}`#include` directives{% endif %}.{% endif %}
{% if allow_new_globals_types %}- You MAY add new global variables, constants or types in the same file.{% else %}- Do NOT add global variables, constants or types.{% endif %}
{% if language == "rust" and parent_kind != "module" %}- This function is a method: the file's contents are placed inside its `impl` block, so only associated items (methods, associated consts) are valid there.{% endif %}

## Checking your work
Run `agent-test`. It splices your file into a copy of the program, checks the signature and
additions, builds the program and runs the visible test suite, then prints a summary.
Keep iterating until `agent-test` passes, then finish with:
`echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
