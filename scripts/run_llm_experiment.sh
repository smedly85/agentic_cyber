#!/usr/bin/env bash
# Run repeated OpenCode patch-generation experiments in isolated Git worktrees.
#
# Example:
#   scripts/run_llm_experiment.sh \
#     --model school-ollama/qwen3-coder-next:latest \
#     --temperature 0.0 \
#     --runs 25 \
#     --max-loops 3 \
#     --prompt prompts/new_sort/001_reverse.md \
#     --feature-test-cmd "python3 -m unittest tests/new_sort/test_001_reverse.py -v"
#
# The script never commits generated changes. Each run is created from the
# same baseline commit and stored under runs/experiments/ by default.

set -uo pipefail

usage() {
    cat <<'EOF'
Usage:
  run_llm_experiment.sh --model MODEL --temperature TEMP --prompt FILE [options]

Required:
  --model MODEL              OpenCode model name, e.g.
                             school-ollama/qwen3-coder-next:latest
  --temperature TEMP         Sampling temperature, e.g. 0, 0.2, 0.7
  --prompt FILE              Prompt file relative to the repository or absolute

Options:
  --runs N                   Number of attempts (default: 100)
  --max-loops N              Maximum repair invocations after the initial
                             generation (default: 0)
  --agent NAME               OpenCode agent (default: build)
  --base-ref REF             Commit/tag/branch used for every attempt (default: HEAD)
  --source PATH              Primary source file to preserve (default:
                             src/new_sort/new_sort.c)
  --source-mode MODE         existing requires the source at the baseline;
                             new requires it to be absent (default: existing)
  --output-dir DIR           Experiment directory. If omitted, a deterministic
                             directory is derived from model, prompt, and temperature.
  --build-cmd CMD            Build command (default: make clean && make)
  --base-test-cmd CMD        Baseline test command. Empty disables it.
  --feature-test-cmd CMD     Checkpoint/flag test command. Empty disables it.
  --extra-test-cmd CMD       Optional sanitizer/hidden/property-test command.
  --timeout SECONDS          OpenCode timeout per run; 0 disables (default: 1800)
  --force                    Delete and rerun completed attempt directories
  --analysis-threshold X     Compatibility shorthand setting both analysis
                             thresholds unless a specific option overrides it
  --analysis-architecture-threshold X
                             Architecture clustering threshold (default: 0.30)
  --analysis-strategy-threshold X
                             Strategy threshold (default: architecture threshold)
  --analysis-diversity-k-max K
                             Fixed family-discovery sampling budget (default: unset)
  -h, --help                 Show this help

Environment:
  OPENCODE_BIN               OpenCode executable (default: opencode)
  PYTHON_BIN                 Python executable (default: python3)

Directory layout:
  <output-dir>/
    experiment.json
    baseline/
    attempt-001/
      metadata.json
      opencode.log
      patch.diff
      diff-numstat.txt
      changed-files.txt
      candidate/
      build.log
      base-tests.log
      feature-tests.log
      extra-tests.log
    analysis/

Repair prompts include only failing validation output. Each included output is
deterministically limited to its final 16000 characters.
EOF
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 2
}

json_value() {
    # Safely JSON-encode one string.
    "${PYTHON_BIN}" -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
}

slugify() {
    printf '%s' "$1" |
        tr '[:upper:]' '[:lower:]' |
        sed -E 's#[^a-z0-9._-]+#-#g; s#^-+##; s#-+$##'
}

write_metadata() {
    local file="$1"
    shift
    "${PYTHON_BIN}" - "$file" "$@" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
pairs = sys.argv[2:]
if len(pairs) % 2:
    raise SystemExit("metadata requires key/value pairs")

data = {}
for i in range(0, len(pairs), 2):
    key, value = pairs[i], pairs[i + 1]
    if value.startswith("__JSON__:"):
        data[key] = json.loads(value.removeprefix("__JSON__:"))
        continue
    if value in {"true", "false"}:
        data[key] = value == "true"
        continue
    try:
        if any(ch in value for ch in ".eE"):
            data[key] = float(value)
        else:
            data[key] = int(value)
    except ValueError:
        data[key] = value

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
}

copy_changed_files() {
    local worktree="$1"
    local destination="$2"
    local base_commit="$3"

    mkdir -p "$destination"

    {
        git -C "$worktree" diff --name-only --diff-filter=ACMRTUXB "$base_commit" --
        git -C "$worktree" ls-files --others --exclude-standard
    } | awk 'NF && !seen[$0]++' |
    while IFS= read -r relative_path; do
        [[ -f "$worktree/$relative_path" ]] || continue
        mkdir -p "$destination/$(dirname "$relative_path")"
        cp -p "$worktree/$relative_path" "$destination/$relative_path"
    done
}

