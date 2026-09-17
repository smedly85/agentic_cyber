"""Finalize v2 statistics after all dispositions and the observation unit freeze."""
from collections import Counter, defaultdict
import math
import statistics
import jsonschema

from security.historical.v2_study import ROOT, INSTRUMENT, IDS, fingerprint, read, write
from security.historical.v2_validate import validate
from security.historical.v2_reporting_gate import assess, require_reportable


def quantile(values, probability):
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def clean(value):
    return int(value) if float(value).is_integer() else value


def summary(values):
    if not values:
        raise RuntimeError("numeric statistics require a nonempty denominator")
    ordered = sorted(values)
    histogram = Counter(str(clean(value)) for value in ordered)
    q1, q3 = quantile(ordered, 0.25), quantile(ordered, 0.75)
    return {"n": len(ordered), "values": [clean(v) for v in ordered],
            "mean": statistics.fmean(ordered), "median": statistics.median(ordered),
            "sample_sd": statistics.stdev(ordered) if len(ordered) >= 2 else None,
            "q1": clean(q1), "q3": clean(q3), "iqr": clean(q3 - q1),
            "minimum": clean(min(ordered)), "maximum": clean(max(ordered)),
            "exact_depth_histogram": dict(sorted(histogram.items(), key=lambda item: float(item[0])))}


def build_statistics(population, mappings, results):
    gate = assess(population, mappings, results)
    require_reportable(gate)
    if gate["approved_primary_observation_unit"] != "CVE_vulnerable_function":
        raise RuntimeError("unapproved primary observation unit")
    by_mapping = {row["cve_id"]: row for row in mappings["members"]}
    by_population = {row["cve_id"]: row for row in population["members"]}
    primary_observations = []
    context_observations = []
    per_cve = []
    numeric_cve_means = []
    for result in results["members"]:
        cve = result["cve_id"]
        mapping = by_mapping[cve]
        description = by_population[cve]
        contexts_by_function = defaultdict(list)
        for observation in result["observations"]:
            if observation["raw_call_depth"] is not None:
                contexts_by_function[observation["source_identity"]].append(observation)
                context_observations.append({"cve_id": cve, "source_identity": observation["source_identity"],
                                             "specimen_id": observation["specimen_id"],
                                             "raw_semantic_depth": observation["raw_call_depth"]})
        functions = []
        for function in mapping["functions"]:
            identity = function["source_identity"]
            contexts = sorted(contexts_by_function.get(identity, []), key=lambda row: row["specimen_id"])
            depths = [row["raw_call_depth"] for row in contexts]
            function_depth = statistics.fmean(depths) if depths else None
            row = {"cve_id": cve, "source_identity": identity,
                   "function_level_depth": clean(function_depth) if function_depth is not None else None,
                   "reducer": "arithmetic_mean_of_executable_specific_semantic_depths" if len(contexts) > 1 else "single_executable_context",
                   "executable_contexts": [{"specimen_id": item["specimen_id"],
                                             "raw_semantic_depth": item["raw_call_depth"]} for item in contexts]}
            functions.append(row)
            if function_depth is not None:
                primary_observations.append(row)
        numeric = [row["function_level_depth"] for row in functions if row["function_level_depth"] is not None]
        cve_mean = statistics.fmean(numeric) if numeric else None
        if cve_mean is not None:
            numeric_cve_means.append(cve_mean)
        scopes = sorted({observation["source_scope_kind"] for observation in result["observations"]})
        per_cve.append({"cve_id": cve,
                        "project_package": mapping.get("project", description["affected_project_package"]),
                        "utility_component": description["utility_component"],
                        "implementation_family": "util-linux su" if cve == "CVE-2017-2616" else description["implementation_family"],
                        "depth_applicability": result["depth_applicability"],
                        "verified_vulnerable_function_count": len(mapping["functions"]),
                        "numeric_vulnerable_function_count": len(numeric),
                        "function_depths": functions,
                        "per_cve_mean_depth": clean(cve_mean) if cve_mean is not None else None,
                        "per_cve_minimum_depth": clean(min(numeric)) if numeric else None,
                        "per_cve_maximum_depth": clean(max(numeric)) if numeric else None,
                        "scope_kinds": scopes,
                        "analysis_status": result.get("analysis_status", result["disposition"]),
                        "disposition": result["disposition"], "reason": result["reason"]})
    if len(primary_observations) != 25 or len(context_observations) != 28 or len(numeric_cve_means) != 22:
        raise RuntimeError("unexpected v2 statistical denominators")
    artifact = {"schema_version": 1, "population_fingerprint": population["population_fingerprint"],
                "mapping_artifact_fingerprint": mappings["mapping_artifact_fingerprint"],
                "instrument_commit": INSTRUMENT,
                "observation_rule": {"primary_unit": "CVE_vulnerable_function",
                    "shared_function_rule": "arithmetic_mean_of_executable_specific_semantic_depths",
                    "raw_contexts_preserved": True,
                    "sensitivity_contexts_are_independent_vulnerability_observations": False},
                "population_accounting": {"population_cves": 24, "depth_applicable_cves": 22,
                    "cves_with_numeric_semantic_depth": 22, "non_depth_applicable_cves": 2,
                    "unavailable_or_unresolved_cves": 0, "all_final_dispositions": True,
                    "verified_vulnerable_function_observations": 25,
                    "numeric_vulnerable_function_observations": 25,
                    "nonnumeric_vulnerable_function_observations": 0},
                "primary_function_observations": primary_observations,
                "primary_function_observation_statistics": summary([row["function_level_depth"] for row in primary_observations]),
                "cve_weighted_statistics": summary(numeric_cve_means),
                "executable_context_sensitivity": {"context_count": 28,
                    "independent_vulnerability_observations": False,
                    "interpretation": "Descriptive sensitivity only; three CVE/function groups contribute multiple dependent executable contexts.",
                    "contexts": context_observations,
                    "statistics": summary([row["raw_semantic_depth"] for row in context_observations])},
                "per_cve": per_cve,
                "statistical_conventions": read("v2_protocol.json")["statistics_conventions"]}
    artifact["statistics_artifact_fingerprint"] = fingerprint(artifact)
    return artifact, gate


