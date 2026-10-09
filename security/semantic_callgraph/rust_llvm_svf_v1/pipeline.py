"""Rust source -> rustc (MIR -> LLVM IR) -> bitcode -> SVF AndersenWaveDiff graph.

Version 1 of the Rust LLVM/SVF experiment.  rustc lowers MIR to LLVM IR with
its ordinary LLVM backend (``--emit=llvm-bc``); nothing exports or translates
MIR by hand.  Crate bitcode is linked with the matching ``llvm-link`` and
verified with ``opt``.  Call edges come only from the structured SVF helper
that the C study uses (``native/semantic_callgraph_svf.cpp``), and BFS
distances come from ``backend.finalize_semantic_graph`` unchanged.  No MIR,
Tree-sitter, regex or signature-derived edge is ever added.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from security.semantic_callgraph.backend import (
    SVF_HELPER_OPTIONS,
    SemanticCallgraphError,
    finalize_semantic_graph,
    validate_definition_inventory,
)
from security.semantic_callgraph.rust_identity import strip_generic_arguments

ROOT = Path(__file__).resolve().parents[3]
TOOLCHAIN = ROOT / "build/rust-mir/toolchain"
RUSTC = TOOLCHAIN / "bin/rustc"
RUST_SRC = TOOLCHAIN / "lib/rustlib/src/rust"
LLVM_BIN = Path("/usr/lib/llvm-21/bin")
CLANG = LLVM_BIN / "clang"
TARGET = "x86_64-unknown-linux-gnu"
CANONICAL_HELPER = ROOT / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf"
SENSITIVITY_HELPER = ROOT / "build/rust-llvm-svf-v1/svf-sensitivity/SVF/Release-build/bin/semantic-callgraph-svf"


def _variant(name: str) -> Path:
    return ROOT / f"build/rust-llvm-svf-v1/{name}/SVF/Release-build/bin/semantic-callgraph-svf"


# Only P is the C study's instrument.  Every other configuration is a
# sensitivity or single-cause diagnostic and cannot authorize historical use
# (see ACCEPTANCE_CRITERIA.md and AMENDMENTS.md A-3).
CONFIGURATIONS: dict[str, dict[str, Any]] = {
    "P": {"helper": CANONICAL_HELPER, "options": tuple(SVF_HELPER_OPTIONS),
          "role": "primary: the C study's helper binary and options, unchanged"},
    "P-noffeq": {"helper": CANONICAL_HELPER, "options": ("-stat=false",),
                 "role": "sensitivity: canonical helper without first-field/base equivalence"},
    "S": {"helper": SENSITIVITY_HELPER, "options": tuple(SVF_HELPER_OPTIONS),
          "role": "sensitivity: SVF 67efb774 + byte-offset and Rust vcall-gate patches"},
    "S-noffeq": {"helper": SENSITIVITY_HELPER, "options": ("-stat=false",),
                 "role": "sensitivity: patched SVF without first-field/base equivalence"},
    "S-bo": {"helper": _variant("svf-byte-offset-only"), "options": tuple(SVF_HELPER_OPTIONS),
             "role": "diagnostic: byte-offset patch alone (cause attribution)"},
    "S-vg": {"helper": _variant("svf-vcall-gate-only"), "options": tuple(SVF_HELPER_OPTIONS),
             "role": "diagnostic: Rust vcall-gate patch alone (cause attribution)"},
    "S3": {"helper": _variant("svf-sensitivity-3"), "options": tuple(SVF_HELPER_OPTIONS),
           "role": "sensitivity: byte-offset + vcall-gate + allockind heap-allocator patches"},
}

# Mirrors Cargo's dev profile (the profile the frozen historical builds used),
# except codegen-units=1 so each crate yields one module.  opt-level=0 keeps
# rustc's MIR inliner and LLVM's inliner off (only #[inline(always)] bodies are
# folded by LLVM's always-inliner), so source-level call boundaries survive.
# No LTO: it would merge and inline across crates before SVF sees the IR.
RUSTC_CODEGEN = (
    f"--target={TARGET}",
    "-C", "opt-level=0",
    "-C", "debuginfo=2",
    "-C", "codegen-units=1",
    "-C", "panic=unwind",
)


def remap_flags() -> tuple[str, ...]:
    # rustc applies the last matching prefix, so the more specific std-source
    # remap (which lies under ROOT) must come second.  Identities therefore
    # read tests/... for repository sources and rust_std/library/... for the
    # compiled std/core/alloc generic bodies that rustc monomorphizes here.
    return (f"--remap-path-prefix={ROOT}=.", f"--remap-path-prefix={RUST_SRC}=rust_std")


class PipelineError(RuntimeError):
    """A compilation, link, verification or analysis stage failed."""


@dataclass(frozen=True)
class Crate:
    name: str
    source: str
    crate_type: str
    edition: str
    externs: tuple[str, ...] = ()
    cfg: tuple[str, ...] = ()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scientific(argv: Iterable[Any], out: Path) -> list[str]:
    """Tokenize machine-specific prefixes so recorded commands are portable."""
    rows = []
    for item in map(str, argv):
        rows.append(item.replace(str(out), "$OUTPUT").replace(str(ROOT), "$REPO"))
    return rows


def run(argv: Sequence[Any], *, cwd: Path, log: list[dict[str, Any]], out: Path, stage: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(list(map(str, argv)), cwd=cwd, text=True, capture_output=True, check=False)
    log.append({"stage": stage, "argv": scientific(argv, out), "returncode": result.returncode})
    if result.returncode != 0:
        raise PipelineError(f"{stage} failed ({result.returncode}): {result.stderr[-2000:]}")
    return result


def compile_crates(crates: Sequence[Crate], out: Path, log: list[dict[str, Any]]) -> list[Path]:
    """Compile each crate to LLVM bitcode in dependency order; return modules."""
    modules: list[Path] = []
    for crate in crates:
        directory = out / "crates" / crate.name
        directory.mkdir(parents=True, exist_ok=False)
        emit = "--emit=llvm-bc,link" if crate.crate_type == "rlib" else "--emit=llvm-bc"
        argv: list[Any] = [
            RUSTC, ROOT / crate.source, f"--crate-name={crate.name}", f"--crate-type={crate.crate_type}",
            f"--edition={crate.edition}", *RUSTC_CODEGEN, *remap_flags(), emit, "--out-dir", directory,
        ]
        for value in crate.cfg:
            argv += ["--cfg", value]
        for dependency in crate.externs:
            dep_dir = out / "crates" / dependency
            argv += ["-L", f"dependency={dep_dir}", "--extern", f"{dependency}={dep_dir / f'lib{dependency}.rlib'}"]
        # rustc records its working directory as the codegen unit's DWARF
        # compilation directory.  Compiling from ROOT (remapped to ".") keeps
        # the bitcode byte-identical regardless of the output directory.
        run(argv, cwd=ROOT, log=log, out=out, stage=f"rustc:{crate.name}")
        produced = sorted(directory.glob("*.bc"))
        if len(produced) != 1:
            raise PipelineError(f"expected one bitcode module for {crate.name}, found {produced}")
        modules.append(produced[0])
    return modules


def link_and_verify(modules: Sequence[Path], out: Path, log: list[dict[str, Any]]) -> tuple[Path, Path]:
    linked = out / "linked.bc"
    run([LLVM_BIN / "llvm-link", *modules, "-o", linked], cwd=out, log=log, out=out, stage="llvm-link")
    run([LLVM_BIN / "opt", "-passes=verify", "-disable-output", linked], cwd=out, log=log, out=out, stage="opt-verify")
    text = out / "linked.ll"
    run([LLVM_BIN / "llvm-dis", linked, "-o", text], cwd=out, log=log, out=out, stage="llvm-dis")
    return linked, text


DEFINE_RE = re.compile(r'^define [^@]*@(?:"((?:[^"\\]|\\.)+)"|([^ (]+))\(')


def definition_inventory(ir_text: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Account for every LLVM definition: exported by the helper or not, and why.

    Uses ``backend.validate_definition_inventory`` for the debug-carrying
    definitions (it raises if any is dropped) and lists the remainder
    explicitly.  This inspects symbols only; it never creates an edge.
    """
    defined: dict[str, bool] = {}
    for line in ir_text.splitlines():
        match = DEFINE_RE.match(line)
        if match:
            symbol = re.sub(r"\\([0-9A-Fa-f]{2})", lambda m: chr(int(m[1], 16)), match.group(1) or match.group(2))
            defined[symbol] = "!dbg !" in line
    exported = {row["llvm_symbol"] for row in raw.get("functions", [])}
    try:
        debug = validate_definition_inventory(ir_text, raw)
        debug_status = "all_debug_definitions_exported"
    except SemanticCallgraphError as error:
        debug = {"error": str(error)}
        debug_status = "debug_definitions_dropped"
    without_debug = sorted(symbol for symbol, has in defined.items() if not has)
    return {
        "llvm_definitions": len(defined),
        "debug_definitions": sum(defined.values()),
        "helper_exported_functions": len(exported),
        "debug_inventory": debug,
        "debug_inventory_status": debug_status,
        "definitions_without_debug_info": without_debug,
        "definitions_without_debug_info_exported": sorted(set(without_debug) & exported),
        "exported_not_defined": sorted(exported - set(defined)),
    }


