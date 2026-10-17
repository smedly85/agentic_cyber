# Longitudinal C structural-diversity results

This descriptive analysis covers 140 public-checkpoint-success candidate observations in 18 separate utility/checkpoint populations and 495 within-checkpoint unordered pairs. The frozen order-aware Architecture (A) and Strategy (S) implementations, `c11-posix2008-v1`, scope rules and comparator defaults are unchanged. The 102 final-checkpoint pair records were verified and reused; 393 earlier-checkpoint pair records were added. A missing result is a recorded outcome, not a zero distance.

Coverage accounting: 480/495 exact A outcomes and 363/495 available S intervals. These totals count records only; diversity statistics remain separate by utility, checkpoint and cohort.

**Cohorts.** All-stage includes every public-checkpoint-success candidate at that stage, preserving successes before later failure. Fixed-survivor uses final-checkpoint `final_population_member=true` lineage IDs for mkdir/grep/chmod and traces those IDs backwards. Earlier rows need not have that flag. **Sort is public-checkpoint-success exploratory throughout:** its fixed **public-completion** cohort is the seven lineages present at 004; those final candidates failed extra validation and are not end-to-end successful.

**Reading the tables.** A means are full-cohort MPD only with complete exact coverage. An asterisk marks an available-pair A mean, descriptive only; the full-cohort mean is unavailable. S intervals average the available lower and upper endpoints separately; they are never collapsed to scalars. Each denominator is the cohort's possible unordered-pair count. Feature columns summarize cumulative requirements; full recorded checkpoint metadata and prompt identities are in JSON. Rounding is for display only.

## mkdir

**All-stage cohort**

| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |
|---|---|---:|---:|---:|---:|---|
| 000 | create directory operands (base) | 7 | 21/21 | 0.090627 | 21/21 | [0.531536, 0.531536] |
| 001 | parents; cumulative -p | 7 | 21/21 | 0.139554 | 21/21 | [0.637245, 0.637245] |
| 002 | mode; cumulative -p -m | 7 | 21/21 | 0.200949 | 20/21 | [0.682493, 0.682588] |

**Fixed survivor cohort**

| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |
|---|---|---:|---:|---:|---:|---|
| 000 | create directory operands (base) | 7 | 21/21 | 0.090627 | 21/21 | [0.531536, 0.531536] |
| 001 | parents; cumulative -p | 7 | 21/21 | 0.139554 | 21/21 | [0.637245, 0.637245] |
| 002 | mode; cumulative -p -m | 7 | 21/21 | 0.200949 | 20/21 | [0.682493, 0.682588] |

Fixed lineage IDs: lineage-001, lineage-003, lineage-004, lineage-005, lineage-006, lineage-009, lineage-010.

All-stage: A MPD increases monotonically; the final-minus-base change is +0.110322. Fixed survivor: A MPD increases monotonically; the final-minus-base change is +0.110322.

There is no population attrition across these checkpoints.

All-stage and fixed cohorts contain the same lineage IDs at every checkpoint; their summaries coincide.

All-stage Strategy: Available-pair S endpoint trends are nondecreasing (lower) and nondecreasing (upper), with coverage 21/21 → 21/21 → 20/21. This describes available subsets, not a full-cohort scalar trajectory.

Fixed survivor Strategy: Available-pair S endpoint trends are nondecreasing (lower) and nondecreasing (upper), with coverage 21/21 → 21/21 → 20/21. This describes available subsets, not a full-cohort scalar trajectory.

Same fixed-cohort lineage-pair A changes (later minus earlier; equal means exact rational equality):

| Transition | Paired coverage | Increased | Decreased | Equal | Unavailable | Mean ΔA | Median ΔA | ΔA range |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 000→001 | 21/21 | 9 | 9 | 3 | 0 | 0.048928 | 0.000000 | [-0.123377, 0.319149] |
| 001→002 | 21/21 | 17 | 4 | 0 | 0 | 0.061394 | 0.069585 | [-0.036742, 0.200000] |

Paired changes use only the same lineage pair measured at both stages. They separate changing pair composition from measured distance changes, but not the effects of added feature requirements.

## grep

**All-stage cohort**

| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |
|---|---|---:|---:|---:|---:|---|
| 000 | fixed-string line selection (base) | 10 | 45/45 | 0.338418 | 33/45 | [0.602409, 0.612759] |
| 001 | with-filename; cumulative -H | 10 | 45/45 | 0.342009 | 33/45 | [0.584234, 0.597436] |
| 002 | no-filename; cumulative -H -h | 10 | 45/45 | 0.342009 | 33/45 | [0.596509, 0.608127] |
| 003 | recursive; cumulative -H -h -r | 10 | 45/45 | 0.308075 | 29/45 | [0.601885, 0.613552] |
| 004 | ignore-case; cumulative -H -h -r -i | 10 | 45/45 | 0.309137 | 24/45 | [0.625018, 0.641619] |

**Fixed survivor cohort**

| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |
|---|---|---:|---:|---:|---:|---|
| 000 | fixed-string line selection (base) | 10 | 45/45 | 0.338418 | 33/45 | [0.602409, 0.612759] |
| 001 | with-filename; cumulative -H | 10 | 45/45 | 0.342009 | 33/45 | [0.584234, 0.597436] |
| 002 | no-filename; cumulative -H -h | 10 | 45/45 | 0.342009 | 33/45 | [0.596509, 0.608127] |
| 003 | recursive; cumulative -H -h -r | 10 | 45/45 | 0.308075 | 29/45 | [0.601885, 0.613552] |
| 004 | ignore-case; cumulative -H -h -r -i | 10 | 45/45 | 0.309137 | 24/45 | [0.625018, 0.641619] |

Fixed lineage IDs: lineage-001, lineage-002, lineage-003, lineage-004, lineage-005, lineage-006, lineage-007, lineage-008, lineage-009, lineage-010.

All-stage: A MPD fluctuates; the final-minus-base change is -0.029281. Fixed survivor: A MPD fluctuates; the final-minus-base change is -0.029281.

There is no population attrition across these checkpoints.

All-stage and fixed cohorts contain the same lineage IDs at every checkpoint; their summaries coincide.

All-stage Strategy: Available-pair S endpoint trends are fluctuating (lower) and fluctuating (upper), with coverage 33/45 → 33/45 → 33/45 → 29/45 → 24/45. This describes available subsets, not a full-cohort scalar trajectory.

Fixed survivor Strategy: Available-pair S endpoint trends are fluctuating (lower) and fluctuating (upper), with coverage 33/45 → 33/45 → 33/45 → 29/45 → 24/45. This describes available subsets, not a full-cohort scalar trajectory.

Same fixed-cohort lineage-pair A changes (later minus earlier; equal means exact rational equality):

| Transition | Paired coverage | Increased | Decreased | Equal | Unavailable | Mean ΔA | Median ΔA | ΔA range |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 000→001 | 45/45 | 19 | 10 | 16 | 0 | 0.003591 | 0.000000 | [-0.025266, 0.035941] |
| 001→002 | 45/45 | 0 | 0 | 45 | 0 | 0.000000 | 0.000000 | [0.000000, 0.000000] |
| 002→003 | 45/45 | 11 | 34 | 0 | 0 | -0.033934 | -0.026614 | [-0.179012, 0.085840] |
| 003→004 | 45/45 | 26 | 19 | 0 | 0 | 0.001061 | 0.001542 | [-0.046469, 0.032326] |

Paired changes use only the same lineage pair measured at both stages. They separate changing pair composition from measured distance changes, but not the effects of added feature requirements.

## chmod

**All-stage cohort**

| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |
|---|---|---:|---:|---:|---:|---|
| 000 | octal/symbolic permission changes (base) | 7 | 21/21 | 0.195994 | 21/21 | [0.575722, 0.585856] |
| 001 | recursive; cumulative -R | 6 | 15/15 | 0.218006 | 13/15 | [0.634032, 0.642837] |
| 002 | changes; cumulative -R -c | 6 | 10/15 | 0.234990* | 3/15 | [0.676088, 0.687597] |
| 003 | verbose; cumulative -R -c -v | 6 | 10/15 | 0.246377* | 3/15 | [0.685648, 0.698011] |
| 004 | silent; cumulative -R -c -v -f | 6 | 10/15 | 0.258514* | 2/15 | [0.677028, 0.684373] |

