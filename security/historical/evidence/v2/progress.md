# Population v2 measurement accounting

Population: exactly 24 CVEs. Completed measurement dispositions: 24/24. No member remains pending.

Population fingerprint: `62745447ca2a53781c18f22d884fd7344a76cccaa46434d212ef3d2e252e1a3b`.
Current frozen mapping artifact fingerprint: `bdb0d2bed1ea41f55987381b86685a0819dd74ae7caf50d37ddac13def98ecb4`.

Final statistics use the approved (CVE, vulnerable function) unit with within-function averaging across affected executables; see `final-report.md`.

| CVE | Project / component | Implementation family | Applicability | Verified functions | Numeric executable measurements | Executable-specific raw depths | Scope | Disposition / reason |
|---|---|---|---|---:|---:|---|---|---|
| CVE-2026-56392 | GNU Coreutils / unexpand | GNU Coreutils | applicable | 1 | 1 | coreutils-9.11/unexpand: src/unexpand.c::unexpand = 1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2026-56391 | GNU Coreutils / uniq | GNU Coreutils | applicable | 1 | 1 | coreutils-9.11/uniq: src/uniq.c::find_field = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2025-5278 | gnu-coreutils / sort | GNU Coreutils | applicable | 1 | 1 | gnu-coreutils/9.7/sort: src/sort.c::begfield = 3 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2024-0684 | GNU Coreutils / split | GNU Coreutils | applicable | 1 | 1 | coreutils-9.4/split: src/split.c::line_bytes_split = 1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2017-18018 | GNU Coreutils / chown, chgrp | GNU Coreutils | applicable | 1 | 2 | coreutils-8.29/chgrp: src/chown-core.c::change_file_owner = 2; coreutils-8.29/chown: src/chown-core.c::change_file_owner = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2017-2616 | util-linux / su | util-linux/shadow su (project assignment to verify independently) | applicable | 1 | 1 | util-linux-2.29.1/su: login-utils/su-common.c::create_watching_parent = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2016-2781 | GNU Coreutils / chroot | GNU Coreutils | applicable | 1 | 1 | coreutils-8.25/chroot: src/chroot.c::main = 0 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2015-4042 | gnu-coreutils / sort | downstream GNU-derived patch | applicable | 1 | 1 | gnu-coreutils/8.23-9.fc22/sort: src/sort.c::keycompare_mb = 3 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2015-4041 | gnu-coreutils / sort | downstream GNU-derived patch | applicable | 1 | 1 | gnu-coreutils/8.23-9.fc22/sort: src/sort.c::keycompare_mb = 3 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2015-1865 | GNU Coreutils / rm | GNU Coreutils | applicable | 1 | 1 | coreutils-8.4/rm: lib/fts.c::opendirat = 4 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2014-9471 | GNU Coreutils / date, touch | GNU Coreutils | applicable | 1 | 2 | coreutils-8.22/date: lib/parse-datetime.y::parse_datetime = 1; coreutils-8.22/touch: lib/parse-datetime.y::parse_datetime = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2013-0223 | GNU Coreutils with Fedora downstream i18n patch / join | downstream GNU-derived patch | applicable | 1 | 1 | gnu-coreutils/8.17-7.fc18/join: src/join.c::keycmp = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2013-0222 | GNU Coreutils with Fedora downstream i18n patch / uniq | downstream GNU-derived patch | applicable | 2 | 2 | gnu-coreutils/8.17-7.fc18/uniq: src/uniq.c::different = 2; gnu-coreutils/8.17-7.fc18/uniq: src/uniq.c::different_multi = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2013-0221 | gnu-coreutils / sort | downstream GNU-derived patch | applicable | 2 | 2 | gnu-coreutils/8.17-7.fc18/sort: src/sort.c::getmonth_mb = 4; gnu-coreutils/8.17-7.fc18/sort: src/sort.c::keycompare_mb = 3 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2009-4135 | GNU Coreutils build machinery / distcheck build machinery | GNU Coreutils | not_applicable | 0 | 0 | — | not applicable | not_applicable_build_or_configuration_only: The upstream fix changes only dist-check.mk build/test-directory handling. The vulnerable unit is a Make rule, not a runtime C function; no executable call-depth observation is applicable. |
| CVE-2008-1946 | Red Hat GNU Coreutils packaging/PAM configuration / su PAM configuration | GNU Coreutils packaging/configuration | not_applicable | 0 | 0 | — | not applicable | not_applicable_build_or_configuration_only: The vendor identifies incorrect pam_succeed_if use in /etc/pam.d/su. This is an authentication-stack configuration vulnerability, not a demonstrated defect in su's C function or in the PAM module implementation. No runtime-function mapping is invented. |
| CVE-2007-4998 | FreeBSD base-system cp / cp | FreeBSD base-system cp | applicable | 1 | 1 | freebsd/5.0/cp: bin/cp/cp.c::copy = 1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2005-1039 | GNU Coreutils / mkdir, mkfifo, mknod | GNU Coreutils | applicable | 4 | 4 | coreutils-5.2.1/mkfifo: src/mkfifo.c::main = 0; coreutils-5.2.1/mknod: src/mknod.c::main = 0; gnu-coreutils/5.2.1/mkdir: lib/makepath.c::make_path = 1; gnu-coreutils/5.2.1/mkdir: src/mkdir.c::main = 0 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2003-0854 | GNU Coreutils / ls | GNU Fileutils/Coreutils | applicable | 1 | 1 | coreutils-5.0/ls: src/ls.c::init_column_info = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2003-0853 | GNU Coreutils / ls | GNU Fileutils/Coreutils | applicable | 1 | 1 | coreutils-5.0/ls: src/ls.c::init_column_info = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2015-1345 | gnu-grep / grep | GNU grep | applicable | 1 | 1 | gnu-grep/2.21/grep: src/kwset.c::bmexec_trans = 4 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2012-5667 | gnu-grep / grep | GNU grep | applicable | 1 | 1 | gnu-grep/2.10/grep: src/dfasearch.c::EGexecute = 4 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2002-0435 | GNU Fileutils / rm, mv | GNU Fileutils | applicable | 1 | 2 | fileutils-4.1/mv: src/remove.c::remove_dir = 4; fileutils-4.1/rm: src/remove.c::remove_dir = 2 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |
| CVE-2001-0310 | FreeBSD base-system sort / sort | FreeBSD base-system sort | applicable | 1 | 1 | freebsd/4.1.1/sort: gnu/usr.bin/sort/sort.c::tempname = 1 | linker_exact | depth_applicable: All independently frozen vulnerable functions measured in every disclosure-governed executable context using linker-exact LLVM/SVF scope. |

