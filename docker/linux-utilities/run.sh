#!/usr/bin/env bash
# Trusted oracle validation only. No generated candidate is admitted here.
set -euo pipefail
image="${1:?usage: run.sh IMMUTABLE_IMAGE_REFERENCE NEW_OUTPUT_DIRECTORY [linux/arm64]}"
output="${2:?new output directory required}"
target="${3:-linux/arm64}"
component='[a-z0-9]+(([._]|__|-+)[a-z0-9]+)*'
host='[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?'
registry="($host(\.$host)*|\[[a-fA-F0-9:]+\])(:[0-9]+)?"
repository="($registry/)?$component(/$component)*(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ || "$image" =~ ^$repository@sha256:[a-f0-9]{64}$ ]] || {
  echo 'immutable image ID or repository SHA-256 digest required' >&2; exit 2;
}
case "$target" in linux/arm64) arch=aarch64;; linux/amd64) arch=x86_64;; *) exit 2;; esac
[[ ! -e "$output" ]] || { echo 'refusing existing output directory' >&2; exit 2; }
# The oracle's existing provenance contract takes a bare Docker ID. Keep the
# repository digest for execution; resolve its local platform ID for metadata.
image_id="$image"
if [[ "$image" == *@* ]]; then
  image_id="$(docker image inspect --platform "$target" --format '{{.Id}}' "$image")"
  [[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'invalid local image ID' >&2; exit 2; }
fi
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
docker create --pull never --name "$name" --platform "$target" --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --cpus 2 --memory 2g --pids-limit 128 --ulimit cpu=900:900 \
  --ulimit fsize=268435456:268435456 --ulimit nofile=256:256 \
  --tmpfs /tmp:rw,nosuid,nodev,size=1g --tmpfs /home/benchmark:rw,nosuid,nodev,size=16m \
  --mount "type=bind,source=$staging,target=/work,readonly" \
  --mount "type=bind,source=$output,target=/output" \
  -e BENCHMARK_ARCH="$arch" -e BENCHMARK_IMAGE_ID="$image_id" \
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
