# Historical population v2 reconnaissance

This artifact is review material, not a population freeze.  It does not alter
`cve_census.json`, `records.json`, or historical-v1 results.  The reconciliation
cutoff is 2026-09-15.

## Result

The authoritative Debian source-package ledgers list 20 Coreutils CVEs and two
GNU grep CVEs.  Adding the one unique GNU Fileutils predecessor CVE not already
represented by the Coreutils ledger and the retained Textutils/sort discovery
hit yields exactly **24 discovery candidates**.

That is not a defensible 24-CVE analysis population:

* `CVE-2017-2616` is assigned to util-linux/shadow `su`, despite its historical
  presence in the Coreutils source-package ledger.
* `CVE-2001-0310` is assigned to FreeBSD base-system `sort`; no primary source
  found links it to GNU Textutils.

Therefore the GNU-lineage package population is **22**, a discrepancy of two
from the requested 24.  Excluding the non-runtime `distcheck` build issue
`CVE-2009-4135` gives **21 runtime vulnerabilities**, a discrepancy of three.
Keeping the original `sort`/`grep`/`mkdir`/`chmod` vulnerable-behavior scope
continues to give **7 CVEs**.  The definitions cannot be interchanged after the
fact merely to obtain a desired count.

The machine-readable companion lists all 24 candidates with package,
component, target relevance, GNU-lineage relevance, proposed disposition,
confidence, sources, and open questions.

## Decisions needed from the professors

1. Is v2 package-wide (all Coreutils/Grep/Fileutils utilities), or restricted
   to the four original target utilities?
2. Does "24" mean the discovery/review universe, even though two entries are
   excluded non-GNU assignments?
3. Are build-system and configuration-only CVEs part of a source-function call
   depth estimand?
4. Are downstream GNU-derived patches included alongside pristine upstream GNU?
5. If a CVE has no defensible vulnerable C function (for example configuration
   or build machinery), is it retained in the CVE denominator with an explicit
   unavailable status?

## Statistical unit planned, not calculated

At function-observation level the future study will report N, mean/median raw
depth, sample SD, IQR, range, histogram, and numeric coverage.  It will also
report per-CVE verified-function count and mean/min/max depth, followed by
summaries across CVEs so CVEs with several mapped functions do not receive
automatic extra weight.  Missing depth will not be imputed.

Primary ledgers and lineage evidence:

* https://security-tracker.debian.org/tracker/source-package/coreutils
* https://security-tracker.debian.org/tracker/source-package/grep
* https://nvd.nist.gov/vuln/detail/CVE-2002-0435
* https://www.freebsd.org/security/advisories/FreeBSD-SA-01:13.sort.asc
* https://nvd.nist.gov/vuln/detail/CVE-2001-0310
* `security/historical/evidence/discovery-census-2026-09-11.md`
