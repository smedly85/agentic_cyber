"""Render the reviewed pre-measurement snapshot from checksum-verified local evidence.

No network access. Acquisition is a separate explicit research.py operation.
Run --write to generate or --check to compare; neither executes historical code.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

from review import (REVIEWS, FILES, PLATFORM_FUNCTIONS, UNRESOLVED, CAVEATS,
                    EXECUTABLES, CONFIGURATION_FILES, AUDIT_NOTES,
                    AUDIT_SOURCE_FILES, LOCATION_REASONS)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CACHE = ROOT / "build/historical-rust/cache"
CUTOFF = "2026-09-11"
AUDIT = "3a07ffc5a9bd4c283e75afa548ba1f1957bad242"
OLD = "2bb9a85ddedc7b8aa1bd866bd70e41364c8783f7"
CONFIG_REVISION = "64203e309810d7e01eaf9c6cc7c21df22a8a896d"
API = "https://api.github.com/repos/uutils/coreutils/"
GH = "https://github.com/uutils/coreutils/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def json_text(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Evidence:
    def __init__(self):
        self.index = json.loads((CACHE / "index.json").read_text())
        self.used = set()
        self.archives = {}

    def read(self, url):
        record = self.index[url]
        data = (ROOT / record["cache_path"]).read_bytes()
        if digest(data) != record["sha256"]:
            raise ValueError("Evidence checksum mismatch: " + url)
        self.used.add(url)
        return data

    def json(self, url):
        return json.loads(self.read(url))

    def source(self, revision, path):
        if revision not in self.archives:
            url = f"https://codeload.github.com/uutils/coreutils/tar.gz/{revision}"
            self.archives[revision] = tarfile.open(fileobj=io.BytesIO(self.read(url)), mode="r:gz")
        member = self.archives[revision].getmember(f"coreutils-{revision}/{path}")
        if not member.isfile():
            raise ValueError("Not a regular source member")
        return self.archives[revision].extractfile(member).read()


def render():
    ev = Evidence()
    advisories = ev.json(API + "security-advisories?per_page=100")
    advisory_by_cve = {a["cve_id"]: a for a in advisories if a["cve_id"]}
    tags = ev.json(API + "tags?per_page=100")
    assert next(t for t in tags if t["name"] == "0.2.2")["commit"]["sha"] == AUDIT
    assert next(t for t in tags if t["name"] == "0.0.3")["commit"]["sha"] == OLD
    assert next(t for t in tags if t["name"] == "0.5.0")["commit"]["sha"] == CONFIG_REVISION
    # Old tag provenance is separately cached; source archive Cargo.toml is also
    # checked below. Do not substitute a modern checkout for either specimen.
    discovery_urls = [u for u in ev.index if any(x in u for x in (
        "security-advisories?", "api.github.com/advisories?", "services.nvd.nist.gov/",
        "openwall.com/", "rustsec.org/", "discourse.ubuntu.com/", "RustSec/advisory-db/git/trees/"))]
    for url in discovery_urls:
        ev.read(url)
    nvd = ev.json(next(u for u in discovery_urls if "services.nvd" in u))
    assert len(nvd["vulnerabilities"]) == nvd["totalResults"]
    cves = [ev.json(u) for u in sorted(ev.index) if "/cvelistV5/" in u]
    aliases = {}
    for url in discovery_urls:
        if "api.github.com/advisories?" in url:
            for a in ev.json(url):
                if a.get("cve_id"):
                    aliases.setdefault(a["cve_id"], set()).add(a["ghsa_id"])
    population, mappings, specimens, source_files, docs = [], [], [], {}, {}
    for cve in sorted(cves, key=lambda c: c["cveMetadata"]["cveId"]):
        meta, cna = cve["cveMetadata"], cve["containers"]["cna"]
        cve_id = meta["cveId"]
        number = int(cve_id.rsplit("-", 1)[1])
        # Inclusion is adjudicated independently of function availability/count.
        # The only discovered other-project record is GNU Fileutils 2002-0435.
        member = cve_id != "CVE-2002-0435" and meta["state"] == "PUBLISHED" and meta["datePublished"][:10] <= CUTOFF
        if member and number not in REVIEWS:
            raise ValueError("New eligible CVE needs explicit review, not silent exclusion: " + cve_id)
        a = advisory_by_cve.get(cve_id, {})
        own_aliases = set(aliases.get(cve_id, set()))
        if a:
            own_aliases.add(a["ghsa_id"])
        refs = sorted({r["url"] for r in cna["references"]})
        own_aliases.update(re.findall(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", " ".join(refs)))
        if number == 29934:
            own_aliases.add("RUSTSEC-2021-0043")
        cve_url = next(u for u in ev.index if "/cvelistV5/" in u and u.endswith(cve_id + ".json"))
        authoritative = sorted(set(refs + [cve_url] + ([a["html_url"]] if a else [])))
        if member:
            component, functions, fix, reason = REVIEWS[number]
            category = "configuration" if number == 35362 else ("shared_runtime_library" if component.startswith("uucore/") else "runtime_function")
            status = "not_applicable" if number == 35362 else ("unresolved" if number in UNRESOLVED else "verified")
        else:
            component, category, status = ("install", "runtime_function", "excluded") if number == 93658 else ("GNU Fileutils", "other_non_function", "excluded")
        nonapplicable = "Compile-time platform gates; no singular runtime function is established as the vulnerable unit." if number == 35362 else ("Outside the frozen population." if not member else None)
        patched = [v.get("patched_versions") for v in a.get("vulnerabilities", []) if v.get("patched_versions")]
        record = {
            "cve_id": cve_id, "aliases": sorted(own_aliases), "cve_state": meta["state"],
            "project": "GNU Fileutils" if number == 435 else "uutils/coreutils",
            "implementation_family": "GNU" if number == 435 else "uutils",
            "utility_component": component, "language": "C" if number == 435 else "Rust",
            "publication_date": meta["datePublished"][:10], "population_member": member,
            "cutoff_date": CUTOFF, "affected_versions": cna["affected"],
            "advisory_version_claims": a.get("vulnerabilities", []),
            "fixed_version": "; ".join(sorted(set(patched))) or ("0.0.4" if number == 29934 else None),
            "authoritative_sources": authoritative, "category": category,
            "depth_applicability": "not_applicable" if nonapplicable else "applicable",
            "depth_nonapplicability_reason": nonapplicable, "mapping_status": status,
            "evidence_file": f"evidence/{cve_id}.md",
            "exclusion_reason": None if member else ("Published after 2026-09-11." if number == 93658 else "Assigned to GNU Fileutils, not uutils Rust source."),
            "notes": [x for x in [CAVEATS.get(number), UNRESOLVED.get(number)] if x],
        }
        population.append(record)
        if not member:
            docs[record["evidence_file"]] = f"# {cve_id}: discovery exclusion\n\nProject/component: {record['project']} / {component}.\n\nCVE publication: {record['publication_date']}; cutoff: {CUTOFF}.\n\nDisposition: {record['exclusion_reason']}\n\nAffected-version assertions are preserved verbatim as structured CNA data in population.json. No vulnerable specimen or functions are selected: source location, fix, executable scope and function-level applicability are outside this population, not an unresolved included mapping.\n\nSources:\n\n" + "\n".join(f"- {u}" for u in authoritative) + "\n"
            continue
        revision, version = (OLD, "0.0.3") if number == 29934 else (AUDIT, "0.2.2")
        if number == 35362:
            revision, version = CONFIG_REVISION, "0.5.0"
            gate_source = ev.source(revision, "src/uucore/src/lib/features.rs").decode()
            if '#[cfg(target_os = "linux")]\npub mod safe_traversal;' not in gate_source:
                raise ValueError("Selected configuration specimen lacks the vulnerable gate")
        if isinstance(fix, int):
            pr_url = API + f"pulls/{fix}"
            pr = ev.json(pr_url)
            if not pr["merged"]:
                raise ValueError("An unmerged proposal cannot establish a fix")
            fix_revision = pr["merge_commit_sha"]
            fix_evidence = [pr_url, GH + f"pull/{fix}.patch"]
        else:
            fix_revision = fix
            patch_url = GH + f"commit/{fix}.patch"
            if patch_url not in ev.index:
                candidates = [u for u in ev.index if u.startswith(GH + "commit/") and u.endswith(".patch")
                              and fix.startswith(u.rsplit("/", 1)[1][:-6])]
                if len(candidates) != 1:
                    raise ValueError("Missing unambiguous cached fix patch: " + fix)
                patch_url = candidates[0]
            if not ev.read(patch_url).startswith(("From " + fix + " ").encode()):
                raise ValueError("Fix SHA does not match patch: " + fix)
            fix_evidence = [patch_url]
        for url in fix_evidence:
            data = ev.read(url)
            if url.endswith(".patch") and not data.startswith(b"From "):
                raise ValueError("Not a patch: " + url)
        default_file = FILES.get(number, f"src/uu/{component}/src/{component}.rs")
        audit_sources = AUDIT_SOURCE_FILES.get(number, [])
        audit_evidence = [GH + f"blob/{revision}/{p}" for p in audit_sources]
        if number in (35351, 35357, 35359):
            issue = {35351: 9714, 35357: 10011, 35359: 10017}[number]
            issue_url = API + f"issues/{issue}"
            ev.json(issue_url)  # SHA-verified primary issue, not just a patch list.
            audit_evidence.append(issue_url)
        for path in audit_sources:
            source_files[(revision, path)] = {"revision": revision, "source_file": path,
                                              "sha256": digest(ev.source(revision, path))}
        locations = PLATFORM_FUNCTIONS.get(number, {default_file: functions})
        verified = []
        for source_file, names in locations.items():
            if not names:
                continue
            raw = ev.source(revision, source_file)
            file_hash = digest(raw)
            source_files[(revision, source_file)] = {"revision": revision, "source_file": source_file, "sha256": file_hash}
            for function in names:
                # Lexical existence check only, NOT Rust parsing or a call graph.
                simple = function.rsplit("::", 1)[-1]
                hits = list(re.finditer(r"\bfn\s+" + re.escape(simple) + r"\b", raw.decode()))
                if not hits:
                    raise ValueError(f"Absent function: {source_file}::{function}")
                source_url = GH + f"blob/{revision}/{source_file}"
                executables = EXECUTABLES.get(number, [component])
                if number == 35354 and function != "copy_xattrs":
                    executables = ["mv"]
                verified.append({
                    "function": function, "source_file": source_file,
                    "source_identity": source_file + "::" + function,
                    "crate_or_package": "uucore" if component.startswith("uucore/") else "uu_" + component,
                    "utility_or_shared_component": component,
                    "affected_executables": sorted(executables),
                    "executable_scope_basis": "Advisory and utility-owned source; shared consumers are supported by the vulnerable source and corrective patch, not graph reachability measurements.",
                    "affected_revision": revision, "affected_version": version,
                    "fix_revision": fix_revision, "source_sha256": file_hash,
                    "mapping_evidence": sorted(set([source_url] + authoritative + fix_evidence
                                                   + audit_evidence)),
                    "mapping_reason": LOCATION_REASONS.get((number, source_file, function), reason), "mapping_confidence": "high",
                    "mapping_status": "verified", "mapping_frozen_before_semantic_measurement": True,
                })
        selection = ("Released tag 0.0.3 is within RustSec's affected range (<0.0.4); exact tag commit and archive bytes are pinned."
                     if number == 29934 else "Released tag 0.2.2 resolves exactly to the Zellic-audited vulnerable commit cited by the repository advisory. Select the audited released specimen, not patched source or current main.")
        if number == 35362:
            selection = "Released tag 0.5.0 is within the advisory's affected range (<0.6.0) and its source contains the Linux-only safe_traversal gate. The common audit commit 0.2.2 lacks this module entirely, so the advisory's boilerplate audit revision is not used as this configuration specimen."
        mapping = {"cve_id": cve_id, "mapping_status": status, "category": category,
                   "depth_applicability": record["depth_applicability"],
                   "depth_nonapplicability_reason": nonapplicable,
                   "mapping_frozen_before_semantic_measurement": True,
                   "vulnerable_functions": verified,
                   "unresolved_reason": UNRESOLVED.get(number),
                   "mapping_completeness": "partial_verified_locations" if number in UNRESOLVED else ("not_applicable" if number == 35362 else "reviewed_primary_evidence"),
                   "review_notes": [reason] + record["notes"],
                   "excluded_changes": "Tests, newly introduced remediation helpers, diagnostics and option/result propagation are not mapped solely because the fix changes them. See location-specific rationale and review notes.",
                   "affected_revision": revision, "affected_version": version,
                   "fix_revision": fix_revision, "fix_evidence": fix_evidence}
        if number == 35362:
            mapping["configuration_source_files"] = CONFIGURATION_FILES
            mapping["affected_executables"] = EXECUTABLES[number]
            for path in CONFIGURATION_FILES:
                source_files[(revision, path)] = {"revision": revision, "source_file": path,
                                                  "sha256": digest(ev.source(revision, path))}
        mappings.append(mapping)
        specimens.append({"cve_id": cve_id, "vulnerable_revision": revision, "vulnerable_tag": version,
                          "affected_version_range": record["affected_versions"], "patched_version": record["fixed_version"],
                          "fix_revision": fix_revision, "selection_rationale": selection,
                          "fix_coverage_note": CAVEATS.get(number),
                          "provenance_urls": sorted(set(authoritative + fix_evidence + [GH + f"tree/{revision}", API + "tags?per_page=100"]))})
        locs = "\n".join(f"- `{f['source_identity']}` ({f['crate_or_package']}); executables: {', '.join(f['affected_executables'])}. Source SHA-256: `{f['source_sha256']}`. {f['mapping_reason']}" for f in verified) or "No function assigned: " + reason
        if number == 35362:
            locs += "\n\nConfiguration locations: " + "; ".join(CONFIGURATION_FILES) + ". Consumers supported by the patch: chmod, du, rm."
        docs[record["evidence_file"]] = f"""# {cve_id}

