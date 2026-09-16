#!/usr/bin/env bash
# Recreate path-sensitive historical configuration and run semantic validation.
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
run_root=$(mktemp -d /tmp/agentic-cyber-semantic.XXXXXX)
case "$run_root" in
  /tmp/agentic-cyber-semantic.*) ;;
  *) echo "unexpected temporary path: $run_root" >&2; exit 1 ;;
esac
cleanup() {
  rm -rf -- "$run_root"
}
trap cleanup EXIT

# Older Automake rejects source directory names containing spaces.  The
# temporary alias changes no source bytes and remains live through analysis,
# so generated config headers and recipes keep resolving correctly.
ln -s "$repo_root" "$run_root/repo"
cd "$run_root/repo"
bash security/historical/prepare_coreutils_9_7_sort_scope.sh
# Keep hundreds of transient bitcode modules on the WSL-native temporary
# filesystem. Scientific paths are normalized to $OUTPUT_ROOT, and the final
# JSON/Markdown artifacts are still written to the repository by default.
PYTHONPATH=. python3 -m security.historical.semantic_validation \
  --build-root "$run_root/semantic-historical-validation" "$@"
