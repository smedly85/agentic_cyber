# Historical RUPTA diagnostic distribution — NOT ACCEPTED

Collection status: **complete_diagnostic_attempts** (29/29 executable groups).

All **45 CVEs** are retained. **42 CVEs** have numerical graph observations; **0** have independently verified depths. All numerical depths, maximum depths and ratios are provisional.

Units: 59 frozen CVE/source-function mapping records (49 in verified CVEs and 10 in partially mapped CVEs), 49 distinct source definitions, 61 executable/function/platform observations, 29 planned Linux executable graphs. 55 observations have numerical depths. The two partially mapped CVEs retain that classification even when individual frozen locations are measured.

## Distribution and counting

**CVE-level depth profiles (one contribution per CVE):** {'6': 3, '3': 9, '2': 4, '5': 9, '4': 7, '10,12,13': 1, '9,11,12': 1, '3,5': 1, '9': 1, '7': 2, '8,9': 1, '10': 1, '12': 1, '14': 1}. A profile such as `4,6` retains both depths; it does not select the shallower vulnerability.

**Single-valued observed CVE subset:** n=38; median 4; range 2–14. Frequency (value: count): 2: 4, 3: 9, 4: 7, 5: 9, 6: 3, 7: 2, 9: 1, 10: 1, 12: 1, 14: 1. This is a selected observed subset, not an estimate of the frozen population.

**Executable/function-level raw vulnerability depths:** n=55; median 5; range 2–14. Frequency (value: count): 2: 4, 3: 10, 4: 7, 5: 10, 6: 4, 7: 2, 8: 1, 9: 8, 10: 2, 11: 2, 12: 3, 13: 1, 14: 1.

**Executable-level primary maximum depths:** n=27; median 12; range 7–17. Frequency (value: count): 7: 1, 9: 1, 10: 1, 11: 4, 12: 15, 13: 3, 14: 1, 17: 1.

**Executable/function-level normalized depths:** n=55; median 0.416667; range 0.166667–0.928571. Frequency (value: count): 0.166667: 3, 0.181818: 1, 0.25: 8, 0.272727: 1, 0.333333: 7, 0.363636: 1, 0.384615: 1, 0.416667: 8, 0.454545: 1, 0.461538: 2, 0.5: 1, 0.538462: 1, 0.615385: 1, 0.692308: 8, 0.7: 1, 0.714286: 2, 0.785714: 2, 0.823529: 1, 0.857143: 4, 0.928571: 1. Displayed ratios are rounded; JSON/CSV retain full precision.

**Single-valued observed CVE normalized subset:** n=38; median 0.348485; range 0.166667–0.857143. Frequency (value: count): 0.166667: 3, 0.181818: 1, 0.25: 7, 0.272727: 1, 0.333333: 7, 0.363636: 1, 0.384615: 1, 0.416667: 7, 0.454545: 1, 0.461538: 1, 0.5: 1, 0.538462: 1, 0.692308: 1, 0.7: 1, 0.714286: 1, 0.823529: 1, 0.857143: 2. Multi-valued CVE profiles remain explicit in the CVE ledger and JSON.

All histograms include only numerical observations. Missing measurements are null, never zero. Repeated CVEs/functions sharing an executable do not multiply the executable Dmax distribution. Utility and platform breakdowns are in the results JSON.

## Complete CVE ledger

| CVE | Observed depths | Measured / planned locations | Status |
|---|---|---:|---|
| CVE-2021-29934 | 6 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35338 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35339 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35340 | 6 | 2/2 | provisional_all_listed_locations_observed |
| CVE-2026-35341 | 2 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35342 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35343 | 5 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35344 | 5 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35345 | 5 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35346 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35347 | 4 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35348 | — | 0/1 | no_numerical_observation |
| CVE-2026-35349 | 4 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35350 | 5 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35351 | 10, 12, 13 | 3/3 | provisional_all_listed_locations_observed |
| CVE-2026-35352 | 2 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35353 | 5 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35354 | 9, 11, 12 | 4/4 | provisional_all_listed_locations_observed |
| CVE-2026-35355 | 5 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35356 | 3, 5 | 2/2 | provisional_all_listed_locations_observed |
| CVE-2026-35357 | 9 | 3/3 | provisional_mapped_subset |
| CVE-2026-35358 | 7 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35359 | 8, 9 | 5/7 | provisional_mapped_subset |
| CVE-2026-35360 | 4 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35361 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35362 | — | 0/0 | not_applicable_configuration_only |
| CVE-2026-35363 | 5 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35364 | 10 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35365 | 12 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35366 | 2 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35367 | 4 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35368 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35369 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35370 | 2 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35371 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35372 | 4 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35373 | 4 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35374 | 6 | 1/2 | provisional_mapped_subset |
| CVE-2026-35375 | 5 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35376 | — | 0/2 | no_numerical_observation |
| CVE-2026-35377 | 14 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35378 | 7 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35379 | 4 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35380 | 3 | 1/1 | provisional_all_listed_locations_observed |
| CVE-2026-35381 | 5 | 1/1 | provisional_all_listed_locations_observed |

