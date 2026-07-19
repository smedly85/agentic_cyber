#!/usr/bin/env bash
# Run OpenCode against a plain temp working directory -- no Git, no worktrees.
#
# For each of --runs equally-spaced temperature points between --temp-min and
# --temp-max, this creates a fresh working directory containing only a copy of
# the prompt, any --test-dir directories, and any --seed-file files, runs
# OpenCode with --dir pointed at it (and an OpenCode config that denies every
# other path), and leaves whatever OpenCode generated sitting in that same
# directory. Nothing else in the repository is ever visible to OpenCode --
# the working directory simply doesn't contain anything else, so there is
# nothing for `bash` (or any other tool) to find outside it either.
#
# Example:
#   scripts/run_sandboxed_pipeline.sh \
#     --model school-ollama/qwen3-coder-next:latest \
#     --runs 10 --temp-min 0 --temp-max 2 \
#     --prompt prompts/mkdir/000_base_new_mkdir.md \
#     --test-dir tests/mkdir-test-suite \
#     --test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir" \
#     --output-dir runs/sandboxed/mkdir/milestone-1

set -uo pipefail

usage() {
    cat <<'EOF'
Usage:
  run_sandboxed_pipeline.sh --model MODEL --prompt FILE [options]

Required:
  --model MODEL               OpenCode model name, e.g.
                              school-ollama/qwen3-coder-next:latest
  --prompt FILE               Prompt file, repo-relative or absolute

Options:
  --runs N                   Number of temperature points to sweep (default:
                              10). Each point gets exactly one attempt -- no
                              same-temperature repeats. Temperatures are N
                              values equally spaced across
                              [--temp-min, --temp-max] inclusive (N=1 uses
                              --temp-min).
  --temp-min MIN              Default: 0
  --temp-max MAX              Default: 2
  --agent NAME                OpenCode agent (default: build)
  --test-dir DIR               Repo-relative directory copied into the working
                               directory at the same relative path (repeatable),
                               e.g. tests/mkdir-test-suite. Omit entirely if the
                               prompt doesn't reference a test suite.
  --seed-file SRC[:DEST]       Existing file copied into the working directory
                               at DEST (default DEST = SRC's path relative to
                               the repository root, when SRC is repo-relative).
                               Repeatable. Omit for from-scratch checkpoints.
  --test-cmd CMD               Verification command run inside the working
                               directory after OpenCode finishes (independent
                               confirmation only -- the prompt already tells the
                               agent to self-test and iterate). Empty/omitted
                               disables it (default).
  --timeout SECONDS            OpenCode timeout per run; 0 disables (default: 1800)
  --output-dir DIR              Default: runs/sandboxed/<model-slug>/<prompt-slug>
  --force                      Delete and rerun completed temperature points
  --remote-base-url URL        Base URL of a self-hosted OpenAI-compatible
                               endpoint (e.g. http://host:8080/v1). When set,
                               --model is parsed as PROVIDER/MODEL and a custom
                               @ai-sdk/openai-compatible provider pointing at
                               URL is injected for this run only.
  --remote-api-key-env NAME    Environment variable (already exported in this
                               shell) holding the API key for --remote-base-url
                               (default: OPENCODE_REMOTE_API_KEY). The key
                               itself is never embedded in the generated
                               config -- OpenCode resolves it from its own
                               environment at call time.
  -h, --help                   Show this help

Environment:
  OPENCODE_BIN                OpenCode executable (default: opencode)
  PYTHON_BIN                  Python executable (default: python3)

Directory layout:
  <output-dir>/
    run.json
    temp-<temp-slug>/
      workdir/          (--dir passed to opencode; the ONLY thing it can see)
      opencode.log
      test.log          (only if --test-cmd is given)
      metadata.json
      COMPLETE

Every run passes --thinking to OpenCode, so opencode.log captures the model's
thinking blocks and every tool call/result (bash commands, file edits) in
order, in the same human-readable form the OpenCode TUI shows -- not just the
final response.

No Git is used anywhere: no worktrees, no commits, no diffing, no baseline
comparison, no analyzer. This is a deliberately simpler, separate alternative
to scripts/run_llm_experiment.sh for prompts that don't need git-diff-based
baseline comparison -- the agent is expected to build and test itself, per the
prompt's own instructions.
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
PROMPT=""
RUNS=10
TEMP_MIN="0"
TEMP_MAX="2"
AGENT="build"
OUTPUT_DIR=""
TEST_CMD=""
TIMEOUT_SECONDS=1800
FORCE=0
REMOTE_BASE_URL=""
REMOTE_API_KEY_ENV="OPENCODE_REMOTE_API_KEY"
TEST_DIRS=()
SEED_FILES=()

OPENCODE_BIN="${OPENCODE_BIN:-opencode}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) MODEL="${2:-}"; shift 2 ;;
        --prompt) PROMPT="${2:-}"; shift 2 ;;
        --runs) RUNS="${2:-}"; shift 2 ;;
        --temp-min) TEMP_MIN="${2:-}"; shift 2 ;;
        --temp-max) TEMP_MAX="${2:-}"; shift 2 ;;
        --agent) AGENT="${2:-}"; shift 2 ;;
        --test-dir) TEST_DIRS+=("${2:-}"); shift 2 ;;
        --seed-file) SEED_FILES+=("${2:-}"); shift 2 ;;
        --test-cmd) TEST_CMD="${2:-}"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
        --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
        --remote-base-url) REMOTE_BASE_URL="${2:-}"; shift 2 ;;
        --remote-api-key-env) REMOTE_API_KEY_ENV="${2:-}"; shift 2 ;;
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[[ -n "$MODEL" ]] || die "--model is required"
[[ -n "$PROMPT" ]] || die "--prompt is required"
[[ "$RUNS" =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer"
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--timeout must be a non-negative integer"

command -v "$OPENCODE_BIN" >/dev/null 2>&1 || die "$OPENCODE_BIN was not found"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN was not found"
command -v git >/dev/null 2>&1 || die "git is required (only to resolve repo-relative paths)"

"$PYTHON_BIN" -c 'import sys; float(sys.argv[1])' "$TEMP_MIN" ||
    die "--temp-min must be numeric"
"$PYTHON_BIN" -c 'import sys; float(sys.argv[1])' "$TEMP_MAX" ||
    die "--temp-max must be numeric"
"$PYTHON_BIN" -c 'import sys; sys.exit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)' \
    "$TEMP_MIN" "$TEMP_MAX" || die "--temp-min must be <= --temp-max"

if [[ -n "$REMOTE_BASE_URL" ]]; then
    [[ "$MODEL" == */* ]] ||
        die "--model must be PROVIDER/MODEL when --remote-base-url is set (got: $MODEL)"
    [[ -n "${!REMOTE_API_KEY_ENV:-}" ]] ||
        die "$REMOTE_API_KEY_ENV is not set (export it before running, or pass --remote-api-key-env)"
fi

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" ||
    die "run this script inside a Git repository (only used to resolve repo-relative paths)"
REPO="$(cd "$REPO" && pwd -P)"

resolve_repo_path() {
    # Usage: resolve_repo_path PATH -- absolute passthrough, else $REPO/PATH
    local path="$1"
    if [[ "$path" == /* ]]; then
        printf '%s' "$path"
    else
        printf '%s' "$REPO/$path"
    fi
}

PROMPT_ABS="$(resolve_repo_path "$PROMPT")"
[[ -f "$PROMPT_ABS" ]] || die "prompt not found: $PROMPT_ABS"

for test_dir in "${TEST_DIRS[@]+"${TEST_DIRS[@]}"}"; do
    [[ -e "$(resolve_repo_path "$test_dir")" ]] ||
        die "--test-dir not found: $(resolve_repo_path "$test_dir")"
done

for seed_spec in "${SEED_FILES[@]+"${SEED_FILES[@]}"}"; do
    seed_src="${seed_spec%%:*}"
    [[ -f "$(resolve_repo_path "$seed_src")" ]] ||
        die "--seed-file source not found: $(resolve_repo_path "$seed_src")"
done

MODEL_SLUG="$(slugify "$MODEL")"
PROMPT_SLUG="$(slugify "$(basename "${PROMPT%.*}")")"

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$REPO/runs/sandboxed/$MODEL_SLUG/$PROMPT_SLUG"
elif [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="$REPO/$OUTPUT_DIR"
fi
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"

TEST_DIRS_JOINED="$(IFS=,; printf '%s' "${TEST_DIRS[*]+"${TEST_DIRS[*]}"}")"
SEED_FILES_JOINED="$(IFS=,; printf '%s' "${SEED_FILES[*]+"${SEED_FILES[*]}"}")"

write_metadata "$OUTPUT_DIR/run.json" \
    schema_version 1 \
    repository "$REPO" \
    model "$MODEL" \
    agent "$AGENT" \
    prompt "$PROMPT_ABS" \
    requested_runs "$RUNS" \
    temp_min "$TEMP_MIN" \
    temp_max "$TEMP_MAX" \
    test_dirs "$TEST_DIRS_JOINED" \
    seed_files "$SEED_FILES_JOINED" \
    test_command "$TEST_CMD" \
    created_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Compute RUNS equally-spaced temperature points across [TEMP_MIN, TEMP_MAX]
# (N=1 uses TEMP_MIN). One line of Python is simpler and less error-prone
# than hand-rolling float arithmetic in bash.
TEMPERATURES="$(
    "$PYTHON_BIN" -c '
import sys
n, lo, hi = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
if n == 1:
    print(lo)
else:
    step = (hi - lo) / (n - 1)
    for i in range(n):
        print(lo + step * i)
' "$RUNS" "$TEMP_MIN" "$TEMP_MAX"
)"

printf 'Repository:  %s\n' "$REPO"
printf 'Model:       %s\n' "$MODEL"
printf 'Prompt:      %s\n' "$PROMPT_ABS"
printf 'Runs:        %s (temperatures %s to %s)\n' "$RUNS" "$TEMP_MIN" "$TEMP_MAX"
printf 'Output:      %s\n\n' "$OUTPUT_DIR"

point_number=0
overall_status=0
while IFS= read -r temperature; do
    [[ -n "$temperature" ]] || continue
    point_number=$((point_number + 1))

    temp_slug="$(slugify "$temperature" | sed 's/\./p/g')"
    point_dir="$OUTPUT_DIR/temp-$temp_slug"
    workdir="$point_dir/workdir"

    if [[ -f "$point_dir/COMPLETE" && "$FORCE" -eq 0 ]]; then
        printf '[%s/%s] temp=%s already complete; skipping\n' \
            "$point_number" "$RUNS" "$temperature"
        continue
    fi

    printf '[%s/%s] starting temp=%s\n' "$point_number" "$RUNS" "$temperature"

    rm -rf "$point_dir"
    mkdir -p "$workdir"

    cp "$PROMPT_ABS" "$workdir/$(basename "$PROMPT_ABS")"

    for test_dir in "${TEST_DIRS[@]+"${TEST_DIRS[@]}"}"; do
        src="$(resolve_repo_path "$test_dir")"
        dest="$workdir/$test_dir"
        mkdir -p "$(dirname "$dest")"
        cp -R "$src" "$dest"
    done

    for seed_spec in "${SEED_FILES[@]+"${SEED_FILES[@]}"}"; do
        seed_src="${seed_spec%%:*}"
        if [[ "$seed_spec" == *:* ]]; then
            seed_dest="${seed_spec#*:}"
        else
            seed_dest="$seed_src"
        fi
        src="$(resolve_repo_path "$seed_src")"
        dest="$workdir/$seed_dest"
        mkdir -p "$(dirname "$dest")"
        cp -p "$src" "$dest"
    done

    ATTEMPT_OPENCODE_CONFIG_CONTENT="$(
        "$PYTHON_BIN" - "$AGENT" "$temperature" "$workdir" \
            "$REMOTE_BASE_URL" "$REMOTE_API_KEY_ENV" "$MODEL" <<'PY'
import json
import sys
from pathlib import Path

agent = sys.argv[1]
temperature = float(sys.argv[2])
workdir = str(Path(sys.argv[3]).resolve())
remote_base_url = sys.argv[4]
remote_api_key_env = sys.argv[5]
model = sys.argv[6]

escaped_workdir = workdir.replace(" ", r"\ ")
external_directory = {
    "*": "deny",
    workdir: "allow",
    f"{workdir}/**": "allow",
}
if escaped_workdir != workdir:
    # OpenCode 1.17.20 preserves backslash-escaped spaces in bash path checks.
    external_directory[escaped_workdir] = "allow"
    external_directory[f"{escaped_workdir}/**"] = "allow"

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

if remote_base_url:
    provider_id, _, model_id = model.partition("/")
    config["provider"] = {
        provider_id: {
            "npm": "@ai-sdk/openai-compatible",
            "options": {
                "baseURL": remote_base_url,
                "apiKey": f"{{env:{remote_api_key_env}}}",
            },
            "models": {model_id: {}},
        }
    }

print(json.dumps(config))
PY
    )" || die "failed to build per-run OpenCode configuration"

    prompt_text="$(cat "$PROMPT_ABS")"
    opencode_start_ns="$(date +%s%N)"

    {
        printf '===== PROMPT SENT =====\n%s\n===== END PROMPT =====\n\n' "$prompt_text"
        if [[ "$TIMEOUT_SECONDS" -gt 0 ]]; then
            OPENCODE_CONFIG_CONTENT="$ATTEMPT_OPENCODE_CONFIG_CONTENT" \
                timeout --signal=TERM --kill-after=30 \
                "$TIMEOUT_SECONDS" \
                "$OPENCODE_BIN" run \
                    --dir "$workdir" \
                    --model "$MODEL" \
                    --agent "$AGENT" \
                    --thinking \
                    "$prompt_text"
        else
            OPENCODE_CONFIG_CONTENT="$ATTEMPT_OPENCODE_CONFIG_CONTENT" \
                "$OPENCODE_BIN" run \
                    --dir "$workdir" \
                    --model "$MODEL" \
                    --agent "$AGENT" \
                    --thinking \
                    "$prompt_text"
        fi
    } >"$point_dir/opencode.log" 2>&1
    opencode_exit=$?
    opencode_end_ns="$(date +%s%N)"
    opencode_ms=$(( (opencode_end_ns - opencode_start_ns) / 1000000 ))

    opencode_permission_rejected=false
    if grep -Eiq \
            'permission requested:[[:space:]]*external_directory|auto-rejecting|user rejected permission|permission denied' \
            "$point_dir/opencode.log"; then
        opencode_permission_rejected=true
    fi

    read -r test_exit test_ms < <(
        cd "$workdir" &&
        run_logged_command "$point_dir/test.log" "$TEST_CMD"
    )

    total_ms=$((opencode_ms + test_ms))

    overall_success=true
    if [[ "$opencode_permission_rejected" == true ||
          "$opencode_exit" -ne 0 ||
          "$test_exit" -ne 0 ]]; then
        overall_success=false
        overall_status=1
    fi

    write_metadata "$point_dir/metadata.json" \
        schema_version 1 \
        model "$MODEL" \
        agent "$AGENT" \
        temperature "$temperature" \
        prompt "$PROMPT_ABS" \
        test_dirs "$TEST_DIRS_JOINED" \
        seed_files "$SEED_FILES_JOINED" \
        test_command "$TEST_CMD" \
        opencode_exit_code "$opencode_exit" \
        opencode_permission_rejected "$opencode_permission_rejected" \
        test_exit_code "$test_exit" \
        opencode_runtime_ms "$opencode_ms" \
        test_runtime_ms "$test_ms" \
        total_runtime_ms "$total_ms" \
        overall_success "$overall_success" \
        completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    touch "$point_dir/COMPLETE"

    printf '  OpenCode=%s test=%s result=%s time=%.2fs\n' \
        "$opencode_exit" "$test_exit" "$overall_success" \
        "$("$PYTHON_BIN" -c "print($total_ms / 1000)")"
done <<< "$TEMPERATURES"

printf '\nFinished: %s\n' "$OUTPUT_DIR"

exit "$overall_status"