**Fixed survivor cohort**

| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |
|---|---|---:|---:|---:|---:|---|
| 000 | octal/symbolic permission changes (base) | 6 | 15/15 | 0.190516 | 15/15 | [0.585599, 0.596913] |
| 001 | recursive; cumulative -R | 6 | 15/15 | 0.218006 | 13/15 | [0.634032, 0.642837] |
| 002 | changes; cumulative -R -c | 6 | 10/15 | 0.234990* | 3/15 | [0.676088, 0.687597] |
| 003 | verbose; cumulative -R -c -v | 6 | 10/15 | 0.246377* | 3/15 | [0.685648, 0.698011] |
| 004 | silent; cumulative -R -c -v -f | 6 | 10/15 | 0.258514* | 2/15 | [0.677028, 0.684373] |

Fixed lineage IDs: lineage-004, lineage-005, lineage-006, lineage-007, lineage-009, lineage-010.

All-stage: Complete-cohort A is 0.195994 at 000 and 0.218006 at 001. The available-pair mean increases monotonically, but its measured pair set changes. The incomplete full-cohort trajectory does not establish an overall full-cohort direction. Fixed survivor: Complete-cohort A is 0.190516 at 000 and 0.218006 at 001. The available-pair mean increases monotonically, but its measured pair set changes. The incomplete full-cohort trajectory does not establish an overall full-cohort direction.

Population attrition: 001 loses lineage-008.

The cohort memberships differ at 000; their means use different lineage-pair sets at those stages. Later cohort memberships coincide.

All-stage Strategy: Available-pair S endpoint trends are fluctuating (lower) and fluctuating (upper), with coverage 21/21 → 13/15 → 3/15 → 3/15 → 2/15. This describes available subsets, not a full-cohort scalar trajectory.

Fixed survivor Strategy: Available-pair S endpoint trends are fluctuating (lower) and fluctuating (upper), with coverage 15/15 → 13/15 → 3/15 → 3/15 → 2/15. This describes available subsets, not a full-cohort scalar trajectory.

Same fixed-cohort lineage-pair A changes (later minus earlier; equal means exact rational equality):

| Transition | Paired coverage | Increased | Decreased | Equal | Unavailable | Mean ΔA | Median ΔA | ΔA range |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 000→001 | 15/15 | 9 | 6 | 0 | 0 | 0.027490 | 0.019852 | [-0.027930, 0.097214] |
| 001→002 | 10/15 | 6 | 4 | 0 | 5 | 0.011079 | 0.011276 | [-0.014487, 0.039792] |
| 002→003 | 10/15 | 7 | 3 | 0 | 5 | 0.011387 | 0.016789 | [-0.014672, 0.030412] |
| 003→004 | 10/15 | 7 | 3 | 0 | 5 | 0.012137 | 0.011391 | [-0.009039, 0.038713] |

Paired changes use only the same lineage pair measured at both stages. They separate changing pair composition from measured distance changes, but not the effects of added feature requirements.

## sort — public-success-only exploratory

**All-stage cohort**

| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |
|---|---|---:|---:|---:|---:|---|
| 000 | bytewise stdin line sorting (base) | 8 | 28/28 | 0.387438 | 28/28 | [0.681239, 0.734934] |
| 001 | reverse; cumulative -r | 8 | 28/28 | 0.383706 | 24/28 | [0.692300, 0.728771] |
| 002 | ignore-case; cumulative -r -f | 8 | 28/28 | 0.372756 | 22/28 | [0.696550, 0.730194] |
| 003 | unique; cumulative -r -f -u | 7 | 21/21 | 0.334398 | 17/21 | [0.672674, 0.689946] |
| 004 | check; cumulative -r -f -u -c | 7 | 21/21 | 0.307801 | 16/21 | [0.653383, 0.697353] |

**Fixed public-completion cohort**

