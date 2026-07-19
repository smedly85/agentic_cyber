#!/usr/bin/env python3
"""
Generation pipeline. Builds unfrozen case skeletons per tier, freezes their
goldens from GNU sort through the shared engine, and writes canonical,
diff-able suite JSON to suites/.

Deterministic: same seed + same GNU sort version => byte-identical suites
(including the gzip container: written with a fixed mtime=0).

The oracle binary (--sort-bin) defaults to paths.oracle_bin in config.json
if present, else /usr/bin/sort. Suites are written gzipped (.json.gz) by
default to keep the large adversarial-input tier small; use --no-gzip for
plain, diffable JSON (e.g. while debugging the generator itself).

Usage:
  gen/generate.py                       # write to ../suites, using config.json
  gen/generate.py --out /tmp/scratch --no-gzip   # determinism check target
  gen/generate.py --tiers singles pairs
  gen/generate.py --seed 1 --sort-bin /usr/bin/sort
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from corpus import corpus as corpus_mod    # noqa: E402
from gen import combos                      # noqa: E402
from gen import curated_cases               # noqa: E402
from gen import freeze                       # noqa: E402
import config as cfgmod                      # noqa: E402


def _freeze_all(cases, sort_bin, jobs):
    """Freeze a list of skeletons in parallel. The 'pipe' stdin mode is used
    for freezing (golden output is identical across stdin modes for a correct
    oracle; the runner still exercises all declared modes)."""
    def one(c):
        return freeze.freeze_case(c, sort_bin=sort_bin, stdin_mode="pipe")
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(one, cases))


def write_suite(path, header, cases, gzipped=True):
    cases = sorted(cases, key=lambda c: c["name"])
    # dedupe by name (defensive: combinators may collide on names)
    seen = {}
    for c in cases:
        seen[c["name"]] = c
    cases = [seen[k] for k in sorted(seen)]
    doc = {"header": header, "cases": cases}
    payload = json.dumps(doc, indent=1, sort_keys=True).encode()
    if gzipped:
        # mtime=0 keeps the gzip container itself byte-identical across
        # runs, which selfcheck.sh's regeneration-determinism gate relies
        # on. (gzip.open() doesn't accept mtime; GzipFile does.)
        with gzip.GzipFile(path, "wb", mtime=0) as f:
            f.write(payload)
    else:
        with open(path, "wb") as f:
            f.write(payload)
    return len(cases)


TIER_BUILDERS = {
    "singles": lambda corpus: combos.gen_singles(corpus),
    "pairs": lambda corpus: combos.gen_pairs(corpus),
    "curated": lambda corpus: curated_cases.build(corpus),
    "adversarial": lambda corpus: curated_cases.build_adversarial(corpus),
    "faults": lambda corpus: curated_cases.build_faults(corpus),
    "random": None,   # provided by combos.gen_random, wired below
}


def _default_sort_bin():
    cfg_path = os.path.join(ROOT, "config.json")
    if os.path.exists(cfg_path):
        v = cfgmod.get(cfgmod.load(cfg_path), "paths.oracle_bin")
        if v:
            return v
    return "/usr/bin/sort"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "suites"))
    ap.add_argument("--sort-bin", default=None,
                    help="GNU sort oracle; defaults to paths.oracle_bin "
                         "in config.json, else /usr/bin/sort")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--no-gzip", action="store_true",
                    help="write plain, diffable .json instead of .json.gz")
    ap.add_argument("--tiers", nargs="*",
                    default=["singles", "pairs", "curated",
                             "adversarial", "faults", "random"])
    args = ap.parse_args()
    sort_bin = args.sort_bin or _default_sort_bin()
    ext = "json" if args.no_gzip else "json.gz"

    os.makedirs(args.out, exist_ok=True)

    # 1-2. build corpus + discrimination assertion (hard abort on failure)
    corpus = dict(corpus_mod.build_core())
    corpus_mod.assert_discriminating(sort_bin)

    sort_ver = _sort_version(sort_bin)
    header_base = {"sort_version": sort_ver, "seed": args.seed,
                   "generator": "gen/generate.py"}

    manifest_counts = {}
    for tier in args.tiers:
        if tier == "random":
            skeletons = combos_gen_random(corpus, args.seed)
        else:
            skeletons = TIER_BUILDERS[tier](corpus)
        frozen = _freeze_all(skeletons, sort_bin, args.jobs)
        path = os.path.join(args.out, f"{tier}.{ext}")
        n = write_suite(path, dict(header_base, tier=tier), frozen,
                        gzipped=not args.no_gzip)
        manifest_counts[tier] = n
        print(f"  {tier:12} {n:5} cases -> {os.path.relpath(path, ROOT)}")

    with open(os.path.join(args.out, "MANIFEST.json"), "w") as f:
        json.dump({"sort_version": sort_ver, "seed": args.seed,
                   "counts": manifest_counts}, f, indent=1, sort_keys=True)
    print(f"total: {sum(manifest_counts.values())} cases")


def combos_gen_random(corpus, seed):
    # imported lazily; defined in combos in P5
    if hasattr(combos, "gen_random"):
        return combos.gen_random(corpus, seed)
    return []


def _sort_version(sort_bin):
    import subprocess
    out = subprocess.run([sort_bin, "--version"], capture_output=True,
                         text=True).stdout.splitlines()
    return out[0] if out else "unknown"


if __name__ == "__main__":
    main()
