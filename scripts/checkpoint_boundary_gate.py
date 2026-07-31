#!/usr/bin/env python3
"""Controller-only gate: reject a candidate that built a later checkpoint early.

THE AGENT MUST NEVER SEE THIS FILE, ITS PROBES, OR ITS RESULTS DURING A
CHECKPOINT. It lives in `scripts/` precisely because `scripts/` is never copied
into a working directory: `run_experiment.sh` seeds a sandbox with the prompt,
the stage test bundle and the seed source, and nothing else. Naming a future
flag anywhere the agent can read it would tell it which option to build next,
which is the very thing the incremental design is measuring.

Why a hidden gate at all
------------------------
Cumulative flag filtering tests the ladder only from below: at checkpoint 000
the judge runs the base cases, and a candidate that had also implemented every
later flag would pass all of them. Nothing detected that. The obvious fix --
freezing "at 000, `-H` must be rejected" as an ordinary suite case -- puts the
string `-H` into the bundle at checkpoint 000, so it trades a methodological
hole for a leak. Hence: same assertion, run by the controller, after the agent's
session is over.

Contract
--------
* runs only after public validation has succeeded, and before promotion;
* is never copied into the worktree or the stage bundle;
* its failures never feed the repair loop -- the agent is not told, and is not
  asked to fix it, because doing so would disclose the flag;
* on failure the stage fails with `premature_feature_implementation`, the
  candidate is not promoted, and no `final/` artifact is produced.

Source of truth
---------------
`experiments/utilities/<utility>.json`. The allowed set at a checkpoint is that
checkpoint's cumulative `implemented_flags`; the forbidden set is every flag the
manifest introduces later. Each flag is probed under every spelling the
manifest's `flag_aliases` declares for it -- short and long -- so a future
feature cannot slip in under its long name. No alias is invented here.

Rejection contract
------------------
A forbidden option must be refused the way an unknown option is refused. The
probe asserts:

  * a nonzero exit status;
  * no termination by signal (a crash is not a rejection);
  * no sanitizer diagnostic;
  * a diagnostic on stderr, where the utility's contract requires one;
  * no successful execution of the future feature (nothing on stdout).

These are deliberately weak enough to accept any reasonable "unknown option"
implementation and strong enough that actually honouring the flag fails.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SANITIZER_MARKERS = (
    b"AddressSanitizer",
    b"UndefinedBehaviorSanitizer",
    b"LeakSanitizer",
    b"runtime error:",
)

PROBE_TIMEOUT_SECONDS = 20


class GateError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"checkpoint_boundary_gate: {message}")


def load_manifest(repo: Path, utility: str) -> dict[str, Any]:
    path = repo / "experiments" / "utilities" / f"{utility}.json"
    if not path.is_file():
        raise GateError(f"no manifest for {utility!r}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GateError(f"cannot read {path}: {error}") from error


def spellings(manifest: dict[str, Any], flag: str) -> list[str]:
    """Every way the manifest says this flag may be written: short, then long.

    Aliases come from the manifest's `flag_aliases` and nowhere else. A long
    option the manifest does not declare is not probed, because guessing one
    would test a contract the prompts never stated.
    """
    aliases = (manifest.get("flag_aliases") or {}).get(flag, [])
    return [flag, *aliases]


def availability(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Per checkpoint: which manifest options are allowed and which forbidden.

    Monotonic by construction -- `allowed` is the checkpoint's own cumulative
    list, `forbidden` is everything the ladder introduces after it -- so the
    matrix cannot drift from the manifest it is derived from.

    `allowed`/`forbidden` list canonical short flags; `allowed_options` and
    `forbidden_options` expand each to all of its declared spellings. The gate
    probes the expanded lists, so implementing a future feature under its long
    name is caught exactly as implementing it under its short name is.
    """
    checkpoints = manifest.get("checkpoints") or []
    ladder: list[str] = []
    for checkpoint in checkpoints:
        for flag in checkpoint.get("implemented_flags", []):
            if flag not in ladder:
                ladder.append(flag)

    rows = []
    for checkpoint in checkpoints:
        allowed = list(checkpoint.get("implemented_flags", []))
        forbidden = [flag for flag in ladder if flag not in allowed]
        rows.append(
            {
                "checkpoint_id": checkpoint["id"],
                "allowed": allowed,
                "forbidden": forbidden,
                "allowed_options": [
                    option for flag in allowed
                    for option in spellings(manifest, flag)
                ],
                # Each entry pairs the option actually passed with the canonical
                # short flag, which is what decides the probe's argument shape.
                "forbidden_options": [
                    {"option": option, "flag": flag}
                    for flag in forbidden
                    for option in spellings(manifest, flag)
                ],
            }
        )
    return rows


def row_for(manifest: dict[str, Any], checkpoint_id: str) -> dict[str, Any]:
    for row in availability(manifest):
        if row["checkpoint_id"] == checkpoint_id:
            return row
    raise GateError(f"no checkpoint {checkpoint_id!r} in this manifest")


# Manually defined rejection contracts. Each entry says how to invoke the
# utility so that the ONLY thing wrong with the command line is the forbidden
# option, and whether the contract requires a diagnostic. A fully featured GNU
# binary is deliberately not used as the oracle here: GNU implements these flags,
# so it could never model "this must be refused".
#
# `args` is built by a callable taking the fixture directory, so a probe can use
# real operands without any shared state between probes.
# `option` is the spelling under test (short or long); `flag` is its canonical
# short form, which decides the argument shape -- `--mode` needs a mode operand
# for exactly the reason `-m` does.
def _sort_probe(option: str, flag: str, fixture: Path) -> dict[str, Any]:
    return {"argv": [option], "stdin": b"b\na\n"}