| Checkpoint | Feature requirements | n | Exact A coverage | Mean A | S coverage | Available-pair S interval |
|---|---|---:|---:|---:|---:|---|
| 000 | bytewise stdin line sorting (base) | 7 | 21/21 | 0.400656 | 21/21 | [0.671429, 0.735771] |
| 001 | reverse; cumulative -r | 7 | 21/21 | 0.394625 | 17/21 | [0.683739, 0.725776] |
| 002 | ignore-case; cumulative -r -f | 7 | 21/21 | 0.373182 | 15/21 | [0.693862, 0.724499] |
| 003 | unique; cumulative -r -f -u | 7 | 21/21 | 0.334398 | 17/21 | [0.672674, 0.689946] |
| 004 | check; cumulative -r -f -u -c | 7 | 21/21 | 0.307801 | 16/21 | [0.653383, 0.697353] |

Fixed lineage IDs: lineage-001, lineage-002, lineage-003, lineage-005, lineage-007, lineage-008, lineage-010.

All-stage: A MPD decreases monotonically; the final-minus-base change is -0.079637. Fixed public-completion: A MPD decreases monotonically; the final-minus-base change is -0.092855.

Population attrition: 003 loses lineage-009.

The cohort memberships differ at 000, 001, 002; their means use different lineage-pair sets at those stages. Later cohort memberships coincide.

All-stage Strategy: Available-pair S endpoint trends are fluctuating (lower) and fluctuating (upper), with coverage 28/28 → 24/28 → 22/28 → 17/21 → 16/21. This describes available subsets, not a full-cohort scalar trajectory.

Fixed public-completion Strategy: Available-pair S endpoint trends are fluctuating (lower) and fluctuating (upper), with coverage 21/21 → 17/21 → 15/21 → 17/21 → 16/21. This describes available subsets, not a full-cohort scalar trajectory.

Same fixed-cohort lineage-pair A changes (later minus earlier; equal means exact rational equality):

| Transition | Paired coverage | Increased | Decreased | Equal | Unavailable | Mean ΔA | Median ΔA | ΔA range |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 000→001 | 21/21 | 6 | 15 | 0 | 0 | -0.006030 | -0.022222 | [-0.055717, 0.120511] |
| 001→002 | 21/21 | 0 | 21 | 0 | 0 | -0.021443 | -0.022176 | [-0.034926, -0.006619] |
| 002→003 | 21/21 | 3 | 18 | 0 | 0 | -0.038784 | -0.038402 | [-0.097285, 0.023810] |
| 003→004 | 21/21 | 0 | 21 | 0 | 0 | -0.026596 | -0.027788 | [-0.054252, -0.002404] |

Paired changes use only the same lineage pair measured at both stages. They separate changing pair composition from measured distance changes, but not the effects of added feature requirements.

## Pair extrema, uncertainty and missingness

Every pair in the extrema column is a **measured-pair** extremum. Missing comparisons can conceal more extreme pairs. Lineage numbers below abbreviate `lineage-NNN`. I/V counts are alignment-invariant (singleton S interval) and alignment-sensitive (nonzero-width S interval), not claims of unique alignments. Identical cohort results are shown together; all 36 separate cohort summaries are retained in JSON/CSV.

Missing-reason codes: **scope** = `no_scope_compatible_architecture_optimum`; **work** = `comparison_work_limit`; **optima** = `architecture_optima_not_exhausted:optimal_alignment_count_limit`; **extract** = `candidate_extraction_or_provenance_unavailable`. Any other reason is shown verbatim. JSON lists exact reasons for every unavailable pair.

