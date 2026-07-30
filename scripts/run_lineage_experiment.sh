#!/usr/bin/env bash
# Run complete sequential lineages through one utility's checkpoint sequence.
#
# The experimental unit here is a LINEAGE: one independent walk through every
# checkpoint of a utility, where the source produced by each stage is the source
# supplied to the next stage of that same lineage.
#
#   lineage-001: 000 -> 001 -> 002 -> ... -> final
#   lineage-002: 000 -> 001 -> 002 -> ... -> final
#
# Lineages never share source. Stage 000 runs --source-mode new; every later
# stage runs --source-mode existing, seeded from the immediately preceding
# successful candidate of the SAME lineage. Each stage is a fresh OpenCode
# session; the only implementation state carried across a stage boundary is that
# one seed file.
#
# This script owns lineage bookkeeping only. All single-stage mechanism --
# isolated work directories, OpenCode permissions, source modes, seed files,
# controller-driven repair loops, build and test validation, candidate capture,
# infrastructure-failure metadata -- belongs to scripts/run_experiment.sh, which
# this script calls once per stage. Nothing is reimplemented here.
#
# A stage that cannot pass validation after its allowed repair attempts STOPS
# its lineage: a failed implementation is never fed into the next feature. The
# lineage is retained with the stopping point and reason recorded, and it is not
# replaced with a fresh attempt -- reliability is measured over lineages
# STARTED, not over lineages that happened to finish.
#
# Example (10 sort lineages at one temperature):
#   scripts/run_lineage_experiment.sh \
#     --utility sort \
#     --model school-ollama/qwen3-coder-next:latest \
#     --temperature 0.2 \
#     --lineages 10 \
#     --max-loops 3
#
# Analysis is a separate step:
#   python3 scripts/analyze_lineages.py --lineage-root <output-dir>

set -uo pipefail

usage() {
    cat <<'EOF'
Usage:
  run_lineage_experiment.sh --utility NAME --model MODEL [options]

Required:
  --utility NAME             Manifest under experiments/utilities/<NAME>.json
  --model MODEL              OpenCode model name, e.g.
                             school-ollama/qwen3-coder-next:latest

Experiment size:
  --temperature T            Single temperature for every stage (default: 0)
  --lineages N               Independent lineages to run (default: 1). There is
                             no built-in lineage count; the planned experiment
                             size of 10 is a command-line value, not a default.
  --lineage-start N          First lineage number to run (default: 1), so an
                             existing run can be extended without touching
                             lineages already on disk.
  --max-loops N              Repair sessions allowed WITHIN each stage after its
                             initial generation (default: 3). 0 disables repair.

Passed through to scripts/run_experiment.sh:
  --agent NAME               OpenCode agent (default: build)
  --timeout SECONDS          Per-session timeout; 0 disables (default: 1800)
  --allow-no-progress        Keep repairing a stage even when a session leaves
                             the source byte-identical
  --repair-prompt FILE       Continuation template
  --keep-workdir             Retain each stage's working directory
  --remote-base-url URL      OpenAI-compatible endpoint for --model
  --remote-api-key-env NAME  Env var holding that endpoint's key

Output:
  --output-dir DIR           Lineage root. Default:
                             runs/lineages/<utility>/<model-slug>/temp-<slug>
  --force                    Rerun stages that are already complete
  --print-plan               Print the resolved stage plan and exit
  --list-utilities           List available manifests and exit
  --dry-run                  Print the run_experiment.sh command for every
                             stage of every lineage without running anything
  -h, --help                 Show this help

Environment:
  OPENCODE_BIN               OpenCode executable (default: opencode)
  PYTHON_BIN                 Python executable (default: python3)

Directory layout:
  <output-dir>/
    lineages.json                  run-level configuration + fingerprint
    lineage-001/
      lineage.json                 per-stage outcome, seed provenance, stop point
      000/                         a complete single-stage run_experiment.sh tree
        test-bundle/               exactly what the agent could read here
        sweep.json
        temp-<slug>/
          experiment.json  baseline/  attempt-001/{metadata.json,candidate/,...}
      001/
      ...
      final/<source-basename>      only when every checkpoint succeeded
    lineage-002/
      ...

Every stage stays inspectable, failed lineages are retained, and `final/` exists
only for lineages that completed the whole sequence.

Visible tests are built per checkpoint, not copied. scripts/stage_test_bundle.py
assembles the runtime judging files plus only those frozen cases whose flags are
implemented at that checkpoint, and the bundle is mounted at the suite's own path
so the prompt and the judge command stay literally correct. A later checkpoint's
cases are absent from the sandbox rather than merely skipped, and no generator,
flag model, specification model or corpus is included at all.
EOF
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 2
}

