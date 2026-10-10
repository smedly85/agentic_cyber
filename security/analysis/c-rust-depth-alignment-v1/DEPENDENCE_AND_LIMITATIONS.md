# Dependence and limitations

## Population accounting

Rust: 45 frozen CVEs; 42 with numeric observations; 59 frozen mapping records; 61 planned context rows, 55 numeric and six nonnumeric; 45 distinct measured function/executable pairs. Ten extra rows repeat measurements across CVE associations. Deduplication uses saved graph identity and authenticated source-function identity, not equality of depth. Multiple executable contexts remain distinct; generic instances are already reduced by the saved diagnostic mapping policy. Every mapped function is retained in the function/CVE ledgers, including missing ones. Configuration-only CVEs have no numeric depth.

C frozen accounting: `{"all_final_dispositions": true, "cves_with_numeric_semantic_depth": 22, "depth_applicable_cves": 22, "measurement_unavailable_cves": 0, "non_depth_applicable_cves": 2, "nonnumeric_vulnerable_function_observations": 0, "numeric_vulnerable_function_observations": 27, "population_cves": 24, "raw_executable_contexts": 30, "unavailable_or_unresolved_cves": 0, "verified_vulnerable_function_observations": 27}`.

## Dependence and uncertainty

Repeated vulnerable functions, multiple locations in one CVE, and multiple CVEs on the same executable graph are dependent. CVE weighting fixes contribution weights; it does not create independence. We connect rows sharing a CVE, executable graph, or source-qualified vulnerable function, transitively. C function identities are conservatively joined across historical versions. The summary lists every component. Shared non-vulnerable helper code, releases and analyzer mechanisms create additional dependence.

No confidence intervals or hypothesis tests are calculated. These frozen purposive populations are not random language samples, and no calibrated model exists for incomplete graphs or missing mappings. Row-wise bootstrap intervals would be misleading. Instead we report leave-one-connected-component-out ranges of the CVE-weighted mean: remove all connected CVEs together, then recompute equal-CVE weighting. These are influence/robustness ranges, not 95% confidence intervals, sampling uncertainty, or bounds on the unknown true depth. There is no resampling unit because there is no bootstrap.

- c: 19 components; deletion ranges: {"library_contracted_depth": {"deleted_components": 19, "maximum": 2.1547619047619047, "minimum": 1.881578947368421}, "raw_depth": {"deleted_components": 19, "maximum": 2.25, "minimum": 1.986842105263158}}
- rust: 25 components; deletion ranges: {"closure_collapsed_raw_depth": {"deleted_components": 25, "maximum": 5.2075000000000005, "minimum": 4.294117647058823}, "entry_aligned_depth": {"deleted_components": 25, "maximum": 3.4325, "minimum": 2.323529411764706}, "entry_and_closure_depth": {"deleted_components": 25, "maximum": 3.2325000000000004, "minimum": 2.323529411764706}, "raw_depth": {"deleted_components": 25, "maximum": 5.407500000000001, "minimum": 4.294117647058823}}

## Evidence strength and missingness

Rust has zero independently verified vulnerability depths. All 55 measurements are provisional known-incomplete-graph observations despite authenticated source/compiler matches and full path witnesses. The independent methodological audit reported no numerical errors; that is not graph validation. Missing callback coverage can alter observed shortest depths and discover additional functions. No statistical adjustment repairs this.

C retains its canonical SVF status and scope fields, including any legacy scope qualifications and pilot reuse status. Independent mapping review is distinct from independent depth validation; this analysis does not promote C results or Rust results to a new validation tier. No accepted-C/provisional-Rust pooling is performed.

Missing Rust measurements, partially mapped CVEs, unsupported platforms and the differing historical packages/versions are explicit in the retained population ledger. A numerical CVE mean is conditional on measured mapped locations. Unknown locations are not silently assigned a minimum or zero; their effects cannot be bounded from this evidence.

## Maximum depth diagnostics only

Original Rust per-row Dmax and normalized depths remain in the Rust CSV; original per-program evidence and deepest witnesses remain in aligned_summary.json under diagnostic_only. They are not aligned cross-language outcomes. Closure frames increase counted depths along deepest witnesses and can change which endpoint maximizes shortest depth; a path-level closure correction cannot be assumed to give a corrected Dmax. Shared uucore error/formatting paths dominate many executable maxima, so those maxima are not independent utility-specific complexity measures. Omitted initializer/formatting callbacks undermine coverage of both numerator and denominator. There are no equivalent validated C Dmax measurements. Neither Dmax nor normalized depth supports a quantitative cross-language claim here.

## Paper use

Suitable for a carefully qualified descriptive/methodological paper section if it explicitly adopts the incomplete-graph observed-path estimand. Report C-aligned function and CVE-weighted units, denominators, missingness, original raw evidence, and paired counting sensitivities together. Label Rust provisional and distinguish C scope/validation. The observed mean gap partly reflects entry counting; remaining differences cannot be assigned to language. Close means or medians do not demonstrate statistical similarity or equivalence. No causal language-effect claim, population generalization, equivalence test, validated-depth claim, or normalized-depth comparison is supported.
