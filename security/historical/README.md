# Historical vulnerability dataset

`records.json` is intentionally empty. Historical mappings must be curated
from authoritative upstream advisories and patches; this repository does not
ship fabricated CVEs or guessed function mappings. Each record must satisfy
`schema.json`, and `verified=true` should be set only after both the source and
patch references have been checked.

This dataset is research input for the retrospective structural study. It is
never copied into lineage results and never affects generation, functional
validation, dynamic security findings, repair, or promotion.

Run an exact-name analysis against a checked-out vulnerable source tree with:

```bash
python3 security/historical/run_historical_analysis.py \
  --source-tree /path/to/upstream --records security/historical/records.json \
  --output build/historical-analysis.json --k 1 --percent 10 25 50 100 \
  --random-seeds 1 2 3 4 5
```

Unresolved or ambiguous function names are reported; they are never guessed.
Unverified records can be inspected and mapped, but are excluded from HVC
denominators and depth-distribution summaries until `verified=true`.
