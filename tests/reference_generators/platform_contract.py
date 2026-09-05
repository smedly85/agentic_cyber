#!/usr/bin/env python3
"""The platform gate for a frozen suite, shared by every suite that has one.

**Offline only. Never copied into an agent-visible bundle.** It lives beside
oracle_contract.py for the same reason: `scripts/stage_test_bundle.py` builds a
bundle from an explicit five-file allowlist that cannot reach this directory.

Why a suite is pinned to one platform
-------------------------------------
A frozen corpus records what a specific utility version did on a specific
operating system. When the same version behaves differently on another OS, the
corpus stops describing that host, and running it there produces conclusions
about the platform rather than about the candidate. Two suites in this
repository are platform-specific:

    mkdir  Darwin  GNU coreutils 9.11 resolves a symbolic mode argument that
                   does not itself set the rwx bits from a 0755 departure on
                   Linux and a 0777 departure on Darwin.
    sort   Darwin  GNU coreutils 9.11 reads `+1` as a filename under
                   POSIXLY_CORRECT (case obs-pos-posixly). The Darwin corpus
                   omits fault-devfull because /dev/full is Linux-only.

Both of those are recorded in the suite's own config.json under
`_platform_contract`; this module prints that text rather than restating it, so
the explanation stays next to the corpus it explains.

Where this is and is NOT used
-----------------------------
Used by each suite's `selfcheck.sh`, which is offline and never bundled, so the
check can be shared here. It is deliberately NOT the implementation used at
judging time: `runner.py` ships inside the sandbox and must run standalone from
the five files the bundle carries, so its `check_platform` is necessarily a
per-suite copy. That duplication is a property of the bundle contract, not an
oversight -- adding a sixth shared file to the allowlist would ship it to chmod
and grep, which have no platform contract to enforce.

Usage from a shell script:

    python3 ../reference_generators/platform_contract.py check \\
        --config config.json --suite sort || exit 2
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

# Same value runner.py exits with, and the value
# scripts/run_lineage_experiment.sh classifies as platform_incompatible rather
# than validation_failed.
PLATFORM_INCOMPATIBLE_EXIT = 3


def _config(config_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def required_platform(config_path: Path) -> str | None:
    """The OS this suite's goldens describe, or None when it is neutral."""
    value = _config(config_path).get("required_platform")
    return str(value) if value else None


def contract_reason(config_path: Path) -> str:
    """The suite's own explanation of why it is pinned."""
    return str(_config(config_path).get("_platform_contract", "")).strip()


def check(config_path: Path, suite: str) -> list[str]:
    """Empty list when this host may run the suite; complaints otherwise."""
    required = required_platform(config_path)
    if not required:
        return []
    actual = platform.system()
    if actual == required:
        return []

    lines = [
        f"selfcheck.sh: refusing to run on {actual}; the {suite} suite "
        f"requires {required}.",
        "",
        f"  The formal goldens under suites/ must be produced AND validated "
        f"on {required}, so on this host:",
        "",
        "    * regeneration would silently redefine the benchmark, and",
        "    * the oracle self-pass would report GNU coreutils as broken for a",
        "      difference that belongs to the platform, not to the binary.",
        "",
        f"  Run this self-check on {required}. Judging a candidate on another",
        "  platform is reported by runner.py as an infrastructure",
        "  incompatibility rather than as a candidate failure.",
    ]
    reason = contract_reason(config_path)
    if reason:
        lines += ["", "  Why this suite is pinned:", f"    {reason}"]
    return lines


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("check", "required"))
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--suite", default="this")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.action == "required":
        print(required_platform(args.config) or "")
        return 0
    problems = check(args.config, args.suite)
    for line in problems:
        print(line, file=sys.stderr)
    return 2 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