## Project and versions

uutils/coreutils, Rust; component `{component}`. CVE published {record['publication_date']} and included under cutoff {CUTOFF}. CNA affected-version assertions and separate GitHub advisory version claims are retained in population.json without silently reconciling conflicting ranges. Advisory patched version: {record['fixed_version'] or 'not established'}.

## Vulnerable specimen and public fix

Vulnerable release `{version}`, exact revision `{revision}`. {selection}

Public corrective revision: `{fix_revision}`. A public corrective revision does not by itself prove every aspect of remediation complete; see review notes below.

## Vulnerable source locations and executable scope

{locs}

These are source/patch-supported executable associations, not calculated semantic reachability or call depth. Trait/impl qualifiers disambiguate methods. For cfg-specific alternatives, the source-qualified name denotes the relevant vulnerable implementation; no binary configuration has been measured.

## Changed neighbors and review limits

{mapping['excluded_changes']}

{chr(10).join(record['notes']) or 'No additional unresolved location was established by the reviewed primary evidence.'}
{(chr(10) + AUDIT_NOTES[number]) if number in AUDIT_NOTES else ''}
## Applicability and freeze

Category: `{category}`. Depth applicability: `{record['depth_applicability']}`. Mapping status: `{status}`.{(' ' + nonapplicable) if nonapplicable else ''}