warn() {
    printf 'warning: %s\n' "$*" >&2
}

slugify() {
    printf '%s' "$1" |
        tr '[:upper:]' '[:lower:]' |
        sed -E 's#[^a-z0-9._-]+#-#g; s#^-+##; s#-+$##'
}

timestamp() {
    date -u +%Y-%m-%dT%H:%M:%SZ
}

UTILITY=""
MODEL=""
TEMPERATURE="0"
LINEAGES=1
LINEAGE_START=1
MAX_LOOPS=3
AGENT="build"
TIMEOUT_SECONDS=1800
ALLOW_NO_PROGRESS=0
REPAIR_TEMPLATE=""
KEEP_WORKDIR=0
REMOTE_BASE_URL=""
REMOTE_API_KEY_ENV=""
OUTPUT_DIR=""
FORCE=0
PRINT_PLAN=0
LIST_UTILITIES=0
DRY_RUN=0

PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --utility|--model|--temperature|--lineages|--lineage-start|--max-loops| \
        --agent|--timeout|--repair-prompt|--remote-base-url| \
        --remote-api-key-env|--output-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            ;;
    esac

    case "$1" in
        --utility) UTILITY="${2:-}"; shift 2 ;;
        --model) MODEL="${2:-}"; shift 2 ;;
        --temperature) TEMPERATURE="${2:-}"; shift 2 ;;
        --lineages) LINEAGES="${2:-}"; shift 2 ;;
        --lineage-start) LINEAGE_START="${2:-}"; shift 2 ;;
        --max-loops) MAX_LOOPS="${2:-}"; shift 2 ;;
        --agent) AGENT="${2:-}"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
        --allow-no-progress) ALLOW_NO_PROGRESS=1; shift ;;
        --repair-prompt) REPAIR_TEMPLATE="${2:-}"; shift 2 ;;
        --keep-workdir) KEEP_WORKDIR=1; shift ;;
        --remote-base-url) REMOTE_BASE_URL="${2:-}"; shift 2 ;;
        --remote-api-key-env) REMOTE_API_KEY_ENV="${2:-}"; shift 2 ;;
        --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
        --force) FORCE=1; shift ;;
        --print-plan) PRINT_PLAN=1; shift ;;
        --list-utilities) LIST_UTILITIES=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --runs)
            die "--runs is a single-stage option; a lineage runs one attempt per stage (use --lineages)" ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN was not found"
command -v git >/dev/null 2>&1 || die "git is required (to resolve repo-relative paths)"

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" ||
    die "run this script inside a Git repository (only used to resolve paths)"
REPO="$(cd "$REPO" && pwd -P)"

PLAN_TOOL="$REPO/scripts/lineage_plan.py"
[[ -f "$PLAN_TOOL" ]] || die "plan resolver not found: $PLAN_TOOL"
STAGE_RUNNER="$REPO/scripts/run_experiment.sh"
[[ -f "$STAGE_RUNNER" ]] || die "single-stage runner not found: $STAGE_RUNNER"
BUNDLE_TOOL="$REPO/scripts/stage_test_bundle.py"
[[ -f "$BUNDLE_TOOL" ]] || die "stage test bundle builder not found: $BUNDLE_TOOL"

