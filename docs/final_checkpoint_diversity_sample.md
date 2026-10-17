# Final-checkpoint C diversity sample

Descriptive, separate populations; frozen order-aware Architecture (A) and Strategy (S), `c11-posix2008-v1`, unchanged scope and budgets. mkdir/grep measurements were reused after candidate, source, experiment, manifest, profile-evidence and algorithm hash verification. chmod/sort were computed afresh. Raw and LF-normalized hashes are recorded separately.

mkdir, grep and chmod are final-population members. **sort is public-success-only exploratory:** all seven have `final_population_member=false` and failed extra validation. It is not an end-to-end successful population. No populations are pooled.

| Population | n | Exact A pairs | Full-population mean A | S pairs | Available-pair mean S interval |
|---|---:|---:|---:|---:|---|
| mkdir/002 | 7 | 21/21 | 0.2009486264 | 20/21 | [0.6824929873, 0.6825878040] |
| grep/004 | 10 | 45/45 | 0.3091366392 | 24/45 | [0.6250179064, 0.6416192981] |
| chmod/004 | 6 | 10/15 | unavailable | 2/15 | [0.6770280828, 0.6843731333] |
| sort/004 | 7 | 21/21 | 0.3078011123 | 16/21 | [0.6533832283, 0.6973528326] |

## mkdir/002

Closest available architectural pair(s): lineage-004 / lineage-005, A=0.0447761194.
Most distant available architectural pair(s): lineage-001 / lineage-006, A=0.3913043478.

S interval counts: 19 singleton; 1 alignment-sensitive. Missing A: none. Missing S: 1 no scope-compatible Architecture optimum.

Average-linkage threshold grid (threshold: cluster count): 0.05: 6; 0.10: 5; 0.15: 4; 0.20: 2; 0.25: 2; 0.30: 2; 0.35: 1; 0.40: 1; 0.45: 1; 0.50: 1; 0.55: 1; 0.60: 1; 0.65: 1; 0.70: 1; 0.75: 1; 0.80: 1; 0.85: 1; 0.90: 1; 0.95: 1.

Continuous merge heights: 0.0447761194, 0.0778985507, 0.1264367816, 0.1597444101, 0.1767125324, 0.3418136715.

Legacy 0.30 clusters: {lineage-001}; {lineage-003, lineage-004, lineage-005, lineage-006, lineage-009, lineage-010}.

The 0.30 partition persists on [0.1767125324, 0.3418136715); merge heights are included at the lower bound.

## grep/004

Closest available architectural pair(s): lineage-006 / lineage-010, A=0.1137724551.
Most distant available architectural pair(s): lineage-004 / lineage-007, A=0.4610778443.

S interval counts: 2 singleton; 22 alignment-sensitive. Missing A: none. Missing S: 13 no scope-compatible Architecture optimum; 2 optimal-alignment enumeration limit; 6 Strategy work limit.

Average-linkage threshold grid (threshold: cluster count): 0.05: 10; 0.10: 10; 0.15: 9; 0.20: 8; 0.25: 6; 0.30: 3; 0.35: 1; 0.40: 1; 0.45: 1; 0.50: 1; 0.55: 1; 0.60: 1; 0.65: 1; 0.70: 1; 0.75: 1; 0.80: 1; 0.85: 1; 0.90: 1; 0.95: 1.

Continuous merge heights: 0.1137724551, 0.1972069237, 0.2324324324, 0.2359550562, 0.2852727921, 0.2859477124, 0.2981458775, 0.3012784292, 0.3418744074.

Legacy 0.30 clusters: {lineage-001, lineage-002, lineage-005, lineage-007, lineage-008, lineage-009}; {lineage-003}; {lineage-004, lineage-006, lineage-010}.

The 0.30 partition persists on [0.2981458775, 0.3012784292); merge heights are included at the lower bound.

## chmod/004

Closest available architectural pair(s): lineage-005 / lineage-006, A=0.1428571429.
Most distant available architectural pair(s): lineage-004 / lineage-009, A=0.3589743590.

S interval counts: 0 singleton; 2 alignment-sensitive. Missing A: 5 candidate extraction failure. Missing S: 5 no scope-compatible Architecture optimum; 5 candidate extraction failure; 2 Strategy work limit; 1 optimal-alignment enumeration limit.

Extraction unavailable for lineage-010: use of undeclared identifier 'S_ISVTX'. Full compiler diagnostics are retained in the JSON; flags were not changed.

Full-population threshold sensitivity, merge heights and 0.30 clusters are unavailable because the Architecture matrix is incomplete. No reduced-population clustering substitutes for them.

## sort/004

Closest available architectural pair(s): lineage-002 / lineage-007, A=0.1238095238.
Most distant available architectural pair(s): lineage-005 / lineage-008, A=0.4698795181.

S interval counts: 2 singleton; 14 alignment-sensitive. Missing A: none. Missing S: 1 Strategy work limit; 4 no scope-compatible Architecture optimum.

Average-linkage threshold grid (threshold: cluster count): 0.05: 7; 0.10: 7; 0.15: 6; 0.20: 4; 0.25: 3; 0.30: 2; 0.35: 2; 0.40: 1; 0.45: 1; 0.50: 1; 0.55: 1; 0.60: 1; 0.65: 1; 0.70: 1; 0.75: 1; 0.80: 1; 0.85: 1; 0.90: 1; 0.95: 1.

Continuous merge heights: 0.1238095238, 0.1568627451, 0.1746031746, 0.2202443649, 0.2979999741, 0.3780059342.

Legacy 0.30 clusters: {lineage-001, lineage-002, lineage-007, lineage-008, lineage-010}; {lineage-003, lineage-005}.

The 0.30 partition persists on [0.2979999741, 0.3780059342); merge heights are included at the lower bound.

## Interpretation and reproduction

Means weight unordered pairs equally. S averages available lower and upper endpoints separately; incomplete coverage is not a full-population estimate. Scope-incompatible optima, enumeration limits and extraction failures remain missing, never zero. Alignment intervals describe all enumerated admissible Architecture-optimal correspondences, not semantic homology. The inherited name-based exclusion policy affects S scope and coverage. A describes function decomposition and directed call/API connectivity, including external API atoms. Pairs share candidates and are dependent; these success-conditioned observations from one model/configuration do not establish generality, functional equivalence or security effects.

Average linkage, the existing 0.05–0.95 grid and continuous merge heights are descriptive. **0.30 is only the legacy reference; no threshold is selected or frozen.**

Validation checked committed candidate bytes (allowing CRLF-to-LF conversion), current header hashes, complete pair identity sets and frozen algorithm hashes. No tracked existing files or tests were changed. The historical reports reference Python test files that are absent from this checkout; those tests were not rerun.

Reproduce in the recorded WSL environment: `python3 docs/final_checkpoint_diversity_sample.py`. Use `--summarize-only` to recheck provenance and regenerate reports without recomputing pairs. The [combined machine-readable results](final_checkpoint_diversity_sample.json) include all pair measurements, identities, provenance checks, matrices and threshold summaries. [New computation evidence](final_checkpoint_diversity_new_pairwise.json) records compiler commands, diagnostics, preprocessing hashes and budgets. Historical evidence and frozen implementations are unchanged. No LLM calls, implementations, functional reruns or semantic-depth analysis were used.
