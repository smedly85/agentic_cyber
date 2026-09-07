#!/usr/bin/env python3
"""Run one checkpoint's held-out cases against a candidate.

This is what `extra_test_command` invokes. It runs in the CONTROLLER's shell
after the repair loop has finished, with the working directory set to the
attempt's sandbox -- but it reads the held-out corpus from the repository, by
absolute path, so the cases never enter that sandbox and the agent never had a
chance to read them.

Three things it deliberately does not do:

  * It does not re-implement judging. Each suite already ships a runner.py that
    materialises fixtures, pins argv and environment, executes the candidate and
    compares against frozen expectations. The held-out corpus is stored in that
    same native case format, so this hands the file to the suite's own runner
    and inherits its comparison semantics exactly. A second comparator could
    disagree with the visible pass and nobody would know which was right.

  * It does not choose which cases to run. The suite's runner already applies
    the cumulative `implemented` flags and the bundle's filtering/scope
    contract, which is how the visible pass gets per-checkpoint selection. This
    reads that same contract out of the bundled config in the sandbox -- the one
    `stage_test_bundle.py` wrote for this checkpoint -- so the held-out pass is
    scoped to exactly the checkpoint being judged, with no per-checkpoint
    configuration of its own to drift.

  * It does not feed anything back. `run_experiment.sh` runs the extra command
    once, after the last repair loop, and never renders its output into a
    continuation prompt.

Exit 0/1 is the runner's pass/candidate-failure verdict. Exit 2 means this
wrapper could not produce a verdict, and exit 3 preserves the runner's platform
incompatibility result. The status is recorded as `extra_test_exit_code` in the
attempt metadata.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

from reference_generators import heldout_contract  # noqa: E402


# Keep candidate verdicts distinct from controller/configuration failures. The
# suite runner returns 0 for pass, 1 for case failures, and 3 when its frozen
# platform contract is unavailable. This wrapper reserves 2 for failures that
# prevented a held-out verdict from being produced at all.
HELDOUT_INFRASTRUCTURE_EXIT = 2

# These are the parts of the per-checkpoint bundle that affect which cases the
# native runner selects or whether it may judge on this host. Paths and the
# suite's generation/build settings are deliberately not inherited: the hidden
# pass supplies its own corpus and candidate and must not acquire a path back to
# the public corpus or an oracle.
JUDGING_CONTRACT_FIELDS = (
    "implemented",
    "unimplemented_policy",
    "excluded_tags",
    "scope",
    "required_platform",
)
JUDGING_CONTRACT_TYPES = {
    "unimplemented_policy": str,
    "excluded_tags": list,
    "scope": dict,
    "required_platform": str,
}


def bundled_config(workdir: Path, test_dir: str) -> Path:
    """The per-checkpoint config the stage bundle placed in the sandbox."""
    return workdir / test_dir / "config.json"


def hidden_runner_config(config_path: Path, candidate: str) -> dict[str, Any]:
    """Copy the bundled checkpoint's filtering contract for hidden judging.

    Read from the sandbox's own bundled config rather than passed in, because
    `extra_test_command` is one string shared by every checkpoint in the
    manifest -- there is nowhere in it to vary the flags or scope per stage.

    Only runner-relevant contract fields are copied. In particular, bundled
    paths are not: the held-out corpus is selected separately by
    `heldout_contract.corpus_path`, and the candidate path must be the candidate
    supplied for this invocation rather than the bundle's placeholder.
    """
    if not config_path.is_file():
        print(
            f"heldout_judge: no bundled config at {config_path}; cannot tell "
            "which checkpoint this is",
            file=sys.stderr,
        )
        raise SystemExit(HELDOUT_INFRASTRUCTURE_EXIT)
    try:
        bundled = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"heldout_judge: cannot read {config_path}: {error}", file=sys.stderr)
        raise SystemExit(HELDOUT_INFRASTRUCTURE_EXIT)
    if not isinstance(bundled, dict):
        print(
            f"heldout_judge: {config_path} must contain a JSON object",
            file=sys.stderr,
        )
        raise SystemExit(HELDOUT_INFRASTRUCTURE_EXIT)

    flags = bundled.get("implemented")
    if not isinstance(flags, list):
        print(
            f"heldout_judge: {config_path} has no 'implemented' list",
            file=sys.stderr,
        )
        raise SystemExit(HELDOUT_INFRASTRUCTURE_EXIT)

    for field, expected_type in JUDGING_CONTRACT_TYPES.items():
        if field in bundled and not isinstance(bundled[field], expected_type):
            print(
                f"heldout_judge: {config_path} field {field!r} must be "
                f"{expected_type.__name__}",
                file=sys.stderr,
            )
            raise SystemExit(HELDOUT_INFRASTRUCTURE_EXIT)

    config: dict[str, Any] = {"paths": {"candidate_bin": str(candidate)}}
    for field in JUDGING_CONTRACT_FIELDS:
        if field in bundled:
            config[field] = bundled[field]
    # Preserve the prior normalization of cumulative flag identifiers while
    # inheriting all other present fields verbatim.
    config["implemented"] = [str(flag) for flag in flags]
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utility", required=True)
    parser.add_argument("--test-dir", required=True,
                        help="where the bundle is mounted inside the workdir")
    parser.add_argument("--candidate", required=True,
                        help="the built executable, relative to the workdir")
    parser.add_argument("--workdir", type=Path, default=Path.cwd())
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    suite_root = repo / "tests" / f"{args.utility}-test-suite"
    # The suite's runner reads `.json.gz` transparently, so the corpus is handed
    # over compressed exactly as it is committed.
    corpus = heldout_contract.corpus_path(suite_root)
    if not corpus.is_file():
        print(f"heldout_judge: no held-out corpus for {args.utility} "
              f"({corpus}); no verdict produced", file=sys.stderr)
        return HELDOUT_INFRASTRUCTURE_EXIT

    runner_config = hidden_runner_config(
        bundled_config(args.workdir, args.test_dir), args.candidate
    )
    flags = runner_config["implemented"]

    # A throwaway config carrying this checkpoint's judging contract. The
    # suite's runner applies the same filtering and platform semantics as the
    # visible pass; nothing in the repository is modified.
    with tempfile.TemporaryDirectory() as temp:
        config = Path(temp) / "heldout-config.json"
        config.write_text(
            json.dumps(runner_config),
            encoding="utf-8",
        )
        command = [
            sys.executable, str(suite_root / "runner.py"), str(corpus),
            "--config", str(config), "--", str(args.candidate),
        ]
        print(f"held-out pass: {args.utility}, implemented={flags or '[]'}")
        completed = subprocess.run(command, cwd=str(args.workdir))
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
