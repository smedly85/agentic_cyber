# Shared by the controller entry points; source in the controller shell so
# stage runners, validation and boundary recompilation inherit the same PATH.
rust_toolchain_preflight() {
    local compiler
    compiler="$(type -P rustc || true)"
    if [[ -z "$compiler" && -n "${HOME:-}" && -x "$HOME/.cargo/bin/rustc" ]]; then
        export PATH="$HOME/.cargo/bin:$PATH"
        compiler="$(type -P rustc || true)"
    fi
    if [[ -z "$compiler" || ! -x "$compiler" ]]; then
        printf 'infrastructure_error: rust_toolchain_unavailable: executable rustc not found in PATH or HOME/.cargo/bin\n' >&2
        return 1
    fi
    # Make PATH resolution stable when validation changes its working directory.
    compiler="$(cd "$(dirname "$compiler")" && pwd -P)/$(basename "$compiler")" || return 1
    export PATH="$(dirname "$compiler"):$PATH"
    RUST_TOOLCHAIN_JSON="$("$PYTHON_BIN" "$REPO/scripts/rust_toolchain.py" "$compiler")" || return 1
}
