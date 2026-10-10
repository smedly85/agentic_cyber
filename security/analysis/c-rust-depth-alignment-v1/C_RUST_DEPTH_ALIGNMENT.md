# C/Rust historical depth alignment v1

Separate statistical postprocessing of saved evidence. Canonical data and analyzers are unchanged. All Rust values remain provisional observations of known-incomplete graphs; zero Rust depths are independently verified.

## Units and distributions

The C rule is `security/historical/v2_statistics.py:build_statistics`: arithmetic mean over measured executable contexts within each `(CVE, source-qualified vulnerable function)`, followed by equal function weights within each CVE. We reproduce the canonical C statistics before deriving sensitivities. Missing values are excluded from arithmetic, never replaced by zero. A CVE mean retains every measured mapped function; it is not the shallowest location. Partially mapped CVEs retain their original qualification. The selected 38 single-valued Rust CVEs are not used.

| Language / unit | Policy | N | Mean | Median | Range |
|---|---|---:|---:|---:|---|
| c / executable_function | raw_depth | 30 | 2.000000 | 2 | 0–4 |
| c / executable_function | library_contracted_depth | 30 | 1.933333 | 2 | 0–4 |
| c / deduplicated_function_executable | raw_depth | 28 | 1.964286 | 2 | 0–4 |
| c / deduplicated_function_executable | library_contracted_depth | 28 | 1.892857 | 2 | 0–4 |
| c / cve_function | raw_depth | 27 | 1.981481 | 2 | 0–4 |
| c / cve_function | library_contracted_depth | 27 | 1.907407 | 2 | 0–4 |
| c / cve_weighted | raw_depth | 22 | 2.147727 | 2 | 0–4 |
| c / cve_weighted | library_contracted_depth | 22 | 2.056818 | 2 | 0–4 |
| rust / executable_function | raw_depth | 55 | 6.163636 | 5 | 2–14 |
| rust / executable_function | entry_aligned_depth | 55 | 4.181818 | 3 | 0–12 |
| rust / executable_function | closure_collapsed_raw_depth | 55 | 5.836364 | 5 | 2–14 |
| rust / executable_function | entry_and_closure_depth | 55 | 3.854545 | 3 | 0–12 |
| rust / deduplicated_function_executable | raw_depth | 45 | 6.022222 | 5 | 2–14 |
| rust / deduplicated_function_executable | entry_aligned_depth | 45 | 4.044444 | 3 | 0–12 |
| rust / deduplicated_function_executable | closure_collapsed_raw_depth | 45 | 5.711111 | 5 | 2–14 |
| rust / deduplicated_function_executable | entry_and_closure_depth | 45 | 3.733333 | 3 | 0–12 |
| rust / cve_function | raw_depth | 53 | 6.084906 | 5 | 2–14 |
| rust / cve_function | entry_aligned_depth | 53 | 4.103774 | 3 | 0–12 |
| rust / cve_function | closure_collapsed_raw_depth | 53 | 5.783019 | 5 | 2–14 |
| rust / cve_function | entry_and_closure_depth | 53 | 3.801887 | 3 | 0–12 |
| rust / cve_weighted | raw_depth | 42 | 5.245238 | 4.5 | 2–14 |
| rust / cve_weighted | entry_aligned_depth | 42 | 3.269048 | 2.5 | 0–12 |
| rust / cve_weighted | closure_collapsed_raw_depth | 42 | 5.054762 | 4.5 | 2–14 |
| rust / cve_weighted | entry_and_closure_depth | 42 | 3.078571 | 2.5 | 0–12 |

### Exact frequencies at the C-aligned `(CVE,function)` unit

- c raw_depth: {"0.0": 4, "1.0": 5, "1.5": 1, "2.0": 8, "3.0": 5, "4.0": 4}
- c library_contracted_depth: {"0.0": 4, "1.0": 5, "1.5": 1, "2.0": 9, "3.0": 5, "4.0": 3}
- rust raw_depth: {"2.0": 4, "3.0": 10, "4.0": 7, "5.0": 10, "6.0": 3, "7.0": 2, "8.0": 1, "9.0": 7, "10.0": 2, "10.5": 1, "11.0": 2, "12.0": 2, "13.0": 1, "14.0": 1}
- rust entry_aligned_depth: {"0.0": 4, "1.0": 10, "2.0": 7, "3.0": 10, "4.0": 2, "5.0": 3, "6.0": 1, "7.0": 7, "8.0": 2, "8.5": 1, "9.0": 2, "10.0": 2, "11.0": 1, "12.0": 1}
- rust closure_collapsed_raw_depth: {"2.0": 4, "3.0": 10, "4.0": 7, "5.0": 10, "6.0": 3, "7.0": 2, "8.0": 3, "8.5": 1, "9.0": 9, "10.0": 2, "11.0": 1, "14.0": 1}
- rust entry_and_closure_depth: {"0.0": 4, "1.0": 10, "2.0": 7, "3.0": 10, "4.0": 2, "5.0": 3, "6.0": 3, "6.5": 1, "7.0": 9, "8.0": 2, "9.0": 1, "12.0": 1}

### Rust original-row frequencies (55 measured rows)

