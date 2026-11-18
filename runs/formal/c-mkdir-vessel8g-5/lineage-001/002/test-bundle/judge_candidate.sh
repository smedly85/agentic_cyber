#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 1 ]] || exit 2
candidate="$1"; shift
controller="${HELDOUT_ROOT:?controller root required for Docker validation}"
exec python3 "$controller/scripts/docker_benchmark.py" judge --utility c-mkdir --candidate "$candidate" -- "$@"
