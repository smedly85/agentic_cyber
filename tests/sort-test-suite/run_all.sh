#!/usr/bin/env bash
# Full robustness run against a candidate sort-like binary:
#   pass 1: normal build, all suites, config-filtered by implemented flags
#   pass 2: ASan/UBSan build, same suites (memory-safety -> hard failures)
#   pass 3: time-boxed differential fuzz vs the oracle
#
# Candidate paths, implemented flags, stdin scope, and fuzz duration can be
# overridden at runtime. Config overrides are written to a temporary copy;
# the supplied config is never modified.
#
# Everything printed is also saved to run_logs/<timestamp>/run_all.log
# (stdout+stderr), alongside per-pass machine-readable JSON, and the run
# ends with an aggregated OVERALL SUMMARY block (report_summary.py) with
# pass/fail counts and percentages suitable for pasting into a report.
#
# Usage: ./run_all.sh [config.json] [fuzz_seconds]
#        ./run_all.sh --candidate PATH [runtime options]
set -u
cd "$(dirname "$0")"

usage() {
  cat <<'EOF'
Usage: ./run_all.sh [config.json] [fuzz_seconds]
       ./run_all.sh [config.json] [options]

Runtime options:
  --candidate PATH          Override paths.candidate_bin
  --candidate-src PATH      Override paths.candidate_src and build ASan/UBSan
  --implemented-flags CSV   Replace the implemented flag list (empty is valid)
  --stdin-only              Run only frozen cases containing stdin_b64
  --fuzz-seconds N          Override the live differential-fuzz duration
EOF
}

BASE_CONFIG=config.json
FUZZ_SECS=
CAND_OVERRIDE=
CAND_SRC_OVERRIDE=
IMPLEMENTED_CSV=
CAND_SET=false
CAND_SRC_SET=false
IMPLEMENTED_SET=false
STDIN_ONLY=false
POSITIONAL=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --candidate|--candidate-src|--implemented-flags|--fuzz-seconds)
      [ "$#" -ge 2 ] || {
        echo "run_all.sh: $1 requires a value" >&2; usage >&2; exit 2; }
      option=$1
      value=$2
      shift 2
      case "$option" in
        --candidate) CAND_OVERRIDE=$value; CAND_SET=true ;;
        --candidate-src) CAND_SRC_OVERRIDE=$value; CAND_SRC_SET=true ;;
        --implemented-flags) IMPLEMENTED_CSV=$value; IMPLEMENTED_SET=true ;;
        --fuzz-seconds) FUZZ_SECS=$value ;;
      esac
      ;;
    --candidate=*) CAND_OVERRIDE=${1#*=}; CAND_SET=true; shift ;;
    --candidate-src=*) CAND_SRC_OVERRIDE=${1#*=}; CAND_SRC_SET=true; shift ;;
    --implemented-flags=*) IMPLEMENTED_CSV=${1#*=}; IMPLEMENTED_SET=true; shift ;;
    --fuzz-seconds=*) FUZZ_SECS=${1#*=}; shift ;;
    --stdin-only) STDIN_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "run_all.sh: unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)
      POSITIONAL=$((POSITIONAL + 1))
      if [ "$POSITIONAL" -eq 1 ]; then
        BASE_CONFIG=$1
      elif [ "$POSITIONAL" -eq 2 ]; then
        [ -z "$FUZZ_SECS" ] || {
          echo "run_all.sh: fuzz duration specified more than once" >&2; exit 2; }
        FUZZ_SECS=$1
      else
        echo "run_all.sh: unexpected argument: $1" >&2; usage >&2; exit 2
      fi
      shift
      ;;
  esac
done

if [ ! -f "$BASE_CONFIG" ]; then
  echo "run_all.sh: config file not found: $BASE_CONFIG" >&2
  echo "Copy config.json.example (or edit config.json) and point it at your binary first." >&2
  exit 2
fi

if [ -n "$FUZZ_SECS" ] &&
   ! [[ "$FUZZ_SECS" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]]; then
  echo "run_all.sh: --fuzz-seconds must be a non-negative number" >&2
  exit 2
fi

CONFIG=$BASE_CONFIG
RUNTIME_DIR=
trap '[ -z "$RUNTIME_DIR" ] || rm -rf "$RUNTIME_DIR"' EXIT
if [ "$CAND_SET" = true ] || [ "$CAND_SRC_SET" = true ] ||
   [ "$IMPLEMENTED_SET" = true ] || [ "$STDIN_ONLY" = true ]; then
  RUNTIME_DIR=$(mktemp -d "${TMPDIR:-/tmp}/sort-test-suite.XXXXXX") || exit 2
  CONFIG="$RUNTIME_DIR/config.json"
  python3 - "$BASE_CONFIG" "$CONFIG" \
      "$CAND_SET" "$CAND_OVERRIDE" \
      "$CAND_SRC_SET" "$CAND_SRC_OVERRIDE" \
      "$IMPLEMENTED_SET" "$IMPLEMENTED_CSV" \
      "$STDIN_ONLY" "$RUNTIME_DIR/candidate_asan" <<'PY' || exit 2
import json
import sys

