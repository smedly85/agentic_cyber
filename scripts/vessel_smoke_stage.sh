#!/usr/bin/env bash
# Bounded checkpoint-000 smoke test for one standardized linux-utilities selector.
#
# Diagnostic only: not a lineage, not a formal result, no lineage seed. It reuses
# the real controllers instead of re-implementing them:
#   scripts/lineage_plan.py          stage-000 prompt, commands, bundle fingerprint
#   scripts/stage_test_bundle.py     the public checkpoint-000 bundle
#   scripts/run_experiment.sh        one Aider generation + at most one repair,
#                                    Docker public validation, controller-only
#                                    held-out evaluation (extra_test_command)
#   scripts/checkpoint_boundary_gate.py  controller-only boundary verification
# The run_experiment.sh arguments mirror the stage-000 arguments built by
# scripts/run_lineage_experiment.sh, with --max-loops capped at 1.
#
# Without --generate only read-only planning commands execute: the resolved
# run_experiment.sh command is printed. With --generate the non-generative preflight
# (scripts/vessel_preflight.py) is retained in the diagnostic output; failures stop before Aider.
#
# Exit: 0 run completed and was classified without infrastructure failure
#       (the candidate verdict itself is in smoke-summary.json), 1 infrastructure
#       or controller failure during the run, 2 usage error, 4 preflight failed.
set -uo pipefail

usage() {
    cat <<'EOF'
Usage:
  vessel_smoke_stage.sh --selector c-cp|rust-cp|py-cp --timeout SECONDS \
      --temperature T --architect-think false|low|medium|high \
      --sampling-seed N --num-ctx N [--max-tokens N] [--top-p P] \
      [--max-loops 0|1] [--ollama-url URL] [--architect-model M] \
      [--editor-model M] [--output-dir NEW_DIR_OUTSIDE_REPO] [--generate]

Temperature, thinking, seed and context must be supplied explicitly; token cap
and top-p remain optional (see docs/benchmarks/linux-utilities-vessel.md).
The editor is pinned by scripts/aider_settings.py (temperature 0, seed 0) and
uses --editor-edit-format editor-diff.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 2; }

SELECTOR=""
TIMEOUT_SECONDS=""
TEMPERATURE=""
ARCHITECT_THINK=""
SAMPLING_SEED=""
NUM_CTX=""
MAX_TOKENS=""
TOP_P=""
MAX_LOOPS=1
OLLAMA_URL="http://127.0.0.1:11434"
MODEL="ollama_chat/qwen3.8:27b"
EDITOR_MODEL="ollama_chat/qwen3-coder-next:latest"
OUTPUT_DIR=""
GENERATE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --selector|--timeout|--temperature|--architect-think|--sampling-seed| \
        --num-ctx|--max-tokens|--top-p|--max-loops|--ollama-url| \
        --architect-model|--editor-model|--output-dir)
            [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a value" ;;
    esac
    case "$1" in
        --selector) SELECTOR="$2"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="$2"; shift 2 ;;
        --temperature) TEMPERATURE="$2"; shift 2 ;;
        --architect-think) ARCHITECT_THINK="$2"; shift 2 ;;
        --sampling-seed) SAMPLING_SEED="$2"; shift 2 ;;
        --num-ctx) NUM_CTX="$2"; shift 2 ;;
        --max-tokens) MAX_TOKENS="$2"; shift 2 ;;
        --top-p) TOP_P="$2"; shift 2 ;;
        --max-loops) MAX_LOOPS="$2"; shift 2 ;;
        --ollama-url) OLLAMA_URL="$2"; shift 2 ;;
        --architect-model) MODEL="$2"; shift 2 ;;
        --editor-model) EDITOR_MODEL="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --generate) GENERATE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

case "$SELECTOR" in
    c-cp|rust-cp|py-cp) ;;
    *) die "--selector must be c-cp, rust-cp or py-cp" ;;
