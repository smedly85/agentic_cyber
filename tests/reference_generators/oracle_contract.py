#!/usr/bin/env python3
"""Resolve and verify the GNU oracle binary for the sort, mkdir and grep suites.

**Offline only. Never copied into an agent-visible bundle.** It lives here for
the same reason the specification models do: `scripts/stage_test_bundle.py`
builds a stage bundle from an explicit allowlist that cannot reach this
directory, so an oracle path can never appear in a sandbox.

Why this exists
---------------
`new_sort`, `new_mkdir` and `new_grep` freeze their goldens by running a real
GNU binary. That makes the oracle part of the benchmark definition, not an
implementation detail: these projects change diagnostic wording and some
behavior between releases, so goldens frozen against one version are not the
goldens another version produces. The suites already recorded which version they
were frozen from --

    tests/sort-test-suite/suites/MANIFEST.json   "sort (GNU coreutils) 9.11"
    tests/mkdir-test-suite/suites/MANIFEST.json  "mkdir (GNU coreutils) 9.11"
    tests/grep-test-suite/suites/MANIFEST.json   "grep (GNU grep) 3.12"

Version identity is necessary but not sufficient. `new_grep`'s contract is
byte-exact, and a build can carry the right version string while still being
unfit -- the Git-for-Windows grep 3.0 opens files in text mode and drops CR from
its output, and aborts outright on `LC_ALL=C -i`. Identity and pin are checked
here; `tests/grep-test-suite/gen/oracle.py:precheck` checks that the binary
actually behaves the way the contract needs before anything is regenerated.

-- but nothing checked it before regenerating. A self-check run against a
different coreutils either failed late and cryptically (a MODEL MISMATCH deep
inside freeze, naming a stderr substring rather than a version) or, worse,
regenerated the frozen corpus against the wrong oracle and overwrote the
committed benchmark.

So: resolve the oracle explicitly, verify it is GNU, verify its version matches
the pin, and fail *early* with a message that names both versions.

Resolution order (first hit wins)
---------------------------------
1. an explicit path passed on the command line (`--oracle-bin` / `--sort-bin`
   / `--mkdir-bin`);
2. the environment variable for that suite -- ``SORT_ORACLE_BIN``,
   ``MKDIR_ORACLE_BIN`` or ``GREP_ORACLE_BIN``;
3. ``paths.oracle_bin`` in the suite's config.json;
4. the first of a few conventional locations that exists.

The environment variable is the portable answer: it needs no edit to a tracked
file, so a WSL, Linux or macOS checkout can each point at its own coreutils
without the repository carrying one machine's layout. The previous mkdir default
was a hard-coded Homebrew path, which is why this failed on WSL.

Usage from a shell script:

    ORACLE="$(python3 ../reference_generators/oracle_contract.py resolve \\
                  --suite mkdir --config config.json)"
    python3 ../reference_generators/oracle_contract.py verify \\
        --suite mkdir --config config.json --oracle-bin "$ORACLE" || exit 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Which environment variable overrides which suite, and where that suite's
# frozen corpus records the version it was produced from.
SUITES: dict[str, dict[str, Any]] = {
    "sort": {
        "env": "SORT_ORACLE_BIN",
        "program": "sort",
        "manifest_key": "sort_version",
        "toolkit": "GNU coreutils",
        "candidates": (
            "/opt/homebrew/opt/coreutils/libexec/gnubin/sort",
            "/usr/local/opt/coreutils/libexec/gnubin/sort",
            "/opt/homebrew/bin/gsort",
            "/usr/local/bin/gsort",
        ),
        "aliases": ("gsort",),
        "fallback_candidates": (
            "/usr/bin/sort",
            "/bin/sort",
        ),
    },
    "mkdir": {
        "env": "MKDIR_ORACLE_BIN",
        "program": "mkdir",
        "manifest_key": "mkdir_version",
        "toolkit": "GNU coreutils",
        "candidates": (
            "/usr/bin/mkdir",
            "/bin/mkdir",
            "/opt/homebrew/opt/coreutils/libexec/gnubin/mkdir",
            "/usr/local/opt/coreutils/libexec/gnubin/mkdir",
        ),
    },
    # grep is not coreutils: it is its own GNU package and reports
    # "grep (GNU grep) 3.12", so it needs its own version line. On macOS
    # /usr/bin/grep is BSD grep, which is why the Homebrew locations are
    # searched -- `brew install grep` installs both a gnubin/grep and a ggrep.
    "grep": {
        "env": "GREP_ORACLE_BIN",
        "program": "grep",
        "manifest_key": "grep_version",
        "toolkit": "GNU grep",
        "candidates": (
            "/usr/bin/grep",
            "/bin/grep",
            "/opt/homebrew/opt/grep/libexec/gnubin/grep",
            "/usr/local/opt/grep/libexec/gnubin/grep",
            "/opt/homebrew/bin/ggrep",
            "/usr/local/bin/ggrep",
        ),
    },
}

VERSION_LINE = re.compile(r"\(GNU coreutils\)\s+(?P<version>[0-9][0-9.]*)")
# One pattern per toolkit. A suite's oracle must come from the toolkit its
# goldens were frozen from: "GNU grep" and "GNU coreutils" are separate
# projects on separate release schedules, so one version number says nothing
# about the other.
TOOLKIT_VERSION = {
    "GNU coreutils": VERSION_LINE,
    "GNU grep": re.compile(r"\(GNU grep\)\s+(?P<version>[0-9][0-9.]*)"),
}


class OracleError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"oracle_contract: {message}")


def _config(config_path: Path | None) -> dict[str, Any]:
    if config_path is None or not config_path.is_file():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def resolve(suite: str, config_path: Path | None = None,
            override: str | None = None) -> str:
    """The oracle path, by the documented precedence. Existence is not checked
    here -- `verify` reports that, with a message that says what to do."""
    if suite not in SUITES:
        raise OracleError(f"unknown suite {suite!r}")
    if override:
        return override
    from_env = os.environ.get(SUITES[suite]["env"])
    if from_env:
        return from_env
    configured = (_config(config_path).get("paths") or {}).get("oracle_bin")
    if configured:
        return configured
    for candidate in SUITES[suite]["candidates"]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    for alias in SUITES[suite].get("aliases", ()):
        found = shutil.which(alias)
        if found:
            return found
    for candidate in SUITES[suite].get("fallback_candidates", ()):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which(SUITES[suite]["program"])
    return found or SUITES[suite]["candidates"][0]


def version_line(binary: str) -> str:
    """The oracle's own first --version line, verbatim."""
    try:
        completed = subprocess.run(
            [binary, "--version"], capture_output=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OracleError(f"cannot run {binary} --version: {error}") from error
    text = completed.stdout.decode("utf-8", "replace").strip()
    return text.splitlines()[0] if text else ""


def coreutils_version(line: str) -> str | None:
    match = VERSION_LINE.search(line)
    return match.group("version") if match else None


def toolkit(suite: str) -> str:
    """Which GNU project this suite's oracle must come from."""
    return SUITES[suite].get("toolkit", "GNU coreutils")


def program_version(suite: str, line: str) -> str | None:
    """The version number in a --version line, per that suite's toolkit."""
    match = TOOLKIT_VERSION[toolkit(suite)].search(line)
    return match.group("version") if match else None


def required_version(suite: str, suite_root: Path,
                     config_path: Path | None = None) -> str | None:
    """The version this suite's frozen corpus was produced from.

    Read from the corpus's own MANIFEST.json, so the pin cannot drift from the
    goldens it describes. `oracle_version_required` in config.json overrides it
    only for a deliberate, documented re-pin.
    """
    override = _config(config_path).get("oracle_version_required")
    if override:
        return str(override)
    manifest = suite_root / "suites" / "MANIFEST.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    recorded = data.get(SUITES[suite]["manifest_key"])
    return program_version(suite, str(recorded)) if recorded else None


def verify(suite: str, suite_root: Path, binary: str,
           config_path: Path | None = None) -> list[str]:
    """Every reason this binary is unfit to regenerate or self-check the suite.

    Empty list means fit. Reported all at once so one run tells the whole story
    rather than one problem per invocation.
    """
    problems: list[str] = []
    if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
        env = SUITES[suite]["env"]
        problems.append(
            f"{binary!r} is not an executable file. Point {env} at a "
            f"{toolkit(suite)} {SUITES[suite]['program']}, e.g. "
            f"{env}=/usr/bin/{SUITES[suite]['program']}"
        )
        return problems

    line = version_line(binary)
    wanted_toolkit = toolkit(suite)
    if wanted_toolkit not in line:
        problems.append(
            f"{binary!r} is not {wanted_toolkit} (--version said {line!r}). "
            "BSD/BusyBox implementations differ in both behavior and "
            "diagnostics, so they cannot produce this suite's goldens."
        )
        return problems

    found = program_version(suite, line)
    wanted = required_version(suite, suite_root, config_path)
    if found is None:
        problems.append(
            f"cannot parse a {wanted_toolkit} version from {binary!r} "
            f"(--version said {line!r}); refusing to regenerate without "
            "an exact oracle version."
        )
    elif wanted and found != wanted:
        problems.append(
            f"oracle version mismatch: this suite's frozen goldens were "
            f"produced by {wanted_toolkit} {wanted}, but {binary!r} is "
            f"{found}. Diagnostic wording and some behavior differ between "
            f"releases, so regenerating against {found} would "
            f"change the benchmark rather than reproduce it. Either install "
            f"coreutils {wanted} and point {SUITES[suite]['env']} at it, or "
            f"re-pin deliberately (see the suite README)."
        )
    return problems


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("resolve", "verify", "version",
                                           "required"))
    parser.add_argument("--suite", required=True, choices=sorted(SUITES))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--suite-root", type=Path, default=None)
    parser.add_argument("--oracle-bin", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = args.config
    suite_root = args.suite_root or (
        config_path.resolve().parent if config_path else Path.cwd()
    )
    binary = resolve(args.suite, config_path, args.oracle_bin)

    if args.action == "resolve":
        print(binary)
        return 0
    if args.action == "version":
        print(version_line(binary))
        return 0
    if args.action == "required":
        print(required_version(args.suite, suite_root, config_path) or "")
        return 0

    problems = verify(args.suite, suite_root, binary, config_path)
    for problem in problems:
        print(f"oracle_contract: {problem}", file=sys.stderr)
    if not problems:
        print(f"oracle: {binary} -- {version_line(binary)}")
    return 2 if problems else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OracleError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