if [[ "$LIST_UTILITIES" -eq 1 ]]; then
    "$PYTHON_BIN" "$PLAN_TOOL" --repo "$REPO" --emit utilities
    exit 0
fi

[[ -n "$UTILITY" ]] || die "--utility is required"
[[ -n "$MODEL" ]] || die "--model is required"
[[ "$LINEAGES" =~ ^[1-9][0-9]*$ ]] || die "--lineages must be a positive integer"
[[ "$LINEAGE_START" =~ ^[1-9][0-9]*$ ]] ||
    die "--lineage-start must be a positive integer"
[[ "$MAX_LOOPS" =~ ^[0-9]+$ ]] || die "--max-loops must be a non-negative integer"
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--timeout must be a non-negative integer"
"$PYTHON_BIN" -c 'import sys; float(sys.argv[1])' "$TEMPERATURE" ||
    die "--temperature must be numeric"

# ---------------------------------------------------------------------------
# Resolve the stage plan
# ---------------------------------------------------------------------------

PLAN_JSON="$(
    "$PYTHON_BIN" "$PLAN_TOOL" \
        --repo "$REPO" \
        --utility "$UTILITY" \
        --model "$MODEL" \
        --temperature "$TEMPERATURE" \
        --agent "$AGENT" \
        --max-loops "$MAX_LOOPS" \
        --timeout-seconds "$TIMEOUT_SECONDS" \
        --emit plan
)" || exit 2

plan_field() {
    "$PYTHON_BIN" - "$PLAN_JSON" "$1" <<'PY'
import json
import sys

print(json.loads(sys.argv[1])[sys.argv[2]])
PY
}

SOURCE_PATH="$(plan_field source_path)"
SOURCE_BASENAME="$(plan_field source_basename)"
BUILD_CMD="$(plan_field build_command)"
TEST_DIR="$(plan_field test_dir)"
BASE_TEST_CMD="$(plan_field base_test_command)"
EXTRA_TEST_CMD="$(plan_field extra_test_command)"
CONFIG_FINGERPRINT="$(plan_field config_fingerprint)"

STAGE_TABLE="$(
    "$PYTHON_BIN" "$PLAN_TOOL" \
        --repo "$REPO" \
        --utility "$UTILITY" \
        --model "$MODEL" \
        --temperature "$TEMPERATURE" \
        --agent "$AGENT" \
        --max-loops "$MAX_LOOPS" \
        --timeout-seconds "$TIMEOUT_SECONDS" \
        --emit stages
)" || exit 2

STAGE_IDS=()
STAGE_NAMES=()
STAGE_PROMPTS=()
STAGE_MODES=()
STAGE_FEATURE_CMDS=()
STAGE_FLAGS=()
STAGE_BUNDLE_FINGERPRINTS=()
while IFS=$'\t' read -r stage_id stage_name stage_prompt stage_mode stage_cmd \
        stage_flags stage_bundle_fingerprint; do
    [[ -n "$stage_id" ]] || continue
    STAGE_IDS+=("$stage_id")
    STAGE_NAMES+=("$stage_name")
    STAGE_PROMPTS+=("$stage_prompt")
    STAGE_MODES+=("$stage_mode")
    STAGE_FEATURE_CMDS+=("$stage_cmd")
    STAGE_FLAGS+=("$stage_flags")
    STAGE_BUNDLE_FINGERPRINTS+=("$stage_bundle_fingerprint")
done <<<"$STAGE_TABLE"

