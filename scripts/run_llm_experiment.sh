#!/usr/bin/env bash
# Run repeated OpenCode patch-generation experiments in isolated Git worktrees.
#
# Example:
#   scripts/run_llm_experiment.sh \
#     --model school-ollama/qwen3-coder-next:latest \
#     --temperature 0.0 \
#     --runs 25 \
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
  --agent NAME               OpenCode agent (default: build)
  --base-ref REF             Commit/tag/branch used for every attempt (default: HEAD)
  --source PATH              Primary source file to preserve (default:
                             src/new_sort/new_sort.c)
  --output-dir DIR           Experiment directory. If omitted, a deterministic
                             directory is derived from model, prompt, and temperature.
  --build-cmd CMD            Build command (default: make clean && make)
  --base-test-cmd CMD        Baseline test command. Empty disables it.
  --feature-test-cmd CMD     Checkpoint/flag test command. Empty disables it.
  --extra-test-cmd CMD       Optional sanitizer/hidden/property-test command.
  --timeout SECONDS          OpenCode timeout per run; 0 disables (default: 1800)
  --force                    Delete and rerun completed attempt directories
  --analysis-threshold X     Agglomerative-clustering distance threshold
                             (default: 0.30)
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

run_logged_command() {
    # Usage: run_logged_command LOGFILE COMMAND
    local logfile="$1"
    local command="$2"
    local start_ns end_ns status

    if [[ -z "$command" ]]; then
        : > "$logfile"
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

MODEL=""
TEMPERATURE=""
PROMPT=""
RUNS=100
AGENT="build"
BASE_REF="HEAD"
SOURCE_PATH="src/new_sort/new_sort.c"
OUTPUT_DIR=""
BUILD_CMD="make clean && make"
BASE_TEST_CMD="PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/new_sort/test_new_sort.py -v"
FEATURE_TEST_CMD=""
EXTRA_TEST_CMD=""
TIMEOUT_SECONDS=1800
FORCE=0
ANALYSIS_THRESHOLD="0.30"

OPENCODE_BIN="${OPENCODE_BIN:-opencode}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODEL="${2:-}"; shift 2 ;;
        --temperature) TEMPERATURE="${2:-}"; shift 2 ;;
        --prompt) PROMPT="${2:-}"; shift 2 ;;
        --runs) RUNS="${2:-}"; shift 2 ;;
        --agent) AGENT="${2:-}"; shift 2 ;;
        --base-ref) BASE_REF="${2:-}"; shift 2 ;;
        --source) SOURCE_PATH="${2:-}"; shift 2 ;;
        --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
        --build-cmd) BUILD_CMD="${2:-}"; shift 2 ;;
        --base-test-cmd) BASE_TEST_CMD="${2:-}"; shift 2 ;;
        --feature-test-cmd) FEATURE_TEST_CMD="${2:-}"; shift 2 ;;
        --extra-test-cmd) EXTRA_TEST_CMD="${2:-}"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
        --analysis-threshold) ANALYSIS_THRESHOLD="${2:-}"; shift 2 ;;
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[[ -n "$MODEL" ]] || die "--model is required"
[[ -n "$TEMPERATURE" ]] || die "--temperature is required"
[[ -n "$PROMPT" ]] || die "--prompt is required"
[[ "$RUNS" =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer"
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--timeout must be a non-negative integer"

command -v git >/dev/null 2>&1 || die "git is required"
command -v "$OPENCODE_BIN" >/dev/null 2>&1 || die "$OPENCODE_BIN was not found"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN was not found"

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" ||
    die "run this script inside a Git repository"
REPO="$(cd "$REPO" && pwd -P)"

if [[ "$PROMPT" != /* ]]; then
    PROMPT="$REPO/$PROMPT"
fi
[[ -f "$PROMPT" ]] || die "prompt not found: $PROMPT"

BASE_COMMIT="$(git -C "$REPO" rev-parse "$BASE_REF^{commit}")" ||
    die "cannot resolve base ref: $BASE_REF"
[[ -f "$REPO/$SOURCE_PATH" ]] ||
    die "source file not found at baseline checkout: $SOURCE_PATH"

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

BASELINE_DIR="$OUTPUT_DIR/baseline"
mkdir -p "$BASELINE_DIR/$(dirname "$SOURCE_PATH")"
git -C "$REPO" show "$BASE_COMMIT:$SOURCE_PATH" \
    > "$BASELINE_DIR/$SOURCE_PATH"

PROMPT_COPY="$OUTPUT_DIR/prompt.md"
cp "$PROMPT" "$PROMPT_COPY"

ANALYZER_PATH="$REPO/scripts/analyze_experiment.py"
[[ -f "$ANALYZER_PATH" ]] || die "analyzer not found: $ANALYZER_PATH"

write_metadata "$OUTPUT_DIR/experiment.json" \
    schema_version 1 \
    repository "$REPO" \
    base_ref "$BASE_REF" \
    base_commit "$BASE_COMMIT" \
    model "$MODEL" \
    temperature "$TEMPERATURE" \
    agent "$AGENT" \
    prompt "$PROMPT" \
    prompt_copy "$PROMPT_COPY" \
    source_path "$SOURCE_PATH" \
    requested_runs "$RUNS" \
    build_command "$BUILD_CMD" \
    base_test_command "$BASE_TEST_CMD" \
    feature_test_command "$FEATURE_TEST_CMD" \
    extra_test_command "$EXTRA_TEST_CMD" \
    created_at "$(date --iso-8601=seconds)"

# OpenCode agent configuration with a model-independent temperature.
OPENCODE_CONFIG_CONTENT="$(
    "$PYTHON_BIN" - "$AGENT" "$TEMPERATURE" <<'PY'
import json
import sys

agent = sys.argv[1]
temperature = float(sys.argv[2])
print(json.dumps({"agent": {agent: {"temperature": temperature}}}))
PY
)" || die "temperature must be numeric"

printf 'Repository:  %s\n' "$REPO"
printf 'Baseline:    %s (%s)\n' "$BASE_REF" "$BASE_COMMIT"
printf 'Model:       %s\n' "$MODEL"
printf 'Temperature: %s\n' "$TEMPERATURE"
printf 'Prompt:      %s\n' "$PROMPT"
printf 'Runs:        %s\n' "$RUNS"
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
            run_id "$attempt_id" \
            model "$MODEL" \
            temperature "$TEMPERATURE" \
            setup_exit_code 1 \
            overall_success false
        touch "$attempt_dir/COMPLETE"
        printf '  worktree creation failed; see %s\n' \
            "$attempt_dir/worktree-add.log" >&2
        continue
    fi

    prompt_text="$(cat "$PROMPT")"
    opencode_start_ns="$(date +%s%N)"

    if [[ "$TIMEOUT_SECONDS" -gt 0 ]]; then
        OPENCODE_CONFIG_CONTENT="$OPENCODE_CONFIG_CONTENT" \
            timeout --signal=TERM --kill-after=30 \
            "$TIMEOUT_SECONDS" \
            "$OPENCODE_BIN" run \
                --dir "$worktree" \
                --model "$MODEL" \
                --agent "$AGENT" \
                "$prompt_text"
    else
        OPENCODE_CONFIG_CONTENT="$OPENCODE_CONFIG_CONTENT" \
            "$OPENCODE_BIN" run \
                --dir "$worktree" \
                --model "$MODEL" \
                --agent "$AGENT" \
                "$prompt_text"
    fi >"$attempt_dir/opencode.log" 2>&1
    opencode_exit=$?
    opencode_end_ns="$(date +%s%N)"
    opencode_ms=$(( (opencode_end_ns - opencode_start_ns) / 1000000 ))

    # Preserve the exact generated state before build/test commands can alter it.
    git -C "$worktree" status --short >"$attempt_dir/git-status.txt"
    git -C "$worktree" diff --binary "$BASE_COMMIT" -- >"$attempt_dir/patch.diff"
    git -C "$worktree" diff --numstat "$BASE_COMMIT" -- >"$attempt_dir/diff-numstat.txt"
    git -C "$worktree" diff --name-status "$BASE_COMMIT" -- \
        >"$attempt_dir/changed-files.txt"
    git -C "$worktree" diff --stat "$BASE_COMMIT" -- >"$attempt_dir/diff-stat.txt"
    git -C "$worktree" ls-files --others --exclude-standard \
        >"$attempt_dir/untracked-files.txt"

    copy_changed_files "$worktree" "$attempt_dir/candidate" "$BASE_COMMIT"

    # Always preserve the primary source, even if OpenCode did not modify it.
    mkdir -p "$attempt_dir/candidate/$(dirname "$SOURCE_PATH")"
    if [[ -f "$worktree/$SOURCE_PATH" ]]; then
        cp -p "$worktree/$SOURCE_PATH" \
            "$attempt_dir/candidate/$SOURCE_PATH"
    fi

    read -r build_exit build_ms < <(
        cd "$worktree" &&
        run_logged_command "$attempt_dir/build.log" "$BUILD_CMD"
    )
    read -r base_test_exit base_test_ms < <(
        cd "$worktree" &&
        run_logged_command "$attempt_dir/base-tests.log" "$BASE_TEST_CMD"
    )
    read -r feature_test_exit feature_test_ms < <(
        cd "$worktree" &&
        run_logged_command "$attempt_dir/feature-tests.log" "$FEATURE_TEST_CMD"
    )
    read -r extra_test_exit extra_test_ms < <(
        cd "$worktree" &&
        run_logged_command "$attempt_dir/extra-tests.log" "$EXTRA_TEST_CMD"
    )

    total_ms=$((opencode_ms + build_ms + base_test_ms + feature_test_ms + extra_test_ms))

    overall_success=true
    if [[ "$opencode_exit" -ne 0 ||
          "$build_exit" -ne 0 ||
          "$base_test_exit" -ne 0 ||
          "$feature_test_exit" -ne 0 ||
          "$extra_test_exit" -ne 0 ]]; then
        overall_success=false
    fi

    write_metadata "$attempt_dir/metadata.json" \
        schema_version 1 \
        run_id "$attempt_id" \
        attempt_number "$attempt_number" \
        model "$MODEL" \
        temperature "$TEMPERATURE" \
        agent "$AGENT" \
        base_commit "$BASE_COMMIT" \
        source_path "$SOURCE_PATH" \
        opencode_exit_code "$opencode_exit" \
        build_exit_code "$build_exit" \
        base_test_exit_code "$base_test_exit" \
        feature_test_exit_code "$feature_test_exit" \
        extra_test_exit_code "$extra_test_exit" \
        opencode_runtime_ms "$opencode_ms" \
        build_runtime_ms "$build_ms" \
        base_test_runtime_ms "$base_test_ms" \
        feature_test_runtime_ms "$feature_test_ms" \
        extra_test_runtime_ms "$extra_test_ms" \
        total_runtime_ms "$total_ms" \
        overall_success "$overall_success" \
        completed_at "$(date --iso-8601=seconds)"

    git -C "$REPO" worktree remove --force "$worktree" \
        >"$attempt_dir/worktree-remove.log" 2>&1 || true
    git -C "$REPO" worktree prune
    touch "$attempt_dir/COMPLETE"

    printf '  OpenCode=%s build=%s base-tests=%s feature-tests=%s extra=%s result=%s time=%.2fs\n' \
        "$opencode_exit" "$build_exit" "$base_test_exit" \
        "$feature_test_exit" "$extra_test_exit" \
        "$overall_success" \
        "$("$PYTHON_BIN" -c "print($total_ms / 1000)")"
done

printf '\nRunning analysis...\n'

"$PYTHON_BIN" "$ANALYZER_PATH" \
    --experiment "$OUTPUT_DIR" \
    --cluster-threshold "$ANALYSIS_THRESHOLD" \
    --strategy-threshold "$ANALYSIS_THRESHOLD" \
    --clean-output \
    2>&1 | tee "$OUTPUT_DIR/analysis.log"

analysis_exit=${PIPESTATUS[0]}

printf '\nFinished: %s\n' "$OUTPUT_DIR"

exit "$analysis_exit"
