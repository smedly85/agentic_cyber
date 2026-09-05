#!/usr/bin/env bash
# Run repeated Aider code-generation experiments in isolated plain
# directories, with a controller-driven generate/validate/continue loop.
#
# Each attempt gets a fresh working directory containing only the prompt, any
# --test-dir directories, and any --seed-file files. Aider runs from inside the
# directory with Git and its repository map disabled. Only the source is
# editable; the other text files in this directory are explicit read-only
# context. No Git worktrees or scratch repositories are involved.
#
# After each Aider process the controller independently runs --build-cmd,
# --base-test-cmd, and --feature-test-cmd. If any of them fails, it renders a
# continuation prompt (prompts/repair_continuation_template.md) containing the
# original task and the specific failures, and starts a NEW Aider process
# against the SAME working directory, so the model picks up where it left off.
# This repeats up to --max-loops times.
#
# Output is written in the layout analyze_experiment.py consumes, and analysis
# runs automatically for each temperature.
#
# Example (from scratch, with repair):
#   scripts/run_experiment.sh \
#     --model ollama_chat/qwen3.8:27b \
#     --editor-model ollama_chat/qwen3-coder-next:latest \
#     --temperature 0.2 --runs 25 --max-loops 3 \
#     --prompt prompts/mkdir/000_base_new_mkdir.md \
#     --source src/new_mkdir/new_mkdir.c --source-mode new \
#     --test-dir tests/mkdir-test-suite \
#     --build-cmd "mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_mkdir/new_mkdir.c -o build/new_mkdir" \
#     --feature-test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir"
#
# Example (temperature sweep):
#   scripts/run_experiment.sh \
#     --model ollama_chat/qwen3.8:27b \
#     --editor-model ollama_chat/qwen3-coder-next:latest \
#     --temp-min 0 --temp-max 2 --temp-points 10 --runs 3 \
#     --prompt prompts/new_sort/000_base_new_sort.md \
#     --source src/new_sort/new_sort.c --source-mode new \
#     --test-dir tests/sort-test-suite \
#     --feature-test-cmd "tests/sort-test-suite/run_all.sh build/new_sort"

set -uo pipefail

usage() {
    cat <<'EOF'
Usage:
  run_experiment.sh --model MODEL --prompt FILE --source PATH [options]

Required:
  --model MODEL              Aider architect/reasoning model, e.g.
                             ollama_chat/qwen3.8:27b
  --editor-model MODEL       Aider editor model (default:
                             ollama_chat/qwen3-coder-next:latest)
  --prompt FILE              Prompt file, repo-relative or absolute
  --source PATH              Path, relative to the working directory, that the
                             agent is expected to write, e.g.
                             src/new_mkdir/new_mkdir.c

Temperature:
  --temperature T            Single temperature point (sets min and max to T)
  --temp-min MIN             Sweep start (default: 0)
  --temp-max MAX             Sweep end (default: 2)
  --temp-points N            Number of equally spaced points across
                             [--temp-min, --temp-max] inclusive (default: 1).
                             Required when --temp-min differs from --temp-max.
  --temp-list T1,T2,...      Explicit temperature points, for grids that are
                             not equally spaced (e.g. 0,0.125,0.25,0.5,1,2).
                             Mutually exclusive with the options above.
  --runs N                   Attempts per temperature point (default: 1)

Other sampling parameters (each optional; unset means the flag is absent from
the request and the server's own default applies, which is the behavior before
these flags existed):
  --architect-think LEVEL   Native architect thinking level: low, medium, or
                             high. Sent directly as the string-valued `think`
                             parameter; never translated to reasoning_effort.
  --editor-edit-format FMT  Editor output protocol: whole or editor-diff
                             (default: editor-diff).
  --top-p P                  Nucleus sampling mass, 0 <= P <= 1. Sent as
                             top_p.
  --sampling-seed N          Pseudorandom seed for token selection, N >= 0.
                             Sent as seed. Deliberately NOT called --seed:
                             --seed-file is the checkpoint source-inheritance
                             file and the two senses must not be confused.
  --max-tokens N             Cap on generated tokens per session, N >= 1. Sent
                             as max_tokens, replacing the model's own output
                             limit.
  --num-ctx N                Ollama total context capacity, N >= 1. Sent as
                             num_ctx to both architect and editor. Independent
                             from --max-tokens; unset preserves Aider sizing.
  --model-provenance-json J  Metadata-only JSON object for model-definition
                             controls such as base_model/top_k/top_k_control.
                             It is never added to an Aider request.

                             There is no --top-k. See the SAMPLING PARAMETERS
                             note in this script for the measurements behind
                             that omission.

Generation and repair:
  --max-loops N              Continuation sessions after the initial
                             generation (default: 3). 0 disables repair.
  --repair-prompt FILE       Continuation template (default:
                             prompts/repair_continuation_template.md)
  --allow-no-progress        Keep looping even when a session leaves the
                             source byte-identical. Default is to stop early.
  --timeout SECONDS          Aider timeout per invocation; 0 disables
                             (default: 1800). Requires timeout or gtimeout;
                             without either, sessions run unwrapped and
                             metadata records timeout_enforced false.

Workspace:
  --source-mode MODE         existing requires a --seed-file for --source;
                             new starts from an empty baseline
                             (default: existing)
  --test-dir SRC[:DEST]      Directory copied into the working directory at
                             DEST (default DEST = SRC). Repeatable. SRC is
                             repo-relative or absolute; DEST is always
                             workdir-relative. A separate DEST lets a caller
                             supply a generated per-checkpoint test bundle while
                             the agent still sees it at the path its prompt and
                             validation command name.
  --seed-file SRC[:DEST]     File copied into the working directory at DEST
                             (default DEST = SRC). Repeatable. The spec whose
                             destination matches --source also becomes the
                             analysis baseline.

Validation (all run by the controller inside the working directory):
  --build-cmd CMD            Build command
  --base-test-cmd CMD        Regression test command
  --feature-test-cmd CMD     Checkpoint test command (alias: --test-cmd)
  --extra-test-cmd CMD       Hidden functional command, run once after repair
                             and never used as repair feedback
  --security-cmd CMD         Independent post-validation security evaluator.
                             Runs only after functional overall_success is
                             finalized; its findings never affect repair or
                             functional success.
  --security-fuzz-seconds N  Security runtime budget (default: 10)
  --security-seed N          Recorded deterministic security seed (default: 1)
  --security-timeout N       Per-input security timeout seconds (default: 2)
  --security-max-inputs N    Security input-count budget (default: 100)

Output and cleanup:
  --output-dir DIR           Sweep root. Default:
                             runs/experiments/<model-slug>/<prompt-slug>
  --keep-glob GLOB           File pattern preserved from the working directory
                             (repeatable, default: *.c and *.h)
  --keep-workdir             Do not delete the working directory afterwards
  --force                    Delete and rerun completed attempts
  --prune-only DIR           Reclaim space in existing runs under DIR and exit
  --no-analysis              Skip the automatic per-temperature analysis

Analysis:
  --analysis-threshold X     Sets both thresholds unless overridden
  --analysis-architecture-threshold X   Default: 0.30
  --analysis-strategy-threshold X       Default: architecture threshold
  --analysis-diversity-k-max K          Default: unset
  -h, --help                 Show this help

Environment:
  AIDER_BIN                  Aider executable (default: aider)
  PYTHON_BIN                 Python executable (default: python3)

Remote endpoints:
  --remote-base-url URL      Native Ollama root for ollama_chat/* models, or
                             an OpenAI-compatible URL for openai/* models
  --remote-api-key-env NAME  Optional environment variable containing the
                             endpoint key. An unauthenticated openai/* gateway
                             receives the conventional dummy value "ollama".
  --ollama-trace             DIAGNOSTIC ONLY: route native Ollama calls through
                             a per-attempt loopback proxy and retain request
                             JSON plus completion metadata under
                             attempt-*/ollama-trace/. Disabled by default.

Directory layout:
  <output-dir>/
    sweep.json
    temp-<slug>/
      experiment.json
      prompt.md
      baseline/<source-basename>
      attempt-001/
        metadata.json  aider.log  aider-model-settings.yml  build.log
        base-tests.log  feature-tests.log  extra-tests.log security-tests.log
        security_results.json security_artifacts/
        repair-prompt-1.md ...
        candidate/          flattened source files the agent produced
        tampered-tests/     only when a visible test was modified
        diff-numstat.txt  untracked-files.txt  changed-files.txt
        COMPLETE
      analysis/

The working directory is deleted after each attempt: it is a per-attempt copy
of the test suite (tests/sort-test-suite alone is 14M) and everything worth
keeping has already been captured into candidate/.
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
    # Portable across BSD and GNU date; `date --iso-8601` is GNU-only.
    date -u +%Y-%m-%dT%H:%M:%SZ
}

# An optional sampling knob, for write_metadata. Recorded as null when it was
# not requested rather than omitted: a reader can then tell "left to the
# server's default" from "this record predates the flag", and the CSV the
# analyzer derives from these files keeps a stable column set either way.
optional_number() {
    if [[ -n "$1" ]]; then
        printf '%s' "$1"
    else
        printf '__JSON__:null'
    fi
}