STAGE_COUNT=${#STAGE_IDS[@]}
[[ "$STAGE_COUNT" -gt 0 ]] || die "manifest for $UTILITY resolved to zero checkpoints"

MODEL_SLUG="$(slugify "$MODEL")"
TEMP_SLUG="$(slugify "$TEMPERATURE" | sed 's/\./p/g')"

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$REPO/runs/lineages/$UTILITY/$MODEL_SLUG/temp-$TEMP_SLUG"
elif [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="$REPO/$OUTPUT_DIR"
fi

if [[ "$PRINT_PLAN" -eq 1 ]]; then
    printf '%s\n' "$PLAN_JSON"
    printf '\nOutput dir: %s\n' "$OUTPUT_DIR"
    printf 'Lineages:   %s..%s\n' \
        "$LINEAGE_START" "$((LINEAGE_START + LINEAGES - 1))"
    exit 0
fi

# A dry run must not touch the filesystem, so the output directory is only
# created when something is actually going to be written into it. OUTPUT_DIR is
# already absolute either way; the cd/pwd pass only resolves symlinks.
if [[ "$DRY_RUN" -eq 0 ]]; then
    mkdir -p "$OUTPUT_DIR"
    OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"
fi

REPO_COMMIT="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || printf 'unknown')"

# ---------------------------------------------------------------------------
# Resume guard: an existing lineage root must describe the same experiment
# ---------------------------------------------------------------------------

RUN_METADATA="$OUTPUT_DIR/lineages.json"
if [[ -f "$RUN_METADATA" && "$DRY_RUN" -eq 0 ]]; then
    mismatch="$(
        "$PYTHON_BIN" - "$RUN_METADATA" "$CONFIG_FINGERPRINT" "$UTILITY" \
            "$MODEL" "$TEMPERATURE" "$AGENT" "$MAX_LOOPS" <<'PY'
import json
import sys
from pathlib import Path

path, fingerprint, utility, model, temperature, agent, max_loops = sys.argv[1:]
try:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    print(f"cannot read {path}: {error}")
    raise SystemExit(0)

expected = {
    "config_fingerprint": fingerprint,
    "utility": utility,
    "model": model,
    "temperature": float(temperature),
    "agent": agent,
    "max_loops": int(max_loops),
}
differences = [key for key, value in expected.items() if data.get(key) != value]
print(", ".join(differences))
PY
    )" || die "cannot compare existing lineage metadata at $RUN_METADATA"
    [[ -z "$mismatch" ]] || die \
        "existing lineage run at $OUTPUT_DIR was produced under a different configuration ($mismatch); use a new --output-dir rather than mixing stage configurations"
fi

CHECKPOINT_LADDER="${STAGE_IDS[0]}"
for (( index = 1; index < STAGE_COUNT; index++ )); do
    CHECKPOINT_LADDER+=" -> ${STAGE_IDS[index]}"
done

printf 'Repository:   %s\n' "$REPO"
printf 'Utility:      %s (%s checkpoints)\n' "$UTILITY" "$STAGE_COUNT"
printf 'Checkpoints:  %s\n' "$CHECKPOINT_LADDER"
printf 'Model:        %s\n' "$MODEL"
printf 'Temperature:  %s\n' "$TEMPERATURE"
printf 'Lineages:     %s (numbered %s..%s)\n' \
    "$LINEAGES" "$LINEAGE_START" "$((LINEAGE_START + LINEAGES - 1))"
printf 'Max loops:    %s per stage\n' "$MAX_LOOPS"
printf 'Fingerprint:  %s\n' "$CONFIG_FINGERPRINT"
printf 'Output:       %s\n\n' "$OUTPUT_DIR"

if [[ "$DRY_RUN" -eq 0 ]]; then
    "$PYTHON_BIN" - "$RUN_METADATA" "$PLAN_JSON" "$REPO" "$REPO_COMMIT" \
        "$LINEAGE_START" "$LINEAGES" "$(timestamp)" <<'PY'
import json
import sys
from pathlib import Path

path, plan_json, repository, commit, start, count, created = sys.argv[1:]
plan = json.loads(plan_json)
target = Path(path)

record = {}
if target.is_file():
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        record = {}

lineage_ids = sorted(
    set(record.get("lineage_ids", []))
    | {f"lineage-{number:03d}" for number in range(int(start), int(start) + int(count))}
)

record.update(
    {
        "schema_version": 1,
        "experiment_unit": "lineage",
        "repository": repository,
        "repository_commit": commit,
        "utility": plan["utility"],
        "program": plan["program"],
        "model": plan["model"],
        "temperature": plan["temperature"],
        "agent": plan["agent"],
        "max_loops": plan["max_loops"],
        "timeout_seconds": plan["timeout_seconds"],
        "source_path": plan["source_path"],
        "source_basename": plan["source_basename"],
        "executable_path": plan["executable_path"],
        "test_dir": plan["test_dir"],
        "judge": plan["judge"],
        "config_fingerprint": plan["config_fingerprint"],
        "checkpoints": plan["checkpoints"],
        "lineage_ids": lineage_ids,
        "lineages_started": len(lineage_ids),
        "updated_at": created,
    }
)
record.setdefault("created_at", created)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
PY
fi

# ---------------------------------------------------------------------------
# Lineages
# ---------------------------------------------------------------------------

overall_status=0
completed_lineages=0
started_lineages=0

for (( offset = 0; offset < LINEAGES; offset++ )); do
    lineage_number=$((LINEAGE_START + offset))
    lineage_id="$(printf 'lineage-%03d' "$lineage_number")"
    lineage_dir="$OUTPUT_DIR/$lineage_id"
    started_lineages=$((started_lineages + 1))

    printf '=== %s ===\n' "$lineage_id"

    seed_repo_relative=""
    stage_records=()
    end_to_end_success=true
    failure_stage_json=null
    failure_reason_json=null

    for (( index = 0; index < STAGE_COUNT; index++ )); do
        stage_id="${STAGE_IDS[index]}"
        stage_name="${STAGE_NAMES[index]}"
        stage_prompt="${STAGE_PROMPTS[index]}"
        stage_mode="${STAGE_MODES[index]}"
        stage_cmd="${STAGE_FEATURE_CMDS[index]}"
        stage_flags="${STAGE_FLAGS[index]}"
        stage_bundle_fingerprint="${STAGE_BUNDLE_FINGERPRINTS[index]}"
        stage_dir="$lineage_dir/$stage_id"
        stage_experiment="$stage_dir/temp-$TEMP_SLUG"
        stage_attempt="$stage_experiment/attempt-001"
        stage_candidate="$stage_attempt/candidate/$SOURCE_BASENAME"
        stage_bundle="$stage_dir/test-bundle"

        # The agent must not be able to read a later checkpoint's tests, so it
        # is given a bundle built for THIS checkpoint rather than the whole
        # suite: the runtime judging files plus only those frozen cases whose
        # flags are implemented here. It is mounted at the suite's own path, so
        # the prompt and the judge command stay literally correct. The bundle is
        # kept next to the stage results as the record of what was visible.
        if [[ "$DRY_RUN" -eq 0 ]]; then
            mkdir -p "$stage_dir"
            built_fingerprint="$(
                "$PYTHON_BIN" "$BUNDLE_TOOL" \
                    --repo "$REPO" \
                    --utility "$UTILITY" \
                    --checkpoint "$stage_id" \
                    --output "$stage_bundle" \
                    --emit fingerprint
            )" || die "failed to build the test bundle for $lineage_id stage $stage_id"
            # The plan hashed this bundle when the run was configured. A
            # mismatch means the suite changed underneath a running experiment.
            [[ "$built_fingerprint" == "$stage_bundle_fingerprint" ]] || die \
                "test bundle for stage $stage_id changed since the run was planned (planned $stage_bundle_fingerprint, built $built_fingerprint); start a new --output-dir rather than mixing test bundles"
        fi

        runner_args=(
            --model "$MODEL"
            --temperature "$TEMPERATURE"
            --runs 1
            --max-loops "$MAX_LOOPS"
            --agent "$AGENT"
            --timeout "$TIMEOUT_SECONDS"
            --prompt "$stage_prompt"
            --source "$SOURCE_PATH"
            --source-mode "$stage_mode"
            --test-dir "$stage_bundle:$TEST_DIR"
            --build-cmd "$BUILD_CMD"
            --feature-test-cmd "$stage_cmd"
            --output-dir "$stage_dir"
            --no-analysis
        )
        [[ -n "$BASE_TEST_CMD" ]] && runner_args+=(--base-test-cmd "$BASE_TEST_CMD")
        [[ -n "$EXTRA_TEST_CMD" ]] && runner_args+=(--extra-test-cmd "$EXTRA_TEST_CMD")
        [[ "$ALLOW_NO_PROGRESS" -eq 1 ]] && runner_args+=(--allow-no-progress)
        [[ "$KEEP_WORKDIR" -eq 1 ]] && runner_args+=(--keep-workdir)
        [[ -n "$REPAIR_TEMPLATE" ]] && runner_args+=(--repair-prompt "$REPAIR_TEMPLATE")
        [[ -n "$REMOTE_BASE_URL" ]] && runner_args+=(--remote-base-url "$REMOTE_BASE_URL")
        [[ -n "$REMOTE_API_KEY_ENV" ]] &&
            runner_args+=(--remote-api-key-env "$REMOTE_API_KEY_ENV")

        if [[ "$stage_mode" == "existing" ]]; then
            # Seeded from the immediately preceding candidate of THIS lineage
            # only. A cross-lineage seed would destroy the independence the
            # design is built on, so an absent seed is fatal rather than
            # silently substituted.
            [[ -n "$seed_repo_relative" ]] ||
                die "$lineage_id stage $stage_id has no seed from the previous stage"
            runner_args+=(--seed-file "$seed_repo_relative:$SOURCE_PATH")
        fi
        [[ "$FORCE" -eq 1 ]] && runner_args+=(--force)

        if [[ "$DRY_RUN" -eq 1 ]]; then
            printf '  [%s %s] bash scripts/run_experiment.sh' "$stage_id" "$stage_name"
            printf ' %q' "${runner_args[@]}"
            printf '\n'
            # A dry run cannot produce a candidate, so fabricate the provenance
            # the next stage would inherit rather than aborting the walk.
            seed_repo_relative="${stage_candidate#"$REPO"/}"
            continue
        fi

        stage_reused=false
        if [[ -f "$stage_attempt/COMPLETE" && "$FORCE" -eq 0 ]]; then
            # A reusable stage must have been produced from the same seed. The
            # runner snapshots its seed as baseline/<basename>, so comparing that
            # against the seed this walk is holding catches the one way a resume
            # could silently mix generations: an earlier stage regenerated while
            # a later one was left alone.
            if [[ "$stage_mode" == "existing" ]]; then
                seed_drift="$(
                    "$PYTHON_BIN" - "$stage_experiment/baseline/$SOURCE_BASENAME" \
                        "$REPO/$seed_repo_relative" <<'PY'