- raw_depth: {"2": 4, "3": 10, "4": 7, "5": 10, "6": 4, "7": 2, "8": 1, "9": 8, "10": 2, "11": 2, "12": 3, "13": 1, "14": 1}
- entry_aligned_depth: {"0": 4, "1": 10, "2": 7, "3": 10, "4": 3, "5": 3, "6": 1, "7": 8, "8": 2, "9": 2, "10": 3, "11": 1, "12": 1}
- closure_collapsed_raw_depth: {"2": 4, "3": 10, "4": 7, "5": 10, "6": 4, "7": 2, "8": 4, "9": 10, "10": 2, "11": 1, "14": 1}
- entry_and_closure_depth: {"0": 4, "1": 10, "2": 7, "3": 10, "4": 3, "5": 3, "6": 4, "7": 10, "8": 2, "9": 1, "12": 1}

## Entry and closure sensitivities

The entry sensitivity counts transitions from the handwritten utility entry body. The verified 0.2.2 prefix is `bin!`-generated binary main → `#[uucore::main]`-generated outer uumain → handwritten inner uumain. Saved compiler DefIds, source locations, source hashes and full transition witnesses are checked per observation. The 0.0.3 od procedural macro calls handwritten uumain directly: only one transition is removed (6 → 5). This is not an unconditional subtraction. Every adjusted depth is checked nonnegative.

Closure identification requires compiler `def_kind == Closure` and the exact lexical parent in the compiler DefId path earlier in the saved witness, with the same source file. Generic arguments containing the word Closure are not classification evidence. Each closure frame is attributed to that defining parent; ordinary named helpers, including callback-invoking helpers, remain. Full witnesses and exact compiler identities are in `alignment_evidence.json`.

**Sensitivity estimand:** these are frame-count contractions on the saved original shortest-path witnesses. They are not newly optimized shortest distances in a quotient graph. Alternate paths could become shorter after contraction; no claim of exhaustiveness or exact graph-policy equivalence is made. This paired witness analysis isolates counting choices while retaining the original graph depths as primary evidence.

Closure contraction changes 9 of 55 measured rows; reduction distribution: {0: 46, 1: 1, 2: 7, 3: 1}. Entry reduction distribution: {1: 1, 2: 54}.

### Every closure-changed observation

| Observation | Raw | Entry aligned | Entry + closure | Closure frames removed |
|---|---:|---:|---:|---:|
| CVE-2026-35351:0:mv:linux | 10 | 8 | 6 | 2 |
| CVE-2026-35351:1:mv:linux | 13 | 11 | 9 | 2 |
| CVE-2026-35351:2:mv:linux | 12 | 10 | 8 | 2 |
| CVE-2026-35354:0:cp:linux | 9 | 7 | 6 | 1 |
| CVE-2026-35354:0:mv:linux | 12 | 10 | 7 | 3 |
| CVE-2026-35354:1:mv:linux | 11 | 9 | 7 | 2 |
| CVE-2026-35354:2:mv:linux | 11 | 9 | 7 | 2 |
| CVE-2026-35364:0:mv:linux | 10 | 8 | 6 | 2 |
| CVE-2026-35365:0:mv:linux | 12 | 10 | 8 | 2 |

## C library sensitivity

The saved C paths contain intermediate gnulib frames only in the rm observation below. `m4/gnulib-comp.m4` lists `lib/fts.c`; definitions and saved SVF function identities support removing `fts_read` and `fts_build` as intermediates. Vulnerable endpoints `opendirat`, `parse_datetime`, and `make_path` are retained, including when they belong to lib/. Ordinary src/ helpers remain.

- CVE-2015-1865:0:coreutils-8.4/rm: 4 → 2; path: src/rm.c::main → src/remove.c::rm → lib/fts.c::fts_read → lib/fts.c::fts_build → lib/fts.c::opendirat; removed: lib/fts.c::fts_read, lib/fts.c::fts_build.

Exact ownership symmetry is **not established**: gnulib is bundled into the C source tree, whereas Rust retains uucore as project implementation but contracts external dependencies. Treat gnulib contraction as a separate library-scope sensitivity, not a validated equivalent instrument.

## Difference decomposition

- cve_function: raw Rust−C mean difference 4.103424; verified entry counting removes 1.981132 (48.28% of that descriptive gap), leaving 2.122292. Entry+closure Rust minus original C: 1.820405; versus library-contracted C: 1.894479.
- cve_weighted: raw Rust−C mean difference 3.097511; verified entry counting removes 1.976190 (63.80% of that descriptive gap), leaving 1.121320. Entry+closure Rust minus original C: 0.930844; versus library-contracted C: 1.021753.

These are within-data arithmetic changes, not causal attribution to programming language.

## Reproduction and preservation

Run `python3 security/analysis/c-rust-depth-alignment-v1/regenerate.py` from the repository (or run the script by absolute path). Python standard library only; saved build evidence must be present. No RUPTA/SVF execution, compilation, network, or canonical writes. `input_sha256.json` pins every consumed input; regeneration fails if evidence changes. The Rust CSV preserves every original field and all 61 rows (55 numeric, six nonnumeric), adds aligned values and repeated-CVE associations. The C CSV includes numeric contexts and nonnumeric population/mapping placeholders. The summary contains all function and CVE aggregates, all four reporting units, dependence components, original program Dmax evidence, and population ledgers. `alignment_evidence.json` contains every transformed path and its original witness.

See `DEPENDENCE_AND_LIMITATIONS.md` for uncertainty and paper-use qualifications.
