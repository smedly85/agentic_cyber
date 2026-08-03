#!/usr/bin/env bash
# Judge a candidate grep-like binary against this suite's frozen goldens,
# with `implemented` set to exactly the flags given on the command line.
#
# Usage: judge_candidate.sh CANDIDATE_BIN [FLAG...]
#   judge_candidate.sh build/new_grep            # no flags declared implemented
#   judge_candidate.sh build/new_grep FLAG...    # those flags declared implemented
#
# FLAG... is the cumulative list of flags the candidate is expected to support.
# A frozen case runs only when every flag it needs appears in that list, so
# passing a checkpoint's cumulative flag list automatically re-checks every
# earlier checkpoint's cases as regression coverage. Base-tier cases (needing
# zero flags) always run.
#
# The checkpoint sequence itself is deliberately NOT written here: this file is
# copied into the agent-visible stage bundle, and naming a later checkpoint's
# flags would disclose work the agent has not been asked for yet. See
# README.md, which stays outside every bundle, for the ladder.
#
# This never touches the committed config.json: it builds a throwaway copy, so
# it is safe to call repeatedly (once per checkpoint from an experiment harness)
# with no shared mutable state.
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
candidates=(suites/*.json suites/*.json.gz)
shopt -u nullglob
# suites/MANIFEST.json records how the goldens were frozen; it holds no cases.
suites=()
for suite in "${candidates[@]}"; do
    [[ "$(basename "$suite")" == "MANIFEST.json" ]] && continue
    suites+=("$suite")
done
[[ ${#suites[@]} -gt 0 ]] || {
    echo "judge_candidate.sh: no suite files found under suites/" >&2
    exit 2
}

python3 runner.py "${suites[@]}" --config "$tmp_config" -- "$candidate_bin"
