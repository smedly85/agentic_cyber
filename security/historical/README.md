# Historical vulnerability dataset

`records.json` is an array and is intentionally empty. Historical mappings
must be curated from authoritative upstream advisories and patches; this
repository does not ship fabricated CVEs or guessed function mappings.
`schema.json` validates the complete array in `records.json`, matching the array
root required by the Python loader. `verified=true` should be set only after
both the source and patch references have been checked.

This dataset is research input for the retrospective structural study. It is
never copied into lineage results and never affects generation, functional
validation, dynamic security findings, repair, or promotion.

Each record is tied to the exact vulnerable source identity
`(upstream_project, affected_version, source_revision)`. `source_manifest.json`
is an array that associates each identity with a local checked-out tree and a
fingerprint of the C inputs. `source_manifest.schema.json` validates that
complete array, matching the array root required by the Python loader. The
analyzer does not download sources. Compute the fingerprint with
`source_tree_sha256()` from `security.historical.analysis`, then run:

Each manifest entry also defines a `programs` map. A utility's entry contains
an exact source-qualified entry point and source-tree-relative `source_globs`.
For example, `sort` can use `src/sort.c::main` with `src/sort.c`, while a
historical grep revision can explicitly include multiple translation units.
Only the deduplicated C files matched by that utility/version scope participate
in its call graph. Program filtering does not alter the immutable whole-tree
fingerprint.

```bash
python3 security/historical/run_historical_analysis.py \
  --source-manifest security/historical/source_manifest.json \
  --records security/historical/records.json \
  --output build/historical-analysis.json --k 1 --percent 10 25 50 100 \
  --random-seeds 1 2 3 4 5
```

Every record is mapped and selected against its utility-specific vulnerable
source graph. Records reuse a cached graph only when the source identity,
utility, source-qualified entry point, and resolved C-file scope are identical.
Missing or mismatched versions, invalid or empty scopes, unresolved entry
points or functions, ambiguous names, and mapped but unreachable functions
remain distinct; targets are never guessed.
Unverified records can be inspected and mapped, but are excluded from HVC
denominators and depth-distribution summaries until `verified=true`.
