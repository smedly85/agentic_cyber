#!/usr/bin/env bash
# Run repeated OpenCode code-generation experiments in isolated plain
# directories, with a controller-driven generate/validate/continue loop.
#
# Each attempt gets a fresh working directory containing only the prompt, any
# --test-dir directories, and any --seed-file files. OpenCode runs with --dir
# pointed at it and a configuration that denies every other path, so nothing
# else in the repository is ever visible. No Git worktrees are involved.
#
# After each OpenCode session the controller independently runs --build-cmd,
# --base-test-cmd, and --feature-test-cmd. If any of them fails, it renders a
# continuation prompt (prompts/repair_continuation_template.md) containing the
# original task and the specific failures, and starts a NEW OpenCode session
# against the SAME working directory, so the model picks up where it left off.
# This repeats up to --max-loops times.
#
# Output is written in the layout analyze_experiment.py consumes, and analysis
# runs automatically for each temperature.
#
# Example (from scratch, with repair):
#   scripts/run_experiment.sh \
#     --model school-ollama/qwen3-coder-next:latest \
#     --temperature 0.2 --runs 25 --max-loops 3 \
#     --prompt prompts/mkdir/000_base_new_mkdir.md \
#     --source src/new_mkdir/new_mkdir.c --source-mode new \
#     --test-dir tests/mkdir-test-suite \
#     --build-cmd "mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 src/new_mkdir/new_mkdir.c -o build/new_mkdir" \
#     --feature-test-cmd "tests/mkdir-test-suite/judge_candidate.sh build/new_mkdir"
#
# Example (temperature sweep):
#   scripts/run_experiment.sh \
#     --model school-ollama/qwen3-coder-next:latest \
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
  --model MODEL              OpenCode model name, e.g.
                             school-ollama/qwen3-coder-next:latest
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

Generation and repair:
  --max-loops N              Continuation sessions after the initial
                             generation (default: 3). 0 disables repair.
  --repair-prompt FILE       Continuation template (default:
                             prompts/repair_continuation_template.md)
  --allow-no-progress        Keep looping even when a session leaves the
                             source byte-identical. Default is to stop early.
  --agent NAME               OpenCode agent (default: build)
  --timeout SECONDS          OpenCode timeout per session; 0 disables
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
  --extra-test-cmd CMD       Sanitizer/hidden command, run once at the end and
                             never used as repair feedback

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
  OPENCODE_BIN               OpenCode executable (default: opencode)
  PYTHON_BIN                 Python executable (default: python3)

Directory layout:
  <output-dir>/
    sweep.json
    temp-<slug>/
      experiment.json
      prompt.md
      baseline/<source-basename>
      attempt-001/
        metadata.json  opencode.log  build.log
        base-tests.log  feature-tests.log  extra-tests.log
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
    # Usage: run_opencode LOGFILE WORKDIR PROMPT INVOCATION KIND
    # Each call is a new OpenCode session against the same working directory.
    local logfile="$1"
    local workdir="$2"
    local prompt="$3"
    local invocation="$4"
    local kind="$5"
    local current_log start_ns end_ns status runtime_ms permission_rejected

    current_log="$attempt_dir/.opencode-current.log"
    printf '\n===== LLM INVOCATION %s: %s =====\n\n' \
        "$invocation" "$kind" >>"$logfile"
    start_ns="$(date +%s%N)"
    # `--thinking` makes OpenCode emit the model's reasoning blocks alongside
    # every tool call and result. Pipe through tee so the log grows live: a
    # large reasoning model can run for many minutes, and buffering until the
    # invocation returns would leave the log empty for all of it. `tee` writes
    # the per-invocation copy used for the permission check below, and passes
    # the same stream through to the cumulative log.
    if [[ "$TIMEOUT_ENFORCED" == true ]]; then
        OPENCODE_CONFIG_CONTENT="$ATTEMPT_OPENCODE_CONFIG_CONTENT" \
            "$TIMEOUT_BIN" --signal=TERM --kill-after=30 \
            "$TIMEOUT_SECONDS" \
            "$OPENCODE_BIN" run \
                --dir "$workdir" \
                --model "$MODEL" \
                --agent "$AGENT" \
                --thinking \
                "$prompt" </dev/null
    else
        OPENCODE_CONFIG_CONTENT="$ATTEMPT_OPENCODE_CONFIG_CONTENT" \
            "$OPENCODE_BIN" run \
                --dir "$workdir" \
                --model "$MODEL" \
                --agent "$AGENT" \
                --thinking \
                "$prompt" </dev/null
    fi 2>&1 | tee "$current_log" >>"$logfile"
    # The exit status of OpenCode itself, not of tee.
    status="${PIPESTATUS[0]}"
    end_ns="$(date +%s%N)"
    runtime_ms=$(( (end_ns - start_ns) / 1000000 ))

    permission_rejected=false
    if grep -Eiq \
            'permission requested:[[:space:]]*external_directory|auto-rejecting|user rejected permission' \
            "$current_log"; then
        permission_rejected=true
    fi
    rm -f "$current_log"
    printf '%s %s %s\n' "$status" "$runtime_ms" "$permission_rejected"
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
    source_sha256,
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
    "source_sha256": source_sha256,
}, separators=(",", ":")))
PY
}

