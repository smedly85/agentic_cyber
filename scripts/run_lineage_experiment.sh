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
# successful candidate of the SAME lineage. Each stage is a fresh Aider
# process; the only implementation state carried across a stage boundary is that
# one seed file.
#
# This script owns lineage bookkeeping only. All single-stage mechanism --
# isolated work directories, explicit Aider file scope, source modes, seed files,
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
#     --model ollama_chat/qwen3.8:27b \
#     --editor-model ollama_chat/qwen3-coder-next:latest \
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
  --model MODEL              Aider architect/reasoning model, e.g.
                             ollama_chat/qwen3.8:27b
  --editor-model MODEL       Aider editor model (default:
                             ollama_chat/qwen3-coder-next:latest)

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

Sampling (optional; each is forwarded unchanged to every stage and every repair
session, and unset means the flag is absent from the request so the server's own
default applies):
  --architect-think LEVEL   Native architect thinking level: low, medium, or
                             high. Forwarded as `think`, not reasoning_effort.
  --top-p P                  Nucleus sampling mass, 0 <= P <= 1
  --sampling-seed N          Token-selection seed, N >= 0. Named this way on
                             purpose: --seed-file is the checkpoint
                             source-inheritance file and the two senses of
                             "seed" must not be confused.
  --max-tokens N             Cap on generated tokens per session, N >= 1
  --model-provenance-json J  Metadata-only JSON object for model-definition
                             controls, e.g. base_model/top_k/top_k_control.
                             It is fingerprinted and never sent in requests.

                             There is no --top-k in this migration. Native
                             ollama_chat can transport it, but adding a new
                             experimental control requires a separate verified
                             change rather than being folded into this one.

                             Every sampling value is part of the lineage
                             configuration fingerprint, so changing one refuses
                             to resume an existing --output-dir rather than
                             mixing conditions.

