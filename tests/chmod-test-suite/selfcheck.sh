#!/usr/bin/env bash
# Self-check the new_chmod suite without any candidate binary.
#
#   pass 1: gen/verify.py -- suites/ is fresh, every frozen case satisfies the
#           model-independent invariants, and every checkpoint's cumulative flag
#           list selects a non-empty, monotonically growing case set
#   pass 2: judge_candidate.sh leaves the committed config.json untouched
#
# Both passes are offline and platform-independent: nothing here executes a
# candidate, so this is the check to run in CI or before committing a change to
# the case definitions.
#
# Usage: ./selfcheck.sh
set -euo pipefail
cd "$(dirname "$0")"

rc=0

echo "########## pass 1: frozen-suite audit ##########"
python3 gen/verify.py || rc=1

echo
echo "########## pass 2: config.json is never mutated ##########"
before="$(python3 -c '
import hashlib, sys
print(hashlib.sha256(open("config.json","rb").read()).hexdigest())
')"

# A binary that exits immediately is enough: the point is whether the wrapper
# writes to config.json, not whether any case passes.
stub="$(mktemp)"
trap 'rm -f "$stub"' EXIT
printf '#!/bin/sh\nexit 1\n' >"$stub"
chmod +x "$stub"
./judge_candidate.sh "$stub" -R >/dev/null 2>&1 || true

after="$(python3 -c '
import hashlib, sys
print(hashlib.sha256(open("config.json","rb").read()).hexdigest())
')"

if [[ "$before" == "$after" ]]; then
    echo "config.json unchanged: OK"
else
    echo "config.json was modified by judge_candidate.sh" >&2
    rc=1
fi

echo
[[ "$rc" -eq 0 ]] && echo "SELFCHECK: CLEAN" || echo "SELFCHECK: PROBLEMS FOUND"
exit "$rc"