def _mkdir_probe(option: str, flag: str, fixture: Path) -> dict[str, Any]:
    target = str(fixture / "made")
    # -m/--mode takes a mode operand; giving it one makes the probe a
    # well-formed invocation of the future feature rather than a malformed
    # command line that any argument parser would reject anyway.
    argv = [option, "755", target] if flag == "-m" else [option, target]
    return {"argv": argv, "stdin": b""}


def _grep_probe(option: str, flag: str, fixture: Path) -> dict[str, Any]:
    haystack = fixture / "a.txt"
    haystack.write_bytes(b"alpha\nbeta\n")
    if flag == "-r":
        return {"argv": [option, "alpha", str(fixture)], "stdin": b""}
    return {"argv": [option, "alpha", str(haystack)], "stdin": b""}


def _chmod_probe(option: str, flag: str, fixture: Path) -> dict[str, Any]:
    target = fixture / "f"
    target.write_bytes(b"x")
    os.chmod(target, 0o644)
    return {"argv": [option, "644", str(target)], "stdin": b""}


PROBES = {
    "sort": {"build": _sort_probe, "requires_diagnostic": True},
    "mkdir": {"build": _mkdir_probe, "requires_diagnostic": True},
    "grep": {"build": _grep_probe, "requires_diagnostic": True},
    "chmod": {"build": _chmod_probe, "requires_diagnostic": True},
}


def run_probe(executable: Path, utility: str, option: str,
              flag: str) -> dict[str, Any]:
    """Invoke the candidate with one forbidden option and judge the refusal."""
    contract = PROBES.get(utility)
    if contract is None:
        raise GateError(f"no rejection contract defined for {utility!r}")

    fixture = Path(tempfile.mkdtemp(prefix="boundary-probe-"))
    try:
        plan = contract["build"](option, flag, fixture)
        try:
            completed = subprocess.run(
                [str(executable), *plan["argv"]],
                input=plan["stdin"],
                capture_output=True,
                timeout=PROBE_TIMEOUT_SECONDS,
                cwd=str(fixture),
            )
        except subprocess.TimeoutExpired:
            return {
                "option": option, "flag": flag, "argv": plan["argv"],
                "rejected": False,
                "violation": "timed out instead of rejecting the option",
            }
        except OSError as error:
            raise GateError(f"cannot execute {executable}: {error}") from error

        stdout, stderr = completed.stdout, completed.stderr
        status = completed.returncode
        combined = stdout + stderr
        problems = []

        if status == 0:
            problems.append(
                "exited 0: the option was accepted, so the feature is "
                "implemented ahead of its checkpoint"
            )
        if status < 0:
            problems.append(f"terminated by signal {-status}: a crash is not a rejection")
        if any(marker in combined for marker in SANITIZER_MARKERS):
            problems.append("sanitizer diagnostic while rejecting the option")
        if stdout:
            problems.append(
                f"wrote {len(stdout)} byte(s) to stdout: the future feature "
                "produced output"
            )
        if contract["requires_diagnostic"] and not stderr:
            problems.append("no diagnostic on stderr")

        return {
            "option": option,
            "flag": flag,
            "argv": plan["argv"],
            "exit_status": status,
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "rejected": not problems,
            "violation": "; ".join(problems) or None,
        }
    finally:
        shutil.rmtree(fixture, ignore_errors=True)


def evaluate(repo: Path, utility: str, checkpoint_id: str,
             executable: Path) -> dict[str, Any]:
    manifest = load_manifest(repo, utility)
    row = row_for(manifest, checkpoint_id)
    if not executable.is_file():
        raise GateError(f"candidate executable not found: {executable}")

    probes = [
        run_probe(executable, utility, entry["option"], entry["flag"])
        for entry in row["forbidden_options"]
    ]
    violations = [probe for probe in probes if not probe["rejected"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "utility": utility,
        "checkpoint_id": checkpoint_id,
        "allowed_flags": row["allowed"],
        "forbidden_flags": row["forbidden"],
        "allowed_options": row["allowed_options"],
        "forbidden_options": [e["option"] for e in row["forbidden_options"]],
        "probes": probes,
        "violations": [probe["option"] for probe in violations],
        "passed": not violations,
        # Named so the controller can record a distinct stage failure reason.
        "failure_reason": "premature_feature_implementation" if violations else None,
        "_comment": (
            "Controller-only. Never copied into a working directory or a stage "
            "test bundle; never shown to the agent during its checkpoint."
        ),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Controller-only checkpoint boundary gate.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--utility", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--executable", type=Path,
                        help="Built candidate. Omit with --emit matrix.")
    parser.add_argument("--report", type=Path, help="Write the JSON report here")
    parser.add_argument("--emit", choices=("report", "matrix"), default="report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()

    if args.emit == "matrix":
        print(json.dumps(availability(load_manifest(repo, args.utility)), indent=2))
        return 0

    if args.executable is None:
        raise GateError("--executable is required")

    report = evaluate(repo, args.utility, args.checkpoint, args.executable)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