| Population | Cohort | Closest A: pair(s), distance | Most distant A: pair(s), distance | S I/V | Missing A | Missing S |
|---|---|---|---|---|---|---|
| mkdir/000 | both | 001/003; 001/004; 001/006; 001/009; 003/004; 003/006; 003/009; 004/006; 004/009; 006/009, 0.000000 | 001/010; 003/010; 004/010; 006/010; 009/010, 0.214286 | 21/0 | none | none |
| mkdir/001 | both | 003/004; 003/006; 004/006, 0.000000 | 001/010, 0.384615 | 21/0 | none | none |
| mkdir/002 | both | 004/005, 0.044776 | 001/006, 0.391304 | 19/1 | none | scope: 1 |
| grep/000 | both | 006/010, 0.106796 | 004/007, 0.511111 | 20/13 | none | scope: 12 |
| grep/001 | both | 006/010, 0.128713 | 004/007, 0.516484 | 20/13 | none | scope: 12 |
| grep/002 | both | 006/010, 0.128713 | 004/007, 0.516484 | 20/13 | none | scope: 12 |
| grep/003 | both | 006/010, 0.105590 | 004/007, 0.448718 | 10/19 | none | scope: 11; work: 4; optima: 1 |
| grep/004 | both | 006/010, 0.113772 | 004/007, 0.461078 | 2/22 | none | scope: 13; optima: 2; work: 6 |
| chmod/000 | all-stage | 005/006, 0.076923 | 006/009, 0.278689 | 14/7 | none | none |
| chmod/000 | fixed | 005/006, 0.076923 | 006/009, 0.278689 | 9/6 | none | none |
| chmod/001 | both | 005/006, 0.095652 | 006/009, 0.312500 | 6/7 | none | scope: 1; optima: 1 |
| chmod/002 | both | 005/006, 0.124088 | 004/009, 0.306667 | 1/2 | extract: 5 | scope: 5; extract: 5; work: 1; optima: 1 |
| chmod/003 | both | 005/006, 0.121622 | 004/009, 0.320261 | 0/3 | extract: 5 | scope: 4; extract: 5; work: 2; optima: 1 |
| chmod/004 | both | 005/006, 0.142857 | 004/009, 0.358974 | 0/2 | extract: 5 | scope: 5; extract: 5; work: 2; optima: 1 |
| sort/000 | all-stage | 003/009, 0.040000 | 001/003, 0.633333 | 9/19 | none | none |
| sort/000 | fixed | 001/008, 0.135135 | 001/003, 0.633333 | 4/17 | none | none |
| sort/001 | all-stage | 003/009, 0.037037 | 001/003, 0.593750 | 9/15 | none | scope: 4 |
| sort/001 | fixed | 001/008, 0.150000 | 001/003, 0.593750 | 4/13 | none | scope: 4 |
| sort/002 | all-stage | 003/009, 0.071429 | 001/003; 001/009, 0.558824 | 10/12 | none | scope: 6 |
| sort/002 | fixed | 001/008, 0.142857 | 001/003, 0.558824 | 6/9 | none | scope: 6 |
| sort/003 | both | 002/007, 0.126214 | 005/008, 0.518987 | 9/8 | none | scope: 4 |
| sort/004 | both | 002/007, 0.123810 | 005/008, 0.469880 | 2/14 | none | work: 1; scope: 4 |

Extraction failures (unchanged compiler flags; no candidate repairs):

- chmod/002 lineage-010: ValueError:extraction:compiler_failure:; use of undeclared identifier 'S_ISVTX'.
- chmod/003 lineage-010: ValueError:extraction:compiler_failure:; use of undeclared identifier 'S_ISVTX'.
- chmod/004 lineage-010: ValueError:extraction:compiler_failure:; use of undeclared identifier 'S_ISVTX'.

## Exploratory Architecture threshold sensitivity

The unchanged average-linkage method is evaluated at 0.05–0.95 in 0.05 steps. Full grid partitions, statistics and continuous stability intervals are in JSON. The table lists continuous merge heights and legacy 0.30 assignments; merge height ≤ threshold merges clusters. **0.30 is a reference only, not a selected or calibrated primary threshold.** Incomplete matrices have no clustering, imputation or candidate-dropping substitute.