`mapping_frozen_before_semantic_measurement: true`. This freezes the reviewed mapping and any explicit uncertainties before measurement; it does not certify unresolved locations as complete. No compilation, call graph or depth measurement was performed.

## Evidence

""" + "\n".join(f"- {u}" for u in sorted(set(authoritative + fix_evidence + audit_evidence + [GH + f"blob/{revision}/{f['source_file']}" for f in verified]))) + "\n"
    expected = {"CVE-2021-29934"} | {f"CVE-2026-{n}" for n in range(35338, 35382)}
    actual = {r["cve_id"] for r in population if r["population_member"]}
    no_cve = [{"ghsa_id": a["ghsa_id"], "url": a["html_url"], "published_at": a["published_at"],
               "summary": a["summary"], "disposition": "No CVE assignment in repository feed; not an additional CVE population unit."}
              for a in advisories if not a["cve_id"]]
    for row in no_cve:
        if row["ghsa_id"] in next(r["aliases"] for r in population if r["cve_id"] == "CVE-2026-93658"):
            row["disposition"] = "CVE record resolves this advisory to CVE-2026-93658; excluded after cutoff despite missing assignment in repository feed."
    pop = {"schema_version": 1, "cutoff_date": CUTOFF, "project": "uutils/coreutils",
           "mapping_frozen_before_semantic_measurement": True,
           "population_rule": "Published CVEs assigned to uutils/coreutils Rust source on or before cutoff, including utility, shared library and non-function defects; exclude dependency-only assignments and other implementation families.",
           "discovery_audit": {"sources": sorted(discovery_urls), "repository_advisories": len(advisories),
                               "repository_cve_assignments": len(advisory_by_cve), "nvd_uutils_results": nvd["totalResults"],
                               "expected_count_not_selection_rule": 45, "verified_member_count": len(actual),
                               "expected_census_missing": sorted(expected - actual), "additional_members": sorted(actual - expected),
                               "rejected_or_withdrawn_discovered": [r["cve_id"] for r in population if r["cve_state"] != "PUBLISHED"],
                               "dependency_only_assignments_encountered": [],
                               "non_cve_advisories": sorted(no_cve, key=lambda r: r["ghsa_id"]),
                               "limits": "Snapshot reconciliation, not a guarantee against future retroactive assignments. Repository feed returned 65 entries (<100); page 2 repeated the same response and was deduplicated. RustSec tree lists uu_od as the only uu_*/uucore/coreutils advisory directory. No dependency-only CVE was encountered in these scoped searches. Multiple GHSA aliases do not add population units."},
           "records": population}
    maps = {"schema_version": 1, "mapping_frozen_before_semantic_measurement": True,
            "population_fingerprint": fingerprint(pop), "records": mappings}
    # Preserve the whole acquisition ledger, including discarded proposals and
    # downloaded material not adopted as evidence. Cache presence is not endorsement.
    for url in ev.index:
        if "/tags/" in url or "git/ref/tags/" in url:
            ev.read(url)
    renderer_inputs = set(ev.used)
    for url in sorted(ev.index):
        ev.read(url)
    manifest = {"schema_version": 1, "mapping_frozen_before_semantic_measurement": True,
                "population_fingerprint": fingerprint(pop), "mapping_fingerprint": fingerprint(maps),
                "specimens": specimens, "source_files": [source_files[k] for k in sorted(source_files)],
                "evidence_cache": [{**{k: ev.index[u][k] for k in ("url", "sha256", "retrieval_date")},
                                    "used_by_renderer": u in renderer_inputs} for u in sorted(ev.used)],
                "cache_ledger_note": "Includes all acquired responses, not only adopted evidence. Unmerged proposals, a non-patch issue response and the downloaded audit PDF are retained for acquisition auditability; cache inclusion does not establish a fixing commit or function mapping. used_by_renderer describes mechanical inputs, not whether a researcher consulted a response.",
                "source_handling": "Archives read in memory without extraction; cached only under ignored controller build directory, never staged to experiment agents. No historical source is committed. No graph or executable was built."}
    docs.update({"population.json": json_text(pop), "vulnerable_function_mappings.json": json_text(maps), "source_manifest.json": json_text(manifest)})
    columns = ["CVE", "Utility / component", "Vulnerable function(s)", "Source file(s)", "Vulnerable version/revision", "Fix revision", "Depth applicability", "Mapping status"]
    rows = []
    by_id = {m["cve_id"]: m for m in mappings}
    for p in population:
        m = by_id.get(p["cve_id"], {})
        fs = m.get("vulnerable_functions", [])
        rows.append([p["cve_id"], p["utility_component"], "; ".join(f["function"] for f in fs) or "not applicable",
                     "; ".join(sorted({f["source_file"] for f in fs} | set(m.get("configuration_source_files", [])))),
                     (m.get("affected_version", "") + " / " + m.get("affected_revision", "")).strip(" /"),
                     m.get("fix_revision", ""), p["depth_applicability"], p["mapping_status"]])
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    docs["mapping_table.tsv"] = out.getvalue()
    table = "| " + " | ".join(columns) + " |\n|" + "---|" * len(columns) + "\n"
    table += "\n".join("| " + " | ".join(row) + " |" for row in rows) + "\n"
    template = (HERE / "README.template.md").read_text()
    docs["README.md"] = template.replace("<!-- MAPPING_TABLE -->", table).rstrip() + "\n"
    lock = {"schema_version": 1, "mapping_frozen_before_semantic_measurement": True,
            "canonical_json_fingerprints": {name: fingerprint(value) for name, value in (("population.json", pop), ("vulnerable_function_mappings.json", maps), ("source_manifest.json", manifest))},
            "protected_c_artifacts_fingerprint": fingerprint(json.loads((HERE / "protected_c_artifacts.json").read_text())),
            "schema_fingerprints": {name: fingerprint(json.loads((HERE / name).read_text())) for name in ("population.schema.json", "vulnerable_function_mappings.schema.json")},
            "review_sha256": digest((HERE / "review.py").read_bytes().replace(b"\r\n", b"\n")),
            "rendered_file_sha256": {name: digest(text.encode()) for name, text in sorted(docs.items()) if not name.endswith(".json")}}
    docs["freeze_manifest.json"] = json_text(lock)
    return docs


def main():
    # Explicit switches avoid any default write or network operation.
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--capture-c-baseline", action="store_true")
    args = parser.parse_args()
    if args.capture_c_baseline:
        target = HERE / "protected_c_artifacts.json"
        if target.exists():
            raise SystemExit("Refusing to replace existing protected C baseline")
        names = subprocess.check_output(["git", "ls-files", "security/historical", "docs/semantic_callgraph_methodology.md"], cwd=ROOT, text=True).splitlines()
        names = [n for n in names if not n.startswith(("security/historical/rust/", "security/historical/sources/"))]
        checksums = {}
        for name in sorted(names):
            # Read the named committed blob without refreshing the enormous
            # historical-source working tree (particularly costly on WSL).
            committed = subprocess.check_output(["git", "show", "HEAD:" + name], cwd=ROOT)
            current = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
            if committed.replace(b"\r\n", b"\n") != current:
                raise SystemExit("Protected C artifact already differs from HEAD: " + name)
            checksums[name] = digest(current)
        baseline = {"hash_normalization": "CRLF to LF; otherwise exact bytes", "files": checksums}
        target.write_text(json_text(baseline), encoding="utf-8", newline="\n")
        print(f"Locked {len(names)} unchanged pre-existing C historical/methodology files")
        return
    outputs = render()
    for name, text in outputs.items():
        path = HERE / name
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.exists() or path.read_text(encoding="utf-8") != text:
            raise SystemExit("Non-reproducible artifact: " + name)
    print(f"{'Wrote' if args.write else 'Verified'} {len(outputs)} pre-measurement artifacts; no code executed or measured.")


if __name__ == "__main__":
    main()
