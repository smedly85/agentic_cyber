"""Small controlled-fixture pilot; never a formal analysis or clustering entry point.

Run from the repo root: python3 -m scripts.ordered_diversity_pilot --output out.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from .analysis.ordered_callgraph import analyze_source_bytes, stable_json
from .analysis.ordered_distances import compare, coverage, provenance, reference_sensitivity

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/ordered_callgraph"


def _counts(path, extraction):
    if extraction["status"] != "success":
        return None, "extraction_unavailable"
    # The actual primary analyzer's extractor is used only for a raw diagnostic.
    # No analyzer main(), evaluator, compiler, or experiment is executed.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from scripts.analyze_experiment import parse_tree_sitter
        counts, _, _, _, error = parse_tree_sitter(path)
        return (None, error) if error else (dict(counts), None)
    except Exception as exc:
        return None, "count_extractor_unavailable:" + type(exc).__name__
    finally:
        sys.path.pop(0)


def _cosine(a, b):
    if a is None or b is None:
        return None
    aa, bb = sum(v*v for v in a.values()), sum(v*v for v in b.values())
    if not aa or not bb:
        return 0.0 if aa == bb else 1.0
    return max(0.0, min(1.0, 1 - sum(v*b.get(k, 0) for k, v in a.items()) / math.sqrt(aa*bb)))


def run_pilot(fixture_dir=FIXTURES):
    manifest = json.loads((fixture_dir / "pilot_manifest.json").read_text())
    output = {
        "provenance": provenance(), "manifest_version": manifest["version"],
        "purpose": manifest["purpose"], "groups": [], "negative_extractions": {},
        "count_diagnostic": "Raw existing Tree-sitter counts/cosine; no baseline deltas, Clang, GumTree, scope normalization, or primary-metric claim",
        "manifest_sha256": hashlib.sha256((fixture_dir / "pilot_manifest.json").read_bytes()).hexdigest(),
        "pilot_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "count_extractor_source_sha256": hashlib.sha256(Path(__file__).with_name("analyze_experiment.py").read_bytes()).hexdigest(),
    }

    def load(name):
        # This runner intentionally accepts only the local controlled manifest.
        path = fixture_dir / name
        if Path(name).name != name:
            raise ValueError("Fixture names must be simple local basenames")
        data = path.read_bytes()
        return analyze_source_bytes(data, source_file=name), hashlib.sha256(data).hexdigest()

    for group in manifest["groups"]:
        if group["language"] != "C" or any(not n.endswith(".c") for n in group["files"]):
            raise ValueError("Pilot groups must contain only C; negative language cases are separate")
        names = group["files"]
        extractions = {n: load(n) for n in names}
        reference = extractions[group["reference"]][0]
        counts = {n: _counts(fixture_dir / n, extractions[n][0]) for n in names}
        row = {
            **group, "extractions": {n: {**coverage(r), "source_sha256": digest, "diagnostics": r["diagnostics"]} for n, (r, digest) in extractions.items()},
            "architecture_distances": [], "strategy_distances": [], "raw_count_cosine_distances": [],
            "strategy_alignment_ranges": [], "alignment_sensitive_pairs": [],
            "comparisons": [], "count_status": {n: error for n, (_, error) in counts.items()},
        }
        for a in names:
            ad, sd, cd, intervals = [], [], [], []
            for b in names:
                measurement = compare(extractions[a][0], extractions[b][0], scope_reference=reference)
                ad.append(measurement["architecture"]["distance"])
                sd.append(measurement["strategy"]["distance"])
                intervals.append(measurement["strategy"].get("alignment_range"))
                if a < b and measurement["strategy"].get("reporting_status") == "alignment_sensitive":
                    row["alignment_sensitive_pairs"].append({"left": a, "right": b, "range": measurement["strategy"]["alignment_range"]})
                cd.append(_cosine(counts[a][0], counts[b][0]))
                row["comparisons"].append({"left": a, "right": b, **measurement})
            row["architecture_distances"].append(ad)
            row["strategy_distances"].append(sd)
            row["strategy_alignment_ranges"].append(intervals)
            row["raw_count_cosine_distances"].append(cd)
        row["coverage"] = {
            "extraction_successes": sum(r[0]["status"] == "success" for r in extractions.values()),
            "extraction_total": len(names),
            "pair_total_including_diagonal": len(names)**2,
            "architecture_available": sum(c["architecture"]["status"] == "success" for c in row["comparisons"]),
            "strategy_available": sum(c["strategy"]["status"] == "success" for c in row["comparisons"]),
        }
        if group.get("scope_reference_alternatives"):
            refs = {name: load(name)[0] for name in group["scope_reference_alternatives"]}
            row["reference_sensitivity"] = reference_sensitivity(extractions[names[0]][0], extractions[names[1]][0], refs)
        output["groups"].append(row)
    for name in manifest["negative_extraction_cases"]:
        result, digest = load(name)
        output["negative_extractions"][name] = {**coverage(result), "diagnostics": result["diagnostics"], "source_sha256": digest}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="JSON destination; defaults to stdout")
    args = parser.parse_args()
    output = stable_json(run_pilot())
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
