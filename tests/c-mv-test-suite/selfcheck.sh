#!/usr/bin/env bash
set -euo pipefail
python3 "$(dirname "$0")/../../scripts/linux_benchmark.py" validate --utility c-mv "$@"