optional_string() {
    if [[ -n "$1" ]]; then
        printf '__STR__:%s' "$1"
    else
        printf '__JSON__:null'
    fi
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
    if value.startswith("__STR__:"):
        # Free text that must never be type-guessed. A shell command is the
        # motivating case: `--base-test-cmd true` would otherwise be stored as
        # the boolean true, and the resume guard -- which compares against the
        # string it was given -- would report a configuration mismatch on every
        # re-run of an unchanged command line.
        data[key] = value.removeprefix("__STR__:")
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

file_sha256() {
    local path="$1"
    if [[ -f "$path" ]]; then
        "$PYTHON_BIN" - "$path" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as handle:
    for chunk in iter(lambda: handle.read(65536), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
    else
        printf 'absent'
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
        export PYTHONDONTWRITEBYTECODE=1
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
        export PYTHONDONTWRITEBYTECODE=1
        eval "$command"
    ) >"$logfile" 2>&1
    status=$?
    end_ns="$(date +%s%N)"

    printf '%s %s\n' "$status" "$(( (end_ns - start_ns) / 1000000 ))"
}

run_aider() {
    # Usage: run_aider LOGFILE WORKDIR PROMPT_FILE INVOCATION KIND
    # Each call is a new Aider process against the same working directory.
    local logfile="$1"
    local workdir="$2"
    local prompt="$3"
    local invocation="$4"
    local kind="$5"
    local current_log start_ns end_ns status runtime_ms isolation_rejected
    local token_limit invalid_editor_output current_log_available
    local durable_log_available current_log_parent_available
    local current_log_parent_writable tee_status log_capture_condition
    local -a pipeline_status
    local env_args

    current_log="$attempt_dir/.aider-current.log"
    printf '\n===== LLM INVOCATION %s: %s =====\n\n' \
        "$invocation" "$kind" >>"$logfile"
    start_ns="$(date +%s%N)"
    # Preserve only the process essentials and the explicitly selected Ollama
    # endpoint. In particular, no inherited AIDER_* variables can turn testing,
    # Git, shell suggestions or a user's global config back on. Git's ceiling
    # prevents Aider's startup discovery (which happens before --no-git is
    # parsed) from walking into the parent agentic_cyber repository.
    env_args=(
        "HOME=$AIDER_HOME"
        "PATH=$PATH"
        "TMPDIR=$AIDER_HOME/tmp"
        "GIT_CEILING_DIRECTORIES=$(dirname "$workdir")"
    )
    if [[ "$OLLAMA_TRACE" -eq 1 ]]; then
        env_args+=("OLLAMA_API_BASE=$OLLAMA_TRACE_PROXY_URL")
        if [[ -n "$REMOTE_API_KEY_ENV" ]]; then
            env_args+=("OLLAMA_API_KEY=${!REMOTE_API_KEY_ENV}")
        fi
    elif [[ "$REMOTE_TRANSPORT" == "ollama_native" ]]; then
        env_args+=("OLLAMA_API_BASE=$REMOTE_BASE_URL")
        if [[ -n "$REMOTE_API_KEY_ENV" ]]; then
            env_args+=("OLLAMA_API_KEY=${!REMOTE_API_KEY_ENV}")
        fi
    elif [[ "$REMOTE_TRANSPORT" == "openai_compatible" ]]; then
        env_args+=("OPENAI_API_BASE=$REMOTE_BASE_URL")
        if [[ -n "$REMOTE_API_KEY_ENV" ]]; then
            env_args+=("OPENAI_API_KEY=${!REMOTE_API_KEY_ENV}")
        else
            # OpenAI clients require a non-empty key even when a local Ollama
            # compatibility endpoint ignores authentication.
            env_args+=("OPENAI_API_KEY=ollama")
        fi
    fi

    # --message-file makes this one-shot. The only editable path is SOURCE_PATH;
    # every other visible text file is added with --read. No --yes-always is
    # needed, and stdin is closed so an unexpected prompt fails instead of
    # hanging an unattended experiment.
    aider_command=(
        "$AIDER_BIN"
        --architect
        --auto-accept-architect
        --model "$MODEL"
        --editor-model "$EDITOR_MODEL"
        --weak-model "$EDITOR_MODEL"
        --editor-edit-format "$EDITOR_EDIT_FORMAT"
        --model-settings-file "$AIDER_MODEL_SETTINGS_FILE"
        --message-file "$prompt"
        --file "$SOURCE_PATH"
        --no-git
        --no-gitignore
        --map-tokens 0
        --no-auto-commits
        --no-dirty-commits
        --no-auto-lint
        --no-auto-test
        --no-suggest-shell-commands
        --no-analytics
        --no-check-update
        --no-show-release-notes
        --no-show-model-warnings
        --no-check-model-accepts-settings
        --no-restore-chat-history
        --no-pretty
        --no-fancy-input
        --no-notifications
        --no-browser
        --no-detect-urls
        --disable-playwright
        --config "$AIDER_CONFIG_FILE"
        --env-file "$AIDER_ENV_FILE"
        --input-history-file /dev/null
        --chat-history-file /dev/null
    )
    aider_command+=("${AIDER_READ_ARGS[@]+"${AIDER_READ_ARGS[@]}"}")

    if [[ "$TIMEOUT_ENFORCED" == true ]]; then
        (
            cd "$workdir" || exit 125
            env -i "${env_args[@]}" \
                "$TIMEOUT_BIN" --signal=TERM --kill-after=30 \
                "$TIMEOUT_SECONDS" \
                "${aider_command[@]}" </dev/null
        )
    else
        (
            cd "$workdir" || exit 125
            env -i "${env_args[@]}" "${aider_command[@]}" </dev/null
        )
    fi 2>&1 | tee "$current_log" >>"$logfile"
    # Snapshot the whole pipeline immediately: even a shell assignment resets
    # PIPESTATUS. The Aider status remains the invocation status; tee's status
    # is separate observable log-capture evidence and never replaces it.
    pipeline_status=("${PIPESTATUS[@]}")
    status="${pipeline_status[0]}"
    tee_status="${pipeline_status[1]}"
    end_ns="$(date +%s%N)"
    runtime_ms=$(( (end_ns - start_ns) / 1000000 ))

    # Aider has no OpenCode-style external-directory permission event. Its
    # boundary is structural: no Git discovery/repo map, one explicit editable
    # source and explicit read-only context. Test tampering remains independently
    # detected by capture_candidate.py.
    isolation_rejected=false
    current_log_parent_available=false
    [[ -d "$(dirname "$current_log")" ]] && current_log_parent_available=true
    current_log_parent_writable=false
    [[ -w "$(dirname "$current_log")" ]] && current_log_parent_writable=true
    durable_log_available=false
    [[ -f "$logfile" ]] && durable_log_available=true

    # These are observations derived from the per-invocation parser log. They
    # are tri-state: absence of the log means unknown, never false. In
    # particular, do not let grep or aider_output.py touch a missing path: both
    # produce misleading diagnostics, and pathlib emits a traceback.
    current_log_available=false
    token_limit=unknown
    invalid_editor_output=unknown
    log_capture_condition=current_log_missing_after_pipeline
    if [[ -f "$current_log" ]]; then
        current_log_available=true
        log_capture_condition=none
        token_limit=false
        if grep -Fq 'has hit a token limit!' "$current_log"; then
            token_limit=true
        fi
        invalid_editor_output=false
        if "$PYTHON_BIN" "$AIDER_OUTPUT_TOOL" \
                --log "$current_log" \
                --editor-edit-format "$EDITOR_EDIT_FORMAT"; then
            invalid_editor_output=true
        fi
        rm -f "$current_log"
    else
        warn "Aider invocation $invocation current log unavailable after pipeline (tee_exit=$tee_status parent_directory_available=$current_log_parent_available parent_directory_writable=$current_log_parent_writable durable_log_available=$durable_log_available); token-limit and editor-output observations are unknown"
    fi
    printf '%s %s %s %s %s %s %s %s %s %s %s\n' \
        "$status" "$runtime_ms" "$isolation_rejected" "$token_limit" \
        "$invalid_editor_output" "$current_log_available" "$tee_status" \
        "$current_log_parent_available" "$current_log_parent_writable" \
        "$durable_log_available" "$log_capture_condition"
}

make_loop_record() {
    "$PYTHON_BIN" - "$@" <<'PY'
import json
import sys

(
    loop,
    kind,
    agent_exit,
    isolation_rejected,
    build_exit,
    base_test_exit,
    feature_test_exit,
    agent_ms,
    build_ms,
    base_test_ms,
    feature_test_ms,
    validation_success,
    source_sha256,
    token_limit,
    invalid_editor_output,
    current_log_available,
    tee_exit,
    log_parent_available,
    log_parent_writable,
    durable_log_available,
    log_capture_condition,
    agent_failure_reason,
) = sys.argv[1:]


def observed_boolean(value):
    if value == "unknown":
        return None
    return value == "true"


print(json.dumps({
    "loop": int(loop),
    "kind": kind,
    "agent_exit_code": int(agent_exit),
    "agent_isolation_rejected": isolation_rejected == "true",
    "build_exit_code": int(build_exit),
    "base_test_exit_code": int(base_test_exit),
    "feature_test_exit_code": int(feature_test_exit),
    "agent_runtime_ms": int(agent_ms),
    "build_runtime_ms": int(build_ms),
    "base_test_runtime_ms": int(base_test_ms),
    "feature_test_runtime_ms": int(feature_test_ms),
    "validation_success": validation_success == "true",
    "source_sha256": source_sha256,
    "agent_token_limit": observed_boolean(token_limit),
    "agent_invalid_editor_output": observed_boolean(invalid_editor_output),
    "agent_current_log_available": current_log_available == "true",
    "agent_log_capture_tee_exit_code": int(tee_exit),
    "agent_log_parent_directory_available": log_parent_available == "true",
    "agent_log_parent_directory_writable": log_parent_writable == "true",
    "agent_durable_log_available": durable_log_available == "true",
    "agent_log_capture_condition": (
        None if log_capture_condition == "none" else log_capture_condition
    ),
    "agent_failure_reason": agent_failure_reason or None,
}, separators=(",", ":")))
PY
}

MODEL=""
EDITOR_MODEL="ollama_chat/qwen3-coder-next:latest"
EDITOR_EDIT_FORMAT="editor-diff"
PROMPT=""
SOURCE_PATH=""
SOURCE_MODE="existing"
TEMPERATURE=""
TEMP_MIN="0"
TEMP_MAX="2"
TEMP_POINTS=""
TEMP_LIST=""
# Tracked separately so `--temp-list ""` is rejected as the mistake it is
# rather than silently falling through to the --temp-min/--temp-max path.
TEMP_LIST_SET=0
# Optional sampling parameters. Empty means "not requested": the key is left
# out of the architect model settings entirely, so the server default applies and
# behavior matches a run from before these flags existed. See the SAMPLING
# PARAMETERS note above the per-attempt config builder for what each one is
# measured to do.
TOP_P=""
SAMPLING_SEED=""
MAX_TOKENS=""
NUM_CTX=""
ARCHITECT_THINK=""
MODEL_PROVENANCE_JSON=""
RUNS=1
MAX_LOOPS=3
REPAIR_TEMPLATE=""
ALLOW_NO_PROGRESS=0
OUTPUT_DIR=""
BUILD_CMD=""
BASE_TEST_CMD=""
FEATURE_TEST_CMD=""
EXTRA_TEST_CMD=""
SECURITY_CMD=""
SECURITY_FUZZ_SECONDS="10"
SECURITY_SEED="1"
SECURITY_TIMEOUT="2"
SECURITY_MAX_INPUTS="100"
TIMEOUT_SECONDS=1800
FORCE=0
KEEP_WORKDIR=0
PRUNE_ONLY=""
NO_ANALYSIS=0
REMOTE_BASE_URL=""
REMOTE_API_KEY_ENV=""
REMOTE_TRANSPORT="default"
OLLAMA_TRACE=0
OLLAMA_TRACE_PROXY_PID=""
OLLAMA_TRACE_PROXY_URL=""
ANALYSIS_THRESHOLD=""
ANALYSIS_ARCHITECTURE_THRESHOLD=""
ANALYSIS_STRATEGY_THRESHOLD=""
ANALYSIS_DIVERSITY_K_MAX=""
TEST_DIRS=()
SEED_FILES=()
KEEP_GLOBS=()

AIDER_BIN="${AIDER_BIN:-aider}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
    # Every option below that consumes a value must be given one. Without this
    # guard a trailing `--flag` leaves `shift 2` unable to shift, so the loop
    # re-reads the same argument forever.
    case "$1" in
        --model|--editor-model|--prompt|--source|--source-mode|--temperature|--temp-min| \
        --temp-max|--temp-points|--temp-list|--runs|--max-loops| \
        --top-p|--sampling-seed|--max-tokens|--num-ctx|--architect-think|--editor-edit-format|--model-provenance-json| \
        --repair-prompt| \
        --test-dir|--seed-file|--keep-glob|--build-cmd|--base-test-cmd| \
        --feature-test-cmd|--test-cmd|--extra-test-cmd|--security-cmd| \
        --security-fuzz-seconds|--security-seed|--security-timeout| \
        --security-max-inputs|--timeout|--output-dir| \
        --prune-only|--remote-base-url|--remote-api-key-env| \
        --analysis-threshold|--analysis-architecture-threshold| \
        --analysis-strategy-threshold|--analysis-diversity-k-max)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            ;;
    esac

    case "$1" in
        --model) MODEL="${2:-}"; shift 2 ;;
        --editor-model) EDITOR_MODEL="${2:-}"; shift 2 ;;
        --prompt) PROMPT="${2:-}"; shift 2 ;;
        --source) SOURCE_PATH="${2:-}"; shift 2 ;;
        --source-mode) SOURCE_MODE="${2:-}"; shift 2 ;;
        --temperature) TEMPERATURE="${2:-}"; shift 2 ;;
        --temp-min) TEMP_MIN="${2:-}"; shift 2 ;;
        --temp-max) TEMP_MAX="${2:-}"; shift 2 ;;
        --temp-points) TEMP_POINTS="${2:-}"; shift 2 ;;
        --temp-list) TEMP_LIST="${2:-}"; TEMP_LIST_SET=1; shift 2 ;;
        --runs) RUNS="${2:-}"; shift 2 ;;
        --top-p) TOP_P="${2:-}"; shift 2 ;;
        --sampling-seed) SAMPLING_SEED="${2:-}"; shift 2 ;;
        --max-tokens) MAX_TOKENS="${2:-}"; shift 2 ;;
        --num-ctx) NUM_CTX="${2:-}"; shift 2 ;;
        --architect-think) ARCHITECT_THINK="${2:-}"; shift 2 ;;
        --editor-edit-format) EDITOR_EDIT_FORMAT="${2:-}"; shift 2 ;;
        --model-provenance-json) MODEL_PROVENANCE_JSON="${2:-}"; shift 2 ;;
        --top-k)
            # Native ollama_chat can carry top_k, but changing that experimental
            # control is intentionally outside this backend migration. It needs
            # its own transport-level validation and study design.
            die "--top-k is not supported by this migration; validate and add it as a separate experimental change" ;;
        --seed)
            # --seed-file is the checkpoint source-inheritance file. The two
            # senses of "seed" must never collide in this harness.
            die "--seed is ambiguous here: use --sampling-seed for the token-selection seed, or --seed-file for the inherited source file" ;;
        --max-loops) MAX_LOOPS="${2:-}"; shift 2 ;;
        --repair-prompt) REPAIR_TEMPLATE="${2:-}"; shift 2 ;;
        --allow-no-progress) ALLOW_NO_PROGRESS=1; shift ;;
        --agent)
            die "--agent was removed with the OpenCode backend; Aider always runs in architect mode" ;;
        --test-dir) TEST_DIRS+=("${2:-}"); shift 2 ;;
        --seed-file) SEED_FILES+=("${2:-}"); shift 2 ;;
        --keep-glob) KEEP_GLOBS+=("${2:-}"); shift 2 ;;
        --build-cmd) BUILD_CMD="${2:-}"; shift 2 ;;
        --base-test-cmd) BASE_TEST_CMD="${2:-}"; shift 2 ;;
        --feature-test-cmd|--test-cmd) FEATURE_TEST_CMD="${2:-}"; shift 2 ;;
        --extra-test-cmd) EXTRA_TEST_CMD="${2:-}"; shift 2 ;;
        --security-cmd) SECURITY_CMD="${2:-}"; shift 2 ;;
        --security-fuzz-seconds) SECURITY_FUZZ_SECONDS="${2:-}"; shift 2 ;;
        --security-seed) SECURITY_SEED="${2:-}"; shift 2 ;;
        --security-timeout) SECURITY_TIMEOUT="${2:-}"; shift 2 ;;
        --security-max-inputs) SECURITY_MAX_INPUTS="${2:-}"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
        --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
        --keep-workdir) KEEP_WORKDIR=1; shift ;;
        --prune-only) PRUNE_ONLY="${2:-}"; shift 2 ;;
        --no-analysis) NO_ANALYSIS=1; shift ;;
        --force) FORCE=1; shift ;;
        --remote-base-url) REMOTE_BASE_URL="${2:-}"; shift 2 ;;
        --remote-api-key-env) REMOTE_API_KEY_ENV="${2:-}"; shift 2 ;;
        --ollama-trace) OLLAMA_TRACE=1; shift ;;
        --analysis-threshold) ANALYSIS_THRESHOLD="${2:-}"; shift 2 ;;
        --analysis-architecture-threshold)
            ANALYSIS_ARCHITECTURE_THRESHOLD="${2:-}"; shift 2 ;;
        --analysis-strategy-threshold)
            ANALYSIS_STRATEGY_THRESHOLD="${2:-}"; shift 2 ;;
        --analysis-diversity-k-max)
            ANALYSIS_DIVERSITY_K_MAX="${2:-}"; shift 2 ;;
        --repeats)
            die "--repeats was removed; use --runs for attempts per temperature" ;;
        --base-ref)
            die "--base-ref was removed; this runner does not use Git baselines" ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