Per-CVE and aggregate statistics are in `final-report.md`; every executable-specific raw depth remains visible above and in the machine-readable results.

## Build and scope evidence

| Specimen | TUs | Scope | Functions | Edges | Indirect edges | Unresolved callsites |
|---|---:|---|---:|---:|---:|---:|
| coreutils-5.0/ls | 26 | linker_exact | 179 | 343 | 16 | 7 |
| coreutils-5.2.1/mkfifo | 10 | linker_exact | 47 | 69 | 0 | 1 |
| coreutils-5.2.1/mknod | 11 | linker_exact | 50 | 90 | 0 | 1 |
| coreutils-8.22/date | 20 | linker_exact | 102 | 158 | 1 | 0 |
| coreutils-8.22/touch | 32 | linker_exact | 123 | 189 | 1 | 0 |
| coreutils-8.25/chroot | 17 | linker_exact | 79 | 132 | 0 | 0 |
| coreutils-8.29/chgrp | 33 | linker_exact | 172 | 296 | 12 | 5 |
| coreutils-8.29/chown | 34 | linker_exact | 174 | 308 | 12 | 5 |
| coreutils-8.4/rm | 36 | linker_exact | 172 | 319 | 50 | 6 |
| coreutils-9.11/unexpand | 25 | linker_exact | 116 | 166 | 0 | 2 |
| coreutils-9.11/uniq | 29 | linker_exact | 125 | 202 | 1 | 2 |
| coreutils-9.4/split | 40 | linker_exact | 152 | 299 | 3 | 0 |
| fileutils-4.1/cp | 20 | linker_exact | 70 | 202 | 1 | 6 |
| fileutils-4.1/mv | 23 | linker_exact | 125 | 307 | 13 | 8 |
| fileutils-4.1/rm | 12 | linker_exact | 84 | 153 | 12 | 6 |
| freebsd/4.1.1/sort | 7 | linker_exact | 52 | 198 | 1 | 1 |
| freebsd/5.0/cp | 2 | linker_exact | 9 | 15 | 0 | 0 |
| gnu-coreutils/5.2.1/mkdir | 14 | linker_exact | 55 | 107 | 0 | 1 |
| gnu-coreutils/8.17-7.fc18/join | 22 | linker_exact | 105 | 188 | 0 | 0 |
| gnu-coreutils/8.17-7.fc18/sort | 46 | linker_exact | 291 | 683 | 58 | 5 |
| gnu-coreutils/8.17-7.fc18/uniq | 22 | linker_exact | 93 | 136 | 7 | 0 |
| gnu-coreutils/8.23-9.fc22/sort | 47 | linker_exact | 293 | 688 | 58 | 5 |
| gnu-coreutils/9.7/sort | 58 | linker_exact | 337 | 767 | 19 | 11 |
| gnu-grep/2.10/grep | 33 | linker_exact | 265 | 671 | 24 | 9 |
| gnu-grep/2.21/grep | 43 | linker_exact | 377 | 975 | 103 | 5 |
| util-linux-2.29.1/su | 4 | linker_exact | 45 | 74 | 1 | 0 |

All numeric observations come from the frozen LLVM/SVF static semantic may-call instrument. Reachability is possible static execution, not guaranteed runtime execution. Every may-target remains in the graph. Tree-sitter prototype depths are not imported.

Sources, mapping evidence and source hashes are in the v2 ledgers. Raw graphs/build logs are retained under ignored build/historical-v2; compact linker maps and scope artifacts are under evidence/v2. Frozen historical-v1 files are unchanged.