MODEL=""
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
RUNS=1
MAX_LOOPS=3
REPAIR_TEMPLATE=""
ALLOW_NO_PROGRESS=0
AGENT="build"
OUTPUT_DIR=""
BUILD_CMD=""
BASE_TEST_CMD=""
FEATURE_TEST_CMD=""
EXTRA_TEST_CMD=""
TIMEOUT_SECONDS=1800
FORCE=0
KEEP_WORKDIR=0
PRUNE_ONLY=""
NO_ANALYSIS=0
REMOTE_BASE_URL=""
REMOTE_API_KEY_ENV="OPENCODE_REMOTE_API_KEY"
ANALYSIS_THRESHOLD=""
ANALYSIS_ARCHITECTURE_THRESHOLD=""
ANALYSIS_STRATEGY_THRESHOLD=""
ANALYSIS_DIVERSITY_K_MAX=""
TEST_DIRS=()
SEED_FILES=()
KEEP_GLOBS=()

OPENCODE_BIN="${OPENCODE_BIN:-opencode}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

while [[ $# -gt 0 ]]; do
    # Every option below that consumes a value must be given one. Without this
    # guard a trailing `--flag` leaves `shift 2` unable to shift, so the loop
    # re-reads the same argument forever.
    case "$1" in
        --model|--prompt|--source|--source-mode|--temperature|--temp-min| \
        --temp-max|--temp-points|--temp-list|--runs|--max-loops| \
        --repair-prompt|--agent| \
        --test-dir|--seed-file|--keep-glob|--build-cmd|--base-test-cmd| \
        --feature-test-cmd|--test-cmd|--extra-test-cmd|--timeout|--output-dir| \
        --prune-only|--remote-base-url|--remote-api-key-env| \
        --analysis-threshold|--analysis-architecture-threshold| \
        --analysis-strategy-threshold|--analysis-diversity-k-max)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            ;;
    esac

    case "$1" in
        --model) MODEL="${2:-}"; shift 2 ;;
        --prompt) PROMPT="${2:-}"; shift 2 ;;
        --source) SOURCE_PATH="${2:-}"; shift 2 ;;
        --source-mode) SOURCE_MODE="${2:-}"; shift 2 ;;
        --temperature) TEMPERATURE="${2:-}"; shift 2 ;;
        --temp-min) TEMP_MIN="${2:-}"; shift 2 ;;
        --temp-max) TEMP_MAX="${2:-}"; shift 2 ;;
        --temp-points) TEMP_POINTS="${2:-}"; shift 2 ;;
        --temp-list) TEMP_LIST="${2:-}"; TEMP_LIST_SET=1; shift 2 ;;
        --runs) RUNS="${2:-}"; shift 2 ;;
        --max-loops) MAX_LOOPS="${2:-}"; shift 2 ;;
        --repair-prompt) REPAIR_TEMPLATE="${2:-}"; shift 2 ;;
        --allow-no-progress) ALLOW_NO_PROGRESS=1; shift ;;
        --agent) AGENT="${2:-}"; shift 2 ;;
        --test-dir) TEST_DIRS+=("${2:-}"); shift 2 ;;
        --seed-file) SEED_FILES+=("${2:-}"); shift 2 ;;
        --keep-glob) KEEP_GLOBS+=("${2:-}"); shift 2 ;;
        --build-cmd) BUILD_CMD="${2:-}"; shift 2 ;;
        --base-test-cmd) BASE_TEST_CMD="${2:-}"; shift 2 ;;
        --feature-test-cmd|--test-cmd) FEATURE_TEST_CMD="${2:-}"; shift 2 ;;
        --extra-test-cmd) EXTRA_TEST_CMD="${2:-}"; shift 2 ;;
        --timeout) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
        --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
        --keep-workdir) KEEP_WORKDIR=1; shift ;;
        --prune-only) PRUNE_ONLY="${2:-}"; shift 2 ;;
        --no-analysis) NO_ANALYSIS=1; shift ;;
        --force) FORCE=1; shift ;;
        --remote-base-url) REMOTE_BASE_URL="${2:-}"; shift 2 ;;
        --remote-api-key-env) REMOTE_API_KEY_ENV="${2:-}"; shift 2 ;;
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

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN was not found"
command -v git >/dev/null 2>&1 || die "git is required (to resolve repo-relative paths)"

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" ||
    die "run this script inside a Git repository (only used to resolve paths)"
