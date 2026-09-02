# Historical vulnerability dataset

`records.json` is intentionally empty. Historical mappings must be curated
from authoritative upstream advisories and patches; this repository does not
ship fabricated CVEs or guessed function mappings. Each record must satisfy
`schema.json`, and `verified=true` should be set only after both the source and
patch references have been checked.

This dataset is research input for the retrospective structural study. It is
never copied into lineage results and never affects generation, functional
validation, dynamic security findings, repair, or promotion.

Each record supplies an exact `source_revision`. `source_manifest.json`
associates that identity with a local checked-out tree and a fingerprint of the
C inputs. The analyzer does not download sources. Compute the fingerprint with
`source_tree_sha256()` from `security.historical.analysis`, then run:

```bash
python3 security/historical/run_historical_analysis.py \
  --source-manifest security/historical/source_manifest.json \
  --records security/historical/records.json \
  --output build/historical-analysis.json --k 1 --percent 10 25 50 100 \
  --random-seeds 1 2 3 4 5
```

Every record is mapped and selected against its own vulnerable source graph.
Records sharing an identical source identity reuse a cached graph. Missing or
mismatched versions, unresolved functions, ambiguous names, and mapped but
unreachable functions remain distinct; targets are never guessed.
Unverified records can be inspected and mapped, but are excluded from HVC
denominators and depth-distribution summaries until `verified=true`.
