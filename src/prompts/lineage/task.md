{{ message }}

---
## How this session works
This section supersedes any "session conditions" above that describe Aider: here you are an agent
with a bash tool, and you can and should inspect files and run commands.
- You are in `/work`, a private copy of the task workspace. The only file whose contents are kept
  is `{{ source_path }}`{% if source_exists %} (it currently holds the implementation to extend){% else %} (it does not exist yet: create it){% endif %}.
  Changes to any other file are discarded.
{% if read_files %}- Read-only context files in `/work`:
{% for f in read_files %}  - `{{ f }}`
{% endfor %}{% endif %}- The visible tests' judge scripts need the controller's Docker sandbox and cannot run here.
  After you finish, the controller builds your source with the official command and runs the tests;
  if they fail you get a new session with the failures.
{% if check_command %}- `{{ check_command }}` compiles `{{ source_path }}` with the benchmark's compiler flags
  (a local approximation of the official build) so you can catch build errors early.
{% endif %}- This session is limited to about {{ time_limit_minutes }} minutes. Submit as soon as the implementation is
  complete rather than polishing it; if time runs out, the file as it stands is still validated.
- When `{{ source_path }}` is complete, finish with:
  `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
