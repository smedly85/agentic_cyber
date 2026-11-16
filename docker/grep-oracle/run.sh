#!/usr/bin/env bash
# Trusted GNU grep corpus validation only. No generated candidate is admitted.
set -euo pipefail
image="${1:?usage: run.sh IMMUTABLE_IMAGE NEW_OUTPUT_DIRECTORY [linux/amd64]}"
output="${2:?new output directory required}"
target="${3:-linux/amd64}"
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ || "$image" =~ @sha256:[a-f0-9]{64}$ ]] || {
  echo 'immutable image ID or repository digest required' >&2; exit 2;
}
case "$target" in linux/amd64) arch=x86_64;; *)
  echo 'only the locked linux/amd64 grep oracle is supported' >&2; exit 2;;
esac
[[ ! -e "$output" ]] || { echo 'refusing existing output directory' >&2; exit 2; }
image_id="$image"
if [[ "$image" == *@* ]]; then
  image_id="$(docker image inspect --platform "$target" --format '{{.Id}}' "$image")"
fi
repo="$(cd "$(dirname "$0")/../.." && pwd)"
staging="$(mktemp -d)"
chmod 755 "$staging"
name="grep-oracle-${staging##*/}"
loader="$name-loader"
inputs="$name-inputs"
results="$name-results"
cleanup() {
  docker rm -fv "$name" "$loader" >/dev/null 2>&1 || true
  docker volume rm "$inputs" "$results" >/dev/null 2>&1 || true
  rm -rf -- "$staging"
}
trap cleanup EXIT
mkdir "$staging/tests"
cp -R "$repo/scripts" "$repo/experiments" "$repo/prompts" "$staging/"
mkdir "$staging/docker"
cp -R "$repo/docker/grep-oracle" "$staging/docker/"
cp -R "$repo/tests/reference_generators" "$staging/tests/"
cp -R "$repo/tests/c-grep-test-suite" "$staging/tests/"
docker volume create "$inputs" >/dev/null
docker volume create "$results" >/dev/null
docker create --pull never --name "$loader" --platform "$target" --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --mount "type=volume,source=$inputs,target=/work" "$image" true >/dev/null
docker cp "$staging/." "$loader:/work"
docker create --pull never --name "$name" --platform "$target" --network none \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --cpus 2 --memory 2g --pids-limit 128 --ulimit cpu=900:900 \
  --ulimit fsize=268435456:268435456 --ulimit nofile=256:256 \
  --tmpfs /tmp:rw,nosuid,nodev,size=1g --tmpfs /home/benchmark:rw,nosuid,nodev,size=16m \
  --mount "type=volume,source=$inputs,target=/work,readonly" \
  --mount "type=volume,source=$results,target=/output" \
  -e BENCHMARK_ARCH="$arch" -e BENCHMARK_IMAGE_ID="$image_id" \
  "$image" bash -c 'umask 022; timeout --signal=KILL 1800 python3 scripts/linux_benchmark.py validate --utility c-grep --output /output/validated' >/dev/null
mkdir -p "$output"
docker start -a "$name" >"$output/validation.log" 2>&1 || true
status="$(docker inspect "$name" --format '{{.State.ExitCode}}')"
docker inspect "$name" >"$output/container-inspect.json"
docker image inspect "$image" >"$output/image-inspect.json"
docker cp "$name:/output/." "$output/" || status=2
cat "$output/validation.log"
exit "$status"
