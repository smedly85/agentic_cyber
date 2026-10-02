"""Expanded controlled-only Rust audit. Never loads historical source specimens."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "security/historical/rust"))
from semantic_gate import verify_frozen
from security.semantic_callgraph.backend import finalize_semantic_graph, validate_definition_inventory
from security.semantic_callgraph.rust_identity import source_key, group_instances, declaration_line, configure_entry, verify_mechanical_body

HERE = Path(__file__).resolve().parent
CACHE = ROOT / "build/rust-instrument-v2/rust"
RUSTC = ROOT / "build/historical-rust/semantic/toolchain/bin/rustc"
LLVM = Path("/usr/lib/llvm-21/bin")
HELPER = ROOT / "build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf"
FIXTURES = ROOT / "tests/fixtures/rust_semantic"
EXPANDED = ["nonfirst_reference", "static_table", "trait_drop", "trait_one", "trait_many",
    "box_trait", "dyn_fn", "box_fnmut", "option_map", "result_or_else", "iterator_flat_map",
    "entry_wrappers", "unwind", "crates_io", "static_and_dyn", "platform", "stack_bytes", "same_method"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def command(argv, directory):
    try:
        p = subprocess.run(list(map(str, argv)), cwd=ROOT, capture_output=True, text=True, timeout=180)
        row = {"argv": list(map(str, argv)), "exit": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except subprocess.TimeoutExpired:
        row = {"argv": list(map(str, argv)), "exit": None, "stdout": "", "stderr": "timeout after 180 seconds"}
    log = directory / "commands.jsonl"
    with log.open("a") as stream:
        stream.write(json.dumps(row) + "\n")
    if row["exit"] != 0:
        raise RuntimeError(json.dumps(row))
    return row["stdout"]


def names(rows):
    return {source_key(f)[-1] for f in rows if f.get("language") == "Rust" and f.get("source_mapping_eligible")}


def selected(raw, file, name, line=None):
    # File, line, crate and complete scope are retained for every candidate.
    groups = [(key, rows) for key, rows in group_instances(raw["functions"]).items()
              if key[1] == file and key[4] == name and (line is None or key[3] == line)]
    if len(groups) != 1:
        raise ValueError("source_identity_ambiguous: " + repr([key for key, _ in groups]))
    return groups[0][1]


def analyze(directory):
    ir = command([LLVM / "llvm-dis", directory / "linked.bc", "-o", "-"], directory)
    (directory / "linked.ll").write_text(ir)
    command([LLVM / "opt", "-passes=verify", "-disable-output", directory / "linked.bc"], directory)
    raw = json.loads(command([HELPER, "-stat=false", "-ff-eq-base", directory / "linked.bc"], directory))
    inventory = validate_definition_inventory(ir, raw)
    write(directory / "raw.json", raw)
    return raw, ir, inventory


def indirect_report(graph, expected_by_owner):
    by_id = {f["identity"]: f for f in graph["functions"]}
    sites = {}
    for e in graph["call_edges"]:
        if e["edge_type"] == "indirect_resolved":
            key = (e["caller"], json.dumps(e["callsite"], sort_keys=True))
            sites[key] = {"caller": e["caller"], "callsite": e["callsite"], "actual_targets": e["indirect_target_set"]}
    for u in graph["unresolved_indirect_callsites"]:
        sites[(u["caller"], json.dumps(u["callsite"], sort_keys=True))] = {
            "caller": u["caller"], "callsite": u["callsite"], "actual_targets": []}
    for row in sites.values():
        owner = by_id[row["caller"]]
        expected = expected_by_owner.get(owner["identity"])
        row["expected_targets"] = sorted(expected) if expected is not None else None
        row["unexpected_targets"] = sorted(set(row["actual_targets"]) - expected) if expected is not None else None
        row["missing_targets"] = sorted(expected - set(row["actual_targets"])) if expected is not None else None
        row["verdict"] = "not_adjudicated_runtime_site" if expected is None else (
            "exact" if set(row["actual_targets"]) == expected else "target_set_mismatch")
    return sorted(sites.values(), key=lambda r: (r["caller"], json.dumps(r["callsite"], sort_keys=True)))


def evaluate(raw, ir, case, source, entry_name, target_name="target", expected_depth=None):
    file = source.relative_to(ROOT).as_posix()
    entry_line = declaration_line(source.read_text(), entry_name)
    entry = selected(raw, file, entry_name, entry_line)
    if len(entry) != 1:
        raise ValueError("configured entry instance ambiguous")
    graph = finalize_semantic_graph(raw, entry_point=entry[0]["identity"])
    write(CACHE / case / "graph.json", graph)
    targets = selected(raw, "tests/fixtures/rust_semantic/dependency.rs" if target_name == "cross_target" else file, target_name)
    by_id = {f["identity"]: f for f in graph["functions"]}
    targets = [by_id[f["identity"]] for f in targets]
    depths = [f["raw_call_depth"] for f in targets if f["raw_call_depth"] is not None]
    checks = {"target_defined": bool(targets), "target_reachable": bool(depths)}
    path_middles = {"direct": ["a"], "recursion": ["recurse"], "function_pointer": ["invoke"],
        "multi_target": ["invoke"], "struct_pointer": ["invoke_holder"], "closure": ["{closure#0}"],
        "generic": ["generic"], "static_trait": ["static_dispatch", "operation"],
        "dynamic_trait": ["dynamic_dispatch", "operation"], "cross_crate_direct": ["cross_direct"],
        "cross_crate_indirect": ["cross_indirect"], "duplicate_names": ["duplicate"], "multiple_instances": [],
        "option_map": ["option_path", "map", "{closure#0}"],
        "result_or_else": ["result_path", "or_else", "{closure#0}"]}
    if case in path_middles:
        expected_names = [entry_name, *path_middles[case], target_name]
        checks["expected_source_path"] = any(
            [source_key(by_id[i])[-1] for i in f["shortest_call_path"]["function_identities"] or []] == expected_names
            for f in targets)
    if expected_depth is not None:
        checks["expected_depth"] = bool(depths) and min(depths) == expected_depth
    for f in graph["functions"]:
        if f["raw_call_depth"] is not None:
            path = f["shortest_call_path"]["edges"]
            if len(path) != f["raw_call_depth"] or any(e not in graph["call_edges"] for e in path):
                raise ValueError("invalid semantic path")
    expected = {}
    target_ids = {f["identity"] for f in targets}
    def owners(name):
        return [f for f in graph["functions"] if f.get("language") == "Rust" and f.get("source_mapping_eligible")
                and source_key(f)[-1] == name and f["source_file"] == file]
    owner_name = {"nonfirst_reference": "by_reference", "stack_bytes": "by_reference", "static_table": "static_table",
                  "struct_pointer": "invoke_holder", "cross_crate_indirect": "cross_indirect"}.get(case)
    if owner_name:
        found = owners(owner_name) if case != "cross_crate_indirect" else selected(raw, "tests/fixtures/rust_semantic/dependency.rs", owner_name)
        checks["indirect_owner_present"] = bool(found)
        expected.update({f["identity"]: target_ids for f in found})
    if case in {"function_pointer", "multi_target"}:
        expected.update({f["identity"]: target_ids | {v["identity"] for v in selected(raw, file, "alternate")} for f in owners("invoke")})
    if case in {"trait_drop", "trait_one", "trait_many", "static_and_dyn", "box_trait", "dynamic_trait"}:
        method = "multiple" if case == "trait_many" else "operation"
        implementations = owners(method)
        # Each expanded binary has only First; the original controlled library has both.
        desired = {f["identity"] for f in implementations}
        dispatch = {"trait_many": "dyn_many", "box_trait": "boxed", "dynamic_trait": "dynamic_dispatch"}.get(case, "dyn_one")
        expected.update({f["identity"]: desired for f in owners(dispatch)})
        checks["method_definitions_present"] = bool(desired)
    if case in {"dyn_fn", "box_fnmut"}:
        closures = owners("{closure#0}")
        checks["closure_definition_present"] = bool(closures)
        dispatchers = owners("dyn_fn") if case == "dyn_fn" else [
            f for f in graph["functions"] if f.get("language") == "Rust"
            and f.get("source_mapping_eligible") and source_key(f)[-1] == "call_mut"
            and f["source_file"] == "rust_std/alloc/src/boxed.rs"]
        checks["dispatch_definition_present"] = bool(dispatchers)
        expected.update({f["identity"]: {c["identity"] for c in closures} for f in dispatchers})
    sites = indirect_report(graph, expected)
    if expected:
        checks["expected_indirect_sites_present"] = set(expected) <= {s["caller"] for s in sites}
        checks["exact_target_sets"] = all(s["verdict"] == "exact" for s in sites if s["caller"] in expected)
    if case in {"option_map", "result_or_else", "iterator_flat_map"}:
        wanted = {"option_map": "map", "result_or_else": "or_else", "iterator_flat_map": "flat_map"}[case]
        compiled = [f for f in graph["functions"] if f.get("definition_kind") == "compiled_rust_runtime"]
        checks["compiled_std_node_present"] = wanted in names(compiled)
        paths = [edge for f in targets for edge in f["shortest_call_path"]["edges"] or []]
        checks["std_node_on_target_path"] = any(by_id[e["caller"]].get("definition_kind") == "compiled_rust_runtime" for e in paths)
    if case == "unwind":
        checks["invoke_and_landingpad"] = " invoke " in ir and "landingpad" in ir
    if case == "crates_io":
        checks["dependency_node_on_path"] = any(
            by_id[e["caller"]].get("debug_scope_chain", [None])[0] == "scopeguard"
            for f in targets for e in f["shortest_call_path"]["edges"] or [])
    if case == "same_method":
        methods = owners("operation")
        checks["distinct_impl_source_keys"] = len({source_key(f) for f in methods}) == 2
    if case == "stack_bytes":
        checks["byte_array_storage_exercised"] = "alloca [16 x i8]" in ir
    if case == "platform":
        checks["linux_cfg_branch_selected"] = bool(depths) and not any(
            f["reachable_from_entry"] for f in owners("third"))
    if case == "duplicate_names":
        checks["distinct_debug_module_keys"] = len({source_key(f) for f in owners("duplicate")}) == 2
    if case == "multiple_instances":
        checks["two_legitimate_instances"] = len(targets) == 2 and len({source_key(f) for f in targets}) == 1
    extra = {}
    if case == "entry_wrappers":
        declarations = [n for n, line in enumerate(source.read_text().splitlines(), 1) if "fn uumain(" in line]
        authored = selected(raw, file, "uumain", declarations[1])
        outer = selected(raw, file, "uumain", declarations[0])
        startup = selected(raw, file, "startup")
        extra["wrapper_body_evidence"] = [
            verify_mechanical_body(ir, startup[0]["llvm_symbol"], outer[0]["llvm_symbol"]),
            verify_mechanical_body(ir, outer[0]["llvm_symbol"], authored[0]["llvm_symbol"])]
        extra["entry_provenance"] = configure_entry(graph, authored, startup[0]["identity"],
            {startup[0]["identity"], outer[0]["identity"]})
        checks["two_synthetic_startup_edges"] = extra["entry_provenance"]["excluded_startup_edges"] == 2
    return {"case": case, "status": "passed" if all(checks.values()) else "failed", "checks": checks,
            "target_instances": targets, "indirect_sites": sites, "minimum_depth": min(depths) if depths else None,
            "configured_entry": entry[0]["identity"], **extra}


def main():
    frozen = verify_frozen()
    CACHE.mkdir(parents=True, exist_ok=True)
    flags = ["-C", "opt-level=0", "-C", "debuginfo=2", "-C", "codegen-units=1", "-C", "embed-bitcode=yes",
             "--target=x86_64-unknown-linux-gnu", "--remap-path-prefix", str(ROOT) + "=."]
    acquisition = ROOT / "build/rust-instrument-v2/acquisition/scopeguard-1.2.0/src/lib.rs"
    command([RUSTC, acquisition, "--crate-name=scopeguard", "--crate-type=rlib", "--edition=2015", '--cfg=feature="use_std"',
             *flags, "--emit=llvm-bc,link", "--out-dir", CACHE], CACHE)
    # The original 13 expectations stay intact, with debug-qualified selection.
    from validate_semantic_instrument import CASES
    rows = []
    for case, target, depth in list(CASES) + [(name, "target", None) for name in EXPANDED]:
        directory = CACHE / case
        directory.mkdir(exist_ok=True)
        try:
            if "--reaudit" in sys.argv:
                source = FIXTURES / ("expanded.rs" if case in EXPANDED else "instrument.rs")
                entry = "main" if case in EXPANDED else "entry_" + case
                raw = json.loads((directory / "raw.json").read_text())
                ir = (directory / "linked.ll").read_text()
                inventory = validate_definition_inventory(ir, raw)
                row = evaluate(raw, ir, case, source, entry, target, depth)
                row["inventory"] = inventory
                row["bitcode_sha256"] = digest(directory / "linked.bc")
                rows.append(row)
                print(case, row["status"], flush=True)
                continue
            elif case in EXPANDED:
                source = FIXTURES / "expanded.rs"
                command([RUSTC, source, "--crate-name=expanded", "--edition=2021", *flags, "-A", "dead_code",
                         "-C", "panic=unwind", '--cfg=audit_case="' + case + '"', "--extern",
                         "scopeguard=" + str(CACHE / "libscopeguard.rlib"), "--emit=llvm-bc", "-o", directory / "case.bc"], directory)
                command([LLVM / "llvm-link", directory / "case.bc", CACHE / "scopeguard.bc", "-o", directory / "linked.bc"], directory)
                entry = "main"
            else:
                source = FIXTURES / "instrument.rs"
                command([RUSTC, FIXTURES / "dependency.rs", "--crate-name=semantic_dependency", "--crate-type=rlib", "--edition=2021",
                         *flags, "-C", "panic=abort", "--emit=llvm-bc,link", "--out-dir", directory], directory)
                command([RUSTC, source, "--crate-name=semantic_instrument", "--crate-type=rlib", "--edition=2021", *flags,
                         "-C", "panic=abort", "--extern", "semantic_dependency=" + str(directory / "libsemantic_dependency.rlib"),
                         "--emit=llvm-bc", "--out-dir", directory], directory)
                command([LLVM / "llvm-link", directory / "semantic_instrument.bc", directory / "semantic_dependency.bc", "-o", directory / "linked.bc"], directory)
                entry = "entry_" + case
            raw, ir, inventory = analyze(directory)
            row = evaluate(raw, ir, case, source, entry, target, depth)
            row["inventory"] = inventory
            row["bitcode_sha256"] = digest(directory / "linked.bc")
        except (RuntimeError, ValueError, KeyError) as error:
            row = {"case": case, "status": "analysis_failure", "error": str(error)}
        rows.append(row)
        print(case, row["status"], flush=True)
        write(CACHE / "results.json", {"frozen_inputs": frozen, "cases": rows,
              "historical_rust_measurement": False, "status": "STOP"})
    write(CACHE / "results.json", {"frozen_inputs": frozen, "cases": rows,
          "historical_rust_measurement": False, "status": "STOP"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
