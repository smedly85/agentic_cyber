#!/usr/bin/env python3
"""
Generation pipeline. Builds unfrozen case skeletons per tier, freezes their
goldens from GNU sort through the shared engine, and writes canonical,
diff-able suite JSON to suites/.

Deterministic: same seed + same GNU sort version + same required platform =>
byte-identical suites (including the gzip container: written with a fixed
mtime=0).

The oracle binary is resolved through the shared strict oracle contract. On
macOS, /usr/bin/sort is BSD sort and is refused; use SORT_ORACLE_BIN or a GNU
coreutils 9.11 Homebrew gsort/gnubin path. Suites are written gzipped
(.json.gz) by default to keep the large adversarial-input tier small; use
--no-gzip for plain, diffable JSON (e.g. while debugging the generator itself).

Usage:
  gen/generate.py                       # write to ../suites, using config.json
  gen/generate.py --out /tmp/scratch --no-gzip   # determinism check target
  gen/generate.py --tiers singles pairs kwise
  SORT_ORACLE_BIN=/opt/homebrew/bin/gsort gen/generate.py --seed 1
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import platform
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(ROOT))

from corpus import corpus as corpus_mod    # noqa: E402
from gen import combos                      # noqa: E402
from gen import curated_cases               # noqa: E402
from reference_generators import oracle_contract, platform_contract  # noqa: E402


def _freeze_all(cases, sort_bin, jobs):
    """Freeze a list of skeletons in parallel. The 'pipe' stdin mode is used
    for freezing (golden output is identical across stdin modes for a correct
    oracle; the runner still exercises all declared modes)."""
    # engine.py uses POSIX resource limits and cannot import on Windows. Keep
    # it behind main()'s platform gate so an accidental local invocation fails
    # cleanly as platform-incompatible before loading the execution engine.
    from gen import freeze

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
    # The 3- and 4-flag subsets of the bounded ladder. Its own tier rather than
    # an extension of `pairs` so that adding it leaves every existing suite file
    # byte-identical -- the goldens this closes a gap in were never wrong, they
    # were absent.
    "kwise": lambda corpus: combos.gen_kwise(corpus),
    "curated": lambda corpus: curated_cases.build(corpus),
    "adversarial": lambda corpus: curated_cases.build_adversarial(corpus),
    "faults": lambda corpus: curated_cases.build_faults(corpus),
    "random": None,   # provided by combos.gen_random, wired below
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "suites"))
    ap.add_argument("--sort-bin", default=None,
                    help="GNU coreutils 9.11 sort oracle; else "
                         "$SORT_ORACLE_BIN, config.json, or a conventional "
                         "GNU/Homebrew location")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--no-gzip", action="store_true",
                    help="write plain, diffable .json instead of .json.gz")
    ap.add_argument("--tiers", nargs="*",
                    default=["singles", "pairs", "kwise", "curated",
                             "adversarial", "faults", "random"])
    args = ap.parse_args()
    config_path = Path(ROOT) / "config.json"
    host_platform = platform.system()
    required_platform = platform_contract.required_platform(config_path)
    platform_problems = platform_contract.check(config_path, "sort")
    if platform_problems:
        for problem in platform_problems:
            print(problem, file=sys.stderr)
        return 2

    sort_bin = oracle_contract.resolve("sort", config_path, args.sort_bin)
    oracle_problems = oracle_contract.verify(
        "sort", Path(ROOT), sort_bin, config_path
    )
    if oracle_problems:
        for problem in oracle_problems:
            print(f"oracle_contract: {problem}", file=sys.stderr)
        return 2
    sort_ver = oracle_contract.version_line(sort_bin)
    oracle_version = oracle_contract.program_version("sort", sort_ver)
    print(f"oracle: {sort_bin} -- {sort_ver}")

    ext = "json" if args.no_gzip else "json.gz"

    os.makedirs(args.out, exist_ok=True)

    # 1-2. build corpus + discrimination assertion (hard abort on failure)
    corpus = dict(corpus_mod.build_core())
    corpus_mod.assert_discriminating(sort_bin)

    header_base = {"sort_version": sort_ver, "seed": args.seed,
                   "generator": "gen/generate.py"}

    manifest_counts = {}
    for tier in args.tiers:
        if tier == "random":
            skeletons = combos_gen_random(corpus, args.seed)
        elif tier == "faults":
            skeletons = curated_cases.build_faults(corpus, host_platform)
        else:
            skeletons = TIER_BUILDERS[tier](corpus)
        frozen = _freeze_all(skeletons, sort_bin, args.jobs)
        path = os.path.join(args.out, f"{tier}.{ext}")
        n = write_suite(path, dict(header_base, tier=tier), frozen,
                        gzipped=not args.no_gzip)
        manifest_counts[tier] = n
        print(f"  {tier:12} {n:5} cases -> {os.path.relpath(path, ROOT)}")

    exclusions = curated_cases.platform_exclusions(host_platform)
    manifest = {
        "sort_version": sort_ver,
        "oracle_version": oracle_version,
        "host_platform": host_platform,
        "required_platform": required_platform,
        "seed": args.seed,
        "counts": manifest_counts,
        "total_generated_cases": sum(manifest_counts.values()),
        "excluded_platform_cases": sorted(exclusions),
        "excluded_platform_case_reasons": exclusions,
    }
    with open(os.path.join(args.out, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"total: {sum(manifest_counts.values())} cases")
    return 0


def combos_gen_random(corpus, seed):
    # imported lazily; defined in combos in P5
    if hasattr(combos, "gen_random"):
        return combos.gen_random(corpus, seed)
    return []


if __name__ == "__main__":
    raise SystemExit(main())