capture_candidate_artifacts() {
    local worktree="$1"
    local attempt_dir="$2"
    local base_commit="$3"
    local source_path="$4"

    git -C "$worktree" status --short >"$attempt_dir/git-status.txt"
    git -C "$worktree" diff --binary "$base_commit" -- >"$attempt_dir/patch.diff"
    git -C "$worktree" diff --numstat "$base_commit" -- \
        >"$attempt_dir/diff-numstat.txt"
    git -C "$worktree" diff --name-status "$base_commit" -- \
        >"$attempt_dir/changed-files.txt"
    git -C "$worktree" diff --stat "$base_commit" -- \
        >"$attempt_dir/diff-stat.txt"
    git -C "$worktree" ls-files --others --exclude-standard \
        >"$attempt_dir/untracked-files.txt"

    rm -rf "$attempt_dir/candidate"
    copy_changed_files "$worktree" "$attempt_dir/candidate" "$base_commit"

    # Always preserve the primary source, even if OpenCode did not modify it.
    mkdir -p "$attempt_dir/candidate/$(dirname "$source_path")"
    if [[ -f "$worktree/$source_path" ]]; then
        cp -p "$worktree/$source_path" \
            "$attempt_dir/candidate/$source_path"
    fi
}

run_logged_command() {
    # Usage: run_logged_command LOGFILE COMMAND LOOP STAGE
    local logfile="$1"
    local command="$2"
    local loop="$3"
    local stage="$4"
    local start_ns end_ns status

    printf '\n===== VALIDATION LOOP %s: %s =====\n\n' \
        "$loop" "$stage" >>"$logfile"
    if [[ -z "$command" ]]; then
        printf '%s %s\n' 0 0
        return
    fi

    start_ns="$(date +%s%N)"
    (
        set +e
        eval "$command"
    ) >>"$logfile" 2>&1
    status=$?
    end_ns="$(date +%s%N)"

    printf '%s %s\n' "$status" "$(( (end_ns - start_ns) / 1000000 ))"
}

run_final_command() {
    # Usage: run_final_command LOGFILE COMMAND
    local logfile="$1"
    local command="$2"
    local start_ns end_ns status

    if [[ -z "$command" ]]; then
        : >"$logfile"
        printf '%s %s\n' 0 0
        return
    fi

    start_ns="$(date +%s%N)"
    (
        set +e
        eval "$command"
    ) >"$logfile" 2>&1
    status=$?
    end_ns="$(date +%s%N)"

    printf '%s %s\n' "$status" "$(( (end_ns - start_ns) / 1000000 ))"
}

run_opencode() {
    # Usage: run_opencode LOGFILE WORKTREE PROMPT INVOCATION KIND
    local logfile="$1"
    local worktree="$2"
    local prompt="$3"
    local invocation="$4"
    local kind="$5"
    local current_log start_ns end_ns status runtime_ms permission_rejected

    current_log="$attempt_dir/.opencode-current.log"
    printf '\n===== LLM INVOCATION %s: %s =====\n\n' \
        "$invocation" "$kind" >>"$logfile"
    start_ns="$(date +%s%N)"
    if [[ "$TIMEOUT_SECONDS" -gt 0 ]]; then
        OPENCODE_CONFIG_CONTENT="$ATTEMPT_OPENCODE_CONFIG_CONTENT" \
            timeout --signal=TERM --kill-after=30 \
            "$TIMEOUT_SECONDS" \
            "$OPENCODE_BIN" run \
                --dir "$worktree" \
                --model "$MODEL" \
                --agent "$AGENT" \
                "$prompt"
    else
        OPENCODE_CONFIG_CONTENT="$ATTEMPT_OPENCODE_CONFIG_CONTENT" \
            "$OPENCODE_BIN" run \
                --dir "$worktree" \
                --model "$MODEL" \
                --agent "$AGENT" \
                "$prompt"
    fi >"$current_log" 2>&1
    status=$?
    end_ns="$(date +%s%N)"
    runtime_ms=$(( (end_ns - start_ns) / 1000000 ))

    permission_rejected=false
    if grep -Eiq \
            'permission requested:[[:space:]]*external_directory|auto-rejecting|user rejected permission' \
            "$current_log"; then
        permission_rejected=true
    fi
    cat "$current_log" >>"$logfile"
    rm -f "$current_log"
    printf '%s %s %s\n' "$status" "$runtime_ms" "$permission_rejected"
}

