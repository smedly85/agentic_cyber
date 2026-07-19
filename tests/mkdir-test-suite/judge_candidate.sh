#!/usr/bin/env bash
# Judge a candidate mkdir-like binary against this suite's frozen goldens,
# with `implemented` set to exactly the flags given on the command line.
#
# Usage: judge_candidate.sh CANDIDATE_BIN [FLAG...]
#   judge_candidate.sh build/new_mkdir              # base checkpoint (no flags)
#   judge_candidate.sh build/new_mkdir -p           # base + -p checkpoint
#   judge_candidate.sh build/new_mkdir -p -m        # base + -p + -m checkpoint
#
# Base-tier cases (needing zero flags) always run regardless of the FLAG
# list, so passing the cumulative flag list for a checkpoint automatically
# re-checks every earlier checkpoint's cases too.
#
# Unlike run_all.sh, this never touches the committed config.json -- it
# builds a throwaway copy so it's safe to call repeatedly (e.g. once per
# checkpoint from an experiment harness) without any shared mutable state.
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: judge_candidate.sh CANDIDATE_BIN [FLAG...]" >&2
    exit 2
fi

candidate_input="$1"; shift
candidate_dir="$(cd "$(dirname "$candidate_input")" && pwd)"
candidate_bin="$candidate_dir/$(basename "$candidate_input")"

cd "$(dirname "$0")"

[[ -x "$candidate_bin" ]] || {
    echo "judge_candidate.sh: not an executable file: $candidate_bin" >&2
    exit 2
}

tmp_config="$(mktemp)"
trap 'rm -f "$tmp_config"' EXIT

python3 - "$tmp_config" "$candidate_bin" "$@" <<'PY'
import json
import sys

out_path, candidate, flags = sys.argv[1], sys.argv[2], sys.argv[3:]
with open("config.json") as handle:
    config = json.load(handle)
config["paths"]["candidate_bin"] = candidate
config["implemented"] = flags
with open(out_path, "w") as handle:
    json.dump(config, handle)
PY

shopt -s nullglob
suites=(suites/*.json.gz)
shopt -u nullglob
[[ ${#suites[@]} -gt 0 ]] || {
    echo "judge_candidate.sh: no suites/*.json.gz found" >&2
    exit 2
}

python3 runner.py "${suites[@]}" --config "$tmp_config" -- "$candidate_bin"
