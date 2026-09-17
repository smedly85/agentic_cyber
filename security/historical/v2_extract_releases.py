"""Extract acquired candidate releases in isolated ignored source directories."""
from pathlib import Path
import hashlib
import tarfile
from security.historical.v2_study import ROOT, read, write
from security.historical.analysis import source_tree_sha256


def main():
    repo = ROOT.parents[1]
    destination = ROOT / "sources/v2"
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in read("v2_releases_acquisition.json")["requests"]:
        if item["status"] != "downloaded":
            continue
        archive = repo / item["cache_path"]
        if hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("archive fingerprint changed")
        with tarfile.open(archive) as tf:
            roots = {Path(m.name).parts[0] for m in tf.getmembers() if Path(m.name).parts}
            if len(roots) != 1:
                raise RuntimeError("unexpected archive roots")
            name = roots.pop()
            tree = destination / name
            if not tree.exists():
                tf.extractall(destination, filter="data")
            # An existing directory is not evidence of completed extraction.
            # Check archive bytes, not a fresh fingerprint of potentially
            # incomplete/modified material, before accepting this candidate.
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                target = destination / member.name
                if not target.resolve().is_relative_to(tree.resolve()):
                    raise RuntimeError("archive member escapes release root")
                stream = tf.extractfile(member)
                if (not target.is_file() or stream is None or
                    hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(stream.read()).digest()):
                    raise RuntimeError("release extraction incomplete or altered: " + member.name)
        row = {"archive": item, "source_tree": tree.relative_to(ROOT).as_posix(),
               "source_tree_sha256": source_tree_sha256(tree),
               "status": "candidate_release_obtained_not_yet_accepted_as_vulnerable_specimen"}
        rows.append(row)
        print(name, row["source_tree_sha256"], flush=True)
    write("v2_candidate_sources.json", {"schema_version": 1, "sources": rows})


if __name__ == "__main__":
    main()
