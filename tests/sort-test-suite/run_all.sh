#!/usr/bin/env bash
# Full robustness run against a candidate sort-like binary:
#   pass 1: normal build, all suites, config-filtered by implemented flags
#   pass 2: ASan/UBSan build, same suites (memory-safety -> hard failures)
#   pass 3: time-boxed differential fuzz vs the oracle
#
# Every path (candidate binary, ASan binary/build settings, oracle binary)
# comes from config.json -- see paths.* in that file. Nothing here is
# hardcoded to any particular candidate.
#
# Everything printed is also saved to run_logs/<timestamp>/run_all.log
# (stdout+stderr), alongside per-pass machine-readable JSON, and the run
# ends with an aggregated OVERALL SUMMARY block (report_summary.py) with
# pass/fail counts and percentages suitable for pasting into a report.
#
# Usage: ./run_all.sh [config.json] [fuzz_seconds]
set -u
cd "$(dirname "$0")"
CONFIG=${1:-config.json}
FUZZ_SECS=${2:-}

if [ ! -f "$CONFIG" ]; then
  echo "run_all.sh: config file not found: $CONFIG" >&2
  echo "Copy config.json.example (or edit config.json) and point it at your binary first." >&2
  exit 2
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
  echo "Edit paths.candidate_bin in $CONFIG to point at your built sort binary." >&2
  exit 2
fi
# Note: the oracle binary is NOT required for passes 1-2 -- those judge
# against the already-frozen suites/ goldens. Only pass 3 (live
# differential fuzzing) needs it; that's checked separately below.

SUITES=(); for s in suites/*.json suites/*.json.gz; do
  [ -f "$s" ] && [[ "$(basename "$s")" != "MANIFEST.json" ]] && SUITES+=("$s")
done

# Rebuildable artifacts only -- never suites/ (goldens) or run_logs/ (report
# history). Run both before (clean start: no stale binary from a prior
# run/candidate can leak into this one) and after (trap, so it also fires
# on failure/Ctrl-C).
clean_artifacts() {
  [ -n "$CAND_SRC" ] && rm -f "$CAND_ASAN"
  find . -maxdepth 3 -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null
}

TS=$(date +%Y%m%d_%H%M%S)
LOGDIR="run_logs/${TS}"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/run_all.log"
exec > >(tee "$LOGFILE") 2>&1
trap clean_artifacts EXIT

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
