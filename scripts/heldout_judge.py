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

  * It does not choose which cases to run. The suite's runner already filters by
    the cumulative `implemented` flag list, which is how the visible pass gets
    per-checkpoint selection. This reads that same list out of the bundled
    config in the sandbox -- the one `stage_test_bundle.py` wrote for this
    checkpoint -- so the held-out pass is scoped to exactly the checkpoint being
    judged, with no per-checkpoint configuration of its own to drift.

  * It does not feed anything back. `run_experiment.sh` runs the extra command
    once, after the last repair loop, and never renders its output into a
    continuation prompt.

Exit status is the runner's own, so a held-out failure surfaces as a nonzero
`extra_test_exit_code` in the attempt metadata.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

from reference_generators import heldout_contract  # noqa: E402


def bundled_config(workdir: Path, test_dir: str) -> Path:
    """The per-checkpoint config the stage bundle placed in the sandbox."""
    return workdir / test_dir / "config.json"


def implemented_flags(config_path: Path) -> list[str]:
    """The cumulative flag list for the checkpoint under judgement.

    Read from the sandbox's own bundled config rather than passed in, because
    `extra_test_command` is one string shared by every checkpoint in the
    manifest -- there is nowhere in it to vary the flags per stage.
    """
    if not config_path.is_file():
        raise SystemExit(
            f"heldout_judge: no bundled config at {config_path}; cannot tell "
            "which checkpoint this is"
        )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"heldout_judge: cannot read {config_path}: {error}")
    flags = data.get("implemented")
    if not isinstance(flags, list):
        raise SystemExit(
            f"heldout_judge: {config_path} has no 'implemented' list"
        )
    return [str(flag) for flag in flags]


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
              f"({corpus}); nothing to run", file=sys.stderr)
        return 0

    flags = implemented_flags(bundled_config(args.workdir, args.test_dir))

    # A throwaway config carrying this checkpoint's flags. The suite's runner
    # reads `implemented` from it and filters the corpus exactly as it filters
    # the visible one; nothing in the repository is modified.
    with tempfile.TemporaryDirectory() as temp:
        config = Path(temp) / "heldout-config.json"
        config.write_text(
            json.dumps({
                "paths": {"candidate_bin": str(args.candidate)},
                "implemented": flags,
                "unimplemented_policy": "skip",
                "excluded_tags": [],
            }),
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
