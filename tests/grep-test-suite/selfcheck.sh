#!/usr/bin/env bash
# Self-check the new_grep suite without any candidate binary.
#
#   pass 0: the oracle, when this host has one -- it is GNU grep at the pinned
#           version AND it behaves the way new_grep's contract needs
#   pass 1: gen/verify.py -- suites/ is fresh, every frozen case satisfies the
#           model-independent invariants, and every checkpoint's cumulative flag
#           list selects a non-empty, monotonically growing case set
#   pass 2: judge_candidate.sh leaves the committed config.json untouched
#
# Passes 1 and 2 are offline and platform-independent: nothing here executes a
# candidate, so this is the check to run in CI or before committing a change to
# the case definitions. Pass 0 needs a GNU grep, which not every host has, so
# it reports "not verified here" and continues -- EXCEPT when GREP_ORACLE_BIN
# is set, which is an explicit statement that this host has the oracle and
# therefore an unfit one is a failure rather than an absence.
#
# Usage: ./selfcheck.sh
#        GREP_ORACLE_BIN=/usr/bin/grep ./selfcheck.sh
set -euo pipefail
cd "$(dirname "$0")"

rc=0

echo "########## pass 0: oracle contract ##########"
# Resolution order (--oracle-bin > $GREP_ORACLE_BIN > config.json > conventional
# locations) lives in one place; this only reports what it chose.
ORACLE_TOOL=../reference_generators/oracle_contract.py
oracle="$(python3 "$ORACLE_TOOL" resolve --suite grep --config config.json \
                  --suite-root . 2>/dev/null || true)"
if python3 "$ORACLE_TOOL" verify --suite grep --config config.json \
        --suite-root . >/dev/null 2>&1 &&
   python3 gen/oracle.py --oracle-bin "$oracle" >/dev/null 2>&1; then
    echo "oracle: ${oracle} -- $(python3 "$ORACLE_TOOL" version --suite grep \
                                        --config config.json --suite-root .)"
    echo "fit to regenerate: OK"
elif [[ -n "${GREP_ORACLE_BIN:-}" ]]; then
    echo "GREP_ORACLE_BIN is set, so its oracle must be usable:" >&2
    python3 "$ORACLE_TOOL" verify --suite grep --config config.json \
            --suite-root . || rc=1
    python3 gen/oracle.py --oracle-bin "$oracle" || rc=1
else
    echo "oracle: not verified on this host (${oracle:-none found})."
    echo "  The committed goldens are judged byte for byte and need no grep;"
    echo "  set GREP_ORACLE_BIN to a GNU grep to check the regeneration path."
fi

echo
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
./judge_candidate.sh "$stub" -H >/dev/null 2>&1 || true

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