import hashlib
import sys
from pathlib import Path


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    accumulator = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            accumulator.update(chunk)
    return accumulator.hexdigest()


recorded, current = (digest(Path(argument)) for argument in sys.argv[1:3])
print("drift" if recorded != current else "")
PY
                )" || die "cannot compare recorded seed for $lineage_id stage $stage_id"
                [[ -z "$seed_drift" ]] || die \
                    "$lineage_id stage $stage_id was run from a different seed than the preceding stage now produces; rerun the lineage with --force rather than mixing generations"
            fi
            stage_reused=true
            printf '  [%s %s] already complete; reusing\n' "$stage_id" "$stage_name"
        else
            printf '  [%s %s] %s\n' "$stage_id" "$stage_name" "$stage_prompt"
            if ! bash "$STAGE_RUNNER" "${runner_args[@]}"; then
                warn "$lineage_id stage $stage_id: run_experiment.sh exited nonzero"
                overall_status=1
            fi
        fi

        stage_summary="$(
            "$PYTHON_BIN" - "$stage_attempt" "$stage_candidate" "$stage_id" \
                "$stage_name" "$stage_prompt" "$stage_mode" "$stage_cmd" \
                "$stage_flags" "${seed_repo_relative:-}" "$stage_reused" \
                "$SOURCE_BASENAME" "$stage_bundle" "$stage_bundle_fingerprint" \
                <<'PY'
