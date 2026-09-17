"""Verify authenticated source fingerprints and evidence without measuring depths."""
import json
from security.historical import semantic_validation as v
from security.historical.analysis import verify_source_tree_sha256
from security.historical.v2_study import ROOT, read, write


def main():
    mappings = read("v2_vulnerable_function_mappings.json")
    manifest = read("v2_source_manifest.json")
    trees = {}
    for item in mappings["members"] + manifest["specimens"]:
        if "source_tree" not in item:
            continue
        path, expected = item["source_tree"], item["source_tree_sha256"]
        if path in trees and trees[path] != expected:
            raise RuntimeError("inconsistent frozen source fingerprint")
        trees[path] = expected
    checked = []
    for path, expected in sorted(trees.items()):
        verify_source_tree_sha256(ROOT / path, expected)
        checked.append({"source_tree": path, "source_tree_sha256": expected, "unchanged": True})
        print("unchanged:", path, flush=True)
    for mapping in mappings["members"]:
        for function in mapping["functions"]:
            if function.get("source_sha256"):
                if v._sha256(ROOT / mapping["source_tree"] / function["source_file"]) != function["source_sha256"]:
                    raise RuntimeError("mapped source file fingerprint changed")
    # This index records both successful and superseded configure attempts.
    receipts = sorted((v.REPO / "build/historical-v2/native").glob("*/v2-configure-status.json"))
    write("v2_configured_builds.json", {"schema_version": 1, "builds": [json.loads(p.read_text()) for p in receipts]})
    write("v2_source_integrity.json", {"schema_version": 1, "population_fingerprint": mappings["population_fingerprint"],
          "mapping_artifact_fingerprint": mappings["mapping_artifact_fingerprint"], "source_trees": checked,
          "all_unchanged": True, "scope": "Frozen C/header tree fingerprint plus independently recorded vulnerable-source file hashes; generated build modules separately hashed in scope artifacts."})


if __name__ == "__main__":
    main()