def number(value):
    if value is None:
        return "—"
    return str(clean(round(value, 12)))


def format_summary(row):
    return (f"N={row['n']}; mean={number(row['mean'])}; median={number(row['median'])}; "
            f"sample SD={number(row['sample_sd'])}; Q1={number(row['q1'])}; Q3={number(row['q3'])}; "
            f"IQR={number(row['iqr'])}; range={number(row['minimum'])}–{number(row['maximum'])}.")


def render(artifact):
    accounting = artifact["population_accounting"]
    primary = artifact["primary_function_observation_statistics"]
    weighted = artifact["cve_weighted_statistics"]
    sensitivity = artifact["executable_context_sensitivity"]["statistics"]
    lines = ["# Historical population v2 semantic call-depth report", "",
             "## Population accounting", "",
             f"Population CVEs: **{accounting['population_cves']}**. Depth-applicable: **{accounting['depth_applicable_cves']}**; with at least one numeric semantic depth: **{accounting['cves_with_numeric_semantic_depth']}**; non-depth-applicable: **{accounting['non_depth_applicable_cves']}**; unavailable/unresolved: **{accounting['unavailable_or_unresolved_cves']}**.", "",
             f"Verified vulnerable-function observations: **{accounting['verified_vulnerable_function_observations']}**; numeric: **{accounting['numeric_vulnerable_function_observations']}**; nonnumeric: **{accounting['nonnumeric_vulnerable_function_observations']}**.", "",
             "The primary unit is `(CVE, vulnerable function)`. When the same vulnerable function is shared by multiple affected executables, its primary depth is the arithmetic mean of the preserved executable-specific semantic depths. The 28-context analysis below is sensitivity only and does not treat those contexts as independent vulnerabilities.", "",
             "## Function-observation statistics", "", format_summary(primary), "",
             "Exact-depth histogram: " + ", ".join(f"depth {depth}: {count}" for depth, count in primary["exact_depth_histogram"].items()) + ".", "",
             "Complete primary depth list (sorted): `" + ", ".join(number(value) for value in primary["values"]) + "`.", "",
             "## CVE-weighted statistics", "",
             "For each of the 22 CVEs with numeric depths, vulnerable-function depths were averaged within that CVE; the following describes those 22 per-CVE means.", "", format_summary(weighted), "",
             "Per-CVE mean-depth list (sorted): `" + ", ".join(number(value) for value in weighted["values"]) + "`.", "",
             "## Executable-context sensitivity analysis", "",
             "This descriptive analysis retains all 28 raw executable contexts. Three vulnerable functions occur in multiple executables, so these 28 values are dependent contexts—not 28 independent vulnerability observations.", "", format_summary(sensitivity), "",
             "Context-depth histogram: " + ", ".join(f"depth {depth}: {count}" for depth, count in sensitivity["exact_depth_histogram"].items()) + ".", "",
             "Complete context-depth list (sorted): `" + ", ".join(number(value) for value in sensitivity["values"]) + "`.", "",
             "## Complete 24-CVE accounting", "",
             "| CVE | Project / component | Family | Applicability | Verified functions | Numeric functions | Function-level depths (raw executable contexts) | Per-CVE mean/min/max | Scope | Status / reason |",
             "|---|---|---|---|---:|---:|---|---|---|---|"]
    for row in artifact["per_cve"]:
        values = []
        for function in row["function_depths"]:
            contexts = ", ".join(context["specimen_id"] + "=" + number(context["raw_semantic_depth"]) for context in function["executable_contexts"])
            values.append(function["source_identity"] + "=" + number(function["function_level_depth"]) + (" (" + contexts + ")" if contexts else ""))
        lines.append("| " + " | ".join([row["cve_id"], row["project_package"] + " / " + row["utility_component"], row["implementation_family"],
            row["depth_applicability"], str(row["verified_vulnerable_function_count"]), str(row["numeric_vulnerable_function_count"]),
            "; ".join(values) or "—", "/".join(number(row[key]) for key in ("per_cve_mean_depth", "per_cve_minimum_depth", "per_cve_maximum_depth")),
            ", ".join(row["scope_kinds"]) or "not applicable", row["disposition"] + ": " + row["reason"]]) + " |")
    lines += ["", "## Coverage and limitations", "",
              "Every numeric result uses the frozen Clang/LLVM/SVF may-call backend and linker-exact executable scope. Static may-call reachability over-approximates possible runtime calls and does not prove execution. Resolved indirect callsites retain every may-target; unresolved indirect calls and external definitions remain graph-quality diagnostics in the source manifest. Historical compiler/configuration reconstruction and heterogeneous implementation families remain limitations.", "",
              "CVE-2009-4135 is a build-machinery vulnerability and CVE-2008-1946 is a PAM-configuration vulnerability; both remain in the 24-CVE population but have no legitimate runtime C-function depth. No value is imputed. Tree-sitter prototype depths do not enter these statistics. The distribution is reported without choosing a shallow-depth cutoff or inferring that depth causes vulnerability.", "",
              f"Population fingerprint: `{artifact['population_fingerprint']}`. Mapping fingerprint: `{artifact['mapping_artifact_fingerprint']}`. Statistics fingerprint: `{artifact['statistics_artifact_fingerprint']}`. Instrument commit: `{artifact['instrument_commit']}`.", ""]
    return "\n".join(lines)


def main():
    population, mappings, results, _ = validate()
    artifact, gate = build_statistics(population, mappings, results)
    jsonschema.Draft202012Validator(read("v2_statistics.schema.json")).validate(artifact)
    write("v2_statistics.json", artifact)
    report = render(artifact)
    if report != render(artifact):
        raise RuntimeError("nondeterministic statistics rendering")
    (ROOT / "evidence/v2/final-report.md").write_text(report)
    gate.update(statistics_reportable=True, statistics_computed=True,
                statistics_artifact="security/historical/v2_statistics.json",
                statistics_artifact_fingerprint=artifact["statistics_artifact_fingerprint"])
    write("v2_reporting_gate.json", gate)
    results["study_status"] = "complete"
    write("v2_semantic_results.json", results)
    print(format_summary(artifact["primary_function_observation_statistics"]))
    print(format_summary(artifact["cve_weighted_statistics"]))
    print(format_summary(artifact["executable_context_sensitivity"]["statistics"]))


if __name__ == "__main__":
    main()