REPO="$(cd "$REPO" && pwd -P)"

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

STATS_TOOL="$REPO/scripts/opencode_stats.py"
[[ -f "$STATS_TOOL" ]] || die "stats helper not found: $STATS_TOOL"

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
[[ "$SOURCE_MODE" == "existing" || "$SOURCE_MODE" == "new" ]] ||
    die "--source-mode must be existing or new"

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
    temp_list_parsed="$("$PYTHON_BIN" - "$TEMP_LIST" <<'PY' 2>&1
import sys

values = [part.strip() for part in sys.argv[1].split(",") if part.strip()]
if not values:
    print("--temp-list must name at least one temperature")
    raise SystemExit(1)
seen: list[float] = []
for value in values:
    try:
        number = float(value)
    except ValueError:
        print(f"--temp-list entry is not numeric: {value}")
        raise SystemExit(1)
    if number in seen:
        print(f"--temp-list repeats {value}; each point runs once")
        raise SystemExit(1)
    seen.append(number)
print(",".join(repr(number) for number in seen))
PY
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
fi

if [[ -n "$REMOTE_BASE_URL" ]]; then
    [[ "$MODEL" == */* ]] ||
        die "--model must be PROVIDER/MODEL when --remote-base-url is set (got: $MODEL)"
    [[ -n "${!REMOTE_API_KEY_ENV:-}" ]] ||
        die "$REMOTE_API_KEY_ENV is not set (export it, or pass --remote-api-key-env)"
fi

PROMPT_ABS="$(resolve_repo_path "$PROMPT")"
[[ -f "$PROMPT_ABS" ]] || die "prompt not found: $PROMPT_ABS"

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
command -v "$OPENCODE_BIN" >/dev/null 2>&1 || die "$OPENCODE_BIN was not found"

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
        "$PYTHON_BIN" -c '
import sys
n, lo, hi = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
if n == 1:
    print(lo)
else:
    step = (hi - lo) / (n - 1)
    for i in range(n):
        print(lo + step * i)
' "$TEMP_POINTS" "$TEMP_MIN" "$TEMP_MAX"
    )"
fi

TEMPERATURES_ARR=()
while IFS= read -r line; do
    [[ -n "$line" ]] && TEMPERATURES_ARR+=("$line")
done <<< "$TEMPERATURES"

write_metadata "$OUTPUT_DIR/sweep.json" \
    schema_version 1 \
    repository "$REPO" \
    repository_commit "$REPO_COMMIT" \
    model "$MODEL" \
    agent "$AGENT" \
    prompt "$PROMPT_ABS" \
    source_workdir_path "$SOURCE_PATH" \
    source_path "$SOURCE_FLAT" \
    source_mode "$SOURCE_MODE" \
    temp_min "$TEMP_MIN" \
    temp_max "$TEMP_MAX" \
    temp_points "$TEMP_POINTS" \
    temp_list "$TEMP_LIST" \
    runs_per_temperature "$RUNS" \
    max_loops "$MAX_LOOPS" \
    test_dirs "$TEST_DIRS_JOINED" \
    seed_files "$SEED_FILES_JOINED" \
    build_command "__STR__:$BUILD_CMD" \
    base_test_command "__STR__:$BASE_TEST_CMD" \
    feature_test_command "__STR__:$FEATURE_TEST_CMD" \
    extra_test_command "__STR__:$EXTRA_TEST_CMD" \
    timeout_seconds "$TIMEOUT_SECONDS" \
    timeout_enforced "$TIMEOUT_ENFORCED" \
    created_at "$(timestamp)"

printf 'Repository:  %s\n' "$REPO"
printf 'Model:       %s\n' "$MODEL"
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
printf 'Output:      %s\n\n' "$OUTPUT_DIR"

# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

overall_status=0

for temperature in "${TEMPERATURES_ARR[@]}"; do
    temp_slug="$(slugify "$temperature" | sed 's/\./p/g')"
    experiment_dir="$OUTPUT_DIR/temp-$temp_slug"
    mkdir -p "$experiment_dir"

    if [[ -f "$experiment_dir/experiment.json" ]]; then
        mismatches="$(
            "$PYTHON_BIN" - "$experiment_dir/experiment.json" \
                "$MODEL" "$temperature" "$AGENT" "$PROMPT_ABS" \
                "$SOURCE_FLAT" "$SOURCE_PATH" "$SOURCE_MODE" "$MAX_LOOPS" \
                "$BUILD_CMD" "$BASE_TEST_CMD" "$FEATURE_TEST_CMD" \
                "$EXTRA_TEST_CMD" \
                "$RESOLVED_ARCHITECTURE_THRESHOLD" \
                "$RESOLVED_STRATEGY_THRESHOLD" \
                "${ANALYSIS_DIVERSITY_K_MAX:-__NONE__}" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
(
    model,
    temperature,
    agent,
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
) = sys.argv[2:]
expected = {
    "model": model,
    "temperature": float(temperature),
    "agent": agent,
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

    cp "$PROMPT_ABS" "$experiment_dir/prompt.md"

    write_metadata "$experiment_dir/experiment.json" \
        schema_version 2 \
        repository "$REPO" \
        repository_commit "$REPO_COMMIT" \
        model "$MODEL" \
        temperature "$temperature" \
        agent "$AGENT" \
        prompt "$PROMPT_ABS" \
        prompt_copy "$experiment_dir/prompt.md" \
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

        # OpenCode keys its sessions by working directory, and this path is
        # reused whenever an attempt is re-run with --force or restarted after
        # an interruption. Without a floor, the stats for this attempt would
        # also collect the abandoned run's sessions.
        attempt_started_ms="$(( $(date +%s) * 1000 ))"

        rm -rf "$attempt_dir"
        mkdir -p "$workdir"

        # Seed the working directory. This is everything the agent can see.
        cp "$PROMPT_ABS" "$workdir/$(basename "$PROMPT_ABS")"
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

        # OpenCode resolves a session's project root by walking up for a .git
        # directory, and only consults its external_directory rules for paths
        # outside that root. Without a .git of its own the workdir inherits
        # this repository as its root, every repository path counts as
        # internal, and the agent can read and write anywhere in the checkout
        # -- observed: a session wrote src/new_mkdir/new_mkdir.c into the real
        # repository. An empty repository here moves the boundary onto the
        # workdir. It is scratch metadata only, never committed to, and it
        # goes away with the workdir during the prune.
        git init -q "$workdir" ||
            die "failed to initialize sandbox marker repository in $workdir"
        sandbox_root="$(git -C "$workdir" rev-parse --show-toplevel 2>/dev/null || printf '')"
        # Fail closed: without this boundary the agent is loose in the repo,
        # which silently corrupts both the checkout and every later attempt.
        [[ "$sandbox_root" == "$(cd "$workdir" && pwd -P)" ]] ||
            die "sandbox boundary not established for $workdir (root=$sandbox_root)"

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
    # Snapshots exist so an interactive user can undo a change. Nothing here
    # reverts, and with a per-attempt project root OpenCode would otherwise
    # keep one snapshot repository per attempt under its shared data
    # directory, copying the whole seeded tree on every step.
    "snapshot": False,
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
        )" || die "failed to build per-attempt OpenCode configuration"

        prompt_text="$(cat "$PROMPT_ABS")"
        : >"$attempt_dir/opencode.log"
        : >"$attempt_dir/build.log"
        : >"$attempt_dir/base-tests.log"
        : >"$attempt_dir/feature-tests.log"

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
        agent_execution_failed=false
        agent_execution_failure_stage_json=null
        stop_reason=""
        previous_source_sha=""
        loop_records=()

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

            read -r opencode_exit opencode_ms invocation_permission_rejected < <(
                run_opencode \
                    "$attempt_dir/opencode.log" \
                    "$workdir" \
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
                "$feature_test_ms" "$validation_success" "$source_sha")")

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
            current_prompt="$(cat "$repair_prompt_file")"
        done
        # ---- end loop -----------------------------------------------------

        # Every path above breaks with a reason; this only guards a future edit
        # that lets the bound expire instead.
        [[ -n "$stop_reason" ]] || stop_reason="loop_limit"

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

        # Hidden/sanitizer evaluation: after the loop, never fed back as repair.
        read -r extra_test_exit extra_test_ms < <(
            cd "$workdir" &&
            run_final_command "$attempt_dir/extra-tests.log" "$EXTRA_TEST_CMD"
        )

        total_ms=$((total_opencode_ms + total_build_ms + total_base_test_ms + total_feature_test_ms + extra_test_ms))

        # A failing candidate is an experimental result, not a runner error, so
        # it is recorded in metadata without affecting the exit status. Only
        # capture or analysis failures make the run itself unsuccessful.
        overall_success=true
        if [[ "$agent_execution_failed" == true ||
              "$public_validation_success" == false ||
              "$extra_test_exit" -ne 0 ]]; then
            overall_success=false
        fi

        # Pull token counts, per-step latency, tool usage and reasoning volume
        # out of OpenCode's own database. `opencode run` prints none of it, and
        # the sessions are keyed by working directory, so this has to happen
        # before the prune renames nothing but while the path is still known.
        "$PYTHON_BIN" "$STATS_TOOL" \
            --workdir "$workdir" \
            --output-dir "$attempt_dir" \
            --model "$MODEL" \
            --temperature "$temperature" \
            --attempt "$attempt_id" \
            --since-ms "$attempt_started_ms" ||
            warn "opencode stats extraction failed for $attempt_id"

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
            model "$MODEL" \
            temperature "$temperature" \
            agent "$AGENT" \
            source_path "$SOURCE_FLAT" \
            source_workdir_path "$SOURCE_PATH" \
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
            stop_reason "$stop_reason" \
            loop_limit_reached "$loop_limit_reached" \
            public_validation_success "$public_validation_success" \
            infrastructure_failure false \
            infrastructure_failure_stage "__JSON__:null" \
            infrastructure_failure_classification_inferred false \
            agent_execution_failure "$agent_execution_failed" \
            agent_execution_failure_stage "__JSON__:$agent_execution_failure_stage_json" \
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