build_repair_prompt() {
    local validation_loop="$1"
    local build_exit="$2"
    local base_test_exit="$3"
    local feature_test_exit="$4"

    "$PYTHON_BIN" - \
        "$validation_loop" \
        "$build_exit" "$attempt_dir/build.log" \
        "$base_test_exit" "$attempt_dir/base-tests.log" \
        "$feature_test_exit" "$attempt_dir/feature-tests.log" \
        "$prompt_text" <<'PY'
import sys
from pathlib import Path

loop = int(sys.argv[1])
stages = [
    ("Build", int(sys.argv[2]), Path(sys.argv[3])),
    ("Base-test", int(sys.argv[4]), Path(sys.argv[5])),
    ("Checkpoint-test", int(sys.argv[6]), Path(sys.argv[7])),
]
original_prompt = sys.argv[8]
limit = 16_000


def failure_output(name: str, exit_code: int, path: Path) -> str:
    if exit_code == 0:
        return "(passed; output omitted)"
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = f"===== VALIDATION LOOP {loop}:"
    marker_index = text.rfind(marker)
    if marker_index >= 0:
        section = text[marker_index:].split("\n", 2)
        text = section[2] if len(section) == 3 else ""
    if len(text) > limit:
        text = (
            f"[truncated deterministically to final {limit} characters]\n"
            + text[-limit:]
        )
    return text.rstrip() or f"({name.lower()} failed without output)"


outputs = {
    name: failure_output(name, exit_code, path)
    for name, exit_code, path in stages
}
print(
    f"""Your previous implementation for the original task did not pass the required validation.

Continue working on the CURRENT implementation in this worktree.

Do not restart the task.
Do not revert to the baseline.
Do not modify, weaken, disable, or delete the tests.
Make only changes necessary to satisfy the original task.

Original task:
{original_prompt}

Build exit code:
{stages[0][1]}

Base-test exit code:
{stages[1][1]}

Checkpoint-test exit code:
{stages[2][1]}

Build output:
{outputs['Build']}

Base-test output:
{outputs['Base-test']}

Checkpoint-test output:
{outputs['Checkpoint-test']}

Repair the current implementation so that it builds successfully and all required base and checkpoint tests pass."""
)
PY
}

make_loop_record() {
    "$PYTHON_BIN" - "$@" <<'PY'
import json
import sys

(
    loop,
    kind,
    opencode_exit,
    permission_rejected,
    build_exit,
    base_test_exit,
    feature_test_exit,
    opencode_ms,
    build_ms,
    base_test_ms,
    feature_test_ms,
    validation_success,
) = sys.argv[1:]
print(json.dumps({
    "loop": int(loop),
    "kind": kind,
    "opencode_exit_code": int(opencode_exit),
    "opencode_permission_rejected": permission_rejected == "true",
    "build_exit_code": int(build_exit),
    "base_test_exit_code": int(base_test_exit),
    "feature_test_exit_code": int(feature_test_exit),
    "opencode_runtime_ms": int(opencode_ms),
    "build_runtime_ms": int(build_ms),
    "base_test_runtime_ms": int(base_test_ms),
    "feature_test_runtime_ms": int(feature_test_ms),
    "validation_success": validation_success == "true",
}, separators=(",", ":")))
PY
}

MODEL=""
TEMPERATURE=""
PROMPT=""
RUNS=100
MAX_LOOPS=0
AGENT="build"
BASE_REF="HEAD"
SOURCE_PATH="src/new_sort/new_sort.c"
SOURCE_MODE="existing"
OUTPUT_DIR=""
BUILD_CMD="make clean && make"
BASE_TEST_CMD="PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/new_sort/test_new_sort.py -v"
FEATURE_TEST_CMD=""
EXTRA_TEST_CMD=""
TIMEOUT_SECONDS=1800
FORCE=0
ANALYSIS_THRESHOLD=""
ANALYSIS_ARCHITECTURE_THRESHOLD=""
ANALYSIS_STRATEGY_THRESHOLD=""
ANALYSIS_DIVERSITY_K_MAX=""

