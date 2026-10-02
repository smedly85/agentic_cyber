"""Explicit, controller-only evidence acquisition; never builds or measures code.

Usage: python -m security.historical.rust.research URL [URL ...]
Responses are cached by URL under ignored build/historical-rust/cache.
The index retains URL, byte SHA-256 and actual UTC retrieval date.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
import sys
import re
import io
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "build/historical-rust/cache"
AUDIT = "3a07ffc5a9bd4c283e75afa548ba1f1957bad242"
OLD = "2bb9a85ddedc7b8aa1bd866bd70e41364c8783f7"


def source(path, revision=AUDIT):
    # Read a single regular member in memory; never extract archive paths.
    data = fetch(f"https://codeload.github.com/uutils/coreutils/tar.gz/{revision}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = archive.getmember(f"coreutils-{revision}/{path}")
        if not member.isfile():
            raise ValueError("source is not a regular archive member")
        return archive.extractfile(member).read()


def fetch(url: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    index_path = CACHE / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    name = hashlib.sha256(url.encode()).hexdigest()
    target = CACHE / name
    if url in index:
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != index[url]["sha256"]:
            raise ValueError("cache checksum mismatch: " + url)
        return data
    request = urllib.request.Request(url, headers={"User-Agent": "historical-uutils-population-research"})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    target.write_bytes(data)
    index[url] = {"url": url, "sha256": hashlib.sha256(data).hexdigest(),
                  "retrieval_date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
                  "cache_path": target.relative_to(ROOT).as_posix()}
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    return data


def census():
    urls = [
        "https://api.github.com/repos/uutils/coreutils/security-advisories?per_page=100",
        "https://api.github.com/repos/uutils/coreutils/security-advisories?per_page=100&page=2",
        "https://www.openwall.com/lists/oss-security/2026/05/02/2",
        "https://rustsec.org/advisories/RUSTSEC-2021-0043.html",
        "https://api.github.com/advisories?ecosystem=rust&affects=coreutils&per_page=100",
        "https://api.github.com/advisories?ecosystem=rust&affects=uu_od&per_page=100",
        "https://api.github.com/advisories?ecosystem=rust&affects=uucore&per_page=100",
        "https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=uutils&resultsPerPage=2000",
        "https://api.github.com/repos/uutils/coreutils/tags?per_page=100",
        "https://discourse.ubuntu.com/t/an-update-on-rust-coreutils/80773.json",
    ]
    ids = set()
    for url in urls:
        try:
            data = fetch(url)
            ids.update(re.findall(r"CVE-\d{4}-\d{4,}", data.decode()))
            print("discovery", url, len(data), flush=True)
        except Exception as error:
            print("FAILED", url, error, flush=True)
    for cve in sorted(ids):
        year, number = cve.split("-")[1:]
        url = f"https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/{year}/{number[:-3]}xxx/{cve}.json"
        try:
            data = json.loads(fetch(url))
            cna = data["containers"]["cna"]
            print(cve, data["cveMetadata"]["state"], cna.get("title", ""), flush=True)
        except Exception as error:
            print("FAILED", url, error, flush=True)


def inventory():
    index = json.loads((CACHE / "index.json").read_text())
    advisories = json.loads(fetch("https://api.github.com/repos/uutils/coreutils/security-advisories?per_page=100"))
    by_cve = {a["cve_id"]: a for a in advisories if a["cve_id"]}
    rows = []
    for url in sorted(index):
        if "/cvelistV5/" not in url:
            continue
        cve = json.loads(fetch(url))
        meta = cve["cveMetadata"]
        cna = cve["containers"]["cna"]
        ghsa = by_cve.get(meta["cveId"], {})
        row = {"id": meta["cveId"], "date": meta["datePublished"], "state": meta["state"],
               "title": cna.get("title"), "affected": cna["affected"],
               "description": cna["descriptions"][0]["value"],
               "references": [r["url"] for r in cna["references"]],
               "advisory": ghsa}
        rows.append(row)
    return rows


def patches():
    for row in inventory():
        urls = set()
        for ref in row["references"]:
            if re.fullmatch(r"https://github.com/uutils/coreutils/(pull/\d+|commit/[a-f0-9]+)", ref):
                urls.add(ref + ".patch")
        desc = row["advisory"].get("description", "")
        for pr in re.findall(r"\bPR #(\d+)", desc):
            if int(pr) > 1000:  # private audit PRs are not upstream PRs
                urls.add(f"https://github.com/uutils/coreutils/pull/{pr}.patch")
        for sha in re.findall(r"\bcommit\s+`?([a-f0-9]{7,40})\b", desc):
            if not sha.startswith("3a07ffc"):
                urls.add(f"https://github.com/uutils/coreutils/commit/{sha}.patch")
        if row["id"] == "CVE-2021-29934":
            urls.add("https://github.com/uutils/coreutils/commit/39d62c6.patch")
        for url in sorted(urls):
            try:
                data = fetch(url).decode()
                print(row["id"], url, len(data), flush=True)
            except Exception as error:
                print("FAILED", row["id"], url, error, flush=True)


def issues():
    urls = sorted({ref for row in inventory() for ref in row["references"]
                   if re.fullmatch(r"https://github.com/uutils/coreutils/issues/\d+", ref)})
    for url in urls:
        api = url.replace("https://github.com/", "https://api.github.com/repos/")
        for endpoint in (api, api + "/timeline?per_page=100"):
            try:
                data = json.loads(fetch(endpoint))
                if isinstance(data, dict):
                    print(url, data.get("title"), data.get("body"), flush=True)
                else:
                    print(url, [(e.get("event"), e.get("commit_id"), e.get("source", {}).get("issue", {}).get("html_url"), e.get("source", {}).get("issue", {}).get("title")) for e in data if e.get("event") in ("closed", "cross-referenced", "referenced")], flush=True)
            except Exception as error:
                print("FAILED", endpoint, error, flush=True)


def fixes():
    # Evidence-followup PRs from issue timelines; closed != merged.
    prs = {10706, 10204, 10545, 11995, 12339, 12773, 11706, 12340, 9781, 13334}
    for row in inventory():
        for ref in row["references"]:
            match = re.fullmatch(r"https://github.com/uutils/coreutils/pull/(\d+)", ref)
            if match:
                prs.add(int(match[1]))
    for pr in sorted(prs):
        url = f"https://api.github.com/repos/uutils/coreutils/pulls/{pr}"
        try:
            data = json.loads(fetch(url))
            print(pr, data.get("merged"), data.get("merge_commit_sha"), data.get("title"), flush=True)
            if pr in {10706, 10204, 10545, 11995, 12339, 12773, 11706, 12340, 9781, 13334}:
                fetch(f"https://github.com/uutils/coreutils/pull/{pr}.patch")
        except Exception as error:
            print("FAILED", url, error, flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--history"]:
        for component in ("cp", "mv", "id", "env", "dd", "tail"):
            url = f"https://api.github.com/repos/uutils/coreutils/commits?sha=0.11.0&path=src/uu/{component}&per_page=100"
            try:
                commits = json.loads(fetch(url))
                print(component, [(c["sha"], c["commit"]["message"].splitlines()[0]) for c in commits], flush=True)
            except Exception as error:
                print("FAILED", url, error, flush=True)
        raise SystemExit(0)
    if sys.argv[1:] == ["--fixes"]:
        fixes()
        raise SystemExit(0)
    if sys.argv[1:] == ["--export-review"]:
        for revision in (AUDIT, OLD):
            data = fetch(f"https://codeload.github.com/uutils/coreutils/tar.gz/{revision}")
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                files = {m.name.split("/", 1)[1]: archive.extractfile(m).read().decode()
                         for m in archive.getmembers()
                         if m.isfile() and (m.name.endswith(".rs") or m.name.endswith("Cargo.toml"))}
            (CACHE.parent / (revision + ".json")).write_text(json.dumps(files, sort_keys=True))
            print(revision, len(files))
        raise SystemExit(0)
    if sys.argv[1:] == ["--issues"]:
        issues()
        raise SystemExit(0)
    if sys.argv[1:2] == ["--excerpt"]:
        lines = source(sys.argv[2]).decode().splitlines()
        selected = set()
        for i, line in enumerate(lines):
            if re.search(sys.argv[3], line):
                selected.update(range(max(0, i - 5), min(len(lines), i + 10)))
        for i in sorted(selected):
            print(f"{i+1}: {lines[i]}")
        raise SystemExit(0)
    if sys.argv[1:2] == ["--functions"]:
        for path in sys.argv[2:]:
            print("FILE", path)
            for i, line in enumerate(source(path).decode().splitlines(), 1):
                if re.search(r"\b(fn|impl)\s", line):
                    print(f"{i}: {line}")
        raise SystemExit(0)
    if sys.argv[1:2] == ["--source"]:
        text = source(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else AUDIT).decode()
        for number, line in enumerate(text.splitlines(), 1):
            print(f"{number}: {line}")
        raise SystemExit(0)
    if sys.argv[1:2] == ["--patch-summary"]:
        index = json.loads((CACHE / "index.json").read_text())
        for url in sorted(index):
            if not url.endswith(".patch") or (len(sys.argv) > 2 and sys.argv[2] not in url):
                continue
            print("\nURL", url)
            active = False
            for line in fetch(url).decode().splitlines():
                if line.startswith("diff --git"):
                    active = " b/src/" in line
                if line.startswith(("From ", "Subject:")) or (active and (len(sys.argv) > 2 or line.startswith(("diff", "@@")))):
                    print(line)
        raise SystemExit(0)
    if sys.argv[1:] == ["--census"]:
        census()
        raise SystemExit(0)
    if sys.argv[1:] == ["--inventory"]:
        for row in inventory():
            print(row["id"], row["date"], row["title"], row["references"], row["affected"])
        print("TAGS", fetch("https://api.github.com/repos/uutils/coreutils/tags?per_page=100").decode())
        raise SystemExit(0)
    if sys.argv[1:] == ["--patches"]:
        patches()
        raise SystemExit(0)
    for url in sys.argv[1:]:
        data = fetch(url)
        print(url, len(data), hashlib.sha256(data).hexdigest())
