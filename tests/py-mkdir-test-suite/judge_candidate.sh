#!/usr/bin/env bash
set -euo pipefail
: "${HELDOUT_ROOT:?controller root required}"
candidate="${1:?candidate required}"
shift
exec python3 "$HELDOUT_ROOT/scripts/docker_benchmark.py" judge --utility py-mkdir --candidate "$candidate" -- "$@"