def run_helper(configuration: str, linked: Path, out: Path) -> tuple[dict[str, Any], list[str]]:
    config = CONFIGURATIONS[configuration]
    helper = Path(config["helper"])
    if not helper.is_file():
        raise PipelineError(f"helper for {configuration} is unavailable: {helper}")
    argv = [helper, *config["options"], linked]
    result = subprocess.run(list(map(str, argv)), cwd=out, text=True, capture_output=True, check=False)
    out.mkdir(parents=True, exist_ok=True)
    (out / "helper.stderr").write_text(result.stderr)
    if result.returncode != 0:
        raise PipelineError(f"SVF helper failed ({result.returncode}): {result.stderr[-2000:]}")
    (out / "raw.json").write_text(result.stdout)
    return json.loads(result.stdout), scientific(argv, out)


def finalize(raw: Mapping[str, Any], entry_identity: str, provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Shared deterministic BFS from the C pipeline; entry is a helper identity."""
    graph = finalize_semantic_graph(raw, entry_point=entry_identity, provenance=provenance)
    graph["analysis_backend"] = "rustc_llvm_svf"
    return graph


def strip_generics(name: str) -> str:
    """``uumain<expanded::Arguments>`` -> ``uumain``; closures are unchanged.

    Reuses the balanced-group stripper of ``rust_identity`` (it ignores the
    ``>`` of ``->`` inside ``fn(..) -> T`` arguments).  An unbalanced debug
    name is returned unchanged so it can never match a preregistered label.
    """
    try:
        return strip_generic_arguments(name)
    except ValueError:
        return name


def origin(row: Mapping[str, Any], application_files: set[str]) -> str:
    """Classify a helper function row for scope accounting (never for edges)."""
    source = str(row.get("source_file") or "")
    if source in application_files:
        return "application"
    if source.startswith("rust_std/"):
        return "rust_std_compiled_generic"
    if source.startswith("build/rust-mir/dependencies/") or "/registry/src/" in source:
        return "dependency"
    if source in ("", "<unknown>"):
        return "compiler_generated"
    return "other_repository_source"

