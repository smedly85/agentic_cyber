#!/usr/bin/env bash
set -euo pipefail
python3 "$(dirname "$0")/../../../src/harness/linux_benchmark.py" validate --utility c-cp "$@"
