#!/usr/bin/env bash
# Existing authenticated/configured Fedora reconstructions are prerequisites.
set -euo pipefail
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
PYTHONPATH=. python3 -m security.historical.fedora_sort_scope_checkpoint "$@"