esac
[[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || die "--timeout must be a positive integer (explicit bound required)"
[[ "$MAX_LOOPS" == 0 || "$MAX_LOOPS" == 1 ]] || die "--max-loops must be 0 or 1 for a smoke test"
[[ -n "$TEMPERATURE" ]] || die "--temperature is required (no default architect sampling)"
[[ -n "$ARCHITECT_THINK" ]] || die "--architect-think is required (no default architect sampling)"
[[ -n "$SAMPLING_SEED" ]] || die "--sampling-seed is required (no default architect sampling)"
[[ -n "$NUM_CTX" ]] || die "--num-ctx is required (no default architect sampling)"
[[ "$MODEL" == ollama_chat/* && "$EDITOR_MODEL" == ollama_chat/* ]] ||
    die "both models must use the native ollama_chat/ transport"
[[ "$OLLAMA_URL" != */v1 && "$OLLAMA_URL" != */v1/ ]] || die "--ollama-url must be the native Ollama root, not /v1"

REPO="$(cd "$(dirname "$0")/.." && pwd -P)" || die "cannot resolve the repository"
cd "$REPO" || die "cannot enter $REPO"
[[ "$(git rev-parse --show-toplevel 2>/dev/null)" == "$REPO" ]] ||
    die "$REPO is not the top of a Git checkout (run_experiment.sh resolves paths from it)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHON_BIN
export PYTHONDONTWRITEBYTECODE=1
export GIT_OPTIONAL_LOCKS=0
MODEL_PROVENANCE_JSON=""
export HELDOUT_ROOT="$REPO"

plan_args=(
    --repo "$REPO" --utility "$SELECTOR" --model "$MODEL" --editor-model "$EDITOR_MODEL"
    --temperature "$TEMPERATURE" --top-p "$TOP_P" --sampling-seed "$SAMPLING_SEED"
    --max-tokens "$MAX_TOKENS" --num-ctx "$NUM_CTX" --architect-think "$ARCHITECT_THINK"
    --editor-edit-format editor-diff --aider-version "aider 0.86.2" --max-loops "$MAX_LOOPS"
    --timeout-seconds "$TIMEOUT_SECONDS" --remote-base-url "$OLLAMA_URL"
)
PLAN_JSON="$("$PYTHON_BIN" scripts/lineage_plan.py "${plan_args[@]}" --emit plan)" ||
    die "lineage_plan.py could not resolve $SELECTOR"
STAGE_ROW="$("$PYTHON_BIN" scripts/lineage_plan.py "${plan_args[@]}" --emit stages | head -1)" ||
    die "lineage_plan.py could not emit stages for $SELECTOR"
IFS=$'\x1f' read -r STAGE_ID STAGE_NAME STAGE_PROMPT STAGE_MODE STAGE_CMD STAGE_FLAGS \
    STAGE_FINGERPRINT <<<"$STAGE_ROW"
[[ "$STAGE_ID" == 000 && "$STAGE_MODE" == new && -z "$STAGE_FLAGS" ]] ||
    die "stage plan did not resolve a clean checkpoint 000 (got '$STAGE_ID' '$STAGE_MODE' '$STAGE_FLAGS')"
[[ "$STAGE_FINGERPRINT" =~ ^[0-9a-f]{64}$ ]] || die "malformed planned bundle fingerprint"

plan_field() {
    "$PYTHON_BIN" -c 'import json,sys; v=json.loads(sys.argv[1])[sys.argv[2]]; print("" if v is None else v)' \
        "$PLAN_JSON" "$1"
}
SOURCE_PATH="$(plan_field source_path)"
BUILD_CMD="$(plan_field build_command)"
EXECUTABLE_PATH="$(plan_field executable_path)"
TEST_DIR="$(plan_field test_dir)"
BASE_TEST_CMD="$(plan_field base_test_command)"
EXTRA_TEST_CMD="$(plan_field extra_test_command)"
CONFIG_FINGERPRINT="$(plan_field config_fingerprint)"
[[ -n "$EXTRA_TEST_CMD" ]] || die "manifest has no held-out command; refusing a smoke test without held-out evaluation"

# Resolve symlinks before accepting either explicit output or any mktemp parent.
outside_path() {
    "$PYTHON_BIN" - "$REPO" "$1" <<'PY'
import sys
from pathlib import Path
repo, path = (Path(x).resolve() for x in sys.argv[1:])
if path == repo or repo in path.parents:
    raise SystemExit("diagnostic output and TMPDIR must be outside the repository")
print(path)
PY
}
TMPDIR="$(outside_path "${TMPDIR:-/tmp}")" || die "unsafe TMPDIR"
[[ -d "$TMPDIR" ]] || die "TMPDIR must be an existing directory"
export TMPDIR
if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DISPLAY="<new mktemp -d under $TMPDIR>"
else
    [[ ! -e "$OUTPUT_DIR" && ! -L "$OUTPUT_DIR" ]] || die "--output-dir must not exist yet: $OUTPUT_DIR"
    OUTPUT_DIR="$(outside_path "$OUTPUT_DIR")" || die "unsafe --output-dir"
    [[ -d "$(dirname "$OUTPUT_DIR")" ]] || die "parent of --output-dir must exist"
    OUTPUT_DISPLAY="$OUTPUT_DIR"
fi

stage_args() {
    # Same arguments run_lineage_experiment.sh builds for stage 000, with the
    # bundle path and stage directory supplied by the caller.
    local bundle="$1" stage_dir="$2"
    runner_args=(
        --model "$MODEL" --editor-model "$EDITOR_MODEL" --editor-edit-format editor-diff
        --temperature "$TEMPERATURE" --runs 1 --max-loops "$MAX_LOOPS"
        --timeout "$TIMEOUT_SECONDS" --prompt "$STAGE_PROMPT" --source "$SOURCE_PATH"
        --source-mode new --test-dir "$bundle:$TEST_DIR" --build-cmd "$BUILD_CMD"
        --feature-test-cmd "$STAGE_CMD" --output-dir "$stage_dir" --no-analysis
    )
    [[ -n "$MODEL_PROVENANCE_JSON" ]] && runner_args+=(--model-provenance-json "$MODEL_PROVENANCE_JSON")
    [[ -n "$TOP_P" ]] && runner_args+=(--top-p "$TOP_P")
    runner_args+=(--sampling-seed "$SAMPLING_SEED")
    [[ -n "$MAX_TOKENS" ]] && runner_args+=(--max-tokens "$MAX_TOKENS")
    runner_args+=(--num-ctx "$NUM_CTX" --architect-think "$ARCHITECT_THINK")
    [[ -n "$BASE_TEST_CMD" ]] && runner_args+=(--base-test-cmd "$BASE_TEST_CMD")
    runner_args+=(--extra-test-cmd "$EXTRA_TEST_CMD" --remote-base-url "$OLLAMA_URL")
}

printf 'Selector:    %s checkpoint %s (%s)\n' "$SELECTOR" "$STAGE_ID" "$STAGE_NAME"
printf 'Prompt:      %s\n' "$STAGE_PROMPT"
printf 'Bundle:      planned fingerprint %s\n' "$STAGE_FINGERPRINT"
printf 'Config:      %s\n' "$CONFIG_FINGERPRINT"
printf 'Lock:        %s\n' "${LINUX_BENCHMARK_LOCK:-${C_BENCHMARK_LOCK:-docker/linux-utilities/lock-amd64.json}}"
printf 'Output:      %s\n' "$OUTPUT_DISPLAY"

if [[ "$GENERATE" -eq 0 ]]; then
    stage_args "$OUTPUT_DISPLAY/000/test-bundle" "$OUTPUT_DISPLAY/000"
    printf '\nPrint-only (no --generate): planning only; no diagnostic output or generation. Would run:\n'
    printf '  bash scripts/run_experiment.sh'
    printf ' %q' "${runner_args[@]}"
    printf '\n'
    exit 0
fi

# Retain failed preflight evidence too; creating this directory never authorizes generation.
if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$(mktemp -d "$TMPDIR/linux-utilities-smoke-$SELECTOR.XXXXXX")" ||
        die "cannot create a temporary output directory"
else
    mkdir "$OUTPUT_DIR" || die "cannot create $OUTPUT_DIR"
fi
OUTPUT_DIR="$(outside_path "$OUTPUT_DIR")" || die "unsafe resolved output directory"
preflight_args=(--selector "$SELECTOR" --ollama-url "$OLLAMA_URL" --architect-model "$MODEL"
                --editor-model "$EDITOR_MODEL" --temperature "$TEMPERATURE"
                --architect-think "$ARCHITECT_THINK" --sampling-seed "$SAMPLING_SEED"
                --num-ctx "$NUM_CTX" --json-report "$OUTPUT_DIR/preflight.json")
[[ -n "$MAX_TOKENS" ]] && preflight_args+=(--max-tokens "$MAX_TOKENS")
[[ -n "$TOP_P" ]] && preflight_args+=(--top-p "$TOP_P")
"$PYTHON_BIN" scripts/vessel_preflight.py "${preflight_args[@]}" >"$OUTPUT_DIR/preflight.log" 2>&1
preflight_status=$?
cat "$OUTPUT_DIR/preflight.log"
if [[ "$preflight_status" -ne 0 ]]; then
    printf 'error: preflight failed; no generation was started; evidence: %s\n' "$OUTPUT_DIR" >&2
    exit 4
fi
MODEL_PROVENANCE_JSON="$("$PYTHON_BIN" - "$OUTPUT_DIR/preflight.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
if report.get("preflight_passed") is not True or set(report.get("models", {})) != {"architect", "editor"}:
    raise SystemExit("successful preflight with both model identities is required")
print(json.dumps({"diagnostic_observed_models": report["models"]}, separators=(",", ":")))
PY
)" || { printf 'error: invalid preflight evidence; no generation started\n' >&2; exit 4; }
plan_args+=(--model-provenance-json "$MODEL_PROVENANCE_JSON")
PLAN_JSON="$("$PYTHON_BIN" scripts/lineage_plan.py "${plan_args[@]}" --emit plan)" || die "cannot record observed provenance"
CONFIG_FINGERPRINT="$(plan_field config_fingerprint)"
STAGE_DIR="$OUTPUT_DIR/000"
BUNDLE_DIR="$STAGE_DIR/test-bundle"
mkdir -p "$STAGE_DIR" || die "cannot create $STAGE_DIR"
printf 'Output:      %s\n' "$OUTPUT_DIR"

built="$("$PYTHON_BIN" scripts/stage_test_bundle.py --repo "$REPO" --utility "$SELECTOR" \
    --checkpoint 000 --output "$BUNDLE_DIR" --emit fingerprint)" || {
    printf 'error: failed to build the checkpoint-000 bundle\n' >&2; exit 1; }
[[ "$built" == "$STAGE_FINGERPRINT" ]] || {
    printf 'error: bundle fingerprint %s != planned %s\n' "$built" "$STAGE_FINGERPRINT" >&2; exit 1; }
printf '%s\n' "$PLAN_JSON" >"$OUTPUT_DIR/plan.json"

stage_args "$BUNDLE_DIR" "$STAGE_DIR"
printf '%q ' bash scripts/run_experiment.sh "${runner_args[@]}" >"$OUTPUT_DIR/command.txt"
printf '\n' >>"$OUTPUT_DIR/command.txt"
bash scripts/run_experiment.sh "${runner_args[@]}"
runner_status=$?

TEMP_SLUG="$("$PYTHON_BIN" scripts/temperature_value.py slug "$TEMPERATURE")" || {
    printf 'error: cannot compute the temperature slug\n' >&2; exit 1; }
ATTEMPT="$STAGE_DIR/temp-$TEMP_SLUG/attempt-001"
CANDIDATE="$ATTEMPT/candidate/$(basename "$SOURCE_PATH")"
GATE_REPORT="$STAGE_DIR/boundary-gate.json"
gate_status=""
public_ok="$("$PYTHON_BIN" -c 'import json,sys; m=json.load(open(sys.argv[1])); print("yes" if m.get("public_validation_success") is True else "no")' \
    "$ATTEMPT/metadata.json" 2>/dev/null || printf 'no')"
if [[ "$public_ok" == yes && -f "$CANDIDATE" ]]; then
    # As in run_lineage_experiment.sh boundary_gate(): rebuild the captured
    # candidate in a throwaway tree, then probe later-checkpoint options. The
    # result is controller-only and never reaches the agent.
    work="$(mktemp -d)" || { printf 'error: mktemp failed\n' >&2; exit 1; }
    mkdir -p "$work/$(dirname "$SOURCE_PATH")" && cp "$CANDIDATE" "$work/$SOURCE_PATH"
    if ( cd "$work" && eval "$BUILD_CMD" ) >"$STAGE_DIR/boundary-gate-build.log" 2>&1; then
        "$PYTHON_BIN" scripts/checkpoint_boundary_gate.py --repo "$REPO" --utility "$SELECTOR" \
            --checkpoint 000 --executable "$work/$EXECUTABLE_PATH" --report "$GATE_REPORT" \
            >"$STAGE_DIR/boundary-gate.log" 2>&1
        gate_status=$?
    else
        gate_status=2
    fi
    rm -rf "$work"
fi

"$PYTHON_BIN" - "$ATTEMPT" "$CANDIDATE" "$runner_status" "$gate_status" "$GATE_REPORT" \
    "$OUTPUT_DIR/smoke-summary.json" "$SELECTOR" "$CONFIG_FINGERPRINT" "$built" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

attempt, candidate, runner, gate, gate_report, out, selector, config, bundle = sys.argv[1:]
attempt, candidate = Path(attempt), Path(candidate)
meta = {}
if (attempt / "metadata.json").is_file():
    meta = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
public = meta.get("public_validation_success") is True
if not attempt.is_dir():
    public_outcome = "stage_runner_failure"
elif not (attempt / "COMPLETE").is_file():
    public_outcome = "stage_run_incomplete"
elif meta.get("infrastructure_failure"):
    public_outcome = "infrastructure_failure"
elif meta.get("agent_execution_failure"):
    public_outcome = "agent_execution_failure"
elif meta.get("feature_test_exit_code") == 3:
    public_outcome = "platform_incompatible"
elif not public:
    public_outcome = str(meta.get("stop_reason") or "validation_failed")
elif not candidate.is_file():
    public_outcome = "candidate_missing"
elif gate == "1":
    public_outcome = "premature_feature_implementation"
elif gate != "0":
    public_outcome = "boundary_gate_error"
else:
    public_outcome = "public_pass"
heldout = {0: "heldout_pass", 1: "heldout_fail", 2: "heldout_infrastructure_failure",
           3: "platform_incompatible", None: "not_run"}.get(meta.get("extra_test_exit_code"), "unknown")
infrastructure = (public_outcome in ("stage_runner_failure", "stage_run_incomplete", "infrastructure_failure",
                                     "platform_incompatible", "boundary_gate_error")
                  or heldout in ("heldout_infrastructure_failure", "platform_incompatible", "unknown"))
summary = {
    "diagnostic_only": True, "formal_result": False, "lineage_seed": False,
    "preflight_report": "preflight.json",
    "selector": selector, "checkpoint": "000", "config_fingerprint": config,
    "test_bundle_fingerprint": bundle, "run_experiment_exit_code": int(runner),
    "public_outcome": public_outcome, "heldout_outcome": heldout,
    "boundary_gate_exit_code": int(gate) if gate else None,
    "boundary_gate": json.loads(Path(gate_report).read_text()) if Path(gate_report).is_file() else None,
    "infrastructure_failure": infrastructure,
    "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest() if candidate.is_file() else None,
}
for key in ("initial_success", "repair_loops", "llm_invocations", "stop_reason", "timeout_enforced",
            "timeout_seconds", "build_exit_code", "feature_test_exit_code", "extra_test_exit_code",
            "infrastructure_failure_stage", "agent_execution_failure_stage", "agent_failure_reason",
            "overall_success", "aider_version", "model_provenance", "architect_sampling", "editor_sampling",
            "editor_edit_format", "remote_base_url", "remote_transport", "total_runtime_ms"):
    summary[key] = meta.get(key)
Path(out).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print("public=%s heldout=%s infrastructure_failure=%s timeout_enforced=%s -> %s" % (
    public_outcome, heldout, infrastructure, summary["timeout_enforced"], out))
sys.exit(1 if infrastructure or summary["timeout_enforced"] is not True else 0)
PY