if [[ -n "$MODEL_PROVENANCE_JSON" ]]; then
    "$PYTHON_BIN" -c 'import json, sys; value=json.loads(sys.argv[1]); sys.exit(0 if isinstance(value, dict) else 1)' \
        "$MODEL_PROVENANCE_JSON" 2>/dev/null ||
        die "--model-provenance-json must be a valid JSON object"
fi

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN was not found"
command -v git >/dev/null 2>&1 || die "git is required (to resolve repo-relative paths)"

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" ||
    die "run this script inside a Git repository (only used to resolve paths)"
REPO="$(cd "$REPO" && pwd -P)"
TEMPERATURE_TOOL="$REPO/scripts/temperature_value.py"
[[ -f "$TEMPERATURE_TOOL" ]] || die "temperature helper not found: $TEMPERATURE_TOOL"

resolve_repo_path() {
    local path="$1"
    if [[ "$path" == /* ]]; then
        printf '%s' "$path"
    else
        printf '%s' "$REPO/$path"
    fi
}

CAPTURE_TOOL="$REPO/scripts/capture_candidate.py"
[[ -f "$CAPTURE_TOOL" ]] || die "capture helper not found: $CAPTURE_TOOL"

AIDER_SETTINGS_TOOL="$REPO/scripts/aider_settings.py"
[[ -f "$AIDER_SETTINGS_TOOL" ]] || die "Aider settings helper not found: $AIDER_SETTINGS_TOOL"
AIDER_OUTPUT_TOOL="$REPO/scripts/aider_output.py"
[[ -f "$AIDER_OUTPUT_TOOL" ]] || die "Aider output helper not found: $AIDER_OUTPUT_TOOL"
OLLAMA_TRACE_TOOL="$REPO/scripts/ollama_trace_proxy.py"
if [[ "$OLLAMA_TRACE" -eq 1 ]]; then
    [[ -f "$OLLAMA_TRACE_TOOL" ]] ||
        die "Ollama trace proxy not found: $OLLAMA_TRACE_TOOL"
fi

# ---------------------------------------------------------------------------
# Standalone cleanup of existing runs
# ---------------------------------------------------------------------------

if [[ -n "$PRUNE_ONLY" ]]; then
    prune_root="$(resolve_repo_path "$PRUNE_ONLY")"
    [[ -d "$prune_root" ]] || die "--prune-only directory not found: $prune_root"

    printf 'Pruning: %s\n' "$prune_root"
    before="$(du -sk "$prune_root" | cut -f1)"

    # New-format attempts: everything worth keeping is already in candidate/.
    while IFS= read -r workdir; do
        attempt="$(dirname "$workdir")"
        [[ -f "$attempt/COMPLETE" ]] || continue
        if [[ -d "$attempt/candidate" ]]; then
            rm -rf "$workdir"
            printf '  removed %s\n' "${workdir#"$prune_root"/}"
        fi
    done < <(find "$prune_root" -type d -name workdir -path '*/attempt-*' 2>/dev/null)

    # Legacy sandbox runs are analyzed straight out of workdir/, so only the
    # copied test suites and build output can go.
    while IFS= read -r run_json; do
        run_root="$(dirname "$run_json")"
        printf '  legacy sandbox run: %s\n' "${run_root#"$prune_root"/}"
        "$PYTHON_BIN" "$CAPTURE_TOOL" --mode prune-legacy --run-root "$run_root"
    done < <(find "$prune_root" -type f -name run.json 2>/dev/null)

    after="$(du -sk "$prune_root" | cut -f1)"
    "$PYTHON_BIN" - "$before" "$after" <<'PY'
import sys

before, after = int(sys.argv[1]), int(sys.argv[2])


def human(kilobytes: int) -> str:
    if kilobytes < 1024:
        return f"{kilobytes} KB"
    return f"{kilobytes / 1024:.1f} MB"


print(f"\nReclaimed {human(before - after)} ({human(before)} -> {human(after)})")
PY
    exit 0
fi

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

[[ -n "$MODEL" ]] || die "--model is required"
[[ "$MODEL" != "$EDITOR_MODEL" ]] ||
    die "--model and --editor-model must differ so their sampling settings remain role-specific"
[[ -n "$PROMPT" ]] || die "--prompt is required"
[[ -n "$SOURCE_PATH" ]] || die "--source is required"
[[ "$RUNS" =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer"
[[ "$MAX_LOOPS" =~ ^[0-9]+$ ]] || die "--max-loops must be a non-negative integer"
# A value beyond the shell's integer range would break the loop comparison.
MAX_LOOPS="$("$PYTHON_BIN" - "$MAX_LOOPS" <<'PY'
import sys

value = int(sys.argv[1], 10)
if value > sys.maxsize:
    raise SystemExit(1)
print(value)
PY
)" || die "--max-loops is too large for this platform"
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--timeout must be a non-negative integer"
[[ "$SECURITY_SEED" =~ ^[0-9]+$ ]] || die "--security-seed must be a non-negative integer"
[[ "$SECURITY_MAX_INPUTS" =~ ^[1-9][0-9]*$ ]] || die "--security-max-inputs must be a positive integer"
"$PYTHON_BIN" -c 'import math,sys; value=float(sys.argv[1]); raise SystemExit(not math.isfinite(value) or value <= 0)' "$SECURITY_FUZZ_SECONDS" 2>/dev/null ||
    die "--security-fuzz-seconds must be a positive finite number"
"$PYTHON_BIN" -c 'import math,sys; value=float(sys.argv[1]); raise SystemExit(not math.isfinite(value) or value <= 0)' "$SECURITY_TIMEOUT" 2>/dev/null ||
    die "--security-timeout must be a positive finite number"
[[ "$SOURCE_MODE" == "existing" || "$SOURCE_MODE" == "new" ]] ||
    die "--source-mode must be existing or new"

# Optional sampling parameters. Validated here so a typo fails before any
# session starts rather than being recorded as a run condition that the server
# then rejected or ignored.
if [[ -n "$TOP_P" ]]; then
    # stderr discarded so a non-numeric value reports the usage error rather
    # than a Python traceback.
    "$PYTHON_BIN" -c '
import sys

value = float(sys.argv[1])
if not 0.0 <= value <= 1.0:
    raise SystemExit(1)
' "$TOP_P" 2>/dev/null || die "--top-p must be a number between 0 and 1 inclusive"
fi
if [[ -n "$SAMPLING_SEED" ]]; then
    [[ "$SAMPLING_SEED" =~ ^[0-9]+$ ]] ||
        die "--sampling-seed must be a non-negative integer (it is the token-selection seed, not --seed-file)"
fi
if [[ -n "$MAX_TOKENS" ]]; then
    [[ "$MAX_TOKENS" =~ ^[1-9][0-9]*$ ]] ||
        die "--max-tokens must be a positive integer"
fi
if [[ -n "$NUM_CTX" ]]; then
    [[ "$NUM_CTX" =~ ^[1-9][0-9]*$ ]] ||
        die "--num-ctx must be a positive integer"
fi
if [[ -n "$ARCHITECT_THINK" &&
      "$ARCHITECT_THINK" != low &&
      "$ARCHITECT_THINK" != medium &&
      "$ARCHITECT_THINK" != high ]]; then
    die "--architect-think must be low, medium, or high"
fi
if [[ "$EDITOR_EDIT_FORMAT" != whole &&
      "$EDITOR_EDIT_FORMAT" != editor-diff ]]; then
    die "--editor-edit-format must be whole or editor-diff"
fi

"$PYTHON_BIN" - "$SOURCE_PATH" <<'PY' ||
import sys
from pathlib import PurePosixPath

raw = sys.argv[1]
path = PurePosixPath(raw)
valid = bool(raw) and not path.is_absolute() and ".." not in path.parts
valid = valid and str(path) == raw and "\\" not in raw
raise SystemExit(0 if valid else 1)
PY
    die "--source must be a normalized relative path without '..'"

if [[ "$TEMP_LIST_SET" -eq 1 ]]; then
    [[ -z "$TEMPERATURE" ]] ||
        die "--temp-list and --temperature are mutually exclusive"
    [[ -z "$TEMP_POINTS" ]] ||
        die "--temp-list and --temp-points are mutually exclusive"
    # Guard the defaults too: a caller who set an explicit range and then a
    # list has described two different grids.
    [[ "$TEMP_MIN" == "0" && "$TEMP_MAX" == "2" ]] ||
        die "--temp-list and --temp-min/--temp-max are mutually exclusive"
fi

if [[ -n "$TEMPERATURE" ]]; then
    [[ -z "$TEMP_POINTS" || "$TEMP_POINTS" == "1" ]] ||
        die "--temperature and --temp-points are mutually exclusive"
    TEMP_MIN="$TEMPERATURE"
    TEMP_MAX="$TEMPERATURE"
    TEMP_POINTS=1
fi

if [[ "$TEMP_LIST_SET" -eq 1 ]]; then
    # Normalized once here so the grid, the slugs and sweep.json all agree, and
    # so a malformed list fails before any model time is spent. Diagnostics come
    # back on stdout so the reason survives into the die message.
    temp_list_parsed="$(
        "$PYTHON_BIN" "$TEMPERATURE_TOOL" list "$TEMP_LIST" 2>&1
    )" || die "$temp_list_parsed"
    TEMP_LIST="$temp_list_parsed"
    TEMP_POINTS="$(awk -F, '{print NF}' <<<"$TEMP_LIST")"
else
    "$PYTHON_BIN" -c 'import sys; float(sys.argv[1])' "$TEMP_MIN" ||
        die "--temp-min must be numeric"
    "$PYTHON_BIN" -c 'import sys; float(sys.argv[1])' "$TEMP_MAX" ||
        die "--temp-max must be numeric"
    "$PYTHON_BIN" -c 'import sys; sys.exit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)' \
        "$TEMP_MIN" "$TEMP_MAX" || die "--temp-min must be <= --temp-max"

    SWEEP_IS_RANGE=0
    "$PYTHON_BIN" -c 'import sys; sys.exit(0 if float(sys.argv[1]) == float(sys.argv[2]) else 1)' \
        "$TEMP_MIN" "$TEMP_MAX" || SWEEP_IS_RANGE=1

    if [[ -z "$TEMP_POINTS" ]]; then
        if [[ "$SWEEP_IS_RANGE" -eq 1 ]]; then
            # --runs used to mean "temperature points" in run_sandboxed_pipeline.sh
            # and "attempts" in run_llm_experiment.sh. Refuse to guess.
            die "--temp-points is required when --temp-min differs from --temp-max (--runs is attempts per temperature)"
        fi
        TEMP_POINTS=1
    fi
    [[ "$TEMP_POINTS" =~ ^[1-9][0-9]*$ ]] || die "--temp-points must be a positive integer"

    # Canonicalize the endpoints after validation so metadata and scalar runs
    # cannot retain a spelling that differs from the materialized sweep value.
    TEMP_MIN="$("$PYTHON_BIN" "$TEMPERATURE_TOOL" canonical "$TEMP_MIN")" ||
        die "--temp-min must be numeric"
    TEMP_MAX="$("$PYTHON_BIN" "$TEMPERATURE_TOOL" canonical "$TEMP_MAX")" ||
        die "--temp-max must be numeric"
    [[ -z "$TEMPERATURE" ]] || TEMPERATURE="$TEMP_MIN"
fi

if [[ -n "$REMOTE_BASE_URL" ]]; then
    if [[ "$MODEL" == ollama_chat/* && "$EDITOR_MODEL" == ollama_chat/* ]]; then
        REMOTE_TRANSPORT="ollama_native"
        [[ "$REMOTE_BASE_URL" != */v1 && "$REMOTE_BASE_URL" != */v1/ ]] ||
            die "ollama_chat/* needs the native Ollama root (for example http://host:11434), not a /v1 URL"
    elif [[ "$MODEL" == openai/* && "$EDITOR_MODEL" == openai/* ]]; then
        REMOTE_TRANSPORT="openai_compatible"
    else
        die "with --remote-base-url, both models must use either ollama_chat/* (native Ollama) or openai/* (OpenAI-compatible gateway)"
    fi
fi
if [[ -n "$REMOTE_API_KEY_ENV" ]]; then
    [[ -n "${!REMOTE_API_KEY_ENV:-}" ]] ||
        die "$REMOTE_API_KEY_ENV is not set (export it, or omit --remote-api-key-env for an unauthenticated Ollama endpoint)"
fi
if [[ "$OLLAMA_TRACE" -eq 1 ]]; then
    [[ "$MODEL" == ollama_chat/* && "$EDITOR_MODEL" == ollama_chat/* ]] ||
        die "--ollama-trace requires ollama_chat/* architect and editor models"
    OLLAMA_TRACE_UPSTREAM="${REMOTE_BASE_URL:-http://127.0.0.1:11434}"
    "$PYTHON_BIN" - "$OLLAMA_TRACE_UPSTREAM" <<'PY' ||
import sys
from urllib.parse import urlsplit

value = urlsplit(sys.argv[1])
valid = (
    value.scheme == "http"
    and value.hostname in {"127.0.0.1", "localhost", "::1"}
    and value.path in {"", "/"}
    and not value.query
    and not value.fragment
)
raise SystemExit(0 if valid else 1)
PY
        die "--ollama-trace requires a loopback native Ollama root (for example http://127.0.0.1:11434)"
else
    OLLAMA_TRACE_UPSTREAM=""
fi

PROMPT_ABS="$(resolve_repo_path "$PROMPT")"
[[ -f "$PROMPT_ABS" ]] || die "prompt not found: $PROMPT_ABS"

# The agent-visible prompt is the task file with the shared automation notice
# expanded into it (scripts/prompt_render.py, the single expansion point). It is
# rendered ONCE here and then used for every downstream purpose -- the durable
# experiment copy, the copy placed in the sandbox, and the text handed to
# `aider --message-file` -- so those cannot disagree: they are the same file.
RENDER_TOOL="$REPO/scripts/prompt_render.py"
[[ -f "$RENDER_TOOL" ]] || die "prompt renderer not found: $RENDER_TOOL"
RENDERED_PROMPT="$(mktemp)" || die "cannot create the rendered prompt file"
cleanup() {
    if [[ -n "${OLLAMA_TRACE_PROXY_PID:-}" ]]; then
        kill "$OLLAMA_TRACE_PROXY_PID" 2>/dev/null || true
        wait "$OLLAMA_TRACE_PROXY_PID" 2>/dev/null || true
        OLLAMA_TRACE_PROXY_PID=""
    fi
    rm -f "${RENDERED_PROMPT:-}"
}
trap cleanup EXIT

start_ollama_trace_proxy() {
    local trace_dir="$attempt_dir/ollama-trace"
    local ready_file="$attempt_dir/.ollama-trace-ready"
    local proxy_log="$attempt_dir/ollama-trace-proxy.log"
    local readiness_checks=0

    [[ "$OLLAMA_TRACE" -eq 1 ]] || return 0
    [[ -z "$OLLAMA_TRACE_PROXY_PID" ]] ||
        die "internal error: an Ollama trace proxy is already running"
    rm -f "$ready_file"
    "$PYTHON_BIN" "$OLLAMA_TRACE_TOOL" \
        --upstream "$OLLAMA_TRACE_UPSTREAM" \
        --trace-dir "$trace_dir" \
        --allowed-root "$attempt_dir" \
        --ready-file "$ready_file" >"$proxy_log" 2>&1 &
    OLLAMA_TRACE_PROXY_PID=$!

    while [[ ! -s "$ready_file" ]]; do
        if ! kill -0 "$OLLAMA_TRACE_PROXY_PID" 2>/dev/null; then
            wait "$OLLAMA_TRACE_PROXY_PID" 2>/dev/null || true
            OLLAMA_TRACE_PROXY_PID=""
            die "Ollama trace proxy failed to start; see $proxy_log"
        fi
        readiness_checks=$((readiness_checks + 1))
        if [[ "$readiness_checks" -ge 200 ]]; then
            die "Ollama trace proxy did not become ready; see $proxy_log"
        fi
        sleep 0.05
    done
    IFS= read -r OLLAMA_TRACE_PROXY_URL <"$ready_file"
    [[ "$OLLAMA_TRACE_PROXY_URL" == http://127.0.0.1:* ]] ||
        die "Ollama trace proxy reported a non-loopback address"
}

stop_ollama_trace_proxy() {
    [[ -n "$OLLAMA_TRACE_PROXY_PID" ]] || return 0
    kill "$OLLAMA_TRACE_PROXY_PID" 2>/dev/null || true
    wait "$OLLAMA_TRACE_PROXY_PID" 2>/dev/null || true
    OLLAMA_TRACE_PROXY_PID=""
    OLLAMA_TRACE_PROXY_URL=""
    rm -f "$attempt_dir/.ollama-trace-ready"
}

"$PYTHON_BIN" "$RENDER_TOOL" --repo "$REPO" --prompt "$PROMPT_ABS" \
    --output "$RENDERED_PROMPT" ||
    die "cannot render the automation notice into $PROMPT_ABS"
AUTOMATION_NOTICE_SHA256="$(
    "$PYTHON_BIN" "$RENDER_TOOL" --repo "$REPO" --emit sha256
)" || die "cannot hash the shared automation notice"

if [[ -z "$REPAIR_TEMPLATE" ]]; then
    REPAIR_TEMPLATE="$REPO/prompts/repair_continuation_template.md"
else
    REPAIR_TEMPLATE="$(resolve_repo_path "$REPAIR_TEMPLATE")"
fi
if [[ "$MAX_LOOPS" -gt 0 ]]; then
    [[ -f "$REPAIR_TEMPLATE" ]] ||
        die "continuation template not found: $REPAIR_TEMPLATE"
fi
REPAIR_TOOL="$REPO/scripts/repair_prompt.py"
if [[ "$MAX_LOOPS" -gt 0 ]]; then
    [[ -f "$REPAIR_TOOL" ]] || die "repair prompt renderer not found: $REPAIR_TOOL"
fi

# --test-dir accepts SRC[:DEST]. DEST is what the agent sees and what the
# prompt and the validation command name; SRC is where the content comes from,
# which may be a generated per-checkpoint bundle outside the source tree. With
# no DEST the two are the same, which is the original behavior.
TEST_DIR_SOURCES=()
TEST_DIR_DESTINATIONS=()
for test_dir_spec in "${TEST_DIRS[@]+"${TEST_DIRS[@]}"}"; do
    # Split on the LAST colon: DEST is a normalized relative path and so never
    # contains one, while SRC may be absolute.
    if [[ "$test_dir_spec" == *:* ]]; then
        test_dir_src="${test_dir_spec%:*}"
        test_dir_dest="${test_dir_spec##*:}"
    else
        test_dir_src="$test_dir_spec"
        test_dir_dest="$test_dir_spec"
    fi
    [[ -n "$test_dir_src" && -n "$test_dir_dest" ]] ||
        die "--test-dir needs a non-empty SRC and DEST: $test_dir_spec"
    [[ -d "$(resolve_repo_path "$test_dir_src")" ]] ||
        die "--test-dir source not found: $(resolve_repo_path "$test_dir_src")"
    # The destination is created inside the working directory, so it must not
    # be absolute and must not climb out of it.
    "$PYTHON_BIN" - "$test_dir_dest" <<'PY' ||
import sys
from pathlib import PurePosixPath

raw = sys.argv[1]
path = PurePosixPath(raw)
valid = bool(raw) and not path.is_absolute() and ".." not in path.parts
valid = valid and str(path) == raw and "\\" not in raw
raise SystemExit(0 if valid else 1)
PY
        die "--test-dir destination must be a normalized relative path without '..': $test_dir_dest"
    TEST_DIR_SOURCES+=("$test_dir_src")
    TEST_DIR_DESTINATIONS+=("$test_dir_dest")
done

SEED_SOURCE=""
for seed_spec in "${SEED_FILES[@]+"${SEED_FILES[@]}"}"; do
    seed_src="${seed_spec%%:*}"
    if [[ "$seed_spec" == *:* ]]; then
        seed_dest="${seed_spec#*:}"
    else
        seed_dest="$seed_src"
    fi
    [[ -f "$(resolve_repo_path "$seed_src")" ]] ||
        die "--seed-file source not found: $(resolve_repo_path "$seed_src")"
    if [[ "$seed_dest" == "$SOURCE_PATH" ]]; then
        SEED_SOURCE="$(resolve_repo_path "$seed_src")"
    fi
done

if [[ "$SOURCE_MODE" == "existing" && -z "$SEED_SOURCE" ]]; then
    die "--source-mode existing requires a --seed-file whose destination is $SOURCE_PATH"
fi
if [[ "$SOURCE_MODE" == "new" && -n "$SEED_SOURCE" ]]; then
    die "--source-mode new conflicts with a --seed-file targeting $SOURCE_PATH"
fi

if [[ ${#KEEP_GLOBS[@]} -eq 0 ]]; then
    KEEP_GLOBS=("*.c" "*.h")
fi

if [[ -n "$ANALYSIS_ARCHITECTURE_THRESHOLD" ]]; then
    RESOLVED_ARCHITECTURE_THRESHOLD="$ANALYSIS_ARCHITECTURE_THRESHOLD"
elif [[ -n "$ANALYSIS_THRESHOLD" ]]; then
    RESOLVED_ARCHITECTURE_THRESHOLD="$ANALYSIS_THRESHOLD"
else
    RESOLVED_ARCHITECTURE_THRESHOLD="0.30"
fi
if [[ -n "$ANALYSIS_STRATEGY_THRESHOLD" ]]; then
    RESOLVED_STRATEGY_THRESHOLD="$ANALYSIS_STRATEGY_THRESHOLD"
elif [[ -n "$ANALYSIS_THRESHOLD" ]]; then
    RESOLVED_STRATEGY_THRESHOLD="$ANALYSIS_THRESHOLD"
else
    RESOLVED_STRATEGY_THRESHOLD="$RESOLVED_ARCHITECTURE_THRESHOLD"
fi
"$PYTHON_BIN" -c 'import math,sys; values=map(float,sys.argv[1:]); sys.exit(0 if all(math.isfinite(v) and v > 0 for v in values) else 1)' \
    "$RESOLVED_ARCHITECTURE_THRESHOLD" "$RESOLVED_STRATEGY_THRESHOLD" ||
    die "analysis thresholds must be positive numbers"
if [[ -n "$ANALYSIS_DIVERSITY_K_MAX" &&
      ! "$ANALYSIS_DIVERSITY_K_MAX" =~ ^[1-9][0-9]*$ ]]; then
    die "--analysis-diversity-k-max must be a positive integer"
fi

ANALYZER_PATH="$REPO/scripts/analyze_experiment.py"
if [[ "$NO_ANALYSIS" -eq 0 ]]; then
    [[ -f "$ANALYZER_PATH" ]] || die "analyzer not found: $ANALYZER_PATH"
fi

# Checked after argument validation so a bad flag reports the bad flag.
command -v "$AIDER_BIN" >/dev/null 2>&1 || die "$AIDER_BIN was not found"
AIDER_VERSION="$({ "$AIDER_BIN" --version 2>/dev/null || true; } | head -1)"
[[ -n "$AIDER_VERSION" ]] || AIDER_VERSION="unknown"

TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_BIN="gtimeout"
fi
TIMEOUT_ENFORCED=false
if [[ "$TIMEOUT_SECONDS" -gt 0 ]]; then
    if [[ -n "$TIMEOUT_BIN" ]]; then
        TIMEOUT_ENFORCED=true
    else
        warn "no timeout or gtimeout found; sessions run without a per-session limit (--timeout $TIMEOUT_SECONDS ignored)"
    fi
fi

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

MODEL_SLUG="$(slugify "$MODEL")"
PROMPT_SLUG="$(slugify "$(basename "${PROMPT_ABS%.*}")")"
SOURCE_FLAT="$(basename "$SOURCE_PATH")"
PROGRAM_NAME="${SOURCE_FLAT%.*}"

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$REPO/runs/experiments/$MODEL_SLUG/$PROMPT_SLUG"
elif [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="$REPO/$OUTPUT_DIR"
fi
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"

REPO_COMMIT="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || printf 'unknown')"
TEST_DIRS_JOINED="$(IFS=,; printf '%s' "${TEST_DIRS[*]+"${TEST_DIRS[*]}"}")"
SEED_FILES_JOINED="$(IFS=,; printf '%s' "${SEED_FILES[*]+"${SEED_FILES[*]}"}")"

if [[ -n "$TEMP_LIST" ]]; then
    TEMPERATURES="$(tr ',' '\n' <<<"$TEMP_LIST")"
else
    TEMPERATURES="$(
        "$PYTHON_BIN" "$TEMPERATURE_TOOL" range \
            "$TEMP_POINTS" "$TEMP_MIN" "$TEMP_MAX"
    )" || die "cannot materialize the temperature grid"
fi

TEMPERATURES_ARR=()
while IFS= read -r line; do
    [[ -n "$line" ]] && TEMPERATURES_ARR+=("$line")
done <<< "$TEMPERATURES"

write_metadata "$OUTPUT_DIR/sweep.json" \
    schema_version 1 \
    repository "$REPO" \
    repository_commit "$REPO_COMMIT" \
    agent_backend aider \
    aider_version "__STR__:$AIDER_VERSION" \
    architect_model "$MODEL" \
    editor_model "$EDITOR_MODEL" \
    architect_mode true \
    model "$MODEL" \
    model_provenance "__JSON__:${MODEL_PROVENANCE_JSON:-null}" \
    editor_temperature 0 \
    editor_sampling_seed 0 \
    editor_edit_format "$EDITOR_EDIT_FORMAT" \
    remote_base_url "$REMOTE_BASE_URL" \
    remote_api_key_env "$REMOTE_API_KEY_ENV" \
    remote_transport "$REMOTE_TRANSPORT" \
    ollama_trace_enabled "$([[ "$OLLAMA_TRACE" -eq 1 ]] && printf true || printf false)" \
    ollama_trace_path "$([[ "$OLLAMA_TRACE" -eq 1 ]] && printf '__STR__:temp-*/attempt-*/ollama-trace' || printf '__JSON__:null')" \
    prompt "$PROMPT_ABS" \
    source_workdir_path "$SOURCE_PATH" \
    source_path "$SOURCE_FLAT" \
    source_mode "$SOURCE_MODE" \
    temp_min "$TEMP_MIN" \
    temp_max "$TEMP_MAX" \
    temp_points "$TEMP_POINTS" \
    temp_list "$TEMP_LIST" \
    top_p "$(optional_number "$TOP_P")" \
    sampling_seed "$(optional_number "$SAMPLING_SEED")" \
    max_tokens "$(optional_number "$MAX_TOKENS")" \
    num_ctx "$(optional_number "$NUM_CTX")" \
    architect_think "$(optional_string "$ARCHITECT_THINK")" \
    runs_per_temperature "$RUNS" \
    max_loops "$MAX_LOOPS" \
    test_dirs "$TEST_DIRS_JOINED" \
    seed_files "$SEED_FILES_JOINED" \
    build_command "__STR__:$BUILD_CMD" \
    base_test_command "__STR__:$BASE_TEST_CMD" \
    feature_test_command "__STR__:$FEATURE_TEST_CMD" \
    extra_test_command "__STR__:$EXTRA_TEST_CMD" \
    security_command "__STR__:$SECURITY_CMD" \
    security_fuzz_seconds "$SECURITY_FUZZ_SECONDS" \
    security_seed "$SECURITY_SEED" \
    security_timeout "$SECURITY_TIMEOUT" \
    security_max_inputs "$SECURITY_MAX_INPUTS" \
    timeout_seconds "$TIMEOUT_SECONDS" \
    timeout_enforced "$TIMEOUT_ENFORCED" \
    created_at "$(timestamp)"

printf 'Repository:  %s\n' "$REPO"
printf 'Architect:   %s\n' "$MODEL"
printf 'Editor:      %s\n' "$EDITOR_MODEL"
printf 'Aider:       %s\n' "$AIDER_VERSION"
printf 'Prompt:      %s\n' "$PROMPT_ABS"
printf 'Source:      %s (captured as %s)\n' "$SOURCE_PATH" "$SOURCE_FLAT"
if [[ -n "$TEMP_LIST" ]]; then
    printf 'Temperature: %s explicit points (%s)\n' "$TEMP_POINTS" "$TEMP_LIST"
elif [[ "$TEMP_POINTS" -gt 1 ]]; then
    printf 'Temperature: %s points across [%s, %s]\n' \
        "$TEMP_POINTS" "$TEMP_MIN" "$TEMP_MAX"
else
    printf 'Temperature: %s\n' "$TEMP_MIN"
fi
printf 'Attempts:    %s per temperature\n' "$RUNS"
printf 'Max loops:   %s\n' "$MAX_LOOPS"
printf 'Num ctx:     %s\n' "${NUM_CTX:-(Aider default)}"
printf 'Output:      %s\n\n' "$OUTPUT_DIR"

# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

overall_status=0

for temperature in "${TEMPERATURES_ARR[@]}"; do
    temp_slug="$("$PYTHON_BIN" "$TEMPERATURE_TOOL" slug "$temperature")" ||
        die "cannot create the directory slug for temperature $temperature"
    experiment_dir="$OUTPUT_DIR/temp-$temp_slug"
    mkdir -p "$experiment_dir"

    if [[ -f "$experiment_dir/experiment.json" ]]; then
        mismatches="$(
            "$PYTHON_BIN" - "$experiment_dir/experiment.json" \
                "$MODEL" "$EDITOR_MODEL" "$AIDER_VERSION" "$temperature" "$PROMPT_ABS" \
                "$SOURCE_FLAT" "$SOURCE_PATH" "$SOURCE_MODE" "$MAX_LOOPS" \
                "$BUILD_CMD" "$BASE_TEST_CMD" "$FEATURE_TEST_CMD" \
                "$EXTRA_TEST_CMD" \
                "$RESOLVED_ARCHITECTURE_THRESHOLD" \
                "$RESOLVED_STRATEGY_THRESHOLD" \
                "${ANALYSIS_DIVERSITY_K_MAX:-__NONE__}" \
                "${TOP_P:-__NONE__}" "${SAMPLING_SEED:-__NONE__}" \
                "${MAX_TOKENS:-__NONE__}" \
                "${NUM_CTX:-__NONE__}" \
                "${ARCHITECT_THINK:-__NONE__}" \
                "$EDITOR_EDIT_FORMAT" \
                "${MODEL_PROVENANCE_JSON:-__NONE__}" \
                "${REMOTE_BASE_URL:-__NONE__}" \
                "${REMOTE_API_KEY_ENV:-__NONE__}" \
                "$REMOTE_TRANSPORT" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
(
    model,
    editor_model,
    aider_version,
    temperature,
    prompt,
    source_path,
    source_workdir_path,
    source_mode,
    max_loops,
    build_command,
    base_test_command,
    feature_test_command,
    extra_test_command,
    architecture_threshold,
    strategy_threshold,
    diversity_k_max,
    top_p,
    sampling_seed,
    max_tokens,
    num_ctx,
    architect_think,
    editor_edit_format,
    model_provenance_json,
    remote_base_url,
    remote_api_key_env,
    remote_transport,
) = sys.argv[2:]
expected = {
    "agent_backend": "aider",
    "aider_version": aider_version,
    "architect_model": model,
    "editor_model": editor_model,
    "architect_mode": True,
    "model": model,
    "model_provenance": (
        None if model_provenance_json == "__NONE__"
        else json.loads(model_provenance_json)
    ),
    "temperature": float(temperature),
    # Sampling conditions are part of what an attempt directory means, so
    # resuming into one with a different knob is the same mistake as resuming
    # into one at a different temperature.
    "top_p": None if top_p == "__NONE__" else float(top_p),
    "sampling_seed": None if sampling_seed == "__NONE__" else int(sampling_seed),
    "max_tokens": None if max_tokens == "__NONE__" else int(max_tokens),
    "num_ctx": None if num_ctx == "__NONE__" else int(num_ctx),
    "architect_think": (
        None if architect_think == "__NONE__" else architect_think
    ),
    "editor_temperature": 0,
    "editor_sampling_seed": 0,
    "editor_edit_format": editor_edit_format,
    "remote_base_url": None if remote_base_url == "__NONE__" else remote_base_url,
    "remote_api_key_env": (
        None if remote_api_key_env == "__NONE__" else remote_api_key_env
    ),
    "remote_transport": remote_transport,
    "prompt": prompt,
    "source_path": source_path,
    "source_workdir_path": source_workdir_path,
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
        [[ -z "$mismatches" ]] ||
            die "existing experiment configuration differs at $experiment_dir: $mismatches"
    fi

    # Baseline the analyzer diffs every candidate against.
    baseline_dir="$experiment_dir/baseline"
    mkdir -p "$baseline_dir"
    if [[ "$SOURCE_MODE" == "existing" ]]; then
        cp -p "$SEED_SOURCE" "$baseline_dir/$SOURCE_FLAT"
        baseline_kind="existing_source_snapshot"
    else
        : > "$baseline_dir/$SOURCE_FLAT"
        baseline_kind="empty_new_source"
    fi

    # The durable copy is the RENDERED prompt, so what provenance records is
    # exactly what the model was shown, notice included.
    cp "$RENDERED_PROMPT" "$experiment_dir/prompt.md"

    write_metadata "$experiment_dir/experiment.json" \
        schema_version 2 \
        repository "$REPO" \
        repository_commit "$REPO_COMMIT" \
        agent_backend aider \
        aider_version "__STR__:$AIDER_VERSION" \
        architect_model "$MODEL" \
        editor_model "$EDITOR_MODEL" \
        architect_mode true \
        model "$MODEL" \
        model_provenance "__JSON__:${MODEL_PROVENANCE_JSON:-null}" \
        temperature "$temperature" \
        top_p "$(optional_number "$TOP_P")" \
        sampling_seed "$(optional_number "$SAMPLING_SEED")" \
        max_tokens "$(optional_number "$MAX_TOKENS")" \
        num_ctx "$(optional_number "$NUM_CTX")" \
        architect_think "$(optional_string "$ARCHITECT_THINK")" \
        editor_temperature 0 \
        editor_sampling_seed 0 \
        editor_edit_format "$EDITOR_EDIT_FORMAT" \
        remote_base_url "$([[ -n "$REMOTE_BASE_URL" ]] && printf '__STR__:%s' "$REMOTE_BASE_URL" || printf '__JSON__:null')" \
        remote_api_key_env "$([[ -n "$REMOTE_API_KEY_ENV" ]] && printf '__STR__:%s' "$REMOTE_API_KEY_ENV" || printf '__JSON__:null')" \
        remote_transport "$REMOTE_TRANSPORT" \
        ollama_trace_enabled "$([[ "$OLLAMA_TRACE" -eq 1 ]] && printf true || printf false)" \
        ollama_trace_path "$([[ "$OLLAMA_TRACE" -eq 1 ]] && printf '__STR__:attempt-*/ollama-trace' || printf '__JSON__:null')" \
        prompt "$PROMPT_ABS" \
        prompt_copy "$experiment_dir/prompt.md" \
        automation_notice_sha256 "$AUTOMATION_NOTICE_SHA256" \
        source_path "$SOURCE_FLAT" \
        source_workdir_path "$SOURCE_PATH" \
        source_mode "$SOURCE_MODE" \
        baseline_source_kind "$baseline_kind" \
        requested_runs "$RUNS" \
        max_loops "$MAX_LOOPS" \
        test_dirs "$TEST_DIRS_JOINED" \
        seed_files "$SEED_FILES_JOINED" \
        build_command "__STR__:$BUILD_CMD" \
        base_test_command "__STR__:$BASE_TEST_CMD" \
        feature_test_command "__STR__:$FEATURE_TEST_CMD" \
        extra_test_command "__STR__:$EXTRA_TEST_CMD" \
        security_command "__STR__:$SECURITY_CMD" \
        security_fuzz_seconds "$SECURITY_FUZZ_SECONDS" \
        security_seed "$SECURITY_SEED" \
        security_timeout "$SECURITY_TIMEOUT" \
        security_max_inputs "$SECURITY_MAX_INPUTS" \
        timeout_seconds "$TIMEOUT_SECONDS" \
        timeout_enforced "$TIMEOUT_ENFORCED" \
        analysis_architecture_threshold "$RESOLVED_ARCHITECTURE_THRESHOLD" \
        analysis_strategy_threshold "$RESOLVED_STRATEGY_THRESHOLD" \
        analysis_diversity_k_max "$([[ -n "$ANALYSIS_DIVERSITY_K_MAX" ]] && printf '%s' "$ANALYSIS_DIVERSITY_K_MAX" || printf '__JSON__:null')" \
        created_at "$(timestamp)"

    printf '=== temperature %s -> %s ===\n' "$temperature" "temp-$temp_slug"

    for attempt_number in $(seq 1 "$RUNS"); do
        attempt_id="$(printf 'attempt-%03d' "$attempt_number")"
        attempt_dir="$experiment_dir/$attempt_id"
        workdir="$attempt_dir/workdir"

        if [[ -f "$attempt_dir/COMPLETE" && "$FORCE" -eq 0 ]]; then
            printf '[%s/%s] %s already complete; skipping\n' \
                "$attempt_number" "$RUNS" "$attempt_id"
            continue
        fi

        printf '[%s/%s] starting %s\n' "$attempt_number" "$RUNS" "$attempt_id"

        rm -rf "$attempt_dir"
        mkdir -p "$workdir"

        # Seed the working directory. This is everything the agent can see.
        # Rendered, under the task file's own name: the copy the agent can read
        # must match the text it was sent.
        WORKDIR_PROMPT_PATH="$(basename "$PROMPT_ABS")"
        cp "$RENDERED_PROMPT" "$workdir/$WORKDIR_PROMPT_PATH"
        for (( test_dir_index = 0;
               test_dir_index < ${#TEST_DIR_SOURCES[@]};
               test_dir_index++ )); do
            test_dir_dest="${TEST_DIR_DESTINATIONS[test_dir_index]}"
            mkdir -p "$(dirname "$workdir/$test_dir_dest")"
            cp -R "$(resolve_repo_path "${TEST_DIR_SOURCES[test_dir_index]}")" \
                "$workdir/$test_dir_dest"
        done
        for seed_spec in "${SEED_FILES[@]+"${SEED_FILES[@]}"}"; do
            seed_src="${seed_spec%%:*}"
            if [[ "$seed_spec" == *:* ]]; then
                seed_dest="${seed_spec#*:}"
            else
                seed_dest="$seed_src"
            fi
            mkdir -p "$(dirname "$workdir/$seed_dest")"
            cp -p "$(resolve_repo_path "$seed_src")" "$workdir/$seed_dest"
        done

        # Aider must receive an editable file even for a new-source checkpoint.
        # The empty file is still the same empty analysis baseline, and a
        # successful invocation must replace it with a non-empty implementation.
        mkdir -p "$(dirname "$workdir/$SOURCE_PATH")"
        [[ -e "$workdir/$SOURCE_PATH" ]] || : >"$workdir/$SOURCE_PATH"

        # Reject config-shaped files at the workspace root. Aider searches CWD
        # during early startup, before all command-line options are applied.
        # Formal inputs must not be able to inject configuration through that
        # search path.
        for reserved in .env .aider.conf.yml .aider.model.settings.yml \
                        .aider.model.metadata.json; do
            [[ ! -e "$workdir/$reserved" ]] ||
                die "attempt workspace contains reserved Aider config path: $reserved"
        done

        AIDER_HOME="$attempt_dir/aider-home"
        mkdir -p "$AIDER_HOME/tmp"
        AIDER_CONFIG_FILE="$attempt_dir/aider.conf.yml"
        AIDER_ENV_FILE="$attempt_dir/aider.env"
        AIDER_MODEL_SETTINGS_FILE="$attempt_dir/aider-model-settings.yml"
        printf '{}\n' >"$AIDER_CONFIG_FILE"
        : >"$AIDER_ENV_FILE"
        "$PYTHON_BIN" "$AIDER_SETTINGS_TOOL" \
            --architect-model "$MODEL" \
            --editor-model "$EDITOR_MODEL" \
            --temperature "$temperature" \
            --top-p "$TOP_P" \
            --sampling-seed "$SAMPLING_SEED" \
            --max-tokens "$MAX_TOKENS" \
            --num-ctx "$NUM_CTX" \
            --architect-think "$ARCHITECT_THINK" \
            --editor-edit-format "$EDITOR_EDIT_FORMAT" \
            --output "$AIDER_MODEL_SETTINGS_FILE" \
            --emit sha256 >"$attempt_dir/aider-model-settings.sha256" ||
            die "failed to build per-attempt Aider model settings"
        AIDER_MODEL_SETTINGS_SHA256="$(tr -d '\r\n' <"$attempt_dir/aider-model-settings.sha256")"
        AIDER_MODEL_SETTINGS_JSON="$(cat "$AIDER_MODEL_SETTINGS_FILE")"

        # Explicit read-only context, limited to text files already copied into
        # this attempt. Binary/compressed corpora remain present for controller
        # validation but are not injected wholesale into either model context.
        AIDER_READ_ARGS=()
        while IFS= read -r visible_file; do
            [[ "$visible_file" == "$SOURCE_PATH" ]] && continue
            # --message-file already supplies the rendered task. Keeping its
            # durable workspace copy out of --read avoids duplicating the full
            # task in both models' contexts.
            [[ "$visible_file" == "$WORKDIR_PROMPT_PATH" ]] && continue
            case "$visible_file" in
                *.c|*.h|*.py|*.sh|*.json|*.md|*.txt|*.toml|*.yaml|*.yml)
                    AIDER_READ_ARGS+=(--read "$visible_file") ;;
            esac
        done < <(cd "$workdir" && find . -type f -print | sed 's#^./##' | LC_ALL=C sort)

        : >"$attempt_dir/aider.log"
        : >"$attempt_dir/build.log"
        : >"$attempt_dir/base-tests.log"
        : >"$attempt_dir/feature-tests.log"

        start_ollama_trace_proxy

        current_prompt="$RENDERED_PROMPT"
        repair_loops=0
        total_agent_ms=0
        initial_agent_ms=0
        repair_agent_ms=0
        total_build_ms=0
        total_base_test_ms=0
        total_feature_test_ms=0
        agent_isolation_rejected=false
        initial_success=false
        public_validation_success=false
        success_loop_json=null
        agent_execution_failed=false
        agent_execution_failure_stage_json=null
        agent_failure_reason_json=null
        stop_reason=""
        previous_source_sha=""
        loop_records=()
        # Timeout provenance. A session that runs out of time may still have
        # written a usable source, and the controller builds and tests that
        # source itself -- so the attempt can have real public-test feedback
        # even though the agent never finished. These record which of those two
        # timeouts happened, and are never used to erase the timeout itself:
        # agent_exit_code stays 124 and timeout_enforced stays true either
        # way.
        initial_session_completed=false
        # agent_exit_code records the LAST process, so after a successful
        # repair it reads 0 and the initial timeout would survive only inside
        # loops[0]. Kept at the top level too, so "this candidate came out of a
        # session that ran out of time" is never lost to a later success.
        initial_agent_exit=""
        candidate_available_after_initial_session=false
        candidate_available_after_timeout=false
        validation_completed_after_timeout=false
        repair_eligible=false
        repair_eligibility_reason="not_evaluated"
        # Post-invocation log-capture evidence is recorded separately from the
        # setup-only infrastructure_failure classification. It must not erase
        # an independently validated candidate outcome.
        agent_log_capture_complete=true
        agent_log_capture_issue_observed=false

        # ---- generate / validate / continue -------------------------------
        # Loop 0 is the initial generation; loops 1..MAX_LOOPS are repairs, so
        # the budget bounds the iteration count directly.
        for (( validation_loop = 0; validation_loop <= MAX_LOOPS; validation_loop++ )); do
            if [[ "$validation_loop" -eq 0 ]]; then
                invocation_kind="INITIAL"
                loop_kind="initial"
            else
                invocation_kind="REPAIR LOOP $validation_loop"
                loop_kind="repair"
                repair_loops=$((repair_loops + 1))
            fi

            read -r agent_exit agent_ms invocation_isolation_rejected \
                invocation_token_limit invocation_invalid_editor_output \
                invocation_current_log_available invocation_tee_exit \
                invocation_log_parent_available \
                invocation_log_parent_writable \
                invocation_durable_log_available \
                invocation_log_capture_condition < <(
                run_aider \
                    "$attempt_dir/aider.log" \
                    "$workdir" \
                    "$current_prompt" \
                    "$validation_loop" \
                    "$invocation_kind"
            )
            total_agent_ms=$((total_agent_ms + agent_ms))
            if [[ "$validation_loop" -eq 0 ]]; then
                initial_agent_ms="$agent_ms"
            else
                repair_agent_ms=$((repair_agent_ms + agent_ms))
            fi
            if [[ "$invocation_isolation_rejected" == true ]]; then
                agent_isolation_rejected=true
            fi
            if [[ "$invocation_current_log_available" != true ]]; then
                agent_log_capture_complete=false
                agent_log_capture_issue_observed=true
            fi

            # Did this session leave a source behind? A timeout is only fatal
            # when it did not. The controller compiles and tests the source
            # itself, so a session that ran out of time after writing one still
            # produced something with a real, actionable validation result --
            # observed: exit 124 with build 0 and checkpoint tests 1, which the
            # controller then refused to repair. Non-empty, because an empty
            # file is not an implementation.
            invocation_candidate_present=false
            if [[ -s "$workdir/$SOURCE_PATH" ]]; then
                invocation_candidate_present=true
            fi
            invocation_timed_out=false
            if [[ "$agent_exit" -eq 124 ]]; then
                invocation_timed_out=true
            fi
            if [[ "$validation_loop" -eq 0 ]]; then
                initial_agent_exit="$agent_exit"
                candidate_available_after_initial_session="$invocation_candidate_present"
                if [[ "$agent_exit" -eq 0 &&
                      "$invocation_isolation_rejected" == false &&
                      "$invocation_token_limit" == false &&
                      "$invocation_invalid_editor_output" == false ]]; then
                    initial_session_completed=true
                fi
                if [[ "$invocation_timed_out" == true &&
                      "$invocation_candidate_present" == true ]]; then
                    candidate_available_after_timeout=true
                fi
            fi

            invocation_agent_execution_failed=false
            invocation_agent_failure_reason=""
            if [[ "$invocation_token_limit" == true ]]; then
                # Aider may exit zero after reporting this explicit generation
                # failure. It is terminal regardless of source contents or
                # controller validation: a truncated architect response is not
                # a completed repair attempt and must never become no_progress.
                invocation_agent_execution_failed=true
                agent_execution_failed=true
                agent_execution_failure_stage_json='"token_limit"'
                agent_failure_reason_json='"output_token_limit"'
                invocation_agent_failure_reason="output_token_limit"
            elif [[ "$invocation_invalid_editor_output" == true ]]; then
                # Only concrete protocol evidence reaches this branch. Failed
                # tests and unchanged candidates are not edit-format failures.
                invocation_agent_execution_failed=true
                agent_execution_failed=true
                agent_execution_failure_stage_json='"editor_output"'
                agent_failure_reason_json='"invalid_edit_format"'
                invocation_agent_failure_reason="invalid_edit_format"
            elif [[ "$invocation_isolation_rejected" == true ]]; then
                # A rejected permission means the sandbox boundary held, not
                # that the model produced work. Unchanged.
                invocation_agent_execution_failed=true
                agent_execution_failed=true
                agent_execution_failure_stage_json='"permission"'
            elif [[ "$invocation_timed_out" == true &&
                    "$invocation_candidate_present" == true ]]; then
                # Repair-eligible timeout: fall through to controller
                # validation and, if that fails, to the repair loop. Nothing is
                # rewritten -- the exit code, timeout_enforced and
                # initial_session_completed all still say the session was cut
                # short, so reliability analysis can tell this apart from a
                # session that finished on its own.
                :
            elif [[ "$agent_exit" -ne 0 ]]; then
                invocation_agent_execution_failed=true
                agent_execution_failed=true
                if [[ "$invocation_timed_out" == true ]]; then
                    # Timed out with nothing to show for it: no implementation
                    # exists, so there is nothing to repair.
                    agent_execution_failure_stage_json='"timeout"'
                else
                    agent_execution_failure_stage_json='"aider"'
                fi
            fi

            source_sha="$(file_sha256 "$workdir/$SOURCE_PATH")"

            # Independent verification, run by the controller not the agent.
            read -r build_exit build_ms < <(
                cd "$workdir" &&
                run_logged_command \
                    "$attempt_dir/build.log" "$BUILD_CMD" \
                    "$validation_loop" "BUILD"
            )
            read -r base_test_exit base_test_ms < <(
                cd "$workdir" &&
                run_logged_command \
                    "$attempt_dir/base-tests.log" "$BASE_TEST_CMD" \
                    "$validation_loop" "BASE TESTS"
            )
            read -r feature_test_exit feature_test_ms < <(
                cd "$workdir" &&
                run_logged_command \
                    "$attempt_dir/feature-tests.log" "$FEATURE_TEST_CMD" \
                    "$validation_loop" "CHECKPOINT TESTS"
            )
            total_build_ms=$((total_build_ms + build_ms))
            total_base_test_ms=$((total_base_test_ms + base_test_ms))
            total_feature_test_ms=$((total_feature_test_ms + feature_test_ms))

            # The controller ran its own build and tests against the source a
            # timed-out session left behind, so this attempt has a validation
            # verdict rather than nothing.
            if [[ "$invocation_timed_out" == true &&
                  "$invocation_candidate_present" == true ]]; then
                validation_completed_after_timeout=true
            fi

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
                "$agent_exit" "$invocation_isolation_rejected" \
                "$build_exit" "$base_test_exit" "$feature_test_exit" \
                "$agent_ms" "$build_ms" "$base_test_ms" \
                "$feature_test_ms" "$validation_success" "$source_sha" \
                "$invocation_token_limit" \
                "$invocation_invalid_editor_output" \
                "$invocation_current_log_available" \
                "$invocation_tee_exit" \
                "$invocation_log_parent_available" \
                "$invocation_log_parent_writable" \
                "$invocation_durable_log_available" \
                "$invocation_log_capture_condition" \
                "$invocation_agent_failure_reason")")

            printf '    loop %s: build=%s base=%s checkpoint=%s\n' \
                "$validation_loop" "$build_exit" "$base_test_exit" \
                "$feature_test_exit"

            if [[ "$invocation_agent_execution_failed" == true ]]; then
                stop_reason="agent_execution_failure"
                break
            fi
            if [[ "$validation_success" == true ]]; then
                public_validation_success=true
                success_loop_json="$validation_loop"
                stop_reason="success"
                break
            fi
            if [[ "$validation_loop" -ge "$MAX_LOOPS" ]]; then
                stop_reason="loop_limit"
                break
            fi
            if [[ "$ALLOW_NO_PROGRESS" -eq 0 &&
                  -n "$previous_source_sha" &&
                  "$source_sha" == "$previous_source_sha" ]]; then
                stop_reason="no_progress"
                printf '    stopping: source unchanged since the previous loop\n'
                break
            fi
            previous_source_sha="$source_sha"

            next_loop=$((validation_loop + 1))
            repair_prompt_file="$attempt_dir/repair-prompt-$next_loop.md"
            json_report_dir=""
            for test_dir_dest in "${TEST_DIR_DESTINATIONS[@]+"${TEST_DIR_DESTINATIONS[@]}"}"; do
                if [[ -d "$workdir/$test_dir_dest/run_logs" ]]; then
                    json_report_dir="$workdir/$test_dir_dest/run_logs"
                    break
                fi
            done

            repair_args=(
                --template "$REPAIR_TEMPLATE"
                # The UNrendered task file on purpose. The continuation
                # template carries its own [AUTOMATION_NOTICE], which
                # repair_prompt.py expands through the same renderer, so the
                # notice is stated once at the top of the repair prompt rather
                # than twice -- once there and again inside the quoted original
                # task.
                --original-prompt "$PROMPT_ABS"
                --program "$PROGRAM_NAME"
                --source-path "$SOURCE_PATH"
                --loop-number "$next_loop"
                --max-loops "$MAX_LOOPS"
                --build-command "$BUILD_CMD"
                --build-log "$attempt_dir/build.log"
                --build-exit "$build_exit"
                --base-test-log "$attempt_dir/base-tests.log"
                --base-test-exit "$base_test_exit"
                --feature-test-log "$attempt_dir/feature-tests.log"
                --feature-test-exit "$feature_test_exit"
            )
            for test_dir_dest in "${TEST_DIR_DESTINATIONS[@]+"${TEST_DIR_DESTINATIONS[@]}"}"; do
                repair_args+=(--test-dir "$test_dir_dest")
            done
            for command in "$BUILD_CMD" "$BASE_TEST_CMD" "$FEATURE_TEST_CMD"; do
                [[ -n "$command" ]] && repair_args+=(--validation-command "$command")
            done
            [[ -n "$json_report_dir" ]] &&
                repair_args+=(--json-report-dir "$json_report_dir")

            if ! "$PYTHON_BIN" "$REPAIR_TOOL" "${repair_args[@]}" \
                    >"$repair_prompt_file"; then
                warn "failed to render continuation prompt; stopping repair"
                stop_reason="repair_prompt_failed"
                break
            fi
            current_prompt="$repair_prompt_file"
        done
        # ---- end loop -----------------------------------------------------

        # Aider is the only traced process. Stop before controller validation
        # artifacts are captured so the proxy can never become agent-visible
        # input or repair feedback.
        stop_ollama_trace_proxy

        # Every path above breaks with a reason; this only guards a future edit
        # that lets the bound expire instead.
        [[ -n "$stop_reason" ]] || stop_reason="loop_limit"

        # Was this attempt in a state a continuation session could act on after
        # its initial generation? Recorded whether or not repair was configured,
        # so a run with --max-loops 0 still says why nothing was retried, and so
        # the repair-recovery denominator can be reconstructed from metadata
        # alone rather than inferred from exit codes.
        if [[ "$agent_execution_failed" == true ]]; then
            repair_eligibility_reason="agent_execution_failure"
        elif [[ "$initial_success" == true ]]; then
            repair_eligibility_reason="initial_validation_passed"
        elif [[ "$candidate_available_after_initial_session" != true ]]; then
            repair_eligibility_reason="no_candidate_after_initial_session"
        elif [[ "$MAX_LOOPS" -eq 0 ]]; then
            # The candidate is real and failed public validation; only the
            # budget is missing. It is a failed implementation, not an absent
            # one.
            repair_eligibility_reason="no_repair_budget"
        else
            repair_eligible=true
            if [[ "$candidate_available_after_timeout" == true ]]; then
                repair_eligibility_reason="controller_validation_after_timeout"
            else
                repair_eligibility_reason="controller_validation_feedback"
            fi
        fi

        llm_invocations=${#loop_records[@]}
        loops_json="$("$PYTHON_BIN" - "${loop_records[@]}" <<'PY'
import json
import sys

print(json.dumps([json.loads(record) for record in sys.argv[1:]], separators=(",", ":")))
PY
        )"

        loop_limit_reached=false
        if [[ "$stop_reason" == "loop_limit" ]]; then
            loop_limit_reached=true
        fi

        # Hidden functional evaluation: after the loop, never fed back as repair.
        #
        # HELDOUT_ROOT lets a committed manifest name a path OUTSIDE the
        # sandbox. The command is eval'd in the controller's shell with the
        # working directory set to the attempt sandbox, so a relative path
        # would resolve inside it -- exactly where held-out material must never
        # be. Exported rather than relying on $REPO so the contract a manifest
        # depends on is explicit and greppable, not an internal variable of
        # this script.
        export HELDOUT_ROOT="$REPO"
        read -r extra_test_exit extra_test_ms < <(
            cd "$workdir" &&
            run_final_command "$attempt_dir/extra-tests.log" "$EXTRA_TEST_CMD"
        )

        total_ms=$((total_agent_ms + total_build_ms + total_base_test_ms + total_feature_test_ms + extra_test_ms))

        # A failing candidate is an experimental result, not a runner error, so
        # it is recorded in metadata without affecting the exit status. Only
        # capture or analysis failures make the run itself unsuccessful.
        overall_success=true
        if [[ "$agent_execution_failed" == true ||
              "$public_validation_success" == false ||
              "$extra_test_exit" -ne 0 ]]; then
            overall_success=false
        fi

        # The functional outcome above is final. Security is a separate,
        # controller-only observation and cannot alter it or enter a repair
        # prompt. Only functionally successful candidates are in scope for the
        # post-validation evaluator.
        security_test_exit=""
        security_test_ms=0
        security_evaluation_completed=false
        security_clean_json=null
        if [[ "$overall_success" == true && -n "$SECURITY_CMD" ]]; then
            export SECURITY_ROOT="$REPO"
            export SECURITY_PYTHON="$PYTHON_BIN"
            export SECURITY_OUTPUT="$attempt_dir/security_results.json"
            export SECURITY_ARTIFACTS="$attempt_dir/security_artifacts"
            export SECURITY_FUZZ_SECONDS SECURITY_SEED SECURITY_TIMEOUT SECURITY_MAX_INPUTS
            read -r security_test_exit security_test_ms < <(
                cd "$workdir" &&
                run_final_command "$attempt_dir/security-tests.log" "$SECURITY_CMD"
            )
            read -r security_evaluation_completed security_clean_json < <(
                "$PYTHON_BIN" - "$attempt_dir/security_results.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    print("false null")
else:
    completed = data.get("security_evaluation_completed") is True
    clean = data.get("security_clean") if completed else None
    print("true" if completed else "false", json.dumps(clean))
PY
            )
        else
            : >"$attempt_dir/security-tests.log"
        fi

        # Flatten the sources, record any test tampering, drop the workdir.
        capture_args=(
            --mode attempt
            --workdir "$workdir"
            --attempt-dir "$attempt_dir"
            --baseline-dir "$baseline_dir"
            --repository "$REPO"
        )
        for glob in "${KEEP_GLOBS[@]}"; do
            capture_args+=(--keep-glob "$glob")
        done
        for (( test_dir_index = 0;
               test_dir_index < ${#TEST_DIR_SOURCES[@]};
               test_dir_index++ )); do
            capture_args+=(--test-dir                 "${TEST_DIR_SOURCES[test_dir_index]}:${TEST_DIR_DESTINATIONS[test_dir_index]}")
        done
        [[ "$KEEP_WORKDIR" -eq 1 ]] && capture_args+=(--keep-workdir)

        capture_json="$("$PYTHON_BIN" "$CAPTURE_TOOL" "${capture_args[@]}")" || {
            warn "capture failed for $attempt_id"
            capture_json='{}'
            overall_status=1
        }
        integrity_json="$("$PYTHON_BIN" - "$capture_json" <<'PY'
import json
import sys

data = json.loads(sys.argv[1] or "{}")
print(json.dumps(data.get("test_dir_integrity", {}), separators=(",", ":")))
PY
        )"
        workdir_pruned="$("$PYTHON_BIN" - "$capture_json" <<'PY'
import json
import sys

data = json.loads(sys.argv[1] or "{}")
print("true" if data.get("workdir_pruned") else "false")
PY
        )"

        write_metadata "$attempt_dir/metadata.json" \
            schema_version 2 \
            run_id "$attempt_id" \
            attempt_number "$attempt_number" \
            agent_backend aider \
            aider_version "__STR__:$AIDER_VERSION" \
            architect_model "$MODEL" \
            editor_model "$EDITOR_MODEL" \
            architect_mode true \
            model "$MODEL" \
            model_provenance "__JSON__:${MODEL_PROVENANCE_JSON:-null}" \
            temperature "$temperature" \
            top_p "$(optional_number "$TOP_P")" \
            sampling_seed "$(optional_number "$SAMPLING_SEED")" \
            max_tokens "$(optional_number "$MAX_TOKENS")" \
            num_ctx "$(optional_number "$NUM_CTX")" \
            architect_think "$(optional_string "$ARCHITECT_THINK")" \
            architect_sampling "__JSON__:$("$PYTHON_BIN" -c 'import json,sys; s=json.loads(sys.argv[1]); print(json.dumps(s[0]["extra_params"],separators=(",",":")))' "$AIDER_MODEL_SETTINGS_JSON")" \
            editor_sampling "__JSON__:$("$PYTHON_BIN" -c 'import json,sys; s=json.loads(sys.argv[1]); print(json.dumps(s[1]["extra_params"],separators=(",",":")))' "$AIDER_MODEL_SETTINGS_JSON")" \
            editor_edit_format "$EDITOR_EDIT_FORMAT" \
            aider_model_settings "__JSON__:$AIDER_MODEL_SETTINGS_JSON" \
            aider_model_settings_sha256 "$AIDER_MODEL_SETTINGS_SHA256" \
            remote_base_url "$([[ -n "$REMOTE_BASE_URL" ]] && printf '__STR__:%s' "$REMOTE_BASE_URL" || printf '__JSON__:null')" \
            remote_api_key_env "$([[ -n "$REMOTE_API_KEY_ENV" ]] && printf '__STR__:%s' "$REMOTE_API_KEY_ENV" || printf '__JSON__:null')" \
            remote_transport "$REMOTE_TRANSPORT" \
            ollama_trace_enabled "$([[ "$OLLAMA_TRACE" -eq 1 ]] && printf true || printf false)" \
            ollama_trace_path "$([[ "$OLLAMA_TRACE" -eq 1 ]] && printf '__STR__:ollama-trace' || printf '__JSON__:null')" \
            source_path "$SOURCE_FLAT" \
            source_workdir_path "$SOURCE_PATH" \
            source_mode "$SOURCE_MODE" \
            max_loops "$MAX_LOOPS" \
            agent_exit_code "$agent_exit" \
            agent_isolation_rejected "$agent_isolation_rejected" \
            build_exit_code "$build_exit" \
            base_test_exit_code "$base_test_exit" \
            feature_test_exit_code "$feature_test_exit" \
            extra_test_exit_code "$extra_test_exit" \
            security_evaluator_exit_code "$(optional_number "$security_test_exit")" \
            security_evaluator_runtime_ms "$security_test_ms" \
            security_evaluation_completed "$security_evaluation_completed" \
            security_clean "__JSON__:$security_clean_json" \
            security_results_path "$([[ -f "$attempt_dir/security_results.json" ]] && printf '__STR__:security_results.json' || printf '__JSON__:null')" \
            agent_runtime_ms "$total_agent_ms" \
            build_runtime_ms "$total_build_ms" \
            base_test_runtime_ms "$total_base_test_ms" \
            feature_test_runtime_ms "$total_feature_test_ms" \
            extra_test_runtime_ms "$extra_test_ms" \
            initial_agent_runtime_ms "$initial_agent_ms" \
            repair_agent_runtime_ms "$repair_agent_ms" \
            total_agent_runtime_ms "$total_agent_ms" \
            total_runtime_ms "$total_ms" \
            initial_success "$initial_success" \
            repair_loops "$repair_loops" \
            llm_invocations "$llm_invocations" \
            success_loop "__JSON__:$success_loop_json" \
            stop_reason "$stop_reason" \
            loop_limit_reached "$loop_limit_reached" \
            public_validation_success "$public_validation_success" \
            infrastructure_failure false \
            infrastructure_failure_stage "__JSON__:null" \
            infrastructure_failure_classification_inferred false \
            agent_log_capture_complete "$agent_log_capture_complete" \
            agent_log_capture_issue_observed "$agent_log_capture_issue_observed" \
            agent_execution_failure "$agent_execution_failed" \
            agent_execution_failure_stage "__JSON__:$agent_execution_failure_stage_json" \
            agent_failure_reason "__JSON__:$agent_failure_reason_json" \
            initial_session_completed "$initial_session_completed" \
            initial_agent_exit_code "$(optional_number "$initial_agent_exit")" \
            candidate_available_after_initial_session "$candidate_available_after_initial_session" \
            candidate_available_after_timeout "$candidate_available_after_timeout" \
            validation_completed_after_timeout "$validation_completed_after_timeout" \
            repair_eligible "$repair_eligible" \
            repair_eligibility_reason "$repair_eligibility_reason" \
            agent_execution_failure_classification_inferred false \
            timeout_seconds "$TIMEOUT_SECONDS" \
            timeout_enforced "$TIMEOUT_ENFORCED" \
            test_dir_integrity "__JSON__:$integrity_json" \
            workdir_pruned "$workdir_pruned" \
            loops "__JSON__:$loops_json" \
            overall_success "$overall_success" \
            completed_at "$(timestamp)"

        touch "$attempt_dir/COMPLETE"

        printf '  loops=%s stop=%s result=%s time=%.2fs\n' \
            "$repair_loops" "$stop_reason" "$overall_success" \
            "$("$PYTHON_BIN" -c "print($total_ms / 1000)")"
    done

    if [[ "$NO_ANALYSIS" -eq 0 ]]; then
        printf '\nAnalyzing %s...\n' "temp-$temp_slug"
        analyzer_args=(
            --experiment "$experiment_dir"
            --cluster-threshold "$RESOLVED_ARCHITECTURE_THRESHOLD"
            --strategy-threshold "$RESOLVED_STRATEGY_THRESHOLD"
            --clean-output
        )
        if [[ -n "$ANALYSIS_DIVERSITY_K_MAX" ]]; then
            analyzer_args+=(--diversity-k-max "$ANALYSIS_DIVERSITY_K_MAX")
        fi
        "$PYTHON_BIN" "$ANALYZER_PATH" "${analyzer_args[@]}" \
            2>&1 | tee "$experiment_dir/analysis.log"
        if [[ "${PIPESTATUS[0]}" -ne 0 ]]; then
            warn "analysis failed for $experiment_dir"
            overall_status=1
        fi
    fi
    printf '\n'
done

printf 'Finished: %s\n' "$OUTPUT_DIR"

exit "$overall_status"