(base, output, candidate_set, candidate, source_set, source,
 implemented_set, implemented_csv, stdin_only, asan_bin) = sys.argv[1:]

with open(base, encoding="utf-8") as handle:
    config = json.load(handle)

paths = config.setdefault("paths", {})
if candidate_set == "true":
    paths["candidate_bin"] = candidate
if source_set == "true":
    paths["candidate_src"] = source
    if source:
        paths["candidate_asan_bin"] = asan_bin
if implemented_set == "true":
    config["implemented"] = [
        flag.strip() for flag in implemented_csv.split(",") if flag.strip()
    ]
if stdin_only == "true":
    config.setdefault("scope", {})["stdin_only"] = True

with open(output, "w", encoding="utf-8") as handle:
    json.dump(config, handle, indent=2)
    handle.write("\n")
PY
fi

cfg() { python3 config.py "$CONFIG" "$@"; }

CAND=$(cfg paths.candidate_bin) || {
  echo "run_all.sh: paths.candidate_bin is not set in $CONFIG" >&2; exit 2; }
CAND_ASAN=$(cfg paths.candidate_asan_bin --default ./candidate_asan)
CAND_SRC=$(cfg paths.candidate_src --default "")
ORACLE=$(cfg paths.oracle_bin --default /usr/bin/sort)
[ -n "$FUZZ_SECS" ] || FUZZ_SECS=$(cfg fuzz.time_budget_s --default 60)

if [ ! -x "$CAND" ]; then
  echo "run_all.sh: paths.candidate_bin ('$CAND') is not an executable file." >&2
  echo "Edit paths.candidate_bin in $CONFIG or pass --candidate PATH." >&2
  exit 2
fi
# The oracle is only required for live differential fuzzing. Passes 1-2
# judge against the already-frozen suites/goldens.

SUITES=(); for s in suites/*.json suites/*.json.gz; do
  [ -f "$s" ] && [[ "$(basename "$s")" != "MANIFEST.json" ]] && SUITES+=("$s")
done

# Rebuildable artifacts only -- never suites/ (goldens) or run_logs/ (report
# history). Run both before and after so stale sanitizer builds cannot leak
# between candidates.
clean_artifacts() {
  [ -n "$CAND_SRC" ] && rm -f "$CAND_ASAN"
  find . -maxdepth 3 -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null
}

cleanup_exit() {
  clean_artifacts
  [ -z "$RUNTIME_DIR" ] || rm -rf "$RUNTIME_DIR"
}

TS=$(date +%Y%m%d_%H%M%S)
LOGDIR="run_logs/${TS}"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/run_all.log"
exec > >(tee "$LOGFILE") 2>&1
trap cleanup_exit EXIT

echo "run_all.sh: config=$CONFIG candidate=$CAND oracle=$ORACLE fuzz_secs=$FUZZ_SECS"
echo "log: $LOGFILE"
echo "cleaning stale build artifacts for a clean start..."
clean_artifacts
rc=0

echo; echo "########## pass 1: normal ##########"
python3 runner.py "${SUITES[@]}" --config "$CONFIG" \
    --json-report "$LOGDIR/normal.json" -- "$CAND" || rc=1

echo; echo "########## pass 2: ASan/UBSan ##########"
if [ -n "$CAND_SRC" ]; then
  if ./build_asan.sh "$CONFIG"; then
    python3 runner.py "${SUITES[@]}" --config "$CONFIG" --sanitizer \
        --json-report "$LOGDIR/asan.json" -- "$CAND_ASAN" || rc=1
  else
    echo "ASan build failed; skipping sanitizer pass"; rc=1
  fi
elif [ -x "$CAND_ASAN" ]; then
  echo "using pre-built ASan binary: $CAND_ASAN"
  python3 runner.py "${SUITES[@]}" --config "$CONFIG" --sanitizer \
      --json-report "$LOGDIR/asan.json" -- "$CAND_ASAN" || rc=1
else
  echo "paths.candidate_src is empty and paths.candidate_asan_bin ($CAND_ASAN)" \
       "doesn't exist -- skipping ASan pass. See config.json's comments" \
       "on candidate_asan_bin / candidate_src."
fi

echo; echo "########## pass 3: differential fuzz (${FUZZ_SECS}s) ##########"
if [ -x "$ORACLE" ]; then
  python3 diff_fuzz.py --candidate "$CAND" --oracle "$ORACLE" \
      --config "$CONFIG" --time-budget "$FUZZ_SECS" --seed 1 \
      --json-report "$LOGDIR/fuzz.json" || rc=1
else
  echo "paths.oracle_bin ('$ORACLE') is not an executable file -- skipping" \
       "live differential fuzz (passes 1-2 don't need it)."
fi

echo
python3 report_summary.py \
    --normal "$LOGDIR/normal.json" \
    --asan "$LOGDIR/asan.json" \
    --fuzz "$LOGDIR/fuzz.json"

echo
[ "$rc" = 0 ] && echo "RUN_ALL: CLEAN" || echo "RUN_ALL: PROBLEMS FOUND"
echo "full log:     $LOGFILE"
echo "json reports: $LOGDIR/{normal,asan,fuzz}.json"
exit $rc