Passed through to scripts/run_experiment.sh:
  --timeout SECONDS          Per-invocation timeout; 0 disables (default: 1800)
  --allow-no-progress        Keep repairing a stage even when a session leaves
                             the source byte-identical
  --repair-prompt FILE       Continuation template
  --keep-workdir             Retain each stage's working directory
  --remote-base-url URL      Native Ollama root for ollama_chat/* models, or
                             an OpenAI-compatible URL for openai/* models
  --remote-api-key-env NAME  Optional env var holding that endpoint's key

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
  AIDER_BIN                  Aider executable (default: aider)
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

# How a path is written into a record. Repository-relative only when the file is
# genuinely inside the repository, so that an --output-dir outside it records an
# absolute path rather than a repo-relative one that resolves nowhere. Every
# filesystem operation uses the absolute form regardless, so nothing depends on
# the working directory the controller was started from.
record_path() {
    local path="$1"
    case "$path" in
        "$REPO"/*) printf '%s' "${path#"$REPO"/}" ;;
        *) printf '%s' "$path" ;;
    esac
}

# Build the captured candidate in a throwaway tree and run the controller-only
# checkpoint boundary gate against it. This happens AFTER public validation has
# already succeeded and BEFORE the candidate is promoted, and its outcome is
# never fed back to the agent: telling the model "your -u handling was rejected"
# at checkpoint 001 would disclose the very flag the checkpoint withholds.
#
# The build is repeated here rather than reused because run_experiment.sh
# discards its working directory; the candidate source is the only durable
# artifact, and rebuilding it is cheap next to an Aider invocation.
#
# 0 = candidate stayed inside its checkpoint, 1 = it implemented a later flag,
# 2 = the gate could not run.
boundary_gate() {
    local candidate="$1" checkpoint="$2" report="$3"
    local work status
    work="$(mktemp -d)" || return 2
    mkdir -p "$work/$(dirname "$SOURCE_PATH")" || { rm -rf "$work"; return 2; }
    cp "$candidate" "$work/$SOURCE_PATH" || { rm -rf "$work"; return 2; }
    if ! ( cd "$work" && eval "$BUILD_CMD" ) >"${report%.json}-build.log" 2>&1; then
        rm -rf "$work"
        return 2
    fi
    "$PYTHON_BIN" "$GATE_TOOL" \
        --repo "$REPO" \
        --utility "$UTILITY" \
        --checkpoint "$checkpoint" \
        --executable "$work/$EXECUTABLE_PATH" \
        --report "$report" >/dev/null 2>&1
    status=$?
    rm -rf "$work"
    return "$status"
}

UTILITY=""
MODEL=""
EDITOR_MODEL="ollama_chat/qwen3-coder-next:latest"
TEMPERATURE="0"
# Optional sampling knobs. Empty means "not requested": the value is recorded as
# a JSON null and no flag is forwarded, so the stage runs exactly as it did
# before these options existed. See the help text for why there is no --top-k.
TOP_P=""
SAMPLING_SEED=""
MAX_TOKENS=""
ARCHITECT_THINK=""
MODEL_PROVENANCE_JSON=""
LINEAGES=1
LINEAGE_START=1
MAX_LOOPS=3
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
AIDER_BIN="${AIDER_BIN:-aider}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --utility|--model|--editor-model|--temperature|--lineages|--lineage-start|--max-loops| \
        --top-p|--sampling-seed|--max-tokens|--architect-think|--model-provenance-json| \
        --timeout|--repair-prompt|--remote-base-url| \
        --remote-api-key-env|--output-dir)
            [[ $# -ge 2 ]] || die "$1 requires a value"
            ;;
    esac

    case "$1" in
        --utility) UTILITY="${2:-}"; shift 2 ;;
        --model) MODEL="${2:-}"; shift 2 ;;
        --editor-model) EDITOR_MODEL="${2:-}"; shift 2 ;;
        --temperature) TEMPERATURE="${2:-}"; shift 2 ;;
        --top-p) TOP_P="${2:-}"; shift 2 ;;
        --sampling-seed) SAMPLING_SEED="${2:-}"; shift 2 ;;
        --max-tokens) MAX_TOKENS="${2:-}"; shift 2 ;;
        --architect-think) ARCHITECT_THINK="${2:-}"; shift 2 ;;
        --model-provenance-json) MODEL_PROVENANCE_JSON="${2:-}"; shift 2 ;;
        --top-k)
            die "--top-k is not supported by this migration; validate and add it as a separate experimental change" ;;
        --seed)
            # --seed-file is the checkpoint source-inheritance file. The two
            # senses of "seed" must never collide in this harness.
            die "--seed is ambiguous here: use --sampling-seed for the token-selection seed, or --seed-file for the inherited source file" ;;
        --lineages) LINEAGES="${2:-}"; shift 2 ;;
        --lineage-start) LINEAGE_START="${2:-}"; shift 2 ;;
        --max-loops) MAX_LOOPS="${2:-}"; shift 2 ;;
        --agent)
            die "--agent was removed with the OpenCode backend; Aider always runs in architect mode" ;;
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
TEMPERATURE_TOOL="$REPO/scripts/temperature_value.py"
[[ -f "$TEMPERATURE_TOOL" ]] || die "temperature helper not found: $TEMPERATURE_TOOL"
# A syntax error in the stage runner must never reach lineage initialization.
# It happened: a here-document inside a $( ) command substitution contained an
# apostrophe, which Bash 4+ parses correctly and Apple's Bash 3.2 does not. On
# Darwin every stage died with "unexpected end of file" before the backend was
# invoked, and because the failure looked like a stage that simply produced
# nothing, the lineage recorded checkpoint 000 as stage_run_incomplete -- a
# model result, for what was a parse error in the controller.
#
# Parsed with the same `bash` that will run the stage, so the check reflects the
# interpreter actually used rather than whichever one is newest on the host.
# This catches the syntax class only; constructs like `declare -n` and
# `mapfile` parse everywhere and fail at run time, which is what the static
# guard in tests/test_lineage_tools.py covers.
bash -n "$STAGE_RUNNER" ||
    die "$STAGE_RUNNER does not parse under $(bash --version | head -1); no lineage was started. On Darwin this is usually an apostrophe or an unbalanced parenthesis inside a here-document that sits within a \$( ) command substitution"
BUNDLE_TOOL="$REPO/scripts/stage_test_bundle.py"
[[ -f "$BUNDLE_TOOL" ]] || die "stage test bundle builder not found: $BUNDLE_TOOL"
STATE_TOOL="$REPO/scripts/lineage_state.py"
[[ -f "$STATE_TOOL" ]] || die "lineage state helper not found: $STATE_TOOL"
GATE_TOOL="$REPO/scripts/checkpoint_boundary_gate.py"
[[ -f "$GATE_TOOL" ]] || die "checkpoint boundary gate not found: $GATE_TOOL"

if [[ "$LIST_UTILITIES" -eq 1 ]]; then
    "$PYTHON_BIN" "$PLAN_TOOL" --repo "$REPO" --emit utilities
    exit 0
fi

[[ -n "$UTILITY" ]] || die "--utility is required"
[[ -n "$MODEL" ]] || die "--model is required"
[[ "$MODEL" != "$EDITOR_MODEL" ]] ||
    die "--model and --editor-model must differ so their sampling settings remain role-specific"
[[ "$LINEAGES" =~ ^[1-9][0-9]*$ ]] || die "--lineages must be a positive integer"
[[ "$LINEAGE_START" =~ ^[1-9][0-9]*$ ]] ||
    die "--lineage-start must be a positive integer"
[[ "$MAX_LOOPS" =~ ^[0-9]+$ ]] || die "--max-loops must be a non-negative integer"
[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--timeout must be a non-negative integer"
TEMPERATURE="$(
    "$PYTHON_BIN" "$TEMPERATURE_TOOL" canonical "$TEMPERATURE"
)" || die "--temperature must be numeric and finite"

# Sampling knobs, validated with the same rules scripts/run_experiment.sh uses.
# This happens BEFORE the plan is resolved and therefore long before any lineage
# directory or lineage.json exists, so a typo can never leave a started lineage
# behind that analysis would have to count.
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
if [[ -n "$ARCHITECT_THINK" &&
      "$ARCHITECT_THINK" != low &&
      "$ARCHITECT_THINK" != medium &&
      "$ARCHITECT_THINK" != high ]]; then
    die "--architect-think must be low, medium, or high"
fi
if [[ -n "$REMOTE_BASE_URL" ]]; then
    if [[ "$MODEL" == ollama_chat/* && "$EDITOR_MODEL" == ollama_chat/* ]]; then
        [[ "$REMOTE_BASE_URL" != */v1 && "$REMOTE_BASE_URL" != */v1/ ]] ||
            die "ollama_chat/* needs the native Ollama root, not a /v1 URL"
    elif [[ "$MODEL" == openai/* && "$EDITOR_MODEL" == openai/* ]]; then
        : # Existing OpenAI-compatible gateways remain supported.
    else
        die "with --remote-base-url, both models must use either ollama_chat/* (native Ollama) or openai/* (OpenAI-compatible gateway)"
    fi
fi
if [[ -n "$REMOTE_API_KEY_ENV" ]]; then
    [[ -n "${!REMOTE_API_KEY_ENV:-}" ]] ||
        die "$REMOTE_API_KEY_ENV is not set"
fi

if command -v "$AIDER_BIN" >/dev/null 2>&1; then
    AIDER_AVAILABLE=1
    AIDER_VERSION="$({ "$AIDER_BIN" --version 2>/dev/null || true; } | head -1)"
    [[ -n "$AIDER_VERSION" ]] || AIDER_VERSION="unknown"
else
    AIDER_AVAILABLE=0
    # Dry-run/plan and platform-incompatible preflight paths invoke no backend.
    # A compatible real run is rejected below before any lineage starts.
    AIDER_VERSION="not-installed"
fi

# ---------------------------------------------------------------------------
# Resolve the stage plan
# ---------------------------------------------------------------------------

PLAN_JSON="$(
    "$PYTHON_BIN" "$PLAN_TOOL" \
        --repo "$REPO" \
        --utility "$UTILITY" \
        --model "$MODEL" \
        --editor-model "$EDITOR_MODEL" \
        --aider-version "$AIDER_VERSION" \
        --temperature "$TEMPERATURE" \
        --top-p "$TOP_P" \
        --sampling-seed "$SAMPLING_SEED" \
        --max-tokens "$MAX_TOKENS" \
        --architect-think "$ARCHITECT_THINK" \
        --model-provenance-json "$MODEL_PROVENANCE_JSON" \
        --max-loops "$MAX_LOOPS" \
        --timeout-seconds "$TIMEOUT_SECONDS" \
        --remote-base-url "$REMOTE_BASE_URL" \
        --remote-api-key-env "$REMOTE_API_KEY_ENV" \
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
EXECUTABLE_PATH="$(plan_field executable_path)"
TEST_DIR="$(plan_field test_dir)"
BASE_TEST_CMD="$(plan_field base_test_command)"
EXTRA_TEST_CMD="$(plan_field extra_test_command)"
CONFIG_FINGERPRINT="$(plan_field config_fingerprint)"
REQUIRED_PLATFORM="$(plan_field required_platform)"
HOST_PLATFORM="$(plan_field host_platform)"

STAGE_TABLE="$(
    "$PYTHON_BIN" "$PLAN_TOOL" \
        --repo "$REPO" \
        --utility "$UTILITY" \
        --model "$MODEL" \
        --editor-model "$EDITOR_MODEL" \
        --aider-version "$AIDER_VERSION" \
        --temperature "$TEMPERATURE" \
        --top-p "$TOP_P" \
        --sampling-seed "$SAMPLING_SEED" \
        --max-tokens "$MAX_TOKENS" \
        --architect-think "$ARCHITECT_THINK" \
        --model-provenance-json "$MODEL_PROVENANCE_JSON" \
        --max-loops "$MAX_LOOPS" \
        --timeout-seconds "$TIMEOUT_SECONDS" \
        --remote-base-url "$REMOTE_BASE_URL" \
        --remote-api-key-env "$REMOTE_API_KEY_ENV" \
        --emit stages
)" || exit 2

STAGE_IDS=()
STAGE_NAMES=()
STAGE_PROMPTS=()
STAGE_MODES=()
STAGE_FEATURE_CMDS=()
STAGE_FLAGS=()
STAGE_BUNDLE_FINGERPRINTS=()

# How many elements a named stage array holds.
#
# Bash namerefs (`declare -n` / `local -n`) arrived in Bash 4.3 and do not exist
# in Bash 3.2.57, which is the newest Bash Apple ships and therefore the shell
# that runs this controller on Darwin -- a supported and required experiment
# platform. `declare -n array_ref="$array_name"` there is
# "declare: -n: invalid option" followed by "array_ref: unbound variable", so
# the guard below aborted every macOS run at exactly the point it exists to
# protect. Requiring a Homebrew Bash instead would make the experiment
# unrunnable on a stock supported host.
#
# The lookup is an explicit case over the arrays this script itself declares:
# only those fixed names resolve, an unrecognized name is an error rather than a
# lookup, and no value -- least of all one that came out of the plan -- is ever
# expanded as code. There is no eval here.
#
# The body is a subshell so `set +u` cannot leak into the caller: in Bash 3.2,
# `${#array[@]}` on an EMPTY array is an "unbound variable" error under `set -u`,
# and a zero count is precisely what this validation has to be able to observe.
# Being a subshell, `exit` here ends only the lookup and never the controller --
# it is used in place of `return`, whose behavior inside a subshell function body
# is not something to rely on across Bash 3.2 and 5.x.
stage_array_length() (
    set +u
    case "$1" in
        STAGE_IDS)                 printf '%s' "${#STAGE_IDS[@]}" ;;
        STAGE_NAMES)               printf '%s' "${#STAGE_NAMES[@]}" ;;
        STAGE_PROMPTS)             printf '%s' "${#STAGE_PROMPTS[@]}" ;;
        STAGE_MODES)               printf '%s' "${#STAGE_MODES[@]}" ;;
        STAGE_FEATURE_CMDS)        printf '%s' "${#STAGE_FEATURE_CMDS[@]}" ;;
        STAGE_FLAGS)               printf '%s' "${#STAGE_FLAGS[@]}" ;;
        STAGE_BUNDLE_FINGERPRINTS) printf '%s' "${#STAGE_BUNDLE_FINGERPRINTS[@]}" ;;
        *) exit 1 ;;
    esac
)

# Fields are separated by ASCII US (0x1f), not tab. Tab is IFS *whitespace*, so
# `IFS=$'\t' read` collapses runs of tabs and drops empty fields: checkpoint 000
# has an empty cumulative flag list, so its record ended `...<TAB><TAB><hash>`,
# the pair collapsed, the fingerprint landed in stage_flags, and
# stage_bundle_fingerprint came back empty -- which then failed the
# planned-vs-built comparison on every single run at stage 000. 0x1f is not IFS
# whitespace, so an empty field survives and nothing is whitespace-trimmed
# (which also keeps paths and commands containing spaces intact).
while IFS=$'\x1f' read -r stage_id stage_name stage_prompt stage_mode stage_cmd \
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

STAGE_COUNT="$(stage_array_length STAGE_IDS)" ||
    die "internal error: STAGE_IDS is not a known stage array"
[[ "$STAGE_COUNT" -gt 0 ]] || die "manifest for $UTILITY resolved to zero checkpoints"

# A plan-loading defect must be caught HERE -- before any lineage directory or
# lineage.json exists, so a parsing bug can never make a lineage count as
# started. The original defect was silent: an empty planned fingerprint simply
# lost the comparison later, after the run had already begun.
for array_name in STAGE_NAMES STAGE_PROMPTS STAGE_MODES STAGE_FEATURE_CMDS \
                  STAGE_FLAGS STAGE_BUNDLE_FINGERPRINTS; do
    array_length="$(stage_array_length "$array_name")" ||
        die "internal error: $array_name is not a known stage array"
    [[ "$array_length" -eq "$STAGE_COUNT" ]] || die \
        "stage plan is malformed: $array_name has $array_length entries but $STAGE_COUNT checkpoints were declared (the plan record format and this reader disagree)"
done

for (( check_index = 0; check_index < STAGE_COUNT; check_index++ )); do
    checkpoint="${STAGE_IDS[check_index]}"
    fingerprint="${STAGE_BUNDLE_FINGERPRINTS[check_index]}"
    [[ -n "$fingerprint" ]] || die \
        "stage plan is malformed: checkpoint $checkpoint has an empty test-bundle fingerprint; the plan record was not parsed correctly"
    [[ "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || die \
        "stage plan is malformed: checkpoint $checkpoint has a test-bundle fingerprint that is not a SHA-256 hex digest: '$fingerprint'"
done

if [[ "$AIDER_AVAILABLE" -eq 0 && "$DRY_RUN" -eq 0 && "$PRINT_PLAN" -eq 0 &&
      ! ( -n "$REQUIRED_PLATFORM" && "$REQUIRED_PLATFORM" != "None" &&
          "$REQUIRED_PLATFORM" != "$HOST_PLATFORM" ) ]]; then
    die "$AIDER_BIN was not found"
fi

MODEL_SLUG="$(slugify "$MODEL")"
TEMP_SLUG="$("$PYTHON_BIN" "$TEMPERATURE_TOOL" slug "$TEMPERATURE")" ||
    die "cannot create the directory slug for temperature $TEMPERATURE"

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$REPO/runs/lineages/$UTILITY/$MODEL_SLUG/temp-$TEMP_SLUG"
elif [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="$REPO/$OUTPUT_DIR"
fi

if [[ "$PRINT_PLAN" -eq 1 ]]; then
    # The plan JSON already carries architect_think, top_p, sampling_seed,
    # max_tokens and the
    # automation-notice hash, all of which are inside config_fingerprint; these
    # lines restate the sampling settings in the same human-readable form the
    # run banner uses.
    printf '%s\n' "$PLAN_JSON"
    printf '\nOutput dir: %s\n' "$OUTPUT_DIR"
    printf 'Lineages:   %s..%s\n' \
        "$LINEAGE_START" "$((LINEAGE_START + LINEAGES - 1))"
    printf 'Sampling:   temperature=%s architect-think=%s top-p=%s sampling-seed=%s max-tokens=%s\n' \
        "$TEMPERATURE" "${ARCHITECT_THINK:-null}" \
        "${TOP_P:-null}" "${SAMPLING_SEED:-null}" \
        "${MAX_TOKENS:-null}"
    exit 0
fi

# A dry run must not touch the filesystem, so the output directory is only
# created when something is actually going to be written into it. OUTPUT_DIR is
# already absolute either way; the cd/pwd pass only resolves symlinks.
if [[ "$DRY_RUN" -eq 0 ]]; then
    mkdir -p "$OUTPUT_DIR"
    OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"
fi
RUN_METADATA_PATH="$OUTPUT_DIR/lineages.json"

REPO_COMMIT="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || printf 'unknown')"

# ---------------------------------------------------------------------------
# Platform preflight -- run-level environment eligibility
# ---------------------------------------------------------------------------
#
# This runs BEFORE any lineage is initialized, because eligibility to run at all
# is a property of the RUN, not of any lineage. Letting the walk begin and
# stopping each lineage at checkpoint 000 would create a lineage directory and a
# start record for every one of them, so all N would count in lineages_started
# and successful_finals / lineages_started would read 0/N -- reporting a model
# reliability of zero for what is purely an environment mismatch. Classifying
# the stop reason distinctly does not fix that: the lineages must never start.
#
# So: no lineage-* directory, no lineage.json, no checkpoint, no agent
# invocation, and lineages_started stays 0. The outcome is recorded at the top
# level only, as a run status.
if [[ -n "$REQUIRED_PLATFORM" && "$REQUIRED_PLATFORM" != "None" &&
      "$REQUIRED_PLATFORM" != "$HOST_PLATFORM" ]]; then
    if [[ "$DRY_RUN" -eq 1 ]]; then
        # A dry run starts no lineage, writes nothing and invokes no agent,
        # so the harm this preflight prevents cannot occur. Resolving the
        # plan stays useful on any host, so warn loudly and continue rather
        # than refusing to describe the experiment.
        warn "platform_incompatible: $UTILITY requires $REQUIRED_PLATFORM but this host is $HOST_PLATFORM; a real run would be refused (exit 4)"
    else
        printf 'error: platform_incompatible\n' >&2
        printf '  %s requires %s; this host is %s.\n' \
            "$UTILITY" "$REQUIRED_PLATFORM" "$HOST_PLATFORM" >&2
        printf '  Its frozen expected results were produced and validated on %s and\n' \
            "$REQUIRED_PLATFORM" >&2
        printf '  do not describe %s. No lineage is started: this is a run-level\n' \
            "$HOST_PLATFORM" >&2
        printf '  environment incompatibility, not a model result.\n' >&2

        if [[ "$DRY_RUN" -eq 0 ]]; then
            # Top-level metadata only, and deliberately NO planned lineage ids:
            # recording them would let analysis later resurrect them as
            # missing_directory or planned_not_started entries, which is exactly the
            # denominator pollution this preflight exists to prevent.
            "$PYTHON_BIN" - "$RUN_METADATA_PATH" "$PLAN_JSON" \
                "$REQUIRED_PLATFORM" "$HOST_PLATFORM" "$CONFIG_FINGERPRINT" \
                "$(timestamp)" <<'PYPRE'
import json
import sys
from pathlib import Path

path, plan_json, required, host, fingerprint, created = sys.argv[1:]
plan = json.loads(plan_json)
target = Path(path)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    json.dumps(
        {
            "schema_version": 1,
            "experiment_unit": "lineage",
            "utility": plan["utility"],
            "agent_backend": plan["agent_backend"],
            "aider_version": plan["aider_version"],
            "architect_model": plan["architect_model"],
            "editor_model": plan["editor_model"],
            "architect_mode": plan["architect_mode"],
            "architect_think": plan["architect_think"],
            "model": plan["model"],
            "aider_model_settings": plan["aider_model_settings"],
            "remote_base_url": plan["remote_base_url"],
            "remote_api_key_env": plan["remote_api_key_env"],
            "remote_transport": plan["remote_transport"],
            "config_fingerprint": fingerprint,
            "run_status": "platform_incompatible",
            "required_platform": required,
            "host_platform": host,
            "lineages_started": 0,
            "lineages_planned": 0,
            "_comment": (
                "No lineage was started: this host does not satisfy the "
                "suite's platform contract. Reliability is not applicable "
                "rather than zero -- there is no denominator."
            ),
            "created_at": created,
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PYPRE
            printf '  recorded run_status=platform_incompatible in %s\n' \
                "$RUN_METADATA_PATH" >&2
        fi
        # Distinct from 1 (a stage failed) and 2 (usage/configuration error).
        exit 4
    fi
fi

# ---------------------------------------------------------------------------
# Resume guard: an existing lineage root must describe the same experiment
# ---------------------------------------------------------------------------

RUN_METADATA="$OUTPUT_DIR/lineages.json"
if [[ -f "$RUN_METADATA" && "$DRY_RUN" -eq 0 ]]; then
    mismatch="$(
        "$PYTHON_BIN" - "$RUN_METADATA" "$CONFIG_FINGERPRINT" "$UTILITY" \
        "$MODEL" "$EDITOR_MODEL" "$AIDER_VERSION" "$TEMPERATURE" "$MAX_LOOPS" \
            "${TOP_P:-__NONE__}" "${SAMPLING_SEED:-__NONE__}" \
            "${MAX_TOKENS:-__NONE__}" "${ARCHITECT_THINK:-__NONE__}" <<'PY'
import json
import sys
from pathlib import Path

(path, fingerprint, utility, model, editor_model, aider_version, temperature, max_loops,
 top_p, sampling_seed, max_tokens, architect_think) = sys.argv[1:]
try:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    print(f"cannot read {path}: {error}")
    raise SystemExit(0)

expected = {
    "config_fingerprint": fingerprint,
    "utility": utility,
    "agent_backend": "aider",
    "architect_model": model,
    "editor_model": editor_model,
    "aider_version": aider_version,
    "architect_mode": True,
    "model": model,
    "temperature": float(temperature),
    # Named individually as well as covered by the fingerprint: a changed
    # sampling knob then reports "top_p" rather than only "config_fingerprint",
    # which is the difference between a diagnosable refusal and a puzzle. An
    # unset knob compares as null, so a record written before these options
    # existed still resumes cleanly when they are not passed.
    "top_p": None if top_p == "__NONE__" else float(top_p),
    "sampling_seed": None if sampling_seed == "__NONE__" else int(sampling_seed),
    "max_tokens": None if max_tokens == "__NONE__" else int(max_tokens),
    "architect_think": (
        None if architect_think == "__NONE__" else architect_think
    ),
    "max_loops": int(max_loops),
}
differences = [key for key, value in expected.items() if data.get(key) != value]
print(", ".join(differences))
PY
    )" || die "cannot compare existing lineage metadata at $RUN_METADATA"
    [[ -z "$mismatch" ]] || die \
        "existing lineage run at $OUTPUT_DIR was produced under a different configuration ($mismatch); use a new --output-dir rather than mixing stage configurations"
fi

CHECKPOINT_ID_CSV="$(IFS=,; printf '%s' "${STAGE_IDS[*]}")"
CHECKPOINT_LADDER="${STAGE_IDS[0]}"
for (( index = 1; index < STAGE_COUNT; index++ )); do
    CHECKPOINT_LADDER+=" -> ${STAGE_IDS[index]}"
done

printf 'Repository:   %s\n' "$REPO"
printf 'Utility:      %s (%s checkpoints)\n' "$UTILITY" "$STAGE_COUNT"
printf 'Checkpoints:  %s\n' "$CHECKPOINT_LADDER"
printf 'Architect:    %s\n' "$MODEL"
printf 'Editor:       %s\n' "$EDITOR_MODEL"
printf 'Aider:        %s\n' "$AIDER_VERSION"
printf 'Temperature:  %s\n' "$TEMPERATURE"
# Printed as "(server default)" rather than omitted, so the console record of a
# run states every sampling condition instead of leaving three of them implied.
printf 'Top-p:        %s\n' "${TOP_P:-(server default)}"
printf 'Sampling seed: %s\n' "${SAMPLING_SEED:-(server default)}"
printf 'Max tokens:   %s\n' "${MAX_TOKENS:-(server default)}"
printf 'Architect think: %s\n' "${ARCHITECT_THINK:-(server default)}"
printf 'Lineages:     %s (numbered %s..%s)\n' \
    "$LINEAGES" "$LINEAGE_START" "$((LINEAGE_START + LINEAGES - 1))"
printf 'Max loops:    %s per stage\n' "$MAX_LOOPS"
printf 'Fingerprint:  %s\n' "$CONFIG_FINGERPRINT"
printf 'Output:       %s\n\n' "$OUTPUT_DIR"

if [[ "$DRY_RUN" -eq 1 ]]; then
    printf 'Aider invocation template:'
    printf ' %q' "$AIDER_BIN" --architect --auto-accept-architect \
        --model "$MODEL" --editor-model "$EDITOR_MODEL" \
        --weak-model "$EDITOR_MODEL" --editor-edit-format editor-diff \
        --model-settings-file '<attempt>/aider-model-settings.yml' \
        --message-file '<prompt-file>' --file '<source>' --no-git \
        --map-tokens 0 --no-auto-commits --no-dirty-commits \
        --no-auto-lint --no-auto-test --no-suggest-shell-commands \
        --no-analytics --no-check-update --no-show-release-notes --no-browser
    printf '\n\n'
fi

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

# What this invocation intends to run. These are PLANNED ids, written before
# any lineage begins, so they must never be read as evidence that a lineage
# started -- a run interrupted after three of ten lineages would otherwise
# report ten. Durable proof of a start is the lineage directory and its
# lineage.json, both created by lineage_state.py init immediately before
# checkpoint 000.
planned_lineage_ids = sorted(
    set(record.get("planned_lineage_ids", record.get("lineage_ids", [])))
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
        "agent_backend": plan["agent_backend"],
        "aider_version": plan["aider_version"],
        "architect_model": plan["architect_model"],
        "editor_model": plan["editor_model"],
        "architect_mode": plan["architect_mode"],
        "model": plan["model"],
        "model_provenance": plan.get("model_provenance"),
        "temperature": plan["temperature"],
        "architect_think": plan["architect_think"],
        # Taken from the plan rather than re-read from the shell, so the run
        # record and the fingerprint cannot describe different conditions.
        # Null means the flag was not passed and the server default applied.
        "top_p": plan["top_p"],
        "sampling_seed": plan["sampling_seed"],
        "max_tokens": plan["max_tokens"],
        "automation_notice_sha256": plan["automation_notice_sha256"],
        "editor_temperature": plan["editor_temperature"],
        "editor_sampling_seed": plan["editor_sampling_seed"],
        "editor_edit_format": plan["editor_edit_format"],
        "aider_model_settings": plan["aider_model_settings"],
        "remote_base_url": plan["remote_base_url"],
        "remote_api_key_env": plan["remote_api_key_env"],
        "remote_transport": plan["remote_transport"],
        "max_loops": plan["max_loops"],
        "timeout_seconds": plan["timeout_seconds"],
        "source_path": plan["source_path"],
        "source_basename": plan["source_basename"],
        "executable_path": plan["executable_path"],
        "test_dir": plan["test_dir"],
        "judge": plan["judge"],
        "required_platform": plan.get("required_platform"),
        "host_platform": plan.get("host_platform"),
        "config_fingerprint": plan["config_fingerprint"],
        "checkpoints": plan["checkpoints"],
        "planned_lineage_ids": planned_lineage_ids,
        "lineages_planned": len(planned_lineage_ids),
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

    seed_absolute=""
    seed_recorded=""
    stage_records=()
    end_to_end_success=true
    failure_stage_json=null
    failure_reason_json=null
    lineage_record="$lineage_dir/lineage.json"

    # The record exists BEFORE checkpoint 000 runs and is rewritten after every
    # checkpoint, so a controller that dies mid-walk still leaves a lineage that
    # analysis counts as started. Writing it only at the end used to drop such a
    # lineage out of the denominator entirely.
    if [[ "$DRY_RUN" -eq 0 ]]; then
        "$PYTHON_BIN" "$STATE_TOOL" --path "$lineage_record" --now "$(timestamp)" \
            init \
            --lineage-id "$lineage_id" \
            --utility "$UTILITY" \
            --model "$MODEL" \
            --editor-model "$EDITOR_MODEL" \
            --aider-version "$AIDER_VERSION" \
            --model-provenance-json "$MODEL_PROVENANCE_JSON" \
            --temperature "$TEMPERATURE" \
            --top-p "$TOP_P" \
            --sampling-seed "$SAMPLING_SEED" \
            --max-tokens "$MAX_TOKENS" \
            --architect-think "$ARCHITECT_THINK" \
            --max-loops "$MAX_LOOPS" \
            --fingerprint "$CONFIG_FINGERPRINT" \
            --checkpoint-count "$STAGE_COUNT" \
            --checkpoint-ids "$CHECKPOINT_ID_CSV" ||
            die "cannot create the lineage record at $lineage_record"
    fi

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
            --editor-model "$EDITOR_MODEL"
            --temperature "$TEMPERATURE"
            --runs 1
            --max-loops "$MAX_LOOPS"
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
        [[ -n "$MODEL_PROVENANCE_JSON" ]] &&
            runner_args+=(--model-provenance-json "$MODEL_PROVENANCE_JSON")
        # Sampling knobs are forwarded only when requested, so an unset one
        # leaves the stage command exactly as it was before these options
        # existed. Added to runner_args, which is the single command every
        # stage uses -- checkpoint 000, every later checkpoint, and the repair
        # sessions run_experiment.sh drives inside that stage -- so a knob
        # cannot reach one kind of session and miss another.
        [[ -n "$TOP_P" ]] && runner_args+=(--top-p "$TOP_P")
        [[ -n "$SAMPLING_SEED" ]] && runner_args+=(--sampling-seed "$SAMPLING_SEED")
        [[ -n "$MAX_TOKENS" ]] && runner_args+=(--max-tokens "$MAX_TOKENS")
        [[ -n "$ARCHITECT_THINK" ]] &&
            runner_args+=(--architect-think "$ARCHITECT_THINK")
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
            [[ -n "$seed_absolute" ]] ||
                die "$lineage_id stage $stage_id has no seed from the previous stage"
            runner_args+=(--seed-file "$seed_absolute:$SOURCE_PATH")
        fi
        [[ "$FORCE" -eq 1 ]] && runner_args+=(--force)

        if [[ "$DRY_RUN" -eq 1 ]]; then
            printf '  [%s %s] bash scripts/run_experiment.sh' "$stage_id" "$stage_name"
            printf ' %q' "${runner_args[@]}"
            printf '\n'
            # A dry run cannot produce a candidate, so fabricate the provenance
            # the next stage would inherit rather than aborting the walk.
            seed_absolute="$stage_candidate"
            seed_recorded="$(record_path "$stage_candidate")"
            continue
        fi

        stage_reused=false
        stage_runner_status=0
        if [[ -f "$stage_attempt/COMPLETE" && "$FORCE" -eq 0 ]]; then
            # A reusable stage must have been produced from the same seed. The
            # runner snapshots its seed as baseline/<basename>, so comparing that
            # against the seed this walk is holding catches the one way a resume
            # could silently mix generations: an earlier stage regenerated while
            # a later one was left alone.
            if [[ "$stage_mode" == "existing" ]]; then
                seed_drift="$(
                    "$PYTHON_BIN" - "$stage_experiment/baseline/$SOURCE_BASENAME" \
                        "$seed_absolute" <<'PY'
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
            bash "$STAGE_RUNNER" "${runner_args[@]}"
            stage_runner_status=$?
            if [[ "$stage_runner_status" -ne 0 ]]; then
                warn "$lineage_id stage $stage_id: run_experiment.sh exited nonzero"
                overall_status=1
            fi
        fi

        stage_summary="$(
            "$PYTHON_BIN" - "$stage_attempt" "$stage_candidate" "$stage_id" \
                "$stage_name" "$stage_prompt" "$stage_mode" "$stage_cmd" \
                "$stage_flags" "${seed_recorded:-}" "${seed_absolute:-}" "$stage_reused" \
                "$SOURCE_BASENAME" "$stage_bundle" "$stage_bundle_fingerprint" \
                "$stage_runner_status" \
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
    seed_absolute,
    reused,
    source_basename,
    test_bundle_dir,
    test_bundle_fingerprint,
    stage_runner_status,
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
attempt_exists = attempt.is_dir()
public_success = bool(metadata.get("public_validation_success"))
# A stage "successfully completed" only if the build/base/checkpoint validation
# run by the controller passed AND the source it produced was captured. The
# next stage inherits that file, so a missing candidate is a stage failure even
# when validation reported success.
success = attempt_complete and public_success and candidate_sha is not None

if not attempt_exists and int(stage_runner_status) == 0:
    # The stage command reported success but did not honor the output path the
    # controller passed to it.  That is a producer/consumer contract failure,
    # not evidence about model reliability.
    reason = "stage_output_contract_failure"
elif not attempt_exists:
    reason = "stage_runner_failure"
elif not attempt_complete:
    reason = "stage_run_incomplete"
elif metadata.get("infrastructure_failure"):
    reason = "infrastructure_failure"
elif metadata.get("agent_execution_failure"):
    reason = "agent_execution_failure"
elif metadata.get("feature_test_exit_code") == 3:
    # runner.py exits 3 for PLATFORM INCOMPATIBLE: the frozen suite cannot be
    # judged on this host at all. That is an environment fault, so it is
    # classified with the infrastructure failures rather than counted against
    # the candidate as validation_failed.
    reason = "platform_incompatible"
elif not public_success:
    reason = str(metadata.get("stop_reason") or "validation_failed")
elif candidate_sha is None:
    reason = "candidate_missing"
else:
    reason = None

backend = metadata.get("agent_backend")
if not backend and any(key.startswith("opencode_") for key in metadata):
    # Historical OpenCode attempts predate agent_backend, but their
    # backend-specific fields are affirmative provenance.  Absence alone is
    # not: a missing/unreadable current metadata file stays unknown.
    backend = "opencode"

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
    "stage_runner_exit_code": int(stage_runner_status),
    "output_contract_failure": reason == "stage_output_contract_failure",
    "success": success,
    "failure_reason": reason,
    # Reuse the metadata vocabulary of the single-stage runner rather than
    # inventing a second classification.
    "public_validation_success": public_success,
    "initial_success": bool(metadata.get("initial_success")),
    "repair_loops": metadata.get("repair_loops"),
    "llm_invocations": metadata.get("llm_invocations"),
    "success_loop": metadata.get("success_loop"),
    "stop_reason": metadata.get("stop_reason"),
    "loop_limit_reached": bool(metadata.get("loop_limit_reached")),
    "infrastructure_failure": bool(metadata.get("infrastructure_failure")),
    "platform_incompatible": metadata.get("feature_test_exit_code") == 3,
    "infrastructure_failure_stage": metadata.get("infrastructure_failure_stage"),
    "agent_execution_failure": bool(metadata.get("agent_execution_failure")),
    "agent_execution_failure_stage": metadata.get("agent_execution_failure_stage"),
    "agent_failure_reason": metadata.get("agent_failure_reason"),
    "architect_think": metadata.get("architect_think"),
    # Timeout provenance, carried into the lineage record so a stage that
    # succeeded or was repaired after a cut-short session is still
    # distinguishable from one whose session finished normally.
    "agent_backend": backend,
    "agent_exit_code": metadata.get(
        "agent_exit_code", metadata.get("opencode_exit_code")
    ),
    "initial_session_completed": metadata.get("initial_session_completed"),
    "candidate_available_after_timeout": metadata.get(
        "candidate_available_after_timeout"
    ),
    "validation_completed_after_timeout": metadata.get(
        "validation_completed_after_timeout"
    ),
    "repair_eligible": metadata.get("repair_eligible"),
    "repair_eligibility_reason": metadata.get("repair_eligibility_reason"),
    "build_exit_code": metadata.get("build_exit_code"),
    "base_test_exit_code": metadata.get("base_test_exit_code"),
    "feature_test_exit_code": metadata.get("feature_test_exit_code"),
    "extra_test_exit_code": metadata.get("extra_test_exit_code"),
    "test_dir_integrity": metadata.get("test_dir_integrity"),
    "total_agent_runtime_ms": metadata.get(
        "total_agent_runtime_ms", metadata.get("total_opencode_runtime_ms")
    ),
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
    # Hashed through the absolute path: `seed` is what gets recorded and may be
    # repository-relative, which only resolves when the controller happens to be
    # running from the repository root.
    seed_file = Path(seed_absolute or seed)
    if seed_file.is_file():
        digest = hashlib.sha256()
        with seed_file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        record["seed_sha256"] = digest.hexdigest()

print(json.dumps(record, separators=(",", ":")))
PY
        )" || die "failed to summarize $lineage_id stage $stage_id"

        # The checkpoint boundary gate runs only on a candidate that already
        # passed public validation, and only to decide promotion. A candidate
        # that implemented a later checkpoint's flags fails the stage here with
        # its own reason, so it is never promoted and no final/ is written.
        if [[ "$DRY_RUN" -eq 0 ]] &&
           "$PYTHON_BIN" -c \
                'import json,sys; sys.exit(0 if json.loads(sys.argv[1])["success"] else 1)' \
                "$stage_summary"; then
            gate_report="$stage_dir/boundary-gate.json"
            boundary_gate "$stage_candidate" "$stage_id" "$gate_report"
            gate_status=$?
            if [[ "$gate_status" -ne 0 ]]; then
                if [[ "$gate_status" -eq 1 ]]; then
                    gate_reason="premature_feature_implementation"
                else
                    gate_reason="boundary_gate_error"
                fi
                stage_summary="$(
                    "$PYTHON_BIN" -c '
import json
import sys
from pathlib import Path

record = json.loads(sys.argv[1])
record["success"] = False
record["failure_reason"] = sys.argv[2]
record["boundary_gate_passed"] = False
report = Path(sys.argv[3])
if report.is_file():
    try:
        record["boundary_gate"] = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        record["boundary_gate"] = None
print(json.dumps(record, separators=(",", ":")))
' "$stage_summary" "$gate_reason" "$gate_report"
                )" || die "cannot record the boundary-gate result for $lineage_id stage $stage_id"
            else
                stage_summary="$(
                    "$PYTHON_BIN" -c \
                        'import json,sys; r=json.loads(sys.argv[1]); r["boundary_gate_passed"]=True; print(json.dumps(r,separators=(",",":")))' \
                        "$stage_summary"
                )"
            fi
        fi

        stage_records+=("$stage_summary")

        # Persist this checkpoint before deciding whether to continue, so an
        # interruption at any point leaves the record describing exactly the
        # checkpoints that actually finished.
        "$PYTHON_BIN" "$STATE_TOOL" --path "$lineage_record" --now "$(timestamp)" \
            stage --stage-json "$stage_summary" ||
            die "cannot update the lineage record at $lineage_record"

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
            if [[ "$stage_reason" == "stage_output_contract_failure" ]]; then
                overall_status=1
            fi
            printf '  [%s %s] STOP: %s\n' \
                "$stage_id" "$stage_name" "${stage_reason:-unknown}"
            break
        fi

        printf '  [%s %s] pass\n' "$stage_id" "$stage_name"
        seed_absolute="$stage_candidate"
        seed_recorded="$(record_path "$stage_candidate")"
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
        cp -p "$seed_absolute" "$final_dir/$SOURCE_BASENAME"
        completed_lineages=$((completed_lineages + 1))
    fi

    # Every stage was already folded into the record as it finished; this only
    # closes the lineage out, moving it from `running` to `completed`/`stopped`.
    finish_args=(--success "$end_to_end_success" --source-basename "$SOURCE_BASENAME")
    if [[ "$end_to_end_success" != true ]]; then
        finish_args+=(--failure-stage "$(printf '%s' "$failure_stage_json" | tr -d '"')")
        finish_args+=(--failure-reason "$(printf '%s' "$failure_reason_json" | tr -d '"')")
    fi
    "$PYTHON_BIN" "$STATE_TOOL" --path "$lineage_record" --now "$(timestamp)" \
        finish "${finish_args[@]}" ||
        die "cannot finalize the lineage record at $lineage_record"

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