import hashlib
import json
import sys
from pathlib import Path

(
    attempt_dir,
    candidate_path,
    checkpoint_id,
    checkpoint_name,
    prompt,
    source_mode,
    feature_test_command,
    implemented_csv,
    seed,
    reused,
    source_basename,
    test_bundle_dir,
    test_bundle_fingerprint,
) = sys.argv[1:]

attempt = Path(attempt_dir)
candidate = Path(candidate_path)
metadata = {}
metadata_path = attempt / "metadata.json"
if metadata_path.is_file():
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = {}

candidate_sha = None
if candidate.is_file():
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    candidate_sha = digest.hexdigest()

attempt_complete = (attempt / "COMPLETE").is_file()
public_success = bool(metadata.get("public_validation_success"))
# A stage "successfully completed" only if the controller's own build/base/
# checkpoint validation passed AND the source it produced was captured. The
# next stage inherits that file, so a missing candidate is a stage failure even
# when validation reported success.
success = attempt_complete and public_success and candidate_sha is not None

if not attempt_complete:
    reason = "stage_run_incomplete"
elif metadata.get("infrastructure_failure"):
    reason = "infrastructure_failure"
elif metadata.get("agent_execution_failure"):
    reason = "agent_execution_failure"
elif not public_success:
    reason = str(metadata.get("stop_reason") or "validation_failed")
