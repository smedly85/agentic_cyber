"""Run only pre-frozen mappings, serially per shared configured build."""
from concurrent.futures import ThreadPoolExecutor
import traceback
from security.historical.v2_build import run
from security.historical.v2_study import ROOT


def measure_group(item):
    release, programs = item
    for program in programs:
        try:
            run(program, release)
        except Exception:
            destination = ROOT.parents[1] / "build/historical-v2" / (release + "-" + program)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "runner-failure.log").write_text(traceback.format_exc())
            print(release, program, "pending diagnostic review; no final unavailable status inferred", flush=True)


if __name__ == "__main__":
    # Distinct build directories may run concurrently. A shared library/build
    # directory is never mutated by two workers; ledger merges are locked.
    groups = [("coreutils-8.25", ["chroot"]), ("coreutils-8.29", ["chown", "chgrp"]),
              ("coreutils-8.4", ["rm"]), ("coreutils-5.0", ["ls"]), ("fileutils-4.1", ["rm", "mv"])]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(measure_group, groups))
