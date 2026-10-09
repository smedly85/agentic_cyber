#!/usr/bin/env bash
set -euo pipefail
ROOT="$(pwd)"
BASE="$ROOT/build/rupta-v1"
export RUSTUP_HOME="$BASE/rustup"
export CARGO_HOME="$BASE/cargo"
export CARGO_TARGET_DIR="$BASE/target"
mkdir -p "$BASE/logs" "$CARGO_HOME"
exec > >(tee "$BASE/logs/setup.log") 2>&1
date -u
git -C "$BASE/upstream" rev-parse HEAD
curl --fail --location --retry 2 https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init -o "$BASE/rustup-init"
curl --fail --location --retry 2 https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init.sha256 -o "$BASE/rustup-init.sha256"
(cd "$BASE" && sha256sum -c rustup-init.sha256)
chmod +x "$BASE/rustup-init"
"$BASE/rustup-init" -y --no-modify-path --default-toolchain none --profile minimal
export PATH="$CARGO_HOME/bin:$PATH"
rustup toolchain install nightly-2024-02-03 --profile minimal --component rust-src,rustc-dev,llvm-tools-preview,rustfmt-preview,clippy-preview
rustc +nightly-2024-02-03 -vV
cargo +nightly-2024-02-03 -V
cd "$BASE/upstream"
timeout 1200 cargo +nightly-2024-02-03 build --locked -j 4
sha256sum "$BASE/target/debug/pta" "$BASE/target/debug/cargo-pta"