| Population | Cohort | Continuous A merge heights | Lineage clusters at legacy 0.30 |
|---|---|---|---|
| mkdir/000 | both | 0.000000, 0.000000, 0.000000, 0.000000, 0.062500, 0.184066 | {001,003,004,005,006,009,010} |
| mkdir/001 | both | 0.000000, 0.000000, 0.034483, 0.061224, 0.088259, 0.334402 | {001}; {003,004,005,006,009,010} |
| mkdir/002 | both | 0.044776, 0.077899, 0.126437, 0.159744, 0.176713, 0.341814 | {001}; {003,004,005,006,009,010} |
| grep/000 | both | 0.106796, 0.190476, 0.212766, 0.245307, 0.252884, 0.280748, 0.304419, 0.374623, 0.387447 | {001,002,007,008}; {003,004,006,010}; {005}; {009} |
| grep/001 | both | 0.128713, 0.187500, 0.188801, 0.247315, 0.254358, 0.280869, 0.304545, 0.374554, 0.396056 | {001,002,007,008}; {003,004,006,010}; {005}; {009} |
| grep/002 | both | 0.128713, 0.187500, 0.188801, 0.247315, 0.254358, 0.280869, 0.304545, 0.374554, 0.396056 | {001,002,007,008}; {003,004,006,010}; {005}; {009} |
| grep/003 | both | 0.105590, 0.184252, 0.221557, 0.224719, 0.273891, 0.283165, 0.288975, 0.303513, 0.343174 | {001,002,007}; {003,004,006,010}; {005,008,009} |
| grep/004 | both | 0.113772, 0.197207, 0.232432, 0.235955, 0.285273, 0.285948, 0.298146, 0.301278, 0.341874 | {001,002,005,007,008,009}; {003}; {004,006,010} |
| chmod/000 | all-stage | 0.076923, 0.115385, 0.124345, 0.207977, 0.229341, 0.241263 | {004,005,006,007,008,009,010} |
| chmod/000 | fixed | 0.076923, 0.115385, 0.124345, 0.233398, 0.246892 | {004,005,006,007,009,010} |
| chmod/001 | both | 0.095652, 0.147650, 0.185185, 0.209909, 0.286898 | {004,005,006,007,009,010} |
| chmod/002 | both | unavailable: incomplete matrix | unavailable |
| chmod/003 | both | unavailable: incomplete matrix | unavailable |
| chmod/004 | both | unavailable: incomplete matrix | unavailable |
| sort/000 | all-stage | 0.040000, 0.135135, 0.162791, 0.184906, 0.279019, 0.336765, 0.497276 | {001,008}; {002,007}; {003,005,009,010} |
| sort/000 | fixed | 0.135135, 0.162791, 0.169811, 0.309833, 0.336765, 0.498276 | {001,008}; {002,007}; {003,010}; {005} |
| sort/001 | all-stage | 0.037037, 0.150000, 0.155556, 0.225000, 0.283883, 0.381932, 0.472789 | {001,008}; {002,007,010}; {003,005,009} |
| sort/001 | fixed | 0.150000, 0.155556, 0.250000, 0.283883, 0.381932, 0.487222 | {001,008}; {002,007,010}; {003,005} |
| sort/002 | all-stage | 0.071429, 0.142857, 0.148936, 0.230769, 0.270510, 0.363921, 0.459190 | {001,008}; {002,007,010}; {003,005,009} |
| sort/002 | fixed | 0.142857, 0.148936, 0.230769, 0.270510, 0.363921, 0.458971 | {001,008}; {002,007,010}; {003,005} |
| sort/003 | both | 0.126214, 0.166667, 0.180328, 0.237834, 0.336192, 0.405632 | {001,008}; {002,007,010}; {003,005} |
| sort/004 | both | 0.123810, 0.156863, 0.174603, 0.220244, 0.298000, 0.378006 | {001,002,007,008,010}; {003,005} |

## Interpretation and limitations

Attrition changes the all-stage population, while fixed cohorts hold lineage identity constant. Extraction and comparator limits instead change measurement coverage within a cohort. Neither is a measured distance change. Each feature checkpoint also changes the requested functionality: a longitudinal difference is not proof of autonomous drift alone. Available-pair S interval trajectories are descriptive of the observed subsets; changing coverage and interval width prevent reading them as a full-population scalar trend.

A describes function decomposition and directed call/API connectivity, including external API atoms. S retains the inherited name-based helper-exclusion policy and evaluates compatible Architecture-optimal alignments. Helper naming can change inclusion and coverage; singleton intervals need not imply one alignment. Exhaustion and incompatibility remain unavailable. No full-population S family counts are reported from incomplete matrices. These syntax/structure measures do not establish behavioral equivalence or security effects. Pairs sharing candidates are dependent; no significance tests or cross-utility inferential treatment-effect comparisons are made. Results are conditional on the observed public successes and this generation configuration.

