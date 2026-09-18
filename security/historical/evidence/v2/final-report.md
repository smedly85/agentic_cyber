# Historical population v2 semantic call-depth report

## Population accounting

Population CVEs: **24**. Depth-applicable: **22**; with at least one numeric semantic depth: **22**; non-depth-applicable: **2**; applicable in principle but measurement-unavailable: **0**.

Verified `(CVE,function)` observations: **27**; numeric: **27**; nonnumeric: **0**. Raw executable contexts: **30**.

The primary unit is `(CVE, vulnerable function)`. When the same vulnerable function is shared by multiple affected executables, its primary depth is the arithmetic mean of the preserved executable-specific semantic depths. The 30-context analysis below is sensitivity only and does not treat those contexts as independent vulnerabilities.

## Function-observation statistics

N=27; mean=1.981481481481; median=2; sample SD=1.274615186887; Q1=1; Q3=3; IQR=2; range=0–4.

Exact-depth histogram: depth 0: 4, depth 1: 5, depth 1.5: 1, depth 2: 8, depth 3: 5, depth 4: 4.

Complete primary depth list (sorted): `0, 0, 0, 0, 1, 1, 1, 1, 1, 1.5, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 4`.

## CVE-weighted statistics

For each of the 22 CVEs with numeric depths, vulnerable-function depths were averaged within that CVE; the following describes those 22 per-CVE means.

N=22; mean=2.147727272727; median=2; sample SD=1.176807350897; Q1=1.125; Q3=3; IQR=1.875; range=0–4.

Per-CVE mean-depth list (sorted): `0, 0.25, 1, 1, 1, 1, 1.5, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3.5, 4, 4, 4`.

## Executable-context sensitivity analysis

This descriptive analysis retains all 30 raw executable contexts. Descriptive sensitivity only; 3 CVE/function groups contribute multiple dependent executable contexts. These values are dependent contexts—not independent vulnerability observations.

N=30; mean=2; median=2; sample SD=1.259447059845; Q1=1; Q3=3; IQR=2; range=0–4.

Context-depth histogram: depth 0: 4, depth 1: 6, depth 2: 11, depth 3: 4, depth 4: 5.

Complete context-depth list (sorted): `0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 4`.

## Complete 24-CVE accounting

| CVE | Project / component | Family | Applicability | Verified functions | Numeric functions | Function-level depths (raw executable contexts) | Per-CVE mean/min/max | Scope | Status / reason |
|---|---|---|---|---:|---:|---|---|---|---|
| CVE-2026-56392 | GNU Coreutils / unexpand | GNU Coreutils | applicable | 1 | 1 | src/unexpand.c::unexpand=1 (coreutils-9.11/unexpand=1) | 1/1/1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2026-56391 | GNU Coreutils / uniq | GNU Coreutils | applicable | 1 | 1 | src/uniq.c::find_field=2 (coreutils-9.11/uniq=2) | 2/2/2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2025-5278 | gnu-coreutils / sort | GNU Coreutils | applicable | 1 | 1 | src/sort.c::begfield=3 (gnu-coreutils/9.7/sort=3) | 3/3/3 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2024-0684 | GNU Coreutils / split | GNU Coreutils | applicable | 1 | 1 | src/split.c::line_bytes_split=1 (coreutils-9.4/split=1) | 1/1/1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2017-18018 | GNU Coreutils / chown/chgrp | GNU Coreutils | applicable | 1 | 1 | src/chown-core.c::change_file_owner=2 (coreutils-8.29/chgrp=2, coreutils-8.29/chown=2) | 2/2/2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2017-2616 | util-linux / su | util-linux su | applicable | 1 | 1 | login-utils/su-common.c::create_watching_parent=2 (util-linux-2.29.1/su=2) | 2/2/2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2016-2781 | GNU Coreutils / chroot | GNU Coreutils | applicable | 1 | 1 | src/chroot.c::main=0 (coreutils-8.25/chroot=0) | 0/0/0 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2015-4042 | gnu-coreutils / sort/keycompare_mb | downstream GNU-derived patch | applicable | 1 | 1 | src/sort.c::keycompare_mb=3 (gnu-coreutils/8.23-9.fc22/sort=3) | 3/3/3 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2015-4041 | gnu-coreutils / sort/keycompare_mb | downstream GNU-derived patch | applicable | 1 | 1 | src/sort.c::keycompare_mb=3 (gnu-coreutils/8.23-9.fc22/sort=3) | 3/3/3 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2015-1865 | GNU Coreutils / rm/fts.c | GNU Coreutils | applicable | 1 | 1 | lib/fts.c::opendirat=4 (coreutils-8.4/rm=4) | 4/4/4 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2014-9471 | GNU Coreutils / date/touch parse_datetime | GNU Coreutils | applicable | 1 | 1 | lib/parse-datetime.y::parse_datetime=1.5 (coreutils-8.22/date=1, coreutils-8.22/touch=2) | 1.5/1.5/1.5 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2013-0223 | GNU Coreutils with Fedora downstream i18n patch / join | downstream GNU-derived patch | applicable | 1 | 1 | src/join.c::keycmp=2 (gnu-coreutils/8.17-7.fc18/join=2) | 2/2/2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2013-0222 | GNU Coreutils with Fedora downstream i18n patch / uniq | downstream GNU-derived patch | applicable | 2 | 2 | src/uniq.c::different=2 (gnu-coreutils/8.17-7.fc18/uniq=2); src/uniq.c::different_multi=2 (gnu-coreutils/8.17-7.fc18/uniq=2) | 2/2/2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2013-0221 | gnu-coreutils / sort/keycompare_mb/getmonth_mb | downstream GNU-derived patch | applicable | 2 | 2 | src/sort.c::keycompare_mb=3 (gnu-coreutils/8.17-7.fc18/sort=3); src/sort.c::getmonth_mb=4 (gnu-coreutils/8.17-7.fc18/sort=4) | 3.5/3/4 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2009-4135 | GNU Coreutils build machinery / distcheck build machinery | GNU Coreutils | not_applicable | 0 | 0 | — | —/—/— | not applicable | not_applicable_build_or_configuration_only: The upstream fix changes only dist-check.mk build/test-directory handling. The vulnerable unit is a Make rule, not a runtime C function; no executable call-depth observation is applicable. |
| CVE-2008-1946 | Red Hat GNU Coreutils packaging/PAM configuration / su PAM configuration | GNU Coreutils packaging/configuration | not_applicable | 0 | 0 | — | —/—/— | not applicable | not_applicable_build_or_configuration_only: The vendor identifies incorrect pam_succeed_if use in /etc/pam.d/su. This is an authentication-stack configuration vulnerability, not a demonstrated defect in su's C function or in the PAM module implementation. No runtime-function mapping is invented. |
| CVE-2007-4998 | FreeBSD base-system cp / cp | FreeBSD base-system cp | applicable | 1 | 1 | bin/cp/cp.c::copy=1 (freebsd/5.0/cp=1) | 1/1/1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2005-1039 | GNU Coreutils / mkdir/mkfifo/mknod | GNU Coreutils | applicable | 4 | 4 | src/mkdir.c::main=0 (gnu-coreutils/5.2.1/mkdir=0); lib/makepath.c::make_path=1 (gnu-coreutils/5.2.1/mkdir=1); src/mkfifo.c::main=0 (coreutils-5.2.1/mkfifo=0); src/mknod.c::main=0 (coreutils-5.2.1/mknod=0) | 0.25/0/1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2003-0854 | GNU Coreutils / ls | GNU Fileutils/Coreutils | applicable | 1 | 1 | src/ls.c::init_column_info=2 (coreutils-5.0/ls=2) | 2/2/2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2003-0853 | GNU Coreutils / ls | GNU Fileutils/Coreutils | applicable | 1 | 1 | src/ls.c::init_column_info=2 (coreutils-5.0/ls=2) | 2/2/2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2015-1345 | gnu-grep / grep/bmexec_trans | GNU grep | applicable | 1 | 1 | src/kwset.c::bmexec_trans=4 (gnu-grep/2.21/grep=4) | 4/4/4 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2012-5667 | gnu-grep / grep/EGexecute | GNU grep | applicable | 1 | 1 | src/dfasearch.c::EGexecute=4 (gnu-grep/2.10/grep=4) | 4/4/4 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2002-0435 | GNU Fileutils / rm/mv | GNU Fileutils | applicable | 1 | 1 | src/remove.c::remove_dir=3 (fileutils-4.1/mv=4, fileutils-4.1/rm=2) | 3/3/3 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2001-0310 | FreeBSD base-system sort / sort temporary files | FreeBSD base-system sort | applicable | 1 | 1 | gnu/usr.bin/sort/sort.c::tempname=1 (freebsd/4.1.1/sort=1) | 1/1/1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |

## Dependence disclosure

Distinct CVEs may legitimately contribute the same function/depth under the chosen `(CVE,function)` estimand. They remain distinct vulnerability IDs/defects, but are not independent call-depth locations.

- `coreutils-5.0/ls::src/ls.c::init_column_info` at depth 2 is counted for CVE-2003-0853, CVE-2003-0854.
- `gnu-coreutils/8.23-9.fc22/sort::src/sort.c::keycompare_mb` at depth 3 is counted for CVE-2015-4041, CVE-2015-4042.

## Coverage and limitations

Every numeric result uses the frozen Clang/LLVM/SVF may-call backend and linker-exact executable scope. Static may-call reachability over-approximates possible runtime calls and does not prove execution. Resolved indirect callsites retain every may-target; unresolved indirect calls and external definitions remain graph-quality diagnostics in the source manifest. Historical compiler/configuration reconstruction and heterogeneous implementation families remain limitations.

The fail-closed executable-coverage gate passed: every program explicitly enumerated by authoritative CVE evidence has a measured vulnerable context or an evidence-backed disposition. Executable membership is disclosure-governed; linked but unenumerated aliases such as `dir` and `vdir` are not added to `ls` CVEs.

For CVE-2007-4998, the numeric observation is the actually affected FreeBSD 5.0 `cp` implementation. GNU Fileutils 4.1 `copy_internal=3` is retained only as descriptive defect-class proxy evidence and is excluded from every CVE denominator and statistic.

CVE-2009-4135 is a build-machinery vulnerability and CVE-2008-1946 is a PAM-configuration vulnerability; both remain in the 24-CVE population but have no legitimate runtime C-function depth. No value is imputed. Tree-sitter prototype depths do not enter these statistics. The distribution is reported without choosing a shallow-depth cutoff or inferring that depth causes vulnerability.

Population fingerprint: `d6912254ad268ada415e588002c91e47719bd7d5e384f7451b462f488d9b6748`. Mapping fingerprint: `fe1626425904001a7ec43d4b59ecdad37612b1525580e0478ad9a0acb316876e`. Statistics fingerprint: `73cca07b3c5f7ef35576eb966b9eb37a7dba1011f28150d87090799f645df369`. Instrument commit: `e73c3a98ea3b4f5b8957674b9a05d182ced4558b`.
