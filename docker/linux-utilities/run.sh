#!/usr/bin/env bash
# Trusted oracle validation only. No generated candidate is admitted here.
set -euo pipefail
image="${1:?usage: run.sh sha256:IMAGE_ID NEW_OUTPUT_DIRECTORY [linux/arm64]}"
output="${2:?new output directory required}"
target="${3:-linux/arm64}"
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'immutable image ID required' >&2; exit 2; }
case "$target" in linux/arm64) arch=aarch64;; linux/amd64) arch=x86_64;; *) exit 2;; esac
[[ ! -e "$output" ]] || { echo 'refusing existing output directory' >&2; exit 2; }
mkdir -p "$output"
output="$(cd "$output" && pwd)"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
name="linux-utilities-$$"
trap 'docker rm -fv "$name" >/dev/null 2>&1 || true' EXIT
# Trusted oracle only: staged inputs mounted read-only, fresh output directory writable.
# No socket, network, candidate execution, historical results mount or privileges.
staging="$(mktemp -d)"
trap 'rm -rf -- "$staging"; docker rm -fv "$name" >/dev/null 2>&1 || true' EXIT
mkdir "$staging/tests"
cp -R "$repo/scripts" "$repo/experiments" "$repo/prompts" "$staging/"
cp -R "$repo/tests/reference_generators" "$staging/tests/"
for utility in cp mv mkdir sort; do cp -R "$repo/tests/c-$utility-test-suite" "$staging/tests/"; done
docker create --name "$name" --platform "$target" --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --cpus 2 --memory 2g --pids-limit 128 --ulimit cpu=900:900 \
  --ulimit fsize=268435456:268435456 --ulimit nofile=256:256 \
  --tmpfs /tmp:rw,nosuid,nodev,size=1g --tmpfs /home/benchmark:rw,nosuid,nodev,size=16m \
  --mount "type=bind,source=$staging,target=/work,readonly" \
  --mount "type=bind,source=$output,target=/output" \
  -e BENCHMARK_ARCH="$arch" -e BENCHMARK_IMAGE_ID="$image" \
  "$image" bash -c 'umask 022; timeout --signal=KILL 1800 bash -c "python3 scripts/linux_benchmark.py verify && python3 scripts/linux_benchmark.py validate --output /output/validated"' >/dev/null
docker start -a "$name" >"$output/validation.log" 2>&1 || true
status="$(docker inspect "$name" --format '{{.State.ExitCode}}')"
state="$(docker inspect "$name" --format '{{.State.Status}}')"
if [[ "$state" != exited ]]; then
  echo "Container did not complete (state=$state); infrastructure failure" >>"$output/validation.log"
  status=2
fi
# Preserve this fresh trusted-oracle output and inspection records, including
# partial results on failure. Candidate execution never uses these mounts.
docker inspect "$name" >"$output/container-inspect.json"
docker image inspect "$image" >"$output/image-inspect.json"
cat "$output/validation.log"
exit "$status"
