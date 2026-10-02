"""Controlled Rust LLVM/SVF compatibility experiment, never historical measurement."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from semantic_gate import HERE, ROOT, verify_frozen
from semantic_validation_checks import audit_case, debug_inventory

CASES = [
    ("direct", "target", 2), ("recursion", "target", 2),
    ("function_pointer", "target", 2), ("multi_target", "target", 2),
    ("struct_pointer", "target", 2), ("closure", "target", 2),
    ("generic", "target", 2), ("static_trait", "target", 3),
    ("dynamic_trait", "target", 3), ("cross_crate_direct", "cross_target", 2),
    ("cross_crate_indirect", "cross_target", 2),
    ("duplicate_names", "target", 2), ("multiple_instances", "generic", 1),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(command, directory, records):
    try:
        result = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True,
                                text=True, timeout=180)
        row = {"command": list(map(str, command)), "returncode": result.returncode,
               "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired as error:
        row = {"command": list(map(str, command)), "returncode": None,
               "stdout": str(error.stdout or ""), "stderr": str(error.stderr or ""),
               "failure": "timeout"}
    records.append(row)
    write(directory / "commands.json", records)
    return row


def main():
    frozen = verify_frozen()  # No subprocess or filesystem mutation precedes this.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/historical-rust/semantic/validation")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefix = ROOT / "build/historical-rust/semantic/toolchain/bin"
    rustc, cargo = prefix / "rustc", prefix / "cargo"
    llvm = Path("/usr/lib/llvm-21/bin")
    helper = ROOT / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf"
    commands = []
    validation = {"schema_version": 1, "frozen_inputs": frozen, "status": "failed",
                  "population_measurement_permitted": False,
                  "cases": [{"case": name, "configured_entry": "entry_" + name,
                             "target_source_name": target, "expected_depth": depth,
                             "measured_depth": None, "status": "not_run"}
                            for name, target, depth in CASES]}
    fixtures = ROOT / "tests/fixtures/rust_semantic"
    validation["fixture_sha256"] = {p.name: sha(p) for p in sorted(fixtures.glob("*.rs"))}
    # An interrupted rerun must not leave a previous successful attestation.
    write(out / "semantic_validation.json", validation)
    validation["environment"] = {key: os.environ.get(key) for key in
                                 ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER")}
    validation["toolchain"] = {
        "rustc": run([rustc, "-vV"], out, commands),
        "cargo": run([cargo, "--version"], out, commands),
        "llvm": run([llvm / "llvm-dis", "--version"], out, commands),
        "svf_revision": run(["git", "-C", ROOT / "build/semantic-toolchain/SVF",
                             "rev-parse", "HEAD"], out, commands),
        "helper_sha256": sha(helper), "options": ["-stat=false", "-ff-eq-base"],
        "target": "x86_64-unknown-linux-gnu",
    }
    # Explicit LLVM output; no Cargo defaults, LTO, post-optimization extraction,
    # or workspace-wide crate selection. std/runtime remains an external boundary.
    flags = ["--edition=2021", "--crate-type=rlib", "--target=x86_64-unknown-linux-gnu",
             "-C", "opt-level=0", "-C", "debuginfo=2", "-C", "codegen-units=1",
             "-C", "panic=abort", "-C", "embed-bitcode=yes",
             "--remap-path-prefix", str(ROOT) + "=."]
    validation["rustc_flags"] = flags
    steps = [
        [rustc, fixtures / "dependency.rs", "--crate-name=semantic_dependency", *flags,
         "--emit=llvm-bc,link", "--out-dir", out],
        [rustc, fixtures / "instrument.rs", "--crate-name=semantic_instrument", *flags,
         "--extern", "semantic_dependency=" + str(out / "libsemantic_dependency.rlib"),
         "--emit=llvm-bc", "--out-dir", out],
        [llvm / "llvm-link", out / "semantic_dependency.bc", out / "semantic_instrument.bc",
         "-o", out / "linked.bc"],
        [llvm / "llvm-dis", out / "linked.bc", "-o", out / "linked.ll"],
        [llvm / "opt", "-passes=verify", "-disable-output", out / "linked.bc"],
        [helper, "-stat=false", "-ff-eq-base", out / "linked.bc"],
    ]
    for step, command in enumerate(steps):
        result = run(command, out, commands)
        if result["returncode"] != 0:
            validation["failure"] = {"stage": ["dependency_compile", "instrument_compile",
                "llvm_link", "llvm_disassemble", "llvm_verify", "svf"][step], **result}
            validation["cases"] = [{**case, "status": "blocked_by_backend_failure"}
                                   for case in validation["cases"]]
            break
    else:
        raw = json.loads(result["stdout"])
        inventory = debug_inventory((out / "linked.ll").read_text())
        if set(inventory) != {f["llvm_symbol"] for f in raw["functions"]}:
            raise ValueError("SVF helper dropped LLVM function definitions")
        symbols = [f["llvm_symbol"] for f in raw["functions"]]
        demangle = run(["c++filt", "-s", "rust", *symbols], out, commands)
        if demangle["returncode"] != 0 or len(demangle["stdout"].splitlines()) != len(symbols):
            raise ValueError("Rust symbol demangling unavailable")
        validation["toolchain"]["demangler"] = run(["c++filt", "--version"], out, commands)
        for f, demangled in zip(raw["functions"], demangle["stdout"].splitlines()):
            f["demangled_symbol"] = demangled
            f["debug_metadata"] = inventory[f["llvm_symbol"]]
            if f["source_file"] != f["debug_metadata"]["source_file"] or f["definition"]["line"] != f["debug_metadata"]["line"]:
                raise ValueError("SVF/debug provenance mismatch")
        validation["definition_inventory_complete"] = True
        validation["semantic_graph"] = raw
        write(out / "raw_graph.json", raw)
        sys.path.insert(0, str(ROOT))
        from security.semantic_callgraph.backend import finalize_semantic_graph
        for case in validation["cases"]:
            graph = finalize_semantic_graph(raw, entry_point=case["configured_entry"])
            write(out / (case["case"] + ".json"), graph)
            matches = [f for f in graph["functions"] if
                       f["name"].split("<")[0] == case["target_source_name"]]
            depths = [f["raw_call_depth"] for f in matches if f["raw_call_depth"] is not None]
            case["target_instances"] = matches
            case["measured_depth"] = min(depths) if depths else None
            audit_case(case, graph)
        failed = [case["case"] for case in validation["cases"] if case["status"] != "passed"]
        validation["failure"] = {"stage": "controlled_semantic_validation", "failed_cases": failed,
            "reason": "Required Rust dispatch validation failed; no historical measurement permitted."}
        # Passing this controlled experiment would still require separate historical
        # scope/identity and pilot gates. This script never runs those stages.
        if not failed:
            validation["status"] = "passed"
            validation["failure"] = None
    validation["artifacts"] = {p.name: sha(p) for p in sorted(out.iterdir())
                               if p.is_file() and p.name != "semantic_validation.json"}
    write(out / "semantic_validation.json", validation)
    print(json.dumps({"status": validation["status"], "failure": validation.get("failure"),
                      "output": str(out)}, indent=2))
    return 1 if validation["status"] != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
