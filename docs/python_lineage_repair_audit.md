# Python lineage repair audit

This audit uses repository source and the operator's Vessel observations. No
Vessel access, saved run retrieval, model inference, or formal rerun was performed.
The historical results, task specifications, formal repair template, models,
sampling settings, budgets, and frozen goldens are unchanged.

## Confirmed causes and patch

* `scripts/run_experiment.sh`, `run_aider`: the first pipeline status already
  preserves Aider/timeout's exit code separately from `tee`. This was correct;
  exit 124 is never rewritten. The log parser in `scripts/aider_output.py`
  identifies explicit protocol failures; it does not establish an editor handoff
  from exit 0. The controller now also records the literal `Applied edit to ...`
  diagnostic. This is a log observation, not proof of handoff or net source change.
* The generate/validate loop formerly checked only `-s "$workdir/$SOURCE_PATH"`
  to admit a timeout to the candidate-recovery branch. A repair inherits a
  nonempty file, so this could credit a timeout that produced no new work.
  The controller now hashes immediately around each invocation and requires
  changed, nonempty source for that branch. An unchanged timeout is still
  independently revalidated for observation, but cannot produce a successful
  invocation outcome. It is not reclassified as infrastructure failure.
* The stopping order is execution failure, success, budget exhaustion, then
  no progress. Budget exhaustion therefore masks no progress in the primary
  reason on the last repair. That order is retained for compatibility; new
  per-loop observations expose both conditions. An unchanged timed-out seed on
  an initial invocation now also stops for no progress when budget remains and
  `--allow-no-progress` was not explicitly requested.
* Python writes `attempt-001/public-validation-N.json`. Previously the repair
  controller searched visible test directories' `run_logs`, and the renderer
  chose the newest JSON recursively, sharing it between base and checkpoint
  stages. This missed the Python report and could select a stale or wrong-stage
  report in other layouts. The controller now passes exact stage/loop paths:
  `public-validation-N-base.json` and `public-validation-N.json`. Missing reports
  fall back to the last validation section of the corresponding public log.
  The controller no longer searches directories. The standalone renderer's
  explicit legacy `--json-report-dir` option remains supported; exact paths
  take precedence even if absent. That legacy option is not used by the harness.
* The repair template assumed a previous nonempty implementation. The renderer
  now corrects only those statements when the controller reports missing/empty
  source. The tracked formal template and ordinary repair wording are unchanged.

`scripts/run_lineage_experiment.sh` delegates these mechanisms to the stage
runner and promotes only successful stage candidates. Its stage metadata links
remain valid; the detailed observations live in the existing attempt `loops`
array. No second timeout policy was added to the lineage wrapper.

## Metadata compatibility

Existing fields, types, schemas, and `stop_reason` values remain. Additive
`controller_observation_schema_version=1` identifies new attempt records.
Each loop has `observation_schema_version=1` and:

| Field | Meaning |
|---|---|
| `agent_timed_out` | Exit code is 124; the existing `timeout_enforced` describes whether the wrapper was enabled. Other termination codes are not guessed to be timeouts. |
| `agent_execution_success` | Exit 0 without observed execution/protocol failure; null when classification evidence is missing. Does not establish an editor handoff. |
| `source_sha256_before`, `source_sha256_after` | SHA-256, or null for an absent file. Empty files still have a hash. |
| `candidate_available_before`, `candidate_available_after` | A nonempty source exists, consistent with the older availability convention. |
| `source_changed`, `new_candidate_produced` | Net bytes/existence changed; the second additionally requires nonempty source afterward. A rewrite to identical bytes is not new work. |
| `timeout_without_new_candidate` | Exit 124 without a new nonempty candidate, including unchanged inherited source. |
| `aider_reported_applied_edit` | Literal applied-edit diagnostic observed; false means not seen in captured output, null means insufficient log evidence. Does not prove the message came from the editor or that source changed. |
| `validation_source` | `new_or_modified`, `inherited`, or `unavailable`. Validation remains controller-owned. |
| `controller_validation_success` | Raw conjunction of build/base/checkpoint exit statuses, before agent/candidate eligibility gates. |
| `public_validation_scores` | Base/checkpoint pass and scored totals from exact reports or current text; missing evidence is null. SKIP/XFAIL are excluded, matching the runner. |
| `public_validation_change` | `improved`, `regressed`, `unchanged`, or null for the first loop, missing/incomparable scores, changed denominators, or mixed stage movement. Relative to the preceding loop, not the best candidate. |
| `repair_budget_exhausted` | This is the final permitted invocation, independently of success or stop reason. |
| `prompt_sha256` | Hash of the actual rendered invocation prompt. |

The attempt also records `repair_template_sha256`. No editor-handoff success
field is inferred. Intermediate edits reverted within an invocation are not
recoverable from net hashes.

The historical `validation_success` remains the controller's eligible success,
not purely a test result. Its correction is intentional: absent/empty candidates
and unchanged timeouts cannot become success even if validation commands return
zero. A changed candidate produced before timeout can still succeed. Successful
exit-0 unchanged candidates retain the previous validation policy.

The old aggregate `agent_execution_failure` remains a terminal-policy flag,
not the inverse of every process success. In particular, an inherited-source
timeout still stops under `no_progress`/`loop_limit`, while the loop records
`agent_execution_success=false` and `agent_failure_reason=timeout_without_source_change`.
The old top-level `candidate_available_after_timeout` remains an **initial-session
availability** observation, and `validation_completed_after_timeout` can include
revalidation of inherited source. Neither means new work. Use per-loop
`new_candidate_produced` for that question. Readers must treat new fields missing
from historical records as unknown, not false. Existing files are not backfilled.

For non-Python suites that only write inside `run_logs`, the controller now uses
textual feedback instead of the ambiguous directory search. Exact external JSON
report support can be added to those judges separately.

