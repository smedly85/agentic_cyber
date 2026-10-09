"""Summarize a validate.py run into committed evidence.

Writes validation_results.json (compact, machine-readable) and
VALIDATION_REPORT.md (generated tables) next to this file.  Full graphs, raw
helper output, bitcode and IR stay under build/ (ignored by git).

    PYTHONPATH=. python3 -m security.semantic_callgraph.rust_llvm_svf_v1.report \
        --results build/rust-llvm-svf-v1/validation/results.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from security.semantic_callgraph.rust_llvm_svf_v1 import pipeline as P

HERE = Path(__file__).resolve().parent
ROOT = P.ROOT
PRIMARY = "P"
STRICT_FAILURE_STATUSES = {"lowered_to_direct_call_exact"}


def read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def short(label: str) -> str:
    """Shorten helper identities for tables; labels are already short."""
    if "#llvm=" in label:
        label = label.split("#llvm=")[0] + "#…"
    return label.replace("rust_std/library/", "std:")


def cell(values: list[str]) -> str:
    return "<br>".join(short(v) for v in values) if values else "∅"


def summarize(results: dict[str, Any]) -> dict[str, Any]:
    rows = results["results"]
    configurations = results["configurations"]
    summary: dict[str, Any] = {}
    for configuration in configurations:
        programs = {k.split("|", 2)[2]: v for k, v in rows.items() if k.startswith(f"run-1|{configuration}|")}
        rust = {k: v for k, v in programs.items() if not k.endswith("/C")}
        c = {k: v for k, v in programs.items() if k.endswith("/C")}
        sites = [s for v in rust.values() for s in v.get("sites", [])]
        strict = Counter("passed" if s["strict_preregistered_passed"] else s["status"] for s in sites)
        amended = Counter("passed" if s["passed"] else s["status"] for s in sites)
        mandatory = [s for s in rows.get(f"run-1|{configuration}|instrument", {}).get("sites", []) if s.get("mandatory")]
        mandatory_case = [c_ for c_ in rows.get(f"run-1|{configuration}|instrument", {}).get("cases", []) if c_.get("mandatory")]
        summary[configuration] = {
            "rust_programs": len(rust),
            "rust_programs_passed": sum(v["status"] == "pass" for v in rust.values()),
            "rust_programs_failed": sorted(k for k, v in rust.items() if v["status"] != "pass"),
            "c_programs": len(c),
            "c_programs_passed": sum(v["status"] == "pass" for v in c.values()),
            "adjudicated_rust_sites": len(sites),
            "site_outcomes_amended": dict(sorted(amended.items())),
            "site_outcomes_strict_preregistered": dict(sorted(strict.items())),
            "mandatory_dynamic_dispatch": [{k: s[k] for k in ("id", "status", "expected", "actual", "missing", "unexpected")}
                                           for s in mandatory],
            "mandatory_dynamic_trait_case": [{"passed": c_["passed"], "failures": c_["failures"],
                                              "targets": [{k: t[k] for k in ("function", "expected_depth", "observed_depth", "status")}
                                                          for t in c_["targets"]]} for c_ in mandatory_case],
            "deterministic_two_runs": all(v for k, v in results["determinism"].items() if k.startswith(configuration + "|")),
        }
    return summary


def acceptance(results: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    primary = summary[PRIMARY]
    before, after = read(Path(results["_output"]) / "toolchain_before.json"), read(Path(results["_output"]) / "toolchain_after.json")
    rows = results["results"]
    primary_rows = {k.split("|", 2)[2]: v for k, v in rows.items() if k.startswith(f"run-1|{PRIMARY}|")}
    inventories = [v.get("inventory", {}).get("debug_inventory_status") for v in primary_rows.values()]
    criteria = {
        "A1_toolchain_identity_unchanged": before["canonical_svf"] == after["canonical_svf"] and before["rustc"] == after["rustc"],
        "A2_bitcode_and_identity_coverage": all(s == "all_debug_definitions_exported" for s in inventories)
                                            and not any("build_or_ir_unavailable" in v.get("failures", []) for v in primary_rows.values()),
        "A3_mandatory_trait_object_dispatch": all(s["status"] == "exact" for s in primary["mandatory_dynamic_dispatch"])
                                              and all(c["passed"] for c in primary["mandatory_dynamic_trait_case"]),
        "A4_A7_controlled_expectations": primary["rust_programs_passed"] == primary["rust_programs"],
        "A8_determinism": primary["deterministic_two_runs"],
        "A9_c_unchanged": all(v.get("identical") for v in results["c_regression"].values())
                          and primary["c_programs_passed"] == primary["c_programs"],
    }
    return {"criteria": criteria, "accepted_for_historical_measurement": all(criteria.values()),
            "decision": "ACCEPT" if all(criteria.values()) else "STOP — not accepted for historical depth measurement"}


def site_matrix(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = results["results"]
    table: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
    for key, value in rows.items():
        run, configuration, program = key.split("|", 2)
        if run != "run-1" or program.endswith("/C"):
            continue
        for site in value.get("sites", []):
            entry = table[(program, site["id"])]
            entry.setdefault("expected", site["expected"])
            entry[configuration] = {"status": site["status"], "actual": site["actual"],
                                    "missing": site["missing"], "unexpected": site["unexpected"]}
    return [{"program": p, "site": s, **v} for (p, s), v in sorted(table.items())]


def markdown(results: dict[str, Any], summary: dict[str, Any], decision: dict[str, Any]) -> str:
    configurations = results["configurations"]
    rows = results["results"]
    tool = read(Path(results["_output"]) / "toolchain_before.json")
    lines = ["# Controlled validation report — Rust LLVM/SVF backend v1", "",
             "Generated by `report.py` from `validate.py` output; do not edit by hand. "
             "Narrative interpretation is in `README.md`.", "",
             f"**Decision: {decision['decision']}.**", "",
             "| Criterion (configuration P) | Holds |", "|---|---|"]
    lines += [f"| {name} | {'yes' if ok else '**no**'} |" for name, ok in decision["criteria"].items()]
    lines += ["", "## Instruments", "",
              f"- rustc: `{tool['rustc'].splitlines()[0]}`; LLVM `{[l for l in tool['rustc'].splitlines() if l.startswith('LLVM')][0]}`",
              f"- clang: `{tool['clang']}`; canonical SVF commit `{tool['canonical_svf']['commit']}`",
              f"- rustc codegen flags: `{' '.join(tool['rustc_codegen_flags'])}`; remaps `{' '.join(tool['remap'])}`", "",
              "| Configuration | Helper SHA-256 | libSvfLLVM SHA-256 | Options | Role |", "|---|---|---|---|---|"]
    for name in configurations:
        config = tool["configurations"][name]
        hashes = tool["configuration_instruments"][name]
        lines.append(f"| `{name}` | `{(hashes['semantic-callgraph-svf'] or 'missing')[:16]}…` | "
                     f"`{(hashes['libSvfLLVM.so.3.4'] or 'missing')[:16]}…` | `{' '.join(config['options'])}` | {config['role']} |")
    lines += ["", "## Summary by configuration (run 1; run 2 compared for determinism)", "",
              "| Configuration | Rust programs passed | C programs passed | Sites exact (amended) | Sites exact (strict) | Other site outcomes | Deterministic |",
              "|---|---|---|---|---|---|---|"]
    for name in configurations:
        s = summary[name]
        amended = s["site_outcomes_amended"]
        other = {k: v for k, v in amended.items() if k != "passed"}
        lines.append(f"| `{name}` | {s['rust_programs_passed']}/{s['rust_programs']} | {s['c_programs_passed']}/{s['c_programs']} | "
                     f"{amended.get('passed', 0)}/{s['adjudicated_rust_sites']} | "
                     f"{s['site_outcomes_strict_preregistered'].get('passed', 0)}/{s['adjudicated_rust_sites']} | "
                     f"{', '.join(f'{k}: {v}' for k, v in other.items()) or '—'} | {'yes' if s['deterministic_two_runs'] else '**no**'} |")
    lines += ["", "## Mandatory case: `instrument.rs::dynamic_dispatch` (line 73)", "",
              "| Configuration | Site status | Actual targets | Missing | Unexpected | `entry_dynamic_trait → target` depth (expected 3) |",
              "|---|---|---|---|---|---|"]
    for name in configurations:
        s = summary[name]
        for site in s["mandatory_dynamic_dispatch"]:
            depth = next((t["observed_depth"] for c in s["mandatory_dynamic_trait_case"] for t in c["targets"] if t["function"] == "target"), None)
            lines.append(f"| `{name}` | {site['status']} | {cell(site['actual'])} | {cell(site['missing'])} | {cell(site['unexpected'])} | "
                         f"{'unreachable' if depth is None else depth} |")
    lines += ["", "## Adjudicated Rust indirect sites (all configurations)", "",
              "Status per configuration; `exact` = exact expected set. Unexpected targets are false may-targets, "
              "which can shorten paths.", "",
              "| Program / site | Expected | " + " | ".join(f"`{c}`" for c in configurations) + " |",
              "|---|---|" + "---|" * len(configurations)]
    for row in site_matrix(results):
        cells = []
        for name in configurations:
            r = row.get(name)
            if not r:
                cells.append("—")
                continue
            detail = ""
            if r["missing"]:
                detail += " −" + ",".join(short(x) for x in r["missing"])
            if r["unexpected"]:
                detail += " +" + ",".join(short(x) for x in r["unexpected"])
            cells.append(r["status"] + detail)
        lines.append(f"| {row['program']} / `{row['site']}` | {cell(row['expected'])} | " + " | ".join(cells) + " |")
    lines += ["", "## Case outcomes under the primary configuration `P`", "",
              "| Program / case | Target | Rule | Expected depth | Observed depth | Status | Other failures |",
              "|---|---|---|---|---|---|---|"]
    for key, value in rows.items():
        run, configuration, program = key.split("|", 2)
        if run != "run-1" or configuration != PRIMARY or "cases" not in value:
            continue
        for case in value["cases"]:
            other = [f for f in case["failures"] if not f.startswith("target:")]
            for target in case["targets"] or [{"function": "—", "rule": "—", "expected_depth": None, "observed_depth": None, "status": "n/a"}]:
                lines.append(f"| {program} / {case['id']} | {short(target['function'])} | {target['rule']} | "
                             f"{target.get('expected_depth') if target.get('expected_depth') is not None else '—'} | "
                             f"{target.get('observed_depth') if target.get('observed_depth') is not None else 'unreachable'} | "
                             f"{target['status']} | {'; '.join(other) or '—'} |")
    lines += ["", "## Calibration pairs (15 frozen C/Rust fixtures)", "",
              "Rust and C target depths from each pair's configured `entry`. C under `P` must reproduce the committed calibration results.", "",
              "| Pair | C `P` status | C regression vs committed | C depth(s) | " + " | ".join(f"Rust `{c}`" for c in configurations) + " |",
              "|---|---|---|---|" + "---|" * len(configurations)]
    pairs = sorted({k.split("|", 2)[2].split("/")[1] for k in rows if "|calibration/" in k})
    for pair in pairs:
        c_row = rows.get(f"run-1|{PRIMARY}|calibration/{pair}/C", {})
        c_depths = ", ".join(str(d["depth"]) if d["depth"] is not None else "unreachable" for d in c_row.get("target_depths", []))
        rust_cells = []
        for name in configurations:
            r = rows.get(f"run-1|{name}|calibration/{pair}/Rust", {})
            depths = ", ".join(str(d["depth"]) if d["depth"] is not None else "unreachable" for d in r.get("target_depths", []))
            rust_cells.append(f"{r.get('status', '—')} ({depths})")
        lines.append(f"| {pair} | {c_row.get('status', '—')} | {'identical' if results['c_regression'][pair].get('identical') else '**differs**'} | "
                     f"{c_depths} | " + " | ".join(rust_cells) + " |")
    effect = results.get("c_raw_identical_primary_vs_sensitivity", {})
    by_config = defaultdict(list)
    for key, same in effect.items():
        by_config[key.split("|")[0]].append(same)
    lines += ["", "C helper output under each non-primary instrument, byte-compared with `P` on the same C bitcode: " +
              "; ".join(f"`{c}` {sum(v)}/{len(v)} identical" for c, v in sorted(by_config.items())) + ".", ""]
    lines += ["## Determinism", "",
              f"{sum(results['determinism'].values())}/{len(results['determinism'])} (configuration, program) pairs produced "
              "byte-identical raw helper output, identical finalized graphs, and identical verdicts across two fresh "
              "compile-and-analyze runs.", ""]
    lines += ["## Definition inventory and scope (configuration `P`, run 1)", "",
              "| Program | LLVM definitions | With debug info | Exported by helper | Without debug info (not exported) | Function origins (exported) | Unadjudicated indirect sites | Unresolved sites | External calls |",
              "|---|---|---|---|---|---|---|---|---|"]
    for key, value in rows.items():
        run, configuration, program = key.split("|", 2)
        if run != "run-1" or configuration != PRIMARY or "inventory" not in value or program.endswith("/C"):
            continue
        inv = value["inventory"]
        if "function_origins" in value:
            origins = ", ".join(f"{k}: {v}" for k, v in sorted(value["function_origins"].items()))
        else:  # calibration programs record origins of entry-reachable nodes
            origins = ", ".join(f"{k}: {v}" for k, v in sorted(value.get("reachable_origins", {}).items())) + " (reachable)"
        unresolved = value.get("unresolved_indirect_callsites")
        if unresolved is None:
            unresolved = (sum(s["status"] == "unresolved" for s in value.get("unadjudicated_indirect_sites", []))
                          + sum(s.get("unresolved_rows", 0) > 0 for s in value.get("sites", [])))
        external = value.get("external_calls", "—")
        external = len(external) if isinstance(external, list) else external
        lines.append(f"| {program} | {inv['llvm_definitions']} | {inv['debug_definitions']} | {inv['helper_exported_functions']} | "
                     f"{', '.join(inv['definitions_without_debug_info']) or '—'} | {origins} | "
                     f"{len(value.get('unadjudicated_indirect_sites', []))} | {unresolved} | {external} |")
    lines += ["", "## LLVM IR shape census (run 1)", "",
              "Constant non-zero `i8` GEP offsets are the accesses that SVF 67efb774 maps to field 0. `[N x i8]` allocas are "
              "the storage that the byte-offset patch can only model field-insensitively.", "",
              "| Program | Defined functions | i8 GEP const ≠0 | i8 GEP zero | i8 GEP variable | Typed aggregate GEP | `[N x i8]` allocas | Typed allocas |",
              "|---|---|---|---|---|---|---|---|"]
    for program, c in sorted(results["ir_census"].items()):
        lines.append(f"| {program} | {c['defined_functions']} | {c['gep_i8_constant_nonzero_offset']} | {c['gep_i8_zero_offset']} | "
                     f"{c['gep_i8_variable_offset']} | {c['gep_typed_aggregate_or_array']} | {c['alloca_byte_array']} | {c['alloca_typed']} |")
    totals = defaultdict(Counter)
    for program, c in results["ir_census"].items():
        totals["C" if program.endswith("/C") else "Rust"].update(c)
    lines += ["", "| Language (all programs) | i8 GEP const ≠0 | Typed aggregate GEP | `[N x i8]` allocas | Typed allocas |", "|---|---|---|---|---|"]
    for language, c in sorted(totals.items()):
        lines.append(f"| {language} | {c['gep_i8_constant_nonzero_offset']} | {c['gep_typed_aggregate_or_array']} | {c['alloca_byte_array']} | {c['alloca_typed']} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    path = (ROOT / args.results) if not args.results.is_absolute() else args.results
    results = read(path)
    results["_output"] = str(path.parent)
    summary = summarize(results)
    decision = acceptance(results, summary)
    compact = {
        "source": path.relative_to(ROOT).as_posix(),
        "results_sha256": P.sha256(path),
        "preregistration": results["preregistration"],
        "decision": decision, "summary": summary,
        "site_matrix": site_matrix(results),
        "determinism": results["determinism"],
        "c_regression": {k: {"identical": v.get("identical"), "checks": v.get("checks")} for k, v in results["c_regression"].items()},
        "c_raw_identical_primary_vs_other_instruments": results.get("c_raw_identical_primary_vs_sensitivity", {}),
        "ir_census": results["ir_census"],
        "toolchain_before": read(path.parent / "toolchain_before.json"),
        "toolchain_after": read(path.parent / "toolchain_after.json"),
        "program_failures": {k: v.get("failures") for k, v in results["results"].items() if v.get("status") != "pass"},
    }
    (HERE / "validation_results.json").write_text(json.dumps(compact, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (HERE / "VALIDATION_REPORT.md").write_text(markdown(results, summary, decision), encoding="utf-8")
    print(decision["decision"])
    print(json.dumps(decision["criteria"], indent=1))


if __name__ == "__main__":
    main()
