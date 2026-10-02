"""Explicit one-time public dependency/upstream metadata acquisition."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "security/historical/rust"))
from semantic_gate import verify_frozen


def main():
    verify_frozen()
    cache = ROOT / "build/rust-instrument-v2/acquisition"
    cache.mkdir(parents=True, exist_ok=True)
    records = []
    def fetch(name, url):
        path = cache / name
        if not path.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "semantic-instrument-audit"})
            path.write_bytes(urllib.request.urlopen(request, timeout=120).read())
        records.append({"url": url, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "retrieved_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), "cache_file": name})
        return path
    metadata = json.loads(fetch("scopeguard.json", "https://crates.io/api/v1/crates/scopeguard/1.2.0").read_text())
    archive = fetch("scopeguard-1.2.0.crate", "https://static.crates.io/crates/scopeguard/scopeguard-1.2.0.crate")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != metadata["version"]["checksum"]:
        raise ValueError("dependency checksum mismatch")
    if not (cache / "scopeguard-1.2.0").exists():
        with tarfile.open(archive) as tar:
            tar.extractall(cache, filter="data")
    head = json.loads(fetch("svf-master.json", "https://api.github.com/repos/SVF-tools/SVF/commits/master").read_text())
    fetch("upstream-SVFIRBuilder.cpp", f"https://raw.githubusercontent.com/SVF-tools/SVF/{head['sha']}/svf-llvm/lib/SVFIRBuilder.cpp")
    fetch("issue-524.json", "https://api.github.com/repos/SVF-tools/SVF/issues/524")
    (cache / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print("Verified scopeguard 1.2.0; cached upstream revision", head["sha"])


if __name__ == "__main__":
    main()
