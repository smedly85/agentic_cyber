# Lineage analysis: grep

* Root: `/Users/sonjabrown/agentic_cyber/runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10`
* Model: `ollama/qwen3-coder-next-topk1:latest`  Temperature: 0.0
* Checkpoints: 000 -> 001 -> 002 -> 003 -> 004
* Configuration fingerprint: `c74cc26cf53ef4a86f79b090344a336a40caf37b3a23bd2339d523984664d797`

## Reliability

The denominator is every lineage started. A lineage that stopped is retained and counted; it is never replaced to keep the number of finals round.

* **lineages started = 10**
* **successful final implementations = 7**
* end-to-end completion rate = 0.700 (95% Wilson 0.397–0.892)

### Where lineages stopped

| checkpoint | lineages stopped here |
|---|---|
| 000 | 3 |
| 001 | 0 |
| 002 | 0 |
| 003 | 0 |
| 004 | 0 |

Reasons: agent_execution_failure × 2, no_progress × 1

## Per-checkpoint behavior

| checkpoint | flags | reached | passed | first try | after repair | mean repair loops | infra fail | agent fail |
|---|---|---|---|---|---|---|---|---|
| 000 base | `(none)` | 10 | 7 | 6 | 1 | 0.20 | 0 | 2 |
| 001 with-filename | `-H` | 7 | 7 | 6 | 1 | 0.14 | 0 | 0 |
| 002 no-filename | `-H -h` | 7 | 7 | 6 | 1 | 0.14 | 0 | 0 |
| 003 recursive | `-H -h -r` | 7 | 7 | 1 | 6 | 0.86 | 0 | 0 |
| 004 ignore-case | `-H -h -r -i` | 7 | 7 | 7 | 0 | 0.00 | 0 | 0 |

## Diversity (final population)

* **final** — 7 implementation(s) from 10 lineages started; report under `/Users/sonjabrown/agentic_cyber/runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10/analysis/populations/final/analysis`
* **checkpoint-000** — 7 implementation(s) from 10 lineages started; report under `/Users/sonjabrown/agentic_cyber/runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10/analysis/populations/checkpoint-000/analysis`
* **checkpoint-001** — 7 implementation(s) from 10 lineages started; report under `/Users/sonjabrown/agentic_cyber/runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10/analysis/populations/checkpoint-001/analysis`
* **checkpoint-002** — 7 implementation(s) from 10 lineages started; report under `/Users/sonjabrown/agentic_cyber/runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10/analysis/populations/checkpoint-002/analysis`
* **checkpoint-003** — 7 implementation(s) from 10 lineages started; report under `/Users/sonjabrown/agentic_cyber/runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10/analysis/populations/checkpoint-003/analysis`
* **checkpoint-004** — 7 implementation(s) from 10 lineages started; report under `/Users/sonjabrown/agentic_cyber/runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10/analysis/populations/checkpoint-004/analysis`

Final diversity compares only completed lineages. The number of lineages started is stated above and is not replaced by the number of finals.

**Baseline.** lineages share no seed, so the final population has no common prior source; a shared constant baseline keeps the clustering and pairwise metrics valid, so the view uses `empty_new_source`. Clustering, family, Vendi, discovery, repetition and pairwise-distance metrics are unaffected by that choice. These metrics in the view's report are **not** maintenance change and must not be read as such:

* `lines_added`
* `lines_deleted`
* `lines_edited`
* `files_edited`
* `tracked_files_edited`
* `untracked_files_created`
* `functions_edited_count`
* `functions_created_count`
* `functions_deleted_count`
* `gumtree_edit_actions`
* `gumtree_normalized_edit_distance`

Measured against an empty baseline these describe program size, not maintenance change; use per_stage_change instead.

## Change

* **Per stage** (28 successful transitions) — baseline: the source the stage was seeded with, i.e. checkpoint N-1's candidate in the same lineage. See `lineage_transitions.csv`.
* **Total per lineage** (7 completed) — baseline: that same lineage's checkpoint 000 source. Total change across the maintenance trajectory, not a single maintenance step. See `lineage_total_change.csv`.