## RQ2 results paragraph

Across 140 existing C candidate observations in 18 public-checkpoint-success populations, we evaluated 495 within-checkpoint pairs using the frozen order-aware Architecture and Strategy measures. For mkdir, the fixed-survivor Architecture mean trajectory was 0.090627 → 0.139554 → 0.200949 (exact-pair coverage: 21/21, 21/21, 21/21). For grep, the fixed-survivor Architecture mean trajectory was 0.338418 → 0.342009 → 0.342009 → 0.308075 → 0.309137 (exact-pair coverage: 45/45, 45/45, 45/45, 45/45, 45/45). For chmod, the fixed-survivor Architecture mean trajectory was 0.190516 → 0.218006 → 0.234990* → 0.246377* → 0.258514* (exact-pair coverage: 15/15, 15/15, 10/15, 10/15, 10/15). For sort, the fixed public-completion Architecture mean trajectory was 0.400656 → 0.394625 → 0.373182 → 0.334398 → 0.307801 (exact-pair coverage: 21/21, 21/21, 21/21, 21/21, 21/21). Final available-pair mean Strategy intervals were mkdir [0.682493, 0.682588] (20/21 pairs); grep [0.625018, 0.641619] (24/45 pairs); chmod [0.677028, 0.684373] (2/15 pairs); sort [0.653383, 0.697353] (16/21 pairs). Asterisks identify available-pair descriptions where full-cohort means are unavailable. All-stage and fixed-cohort views expose population-membership changes, while adjacent fixed-lineage-pair comparisons describe structural-distance changes among the pairs measured at both stages. Strategy results remain coverage-qualified intervals rather than scalars. Sort is exploratory public-checkpoint success only: its final candidates failed extra validation. These descriptive trajectories reflect both evolving implementations and added feature requirements, and do not identify autonomous drift or an inferential effect across utilities.

## Reproduction and checks

`python3 docs/checkpoint_diversity_trajectories.py` resumes completed measurements and writes reports. `--summarize-only` revalidates provenance and regenerates outputs without extraction or comparison. The durable [measurement journal](checkpoint_diversity_measurements.json) records candidates, all 495 pair outcomes, compiler diagnostics, raw/LF hashes and command provenance. ASTs and representations are cached under `build/checkpoint-diversity-trajectories/`. Final-checkpoint candidates are not re-extracted. The journal is atomically saved before and after each operation; completed failures are never retried. After interruption a completed worker result is recovered, while an interrupted extraction or comparison without a result remains explicitly unavailable.

Budget-charged new comparison time was 538.55 seconds, within the prespecified 3,600-second total and 900-second per-population budgets. The existing 100-second pair-process guard, 45-second alignment/Strategy limits, 128-optimum limit, 2,000,000 Strategy work-unit limit and extraction timeouts were retained. Interrupted work is conservatively charged the full 100-second pair guard; this budget counter is not a pure wall-time benchmark. A completed worker result survives a journal-write interruption and is recovered without recomputation. Journal-write retries do not retry measurements. No failed measurement received increased limits.

Checks verified manifest and committed source identities; formal run, checkpoint and lineage membership; raw and LF-normalized source hashes separately; historical profile and algorithm hashes; compiler and header hashes; 140/18/495 counts; all 36 cohort summaries; 468 fixed-cohort selected pair records; rational Architecture means; missingness accounting; incomplete-matrix clustering guards; all four final summaries against historical results; and 14 adjacent fixed-lineage-pair transitions. Resume regression checks on in-memory copies forbid all compiler/worker calls and verify completed-outcome skipping, worker-result recovery, and explicit missingness when interrupted work has no output. Historical reports reference `tests/test_ordered_*.py` files that are absent in this checkout, so those tests were not rerun. Existing candidate, metric, historical result and test files were preserved. No new generations, functional reruns, security-depth changes, threshold selection, commits or pushes were performed.

Outputs: [JSON results](checkpoint_diversity_trajectories.json), [36-row CSV](checkpoint_diversity_trajectories.csv), [runner](checkpoint_diversity_trajectories.py), [reporting code](checkpoint_diversity_reporting.py).