elif candidate_sha is None:
    reason = "candidate_missing"
else:
    reason = None

record = {
    "checkpoint_id": checkpoint_id,
    "checkpoint_name": checkpoint_name,
    "prompt": prompt,
    "source_mode": source_mode,
    "implemented_flags": [f for f in implemented_csv.split(",") if f],
    "feature_test_command": feature_test_command,
    "stage_dir": str(attempt.parent.parent.as_posix()),
    "attempt_dir": str(attempt.as_posix()),
    "candidate": str(candidate.as_posix()) if candidate_sha else None,
    "candidate_source_basename": source_basename,
    "candidate_sha256": candidate_sha,
    "seed": seed or None,
    "seed_sha256": None,
    # Exactly what the agent could read at this checkpoint, and the hash the run
    # was planned against.
    "test_bundle_dir": test_bundle_dir,
    "test_bundle_fingerprint": test_bundle_fingerprint,
    "test_bundle": None,
    "reused_existing_stage_run": reused == "true",
    "success": success,
    "failure_reason": reason,
    # Reuse the single-stage runner's own metadata vocabulary rather than
    # inventing a second classification.
    "public_validation_success": public_success,
    "initial_success": bool(metadata.get("initial_success")),
    "repair_loops": metadata.get("repair_loops"),
    "llm_invocations": metadata.get("llm_invocations"),
    "success_loop": metadata.get("success_loop"),
    "stop_reason": metadata.get("stop_reason"),
    "loop_limit_reached": bool(metadata.get("loop_limit_reached")),
    "infrastructure_failure": bool(metadata.get("infrastructure_failure")),
    "infrastructure_failure_stage": metadata.get("infrastructure_failure_stage"),
    "agent_execution_failure": bool(metadata.get("agent_execution_failure")),
    "agent_execution_failure_stage": metadata.get("agent_execution_failure_stage"),
    "build_exit_code": metadata.get("build_exit_code"),
    "base_test_exit_code": metadata.get("base_test_exit_code"),
    "feature_test_exit_code": metadata.get("feature_test_exit_code"),
    "extra_test_exit_code": metadata.get("extra_test_exit_code"),
    "test_dir_integrity": metadata.get("test_dir_integrity"),
    "total_opencode_runtime_ms": metadata.get("total_opencode_runtime_ms"),
    "total_runtime_ms": metadata.get("total_runtime_ms"),
}