## Missing observations

- CVE-2026-35348 `uumain` (linux): build_or_analysis_failure; build=completed, mapping=authenticated_unique_declaration, reachability=not_assessed.
- CVE-2026-35359 `copy_on_write` (other_unix): unsupported_platform; build=platform_not_built, mapping=frozen_source_qualified, reachability=not_assessed.
- CVE-2026-35359 `copy_on_write` (macos): unsupported_platform; build=platform_not_built, mapping=frozen_source_qualified, reachability=not_assessed.
- CVE-2026-35374 `instantiate_current_writer` (windows): unsupported_platform; build=platform_not_built, mapping=frozen_source_qualified, reachability=not_assessed.
- CVE-2026-35376 `process_file` (linux): build_or_analysis_failure; build=failure, mapping=authenticated_unique_declaration, reachability=not_assessed.
- CVE-2026-35376 `change_file_context` (linux): build_or_analysis_failure; build=failure, mapping=authenticated_unique_declaration, reachability=not_assessed.

Failed executable diagnostics (complete commands and stderr are retained under build):

- `0.2.2/sort`: `/rustc-dev/8925ea358a0f265ca61026aadc7ecc506c545cbe/compiler/rustc_middle/src/ty/instance.rs:640:21: failed to resolve instance for std::ptr::drop_glue::<<std::iter::Flatten<std::io::Split<std::io::BufReader<std::boxed::Box<dyn std::io::Read + std::marker::Send>>>> as std::iter::Iterator>::Item>`
- `0.2.2/chcon`: `selinux-sys: Failed to find 'selinux/selinux.h'. Please make sure the C header files of libselinux are installed and accessible: Kind(NotFound)`

## Validity and comparison

Every numerical observation identifies an authenticated source declaration and compiler definition, retains all monomorphized instances, and has callsite witnesses for its shortest path. Program records retain a shortest path attaining Dmax. This validates the observed paths, not their global minimality under omitted calls. No numerical observation has been independently promoted.

Each executable has a separate coverage ledger listing recognized unresolved sites, unavailable bodies, reachable LazyLock/TLS mechanisms and formatting boundaries. Full owner-to-boundary exposure is preserved in hashed build artifacts. Initializer and Display omissions can hide implementation callbacks and can affect either metric; an absent mapped function in an incomplete graph is not declared semantically unreachable. No exact error bounds follow from these omissions.

Primary scope and entry match the preregistered RUPTA policy: selected utility plus reachable first-party uucore and authenticated generated project code, rooted at source main. A witnessed path through excluded dependencies counts one implementation transition and stops at the next included function. Both metrics use that same graph. Utility-only sensitivity is separate. Full dependency graphs remain supporting evidence.

Canonical Rust MIR files are unchanged and separately fingerprinted; they use a different entry and retained compiler-resolved graph. Existing C/SVF results are unchanged. Different analyzers, call resolution, wrapper/instance treatment and dependency-mediated projection prevent a claim of direct C/Rust numerical equivalence.

Separately labeled canonical MIR baseline: 48 numerical table rows; raw depth frequency {0: 5, 1: 10, 2: 6, 3: 10, 4: 3, 5: 3, 7: 1, 9: 2, 10: 2, 11: 3, 12: 3}. This is not the same scope/entry or a repair source for RUPTA, and the two distributions are not interchangeable.

**Readiness:** suitable as a reproducible diagnostic dataset with explicit missingness, not accepted historical findings. Before substantive paper comparisons, review frozen-function/compiler matches and graph scope, then establish that omitted implementation callbacks cannot materially change the reported metrics (or adopt an explicitly justified incomplete-graph estimand). Validate the cross-language counting policy separately. No new pointer-analysis development was performed.

See `REPRODUCTION.md`, the three CSV tables, `historical_rupta_results.json`, and `historical_rupta_coverage.json`.
