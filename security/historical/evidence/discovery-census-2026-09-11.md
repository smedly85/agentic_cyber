# Target-utility historical vulnerability discovery census

Cutoff: **2026-09-11**. Discovery was performed before measuring the two new
records. Search terms named packages, projects, utilities, and known advisory
identifiers; no depth-related terms or mapping convenience criteria were used.

## Population and sources

The in-population lineage is GNU Coreutils, GNU grep, predecessor GNU
fileutils/textutils/sh-utils packages when they supplied `sort`, `mkdir`,
`grep`, or `chmod`, and downstream patches applied to those GNU sources.
Independent implementations returned by name-based searches are recorded as
excluded false positives so that they cannot silently enter the GNU/CVE
denominator.

The pass reconciled CVE/NVD, GNU/Savannah and GNU mailing archives,
oss-security, Red Hat, Debian source-package ledgers, SUSE/openSUSE references,
Ubuntu notices, Fedora packaging history, and searches for predecessor-package
names. Debian's `grep` and `coreutils` source ledgers provided a useful complete
package-level cross-check. No target-utility CVE was found for GNU `chmod`, and
no additional target candidate was found in the predecessor GNU packages.

## Frozen dispositions

| Identifier | Type | Utility | Provenance | Disposition | Reason |
| --- | --- | --- | --- | --- | --- |
| CVE-2025-5278 | CVE | sort | upstream GNU | eligible | Existing verified record. |
| CVE-2015-1345 | CVE | grep | upstream GNU | eligible | Existing verified record. |
| CVE-2005-1039 | CVE | mkdir | upstream GNU | eligible | Existing verified record. |
| CVE-2012-5667 | CVE | grep | upstream GNU | eligible | Existing verified record. |
| CVE-2015-4041 | CVE | sort | downstream patch | eligible | The Fedora 22 source state is reproducibly reconstructed from authenticated GNU source plus frozen dist-git content; the multibyte-expansion defect is mapped. The SRPM itself was not authenticated. |
| CVE-2015-4042 | CVE | sort | downstream patch | eligible | The distinct aggregate-size overflow is authenticated and mapped. |
| CVE-2013-0221 | CVE | sort | downstream patch | unresolved | Downstream provenance is established, but an exact vulnerable patch generation and mapping have not yet been frozen. |
| TEMP-0306076-4B7D89 | temporary | mkdir | upstream GNU | excluded | Debian says this automatically generated name is not for external reference; it is not a CVE denominator member. |
| CVE-2026-35338 | CVE | chmod | unrelated implementation | excluded | uutils Rust implementation, outside the GNU lineage. |
| CVE-2026-35339 | CVE | chmod | unrelated implementation | excluded | uutils Rust implementation, outside the GNU lineage. |
| CVE-2026-35348 | CVE | sort | unrelated implementation | excluded | uutils Rust implementation, outside the GNU lineage. |
| CVE-2026-35353 | CVE | mkdir | unrelated implementation | excluded | uutils Rust implementation, outside the GNU lineage. |

Thus the ledger contains 12 discoveries: 11 CVE identifiers and one temporary
identifier. Six CVEs are analysis-ready, one CVE remains unresolved, and five
entries are excluded. `records.json` contains only the six verified/mapped
CVEs; neither the unresolved CVE nor any excluded identifier enters it.

Key package-ledger references:

* https://security-tracker.debian.org/tracker/source-package/coreutils
* https://security-tracker.debian.org/tracker/source-package/grep
* https://security-tracker.debian.org/tracker/source-package/rust-coreutils
* https://security-tracker.debian.org/tracker/TEMP-0306076-4B7D89
* https://nvd.nist.gov/vuln/detail/CVE-2013-0221
* https://ubuntu.com/security/CVE-2015-4041
* https://ubuntu.com/security/CVE-2015-4042
* https://www.suse.com/support/update/announcement/2015/suse-su-20151637-1.html
