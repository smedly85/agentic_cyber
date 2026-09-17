# Population-v2 measurement checkpoint

The complete 24-CVE population was fixed before semantic call-depth measurement was expanded beyond the validated historical pilot. No CVE was excluded because its vulnerable function was deep, unreachable, unavailable, ambiguous, or not amenable to function-level depth measurement.

Instrument commit: `e73c3a98ea3b4f5b8957674b9a05d182ced4558b`. The backend is unchanged: Clang/LLVM 21.1.8; SVF 3.4 at `67efb7745ce47b2b6853fd5696fc22c83d701e6c`; AndersenWaveDiff with `-stat=false -ff-eq-base`. Both direct and resolved indirect edges count one. All may-targets are retained. A may-call edge is not guaranteed runtime execution.

## State of the study

All 24 CVEs have justified measurement dispositions. Twenty-two have numeric semantic measurements; two are build/configuration-only. There are 25 verified `(CVE, function)` pairs and 28 executable-specific measurements. Every numeric measurement uses linker-exact program scope. The nine reused pilot depths are unchanged. See [the complete accounting table](progress.md), [the measurement ledger](../../v2_semantic_results.json), and [the reporting gate](../../v2_reporting_gate.json).

The primary statistical unit is `(CVE, vulnerable function)`, as explicitly approved after all raw measurements were preserved. For a vulnerable function shared by multiple affected executables, its executable-specific semantic depths are averaged into one function-level value. `remove_dir` has raw depths 2/4 in rm/mv and primary value 3; `parse_datetime` has 1/2 in date/touch and primary value 1.5; `change_file_owner` has 2/2 in chown/chgrp and primary value 2. All 28 contexts remain raw provenance and form a separately labeled sensitivity analysis; they are not 28 independent vulnerability observations. See [the final statistical report](final-report.md). No missing value was assigned zero. Genuine vulnerable entry functions have measured depth zero.

## Evidence and mapping freeze

`v2_population.json` freezes all 24 IDs; implementation family, GNU relationship, and the old proposed inclusion labels are descriptive only. `v2_vulnerable_function_mappings.json` contains primary evidence, exact affected release/revision, source hashes, function identity, rationale excluding patched-only neighbors, and fingerprints frozen before each new measurement. All member decisions and the full mapping artifact are frozen before aggregate statistics. Pilot reuse is explicitly distinguished from new discovery.

The two non-applicable cases remain population members:

- CVE-2009-4135: the primary fix is in `dist-check.mk`, not a runtime C function.
- CVE-2008-1946: the affected unit is the RHEL PAM configuration for su; no runtime C-function defect has been established by that evidence.

The util-linux and FreeBSD cases retain their actual implementation families. FreeBSD sort is not relabeled GNU Coreutils.

## Reproduction and build provenance

Run the Python modules from the repository root in the Linux environment used by the frozen instrument. Large source archives, sysroots, native objects, bitcode, raw graphs, and compiler logs are retained under ignored `build/historical-v2` and `security/historical/sources/v2`. The v2 ledgers retain URLs, hashes, exact configure/compiler commands, native link evidence, source/object correspondence, generated module provenance, complete shortest paths and indirect target sets. System CRT/libc/PAM definitions remain explicitly external, consistently with the pilot boundary.

The staged workflow is acquisition (`v2_acquire`), authenticated release extraction (`v2_extract_releases`), evidence review/mapping freeze (`v2_review`, `v2_review_releases`, `v2_freebsd`), configured builds, then measurement (`v2_build`, `v2_util_linux`, `v2_freebsd_measure`). Do not run `v2_seed` over existing ledgers: it deliberately refuses replacement. Do not choose a revision or mapping based on depth.

GNU targets use their original configure and Make/Automake recipes. Actual native linker extraction identifies archive members; an archive on a link line is not an archive-wide scope. Generated version modules remain separately labeled configured-build inputs. `v2_build PROGRAM --release RELEASE` reproduces GNU measurements; the Fedora join/uniq adapters reuse the authenticated downstream release without altering the frozen pilot artifacts. Coreutils 8.4 uses `--configured-build build/historical-v2/native/coreutils-8.4-clang`.

Documented compatibility corrections, not source patches:

- Coreutils 9.11's configured GCC 15 implicit C23 dialect is transferred explicitly to Clang, whose default differs. No pointer-analysis option changes.
- Older GNU stdio compatibility definitions use the already validated pilot reconstruction policy. Coreutils 8.25 restores the historical warning policy for native configure/build inputs; only actually linked objects enter LLVM.
- Coreutils 8.4's old gnulib GCC warning-only `gets` declaration is incompatible with modern glibc even after the attempted C99 configuration. That attempt failed and remains recorded. A fresh, legitimate Clang configuration selects the original header's supported alternate branch; it succeeds without a fabricated declaration or source edit.
- util-linux 2.29.1 uses locally extracted PAM development/runtime packages matching the installed version. Nothing is installed system-wide.
- FreeBSD 4.1.1 uses the pinned release commit, official i386 4.1.1 sysroot, original BSD Make target and seven direct source objects. Its old `sys/cdefs.h` recognizes GCC major 2 only; exact historical `noreturn`, `const`, and `unused` macro expansions are supplied through compiler flags, without changing headers or pretending Clang is GCC 2. Pinned GCC source establishes the `-lgcc -lc -lgcc` runtime sequence and `/usr/libexec/ld-elf.so.1` loader path, replacing modern-driver defaults unavailable in that release. LLVM 21 lld is locally extracted. No historical binary is executed. See `v2_freebsd_cross_build.json`, including preserved failed attempts, and `freebsd-4.1.1-sort/scope.json`.

For FreeBSD: run `v2_freebsd_sysroot`, `v2_prepare_lld`, `v2_freebsd_build`, then `v2_freebsd_measure`. The native cross-link is scope evidence, not binary-level call-graph analysis. Every scientific call edge still comes from LLVM/SVF. The mapped `tempname` has depth 1 through `main -> tempname`.

## Validation and limitations

`python3 -m security.historical.v2_validate` checks schema, exactly-24 membership, population/mapping/graph fingerprints, queried identities, raw path lengths, graph edge membership, complete indirect targets, scope equality, frozen-v1 byte integrity, deterministic rendering, the 28 raw contexts, and recomputation of all 25 function-level values. `v2_integrity` verifies authenticated source fingerprints; `v2_reporting_gate` records the approved unit and statistics fingerprint. Local tests remain under ignored `build/`; intentionally deleted public test files were not restored.

Static may-call graphs can over-approximate runtime targets. Numeric vulnerable-function coverage is not proof of global graph completeness: per-specimen unresolved indirect calls, external definitions, reachable functions, and identity collisions remain in `v2_source_manifest.json`. Linker-exact scope means program object closure, not inclusion of operating-system/library implementations. Modern compiler/host reconstructions and the heterogeneous implementation families remain explicit limitations. The numeric subset must not be described as all 24 CVEs having function depths, nor used here to declare vulnerabilities shallow/deep or select a cutoff.