bundle_manifest = Path(test_bundle_dir) / "BUNDLE.json"
if bundle_manifest.is_file():
    try:
        record["test_bundle"] = json.loads(
            bundle_manifest.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        record["test_bundle"] = None

if seed:
    seed_file = Path(seed)
    if seed_file.is_file():
        digest = hashlib.sha256()
        with seed_file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        record["seed_sha256"] = digest.hexdigest()

print(json.dumps(record, separators=(",", ":")))
PY
        )" || die "failed to summarize $lineage_id stage $stage_id"

        stage_records+=("$stage_summary")

        stage_success="$(
            "$PYTHON_BIN" -c \
                'import json,sys; print("true" if json.loads(sys.argv[1])["success"] else "false")' \
                "$stage_summary"
        )"
        stage_reason="$(
            "$PYTHON_BIN" -c \
                'import json,sys; print(json.loads(sys.argv[1])["failure_reason"] or "")' \
                "$stage_summary"
        )"

        if [[ "$stage_success" != true ]]; then
            end_to_end_success=false
            failure_stage_json="\"$stage_id\""
            failure_reason_json="\"${stage_reason:-unknown}\""
            printf '  [%s %s] STOP: %s\n' \
                "$stage_id" "$stage_name" "${stage_reason:-unknown}"
            break
        fi

        printf '  [%s %s] pass\n' "$stage_id" "$stage_name"
        seed_repo_relative="${stage_candidate#"$REPO"/}"
    done

    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '\n'
        continue
    fi

    # The final source is a completion artifact: it exists only for a lineage
    # that passed every checkpoint, so its presence is never ambiguous.
    final_dir="$lineage_dir/final"
    rm -rf "$final_dir"
    if [[ "$end_to_end_success" == true ]]; then
        mkdir -p "$final_dir"
        cp -p "$REPO/$seed_repo_relative" "$final_dir/$SOURCE_BASENAME"
        completed_lineages=$((completed_lineages + 1))
    fi

    "$PYTHON_BIN" - "$lineage_dir/lineage.json" "$lineage_id" "$UTILITY" \
        "$MODEL" "$TEMPERATURE" "$AGENT" "$MAX_LOOPS" "$CONFIG_FINGERPRINT" \
        "$STAGE_COUNT" "$end_to_end_success" "$failure_stage_json" \
        "$failure_reason_json" "$SOURCE_BASENAME" "$(timestamp)" \
        "${stage_records[@]+"${stage_records[@]}"}" <<'PY'
import json
import sys
from pathlib import Path

(
    path,
    lineage_id,
    utility,
    model,
    temperature,
    agent,
    max_loops,
    fingerprint,
    checkpoint_count,
    end_to_end,
    failure_stage,
    failure_reason,
    source_basename,
    finished,
) = sys.argv[1:15]
stages = [json.loads(record) for record in sys.argv[15:]]

completed = end_to_end == "true"
record = {
    "schema_version": 1,
    "lineage_id": lineage_id,
    "utility": utility,
    "model": model,
    "temperature": float(temperature),
    "agent": agent,
    "max_loops": int(max_loops),
    "config_fingerprint": fingerprint,
    "checkpoint_count": int(checkpoint_count),
    "checkpoints_completed": sum(1 for stage in stages if stage["success"]),
    "end_to_end_success": completed,
    "failure_stage": json.loads(failure_stage),
    "failure_reason": json.loads(failure_reason),
    "final_source": f"final/{source_basename}" if completed else None,
    "stages": stages,
    "finished_at": finished,
}
Path(path).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
PY

    if [[ "$end_to_end_success" == true ]]; then
        printf '  lineage complete: final/%s\n\n' "$SOURCE_BASENAME"
    else
        printf '  lineage stopped\n\n'
    fi
done

if [[ "$DRY_RUN" -eq 1 ]]; then
    printf 'Dry run: nothing was executed.\n'
    exit 0
fi

printf 'Lineages started this invocation:   %s\n' "$started_lineages"
printf 'Lineages completed all checkpoints: %s\n' "$completed_lineages"
printf 'Output: %s\n' "$OUTPUT_DIR"
printf '\nAnalyze with:\n  %s scripts/analyze_lineages.py --lineage-root %s\n' \
    "$PYTHON_BIN" "${OUTPUT_DIR#"$REPO"/}"

exit "$overall_status"