## Interpretation of the supplied Vessel evidence

The 6/10 checkpoint-000 completions, 4/10 checkpoint-001 completions and zero
checkpoint-002 completions remain valid. The reported hashes and public scores
remain observations of those candidates. Lineages 004 and 005 exhausted their
repair budget with an unchanged final timeout; 007 stopped earlier for no
progress after its unchanged timeout. Those final timeouts did not produce
incorrect new edits. Lineage 006 did produce a changed final candidate, and its
57/62 to 54/62 regression remains a distinct observed outcome. This patch does
not roll back candidates or promote a best-so-far source.

For 004, the supplied transcript inspection establishes ongoing architect
analysis, identification of the relevant symbolic-mode defects, and no applied
edit before timeout. It does not establish an incorrect final editor edit.
For 005/007 the supplied evidence establishes timeout with unchanged source;
the precise generation stage cannot be determined from that evidence alone.
No original logs were inspected locally. Correct textual feedback for 004 means
the missing JSON route is not its confirmed timeout cause.

The existing template already requests underlying-defect fixes and preservation
of passing behavior. Quoting the entire original task and requesting a four-part
final report may encourage broader discussion, but that is a hypothesis, not a
proven cause. The patch does not guarantee checkpoint 002 completion.

## Proposed diagnostic prompt condition (not implemented)

For a separately named `focused-repair-v1` condition, propose inserting this
block immediately before `## Original task` in a **copy** of the repair template:

> For this repair, use the current public failures to identify the smallest set
> of underlying defects. Inspect only behavior needed to fix those defects and
> preserve passing cases. Once the defects are identified, finish the architect
> response with concrete source-edit instructions: the affected functions, the
> required changes, and the failing cases each change addresses. Do not continue
> surveying unrelated functionality after you have an actionable edit plan.
> Hand the instructions to the editor in this invocation. Do not claim tests
> passed; validation is performed afterward by the controller.

This is proposed text for review, not a changed experimental control. Before
using it, include the selected repair-template content hash in the lineage plan
fingerprint/resume guard: currently `--repair-prompt` is forwarded but its content
is not in `lineage_plan.py`'s configuration fingerprint. The new per-attempt hash
records provenance but is not a replacement for that guard. Use a separately
named fresh output directory and retain the rendered prompts. Do not pool that
condition with the original prompt. No diagnostic prompt file was installed by
this patch.

## Local validation and deployment

Local WSL, no models: 12 tests passed with `python3 -B -m unittest discover -s
tests -p 'test_*.py' -v`. Tests include all six invocation cases, empty source,
inherited passing seeds, the four-invocation final timeout, regression, report
selection/fallback, public/held-out isolation, and existing metadata types.
One test uses a real one-second GNU timeout against a sleeping stub; the other
timeouts use synthetic exit 124. The suite takes approximately 22 seconds.
Both shell controllers passed `bash -n`; Python compilation of all scripts and
the new test module passed, as did `git diff --check`. The repository isolation scanner
passed for all 10 utilities. The Python mkdir `--audit` passed frozen hashes,
cumulative flags and isolation without regenerating goldens.

`make test` cannot start because this checkout lacks `src/new_sort/new_sort.c`,
an existing Makefile prerequisite. Direct unittest discovery is the available
repository test suite here. GNU 9.11 oracle regeneration/self-checks and real
model behavior were not tested.

After review, commit these changes locally and push through your normal workflow.
On Vessel, pull that reviewed commit (`git pull --ff-only` on the appropriate
branch), activate the same Python/Aider environment used for the experiment,
and record `git rev-parse HEAD`. If running in Docker, update/rebuild the existing
controller environment from that commit using your normal deployment procedure.
Run these non-model checks there before the diagnostic:

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
bash -n scripts/run_experiment.sh
bash -n scripts/run_lineage_experiment.sh
python3 -B scripts/check_heldout_isolation.py
python3 -B tests/python-mkdir-test-suite/gen/generate.py --audit
```

Run the following **manually**, in the same Linux runtime as the prior mkdir
experiment. Set `VESSEL_AIDER_TIMEOUT_SECONDS` to the prior run's recorded
`timeout_seconds` and `VESSEL_OLLAMA_BASE_URL` to its endpoint; these are explicit
to avoid silently changing either setting. Keep the original prompts and Aider
0.86.2. This starts one new lineage and may stop before 002; it does not recreate
or resume the original run:

```bash
: "${VESSEL_AIDER_TIMEOUT_SECONDS:?set to the original timeout_seconds}"
: "${VESSEL_OLLAMA_BASE_URL:?set to the existing runtime endpoint}"
mkdir -p runs/diagnostic
diagnostic_dir=$(mktemp -d runs/diagnostic/python-mkdir-repair-audit-XXXXXX)
PYTHON_BIN="$(command -v python3)" bash scripts/run_lineage_experiment.sh \
  --utility python-mkdir \
  --model ollama_chat/qwen3.8:27b \
  --editor-model ollama_chat/qwen3-coder-next:latest \
  --architect-think false --temperature 1.0 --sampling-seed 42 \
  --num-ctx 65536 --lineages 1 --max-loops 3 \
  --timeout "$VESSEL_AIDER_TIMEOUT_SECONDS" \
  --remote-base-url "$VESSEL_OLLAMA_BASE_URL" \
  --output-dir "$diagnostic_dir"
```

Inspect the new attempt metadata and rendered repair prompts. On any timeout,
check the two source hashes, `new_candidate_produced`, `validation_source`, and
the unchanged exit 124. Do not resume the old formal directory under the new
harness; the existing configuration fingerprint does not encode controller code
changes. Preserve the old run and distinguish the reviewed commit in analysis.