OPENCODE_BIN="${OPENCODE_BIN:-opencode}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODEL="${2:-}"; shift 2 ;;
        --temperature) TEMPERATURE="${2:-}"; shift 2 ;;
        --prompt) PROMPT="${2:-}"; shift 2 ;;
        --runs) RUNS="${2:-}"; shift 2 ;;
        --max-loops)
            [[ $# -ge 2 ]] || die "--max-loops requires a value"
            MAX_LOOPS="$2"
            shift 2
            ;;
        --agent) AGENT="${2:-}"; shift 2 ;;
        --base-ref) BASE_REF="${2:-}"; shift 2 ;;
        --source)
            [[ $# -ge 2 ]] || die "--source requires a value"
            SOURCE_PATH="$2"
            shift 2
            ;;
        --source-mode)
            [[ $# -ge 2 ]] || die "--source-mode requires a value"
            SOURCE_MODE="$2"
            shift 2
            ;;
        --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
        --build-cmd) BUILD_CMD="${2:-}"; shift 2 ;;
        --base-test-cmd) BASE_TEST_CMD="${2:-}"; shift 2 ;;
        --feature-test-cmd) FEATURE_TEST_CMD="${2:-}"; shift 2 ;;
        --extra-test-cmd) EXTRA_TEST_CMD="${2:-}"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
        --analysis-threshold)
            [[ $# -ge 2 ]] || die "--analysis-threshold requires a value"
            ANALYSIS_THRESHOLD="$2"
            shift 2
            ;;
        --analysis-architecture-threshold)
            [[ $# -ge 2 ]] ||
                die "--analysis-architecture-threshold requires a value"
            ANALYSIS_ARCHITECTURE_THRESHOLD="$2"
            shift 2
            ;;
        --analysis-strategy-threshold)
            [[ $# -ge 2 ]] ||
                die "--analysis-strategy-threshold requires a value"
            ANALYSIS_STRATEGY_THRESHOLD="$2"
            shift 2
            ;;
        --analysis-diversity-k-max)
            [[ $# -ge 2 ]] ||
                die "--analysis-diversity-k-max requires a value"
            ANALYSIS_DIVERSITY_K_MAX="$2"
            shift 2
            ;;
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[[ -n "$MODEL" ]] || die "--model is required"
[[ -n "$TEMPERATURE" ]] || die "--temperature is required"
[[ -n "$PROMPT" ]] || die "--prompt is required"
[[ "$RUNS" =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer"
[[ "$MAX_LOOPS" =~ ^[0-9]+$ ]] || die "--max-loops must be a non-negative integer"
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--timeout must be a non-negative integer"
[[ "$SOURCE_MODE" == "existing" || "$SOURCE_MODE" == "new" ]] ||
    die "--source-mode must be existing or new"

command -v git >/dev/null 2>&1 || die "git is required"
command -v "$OPENCODE_BIN" >/dev/null 2>&1 || die "$OPENCODE_BIN was not found"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN was not found"
"$PYTHON_BIN" - "$SOURCE_PATH" <<'PY' ||
import sys
from pathlib import PurePosixPath

raw = sys.argv[1]
path = PurePosixPath(raw)
valid = bool(raw) and not path.is_absolute() and ".." not in path.parts
valid = valid and str(path) == raw and "\\" not in raw
raise SystemExit(0 if valid else 1)
PY
    die "--source must be a normalized repository-relative path without '..'"

if [[ -n "$ANALYSIS_ARCHITECTURE_THRESHOLD" ]]; then
    RESOLVED_ANALYSIS_ARCHITECTURE_THRESHOLD="$ANALYSIS_ARCHITECTURE_THRESHOLD"
elif [[ -n "$ANALYSIS_THRESHOLD" ]]; then
    RESOLVED_ANALYSIS_ARCHITECTURE_THRESHOLD="$ANALYSIS_THRESHOLD"
else
    RESOLVED_ANALYSIS_ARCHITECTURE_THRESHOLD="0.30"
fi
if [[ -n "$ANALYSIS_STRATEGY_THRESHOLD" ]]; then
    RESOLVED_ANALYSIS_STRATEGY_THRESHOLD="$ANALYSIS_STRATEGY_THRESHOLD"
elif [[ -n "$ANALYSIS_THRESHOLD" ]]; then
    RESOLVED_ANALYSIS_STRATEGY_THRESHOLD="$ANALYSIS_THRESHOLD"
else
    RESOLVED_ANALYSIS_STRATEGY_THRESHOLD="$RESOLVED_ANALYSIS_ARCHITECTURE_THRESHOLD"
fi
"$PYTHON_BIN" -c 'import math,sys; values=map(float,sys.argv[1:]); sys.exit(0 if all(math.isfinite(v) and v > 0 for v in values) else 1)' \
    "$RESOLVED_ANALYSIS_ARCHITECTURE_THRESHOLD" \
    "$RESOLVED_ANALYSIS_STRATEGY_THRESHOLD" ||
    die "analysis thresholds must be positive numbers"
if [[ -n "$ANALYSIS_DIVERSITY_K_MAX" &&
      ! "$ANALYSIS_DIVERSITY_K_MAX" =~ ^[1-9][0-9]*$ ]]; then
    die "--analysis-diversity-k-max must be a positive integer"
fi

MAX_LOOPS="$("$PYTHON_BIN" - "$MAX_LOOPS" <<'PY'
import sys

value = int(sys.argv[1], 10)
if value > sys.maxsize:
    raise SystemExit(1)
print(value)
PY
)" || die "--max-loops is too large for this platform"

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" ||
    die "run this script inside a Git repository"
REPO="$(cd "$REPO" && pwd -P)"

if [[ "$PROMPT" != /* ]]; then
    PROMPT="$REPO/$PROMPT"
fi
[[ -f "$PROMPT" ]] || die "prompt not found: $PROMPT"

BASE_COMMIT="$(git -C "$REPO" rev-parse "$BASE_REF^{commit}")" ||
    die "cannot resolve base ref: $BASE_REF"
BASELINE_SOURCE_EXISTS=false
BASELINE_SOURCE_TYPE=""
if BASELINE_SOURCE_TYPE="$(git -C "$REPO" cat-file -t "$BASE_COMMIT:$SOURCE_PATH" 2>/dev/null)"; then
    BASELINE_SOURCE_EXISTS=true
fi
if [[ "$SOURCE_MODE" == "existing" && "$BASELINE_SOURCE_EXISTS" == false ]]; then
    die "source file not found in baseline commit for --source-mode existing: $SOURCE_PATH"
fi
if [[ "$SOURCE_MODE" == "existing" && "$BASELINE_SOURCE_TYPE" != "blob" ]]; then
    die "baseline source is not a file blob: $SOURCE_PATH"
fi
if [[ "$SOURCE_MODE" == "new" && "$BASELINE_SOURCE_EXISTS" == true ]]; then
    die "source file already exists in baseline commit for --source-mode new: $SOURCE_PATH"
fi

MODEL_SLUG="$(slugify "$MODEL")"
PROMPT_SLUG="$(slugify "$(basename "${PROMPT%.*}")")"
TEMP_SLUG="$(slugify "$TEMPERATURE" | sed 's/\./p/g')"

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$REPO/runs/experiments/$MODEL_SLUG/$PROMPT_SLUG/temp-$TEMP_SLUG"
elif [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="$REPO/$OUTPUT_DIR"
fi
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"

if [[ -f "$OUTPUT_DIR/experiment.json" ]]; then
    EXISTING_MISMATCHES="$(
        "$PYTHON_BIN" - "$OUTPUT_DIR/experiment.json" \
            "$BASE_COMMIT" "$MODEL" "$TEMPERATURE" "$AGENT" "$PROMPT" \
            "$SOURCE_PATH" "$SOURCE_MODE" "$MAX_LOOPS" "$BUILD_CMD" \
            "$BASE_TEST_CMD" "$FEATURE_TEST_CMD" "$EXTRA_TEST_CMD" \
            "$RESOLVED_ANALYSIS_ARCHITECTURE_THRESHOLD" \
            "$RESOLVED_ANALYSIS_STRATEGY_THRESHOLD" \
            "${ANALYSIS_DIVERSITY_K_MAX:-__NONE__}" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
(
    base_commit,
    model,
    temperature,
    agent,
    prompt,
    source_path,
    source_mode,
    max_loops,
    build_command,
    base_test_command,
    feature_test_command,
    extra_test_command,
    architecture_threshold,
    strategy_threshold,
    diversity_k_max,
) = sys.argv[2:]
expected = {
    "base_commit": base_commit,
    "model": model,
    "temperature": float(temperature),
    "agent": agent,
    "prompt": prompt,
    "source_path": source_path,
    "source_mode": source_mode,
    "max_loops": int(max_loops),
    "build_command": build_command,
    "base_test_command": base_test_command,
    "feature_test_command": feature_test_command,
    "extra_test_command": extra_test_command,
    "analysis_architecture_threshold": float(architecture_threshold),
    "analysis_strategy_threshold": float(strategy_threshold),
    "analysis_diversity_k_max": (
        None if diversity_k_max == "__NONE__" else int(diversity_k_max)
    ),
}
print(", ".join(key for key, value in expected.items() if data.get(key) != value))
PY
    )" || die "cannot read existing experiment metadata"
    [[ -z "$EXISTING_MISMATCHES" ]] ||
        die "output directory experiment configuration differs: $EXISTING_MISMATCHES"
fi

BASELINE_DIR="$OUTPUT_DIR/baseline"
mkdir -p "$BASELINE_DIR/$(dirname "$SOURCE_PATH")"
if [[ "$SOURCE_MODE" == "existing" ]]; then
    git -C "$REPO" show "$BASE_COMMIT:$SOURCE_PATH" \
        > "$BASELINE_DIR/$SOURCE_PATH"
    BASELINE_SOURCE_KIND="existing_source_snapshot"
else
    : > "$BASELINE_DIR/$SOURCE_PATH"
    BASELINE_SOURCE_KIND="empty_new_source"
fi

PROMPT_COPY="$OUTPUT_DIR/prompt.md"
cp "$PROMPT" "$PROMPT_COPY"

ANALYZER_PATH="$REPO/scripts/analyze_experiment.py"
[[ -f "$ANALYZER_PATH" ]] || die "analyzer not found: $ANALYZER_PATH"

write_metadata "$OUTPUT_DIR/experiment.json" \
    schema_version 2 \
    repository "$REPO" \
    base_ref "$BASE_REF" \
    base_commit "$BASE_COMMIT" \
    model "$MODEL" \
    temperature "$TEMPERATURE" \
    agent "$AGENT" \
    prompt "$PROMPT" \
    prompt_copy "$PROMPT_COPY" \
    source_path "$SOURCE_PATH" \
    source_mode "$SOURCE_MODE" \
    baseline_source_kind "$BASELINE_SOURCE_KIND" \
    requested_runs "$RUNS" \
    max_loops "$MAX_LOOPS" \
    build_command "$BUILD_CMD" \
    base_test_command "$BASE_TEST_CMD" \
    feature_test_command "$FEATURE_TEST_CMD" \
    extra_test_command "$EXTRA_TEST_CMD" \
    analysis_architecture_threshold "$RESOLVED_ANALYSIS_ARCHITECTURE_THRESHOLD" \
    analysis_strategy_threshold "$RESOLVED_ANALYSIS_STRATEGY_THRESHOLD" \
    analysis_diversity_k_max "$([[ -n "$ANALYSIS_DIVERSITY_K_MAX" ]] && printf '%s' "$ANALYSIS_DIVERSITY_K_MAX" || printf '__JSON__:null')" \
    created_at "$(date --iso-8601=seconds)"

"$PYTHON_BIN" -c 'import sys; float(sys.argv[1])' "$TEMPERATURE" ||
    die "temperature must be numeric"

printf 'Repository:  %s\n' "$REPO"
printf 'Baseline:    %s (%s)\n' "$BASE_REF" "$BASE_COMMIT"
printf 'Model:       %s\n' "$MODEL"
printf 'Temperature: %s\n' "$TEMPERATURE"
printf 'Prompt:      %s\n' "$PROMPT"
printf 'Runs:        %s\n' "$RUNS"
printf 'Max loops:   %s\n' "$MAX_LOOPS"
printf 'Output:      %s\n\n' "$OUTPUT_DIR"

for attempt_number in $(seq 1 "$RUNS"); do
    attempt_id="$(printf 'attempt-%03d' "$attempt_number")"
    attempt_dir="$OUTPUT_DIR/$attempt_id"
    worktree="$attempt_dir/worktree"

    if [[ -f "$attempt_dir/COMPLETE" && "$FORCE" -eq 0 ]]; then
        printf '[%s/%s] %s already complete; skipping\n' \
            "$attempt_number" "$RUNS" "$attempt_id"
        continue
    fi

    printf '[%s/%s] starting %s\n' "$attempt_number" "$RUNS" "$attempt_id"

    if [[ -d "$attempt_dir" ]]; then
        git -C "$REPO" worktree remove --force "$worktree" >/dev/null 2>&1 || true
        rm -rf "$attempt_dir"
    fi
    mkdir -p "$attempt_dir"

    git -C "$REPO" worktree prune
    if ! git -C "$REPO" worktree add --detach "$worktree" "$BASE_COMMIT" \
            >"$attempt_dir/worktree-add.log" 2>&1; then
        write_metadata "$attempt_dir/metadata.json" \
            schema_version 2 \
            run_id "$attempt_id" \
            model "$MODEL" \
            temperature "$TEMPERATURE" \
            setup_exit_code 1 \
            infrastructure_failure true \
            infrastructure_failure_stage setup \
            infrastructure_failure_classification_inferred false \
            agent_execution_failure false \
            agent_execution_failure_stage "__JSON__:null" \
            agent_execution_failure_classification_inferred false \
            opencode_permission_rejected false \
            max_loops "$MAX_LOOPS" \
            initial_success false \
            repair_loops 0 \
            llm_invocations 0 \
            success_loop "__JSON__:null" \
            loop_limit_reached false \
            public_validation_success false \
            initial_opencode_runtime_ms 0 \
            repair_opencode_runtime_ms 0 \
            total_opencode_runtime_ms 0 \
            total_runtime_ms 0 \
            loops "__JSON__:[]" \
            overall_success false
        touch "$attempt_dir/COMPLETE"
        printf '  worktree creation failed; see %s\n' \
            "$attempt_dir/worktree-add.log" >&2
        continue
    fi

    ATTEMPT_OPENCODE_CONFIG_CONTENT="$(
        "$PYTHON_BIN" - "$AGENT" "$TEMPERATURE" "$attempt_dir" <<'PY'
import json
import sys
from pathlib import Path

agent = sys.argv[1]
temperature = float(sys.argv[2])
attempt_dir = str(Path(sys.argv[3]).resolve())
escaped_attempt_dir = attempt_dir.replace(" ", r"\ ")
external_directory = {
    "*": "deny",
    attempt_dir: "allow",
    f"{attempt_dir}/**": "allow",
}
if escaped_attempt_dir != attempt_dir:
    # OpenCode 1.17.20 preserves backslash-escaped spaces in bash path checks.
    external_directory[escaped_attempt_dir] = "allow"
    external_directory[f"{escaped_attempt_dir}/**"] = "allow"
config = {
    "$schema": "https://opencode.ai/config.json",
    "agent": {
        agent: {
            "temperature": temperature,
            "permission": {
                "external_directory": external_directory,
            },
        }
    },
}
print(json.dumps(config))
PY
    )" || die "failed to build per-attempt OpenCode configuration"

    prompt_text="$(cat "$PROMPT")"
    : >"$attempt_dir/opencode.log"
    : >"$attempt_dir/build.log"
    : >"$attempt_dir/base-tests.log"
    : >"$attempt_dir/feature-tests.log"

    validation_loop=0
    current_prompt="$prompt_text"
    repair_loops=0
    total_opencode_ms=0
    initial_opencode_ms=0
    repair_opencode_ms=0
    total_build_ms=0
    total_base_test_ms=0
    total_feature_test_ms=0
    opencode_permission_rejected=false
    initial_success=false
    public_validation_success=false
    success_loop_json=null
    infrastructure_failed=false
    infrastructure_failure_stage_json=null
    agent_execution_failed=false
    agent_execution_failure_stage_json=null
    loop_records=()

    while true; do
        if [[ "$validation_loop" -eq 0 ]]; then
            invocation_kind="INITIAL"
            loop_kind="initial"
        else
            invocation_kind="REPAIR LOOP $validation_loop"
            loop_kind="repair"
            repair_loops=$((repair_loops + 1))
        fi

        read -r opencode_exit opencode_ms invocation_permission_rejected < <(
            run_opencode \
                "$attempt_dir/opencode.log" \
                "$worktree" \
                "$current_prompt" \
                "$validation_loop" \
                "$invocation_kind"
        )
        total_opencode_ms=$((total_opencode_ms + opencode_ms))
        if [[ "$validation_loop" -eq 0 ]]; then
            initial_opencode_ms="$opencode_ms"
        else
            repair_opencode_ms=$((repair_opencode_ms + opencode_ms))
        fi
        if [[ "$invocation_permission_rejected" == true ]]; then
            opencode_permission_rejected=true
        fi
        invocation_agent_execution_failed=false
        if [[ "$invocation_permission_rejected" == true ]]; then
            invocation_agent_execution_failed=true
            agent_execution_failed=true
            agent_execution_failure_stage_json='"permission"'
        elif [[ "$opencode_exit" -ne 0 ]]; then
            invocation_agent_execution_failed=true
            agent_execution_failed=true
            if [[ "$opencode_exit" -eq 124 ]]; then
                agent_execution_failure_stage_json='"timeout"'
            else
                agent_execution_failure_stage_json='"opencode"'
            fi
        fi

        # Snapshot after each invocation. The last snapshot is the final model
        # implementation and excludes subsequent build/test side effects.
        capture_candidate_artifacts \
            "$worktree" "$attempt_dir" "$BASE_COMMIT" "$SOURCE_PATH"

        read -r build_exit build_ms < <(
            cd "$worktree" &&
            run_logged_command \
                "$attempt_dir/build.log" "$BUILD_CMD" \
                "$validation_loop" "BUILD"
        )
        read -r base_test_exit base_test_ms < <(
            cd "$worktree" &&
            run_logged_command \
                "$attempt_dir/base-tests.log" "$BASE_TEST_CMD" \
                "$validation_loop" "BASE TESTS"
        )
        read -r feature_test_exit feature_test_ms < <(
            cd "$worktree" &&
            run_logged_command \
                "$attempt_dir/feature-tests.log" "$FEATURE_TEST_CMD" \
                "$validation_loop" "CHECKPOINT TESTS"
        )
        total_build_ms=$((total_build_ms + build_ms))
        total_base_test_ms=$((total_base_test_ms + base_test_ms))
        total_feature_test_ms=$((total_feature_test_ms + feature_test_ms))

        validation_success=false
        if [[ "$build_exit" -eq 0 &&
              "$base_test_exit" -eq 0 &&
              "$feature_test_exit" -eq 0 ]]; then
            validation_success=true
        fi
        if [[ "$invocation_agent_execution_failed" == true ]]; then
            validation_success=false
        fi
        if [[ "$validation_loop" -eq 0 ]]; then
            initial_success="$validation_success"
        fi

        loop_records+=("$(make_loop_record \
            "$validation_loop" "$loop_kind" \
            "$opencode_exit" "$invocation_permission_rejected" \
            "$build_exit" "$base_test_exit" "$feature_test_exit" \
            "$opencode_ms" "$build_ms" "$base_test_ms" \
            "$feature_test_ms" "$validation_success")")

        # A failed attempted invocation is a valid agent trial, but repair does
        # not continue after that invocation fails to complete.
        if [[ "$invocation_agent_execution_failed" == true ]]; then
            break
        fi
        if [[ "$validation_success" == true ]]; then
            public_validation_success=true
            success_loop_json="$validation_loop"
            break
        fi
        if [[ "$validation_loop" -ge "$MAX_LOOPS" ]]; then
            break
        fi

        current_prompt="$(build_repair_prompt \
            "$validation_loop" "$build_exit" \
            "$base_test_exit" "$feature_test_exit")"
        validation_loop=$((validation_loop + 1))
    done

    llm_invocations=${#loop_records[@]}
    loops_json="$("$PYTHON_BIN" - "${loop_records[@]}" <<'PY'
import json
import sys

print(json.dumps([json.loads(record) for record in sys.argv[1:]], separators=(",", ":")))
PY
    )"
    loop_limit_reached=false
    if [[ "$public_validation_success" == false &&
          "$infrastructure_failed" == false &&
          "$agent_execution_failed" == false &&
          "$repair_loops" -eq "$MAX_LOOPS" ]]; then
        loop_limit_reached=true
    fi

    read -r extra_test_exit extra_test_ms < <(
        cd "$worktree" &&
        run_final_command "$attempt_dir/extra-tests.log" "$EXTRA_TEST_CMD"
    )

    total_ms=$((total_opencode_ms + total_build_ms + total_base_test_ms + total_feature_test_ms + extra_test_ms))

    overall_success=true
    if [[ "$agent_execution_failed" == true ||
          "$public_validation_success" == false ||
          "$extra_test_exit" -ne 0 ]]; then
        overall_success=false
    fi

    write_metadata "$attempt_dir/metadata.json" \
        schema_version 2 \
        run_id "$attempt_id" \
        attempt_number "$attempt_number" \
        model "$MODEL" \
        temperature "$TEMPERATURE" \
        agent "$AGENT" \
        base_commit "$BASE_COMMIT" \
        source_path "$SOURCE_PATH" \
        source_mode "$SOURCE_MODE" \
        max_loops "$MAX_LOOPS" \
        opencode_exit_code "$opencode_exit" \
        opencode_permission_rejected "$opencode_permission_rejected" \
        build_exit_code "$build_exit" \
        base_test_exit_code "$base_test_exit" \
        feature_test_exit_code "$feature_test_exit" \
        extra_test_exit_code "$extra_test_exit" \
        opencode_runtime_ms "$total_opencode_ms" \
        build_runtime_ms "$total_build_ms" \
        base_test_runtime_ms "$total_base_test_ms" \
        feature_test_runtime_ms "$total_feature_test_ms" \
        extra_test_runtime_ms "$extra_test_ms" \
        initial_opencode_runtime_ms "$initial_opencode_ms" \
        repair_opencode_runtime_ms "$repair_opencode_ms" \
        total_opencode_runtime_ms "$total_opencode_ms" \
        total_runtime_ms "$total_ms" \
        initial_success "$initial_success" \
        repair_loops "$repair_loops" \
        llm_invocations "$llm_invocations" \
        success_loop "__JSON__:$success_loop_json" \
        loop_limit_reached "$loop_limit_reached" \
        public_validation_success "$public_validation_success" \
        infrastructure_failure "$infrastructure_failed" \
        infrastructure_failure_stage "__JSON__:$infrastructure_failure_stage_json" \
        infrastructure_failure_classification_inferred false \
        agent_execution_failure "$agent_execution_failed" \
        agent_execution_failure_stage "__JSON__:$agent_execution_failure_stage_json" \
        agent_execution_failure_classification_inferred false \
        loops "__JSON__:$loops_json" \
        overall_success "$overall_success" \
        completed_at "$(date --iso-8601=seconds)"

    git -C "$REPO" worktree remove --force "$worktree" \
        >"$attempt_dir/worktree-remove.log" 2>&1 || true
    git -C "$REPO" worktree prune
    touch "$attempt_dir/COMPLETE"

    printf '  OpenCode=%s loops=%s build=%s base-tests=%s feature-tests=%s extra=%s result=%s time=%.2fs\n' \
        "$opencode_exit" "$repair_loops" "$build_exit" "$base_test_exit" \
        "$feature_test_exit" "$extra_test_exit" \
        "$overall_success" \
        "$("$PYTHON_BIN" -c "print($total_ms / 1000)")"
done

printf '\nRunning analysis...\n'

ANALYZER_ARGS=(
    --experiment "$OUTPUT_DIR"
    --cluster-threshold "$RESOLVED_ANALYSIS_ARCHITECTURE_THRESHOLD"
    --strategy-threshold "$RESOLVED_ANALYSIS_STRATEGY_THRESHOLD"
    --clean-output
)
if [[ -n "$ANALYSIS_DIVERSITY_K_MAX" ]]; then
    ANALYZER_ARGS+=(--diversity-k-max "$ANALYSIS_DIVERSITY_K_MAX")
fi
"$PYTHON_BIN" "$ANALYZER_PATH" "${ANALYZER_ARGS[@]}" \
    2>&1 | tee "$OUTPUT_DIR/analysis.log"

analysis_exit=${PIPESTATUS[0]}

printf '\nFinished: %s\n' "$OUTPUT_DIR"

exit "$analysis_exit"
