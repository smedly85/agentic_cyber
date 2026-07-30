#!/usr/bin/env python3
"""Resolve a utility manifest into an ordered lineage stage plan.

`scripts/run_lineage_experiment.sh` shells out to this once per invocation so
that no utility detail -- source path, build command, prompt ordering,
cumulative flag list -- lives in the controller. Everything the controller needs
per stage comes back either as JSON (`--emit plan`, stored for provenance) or as
a tab-separated table the shell reads line by line (`--emit stages`).

The plan also carries a configuration fingerprint. A resumed lineage run must
not silently mix stage configurations, and comparing one hash is both cheaper
and harder to get wrong than comparing a dozen fields: the fingerprint covers
the resolved manifest, the *contents* of every checkpoint prompt, the contents
of the judge script, each checkpoint's cumulative implemented flags, each
checkpoint's visible test bundle, and the model/agent/temperature/repair
settings the stages run under. The number of lineages is deliberately excluded,
so extending an existing run from 10 lineages to 15 is allowed while editing a
prompt is not.

Each checkpoint additionally resolves the fingerprint of the test bundle the
agent will be able to read there (`scripts/stage_test_bundle.py`). That is the
one piece of stage configuration that is neither a file in the repository nor a
command-line setting -- it is derived from the suite, the allowlist and the
checkpoint's flags -- so it has to be computed rather than hashed from a path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage_test_bundle  # noqa: E402

SCHEMA_VERSION = 1


class ManifestError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"lineage_plan: {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_workdir_relative(value: str, label: str) -> str:
    path = PurePosixPath(value)
    ok = bool(value) and not path.is_absolute() and ".." not in path.parts
    ok = ok and str(path) == value and "\\" not in value
    if not ok:
        raise ManifestError(f"{label} must be a normalized relative path: {value!r}")
    return value


def require_repo_file(repo: Path, value: str, label: str) -> Path:
    require_workdir_relative(value, label)
    resolved = repo / value
    if not resolved.is_file():
        raise ManifestError(f"{label} not found: {resolved}")
    return resolved


def load_manifest(repo: Path, utility: str) -> tuple[Path, dict[str, Any]]:
    if "/" in utility or "\\" in utility or utility.startswith("."):
        raise ManifestError(f"--utility must be a bare manifest name: {utility!r}")
    path = repo / "experiments" / "utilities" / f"{utility}.json"
    if not path.is_file():
        available = ", ".join(sorted(available_utilities(repo))) or "(none)"
        raise ManifestError(f"no manifest for {utility!r}; available: {available}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise ManifestError(f"{path} must contain a JSON object")
    return path, data


def available_utilities(repo: Path) -> list[str]:
    directory = repo / "experiments" / "utilities"
    if not directory.is_dir():
        return []
    return [entry.stem for entry in sorted(directory.glob("*.json"))]


def resolve_plan(
    repo: Path,
    utility: str,
    model: str,
    temperature: str,
    agent: str,
    max_loops: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    manifest_path, manifest = load_manifest(repo, utility)

    schema_version = manifest.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ManifestError(
            f"{manifest_path}: schema_version must be {SCHEMA_VERSION}, "
            f"got {schema_version!r}"
        )
    if manifest.get("utility") != utility:
        raise ManifestError(
            f"{manifest_path}: 'utility' is {manifest.get('utility')!r} but the "
            f"file is named {utility}.json"
        )

    for key in ("program", "source_path", "executable_path", "build_command",
                "test_dir", "judge"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ManifestError(f"{manifest_path}: '{key}' must be a non-empty string")

    source_path = require_workdir_relative(manifest["source_path"], "source_path")
    executable_path = require_workdir_relative(
        manifest["executable_path"], "executable_path"
    )
    test_dir = require_workdir_relative(manifest["test_dir"], "test_dir")
    if not (repo / test_dir).is_dir():
        raise ManifestError(f"test_dir not found: {repo / test_dir}")
    judge = manifest["judge"]
    judge_file = require_repo_file(repo, judge, "judge")

    checkpoints = manifest.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise ManifestError(f"{manifest_path}: 'checkpoints' must be a non-empty list")

    resolved: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    previous_flags: set[str] = set()
    for index, checkpoint in enumerate(checkpoints):
        if not isinstance(checkpoint, dict):
            raise ManifestError(f"{manifest_path}: checkpoint {index} must be an object")
        checkpoint_id = checkpoint.get("id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            raise ManifestError(f"{manifest_path}: checkpoint {index} needs a string id")
        if any(character in checkpoint_id for character in "/\\ \t"):
            raise ManifestError(
                f"{manifest_path}: checkpoint id {checkpoint_id!r} must be a bare "
                "directory-safe token"
            )
        if checkpoint_id in seen_ids:
            raise ManifestError(f"{manifest_path}: duplicate checkpoint id {checkpoint_id!r}")
        seen_ids.add(checkpoint_id)

        expected_mode = "new" if index == 0 else "existing"
        source_mode = checkpoint.get("source_mode", expected_mode)
        if source_mode != expected_mode:
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} must use "
                f"source_mode {expected_mode!r} (a lineage creates the source at the "
                "first checkpoint and inherits it at every later one)"
            )

        prompt = checkpoint.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} needs a 'prompt' path"
            )
        prompt_file = require_repo_file(repo, prompt, f"checkpoint {checkpoint_id} prompt")

        flags = checkpoint.get("implemented_flags", [])
        if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} implemented_flags must "
                "be a list of strings"
            )
        if any("\t" in flag or not flag for flag in flags):
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} implemented_flags must "
                "be non-empty and tab-free"
            )
        if len(set(flags)) != len(flags):
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} repeats an implemented flag"
            )
        # implemented_flags is cumulative by contract: the judge receives it
        # verbatim, and a checkpoint that dropped an earlier flag would stop
        # re-checking that earlier checkpoint's cases.
        if not previous_flags <= set(flags):
            missing = sorted(previous_flags - set(flags))
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} drops previously "
                f"implemented flags {missing}; implemented_flags must be cumulative"
            )
        previous_flags = set(flags)

        feature_test_command = checkpoint.get("feature_test_command")
        if feature_test_command is None:
            feature_test_command = " ".join([judge, executable_path, *flags])
        if not isinstance(feature_test_command, str) or not feature_test_command:
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} feature_test_command "
                "must be a non-empty string"
            )
        if "\t" in feature_test_command:
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} feature_test_command "
                "must not contain a tab"
            )

        entry = {
            "index": index,
            "id": checkpoint_id,
            "name": checkpoint.get("name", checkpoint_id),
            "prompt": prompt,
            "prompt_sha256": sha256_file(prompt_file),
            "source_mode": source_mode,
            "implemented_flags": list(flags),
            "feature_test_command": feature_test_command,
        }
        # What the agent will actually be able to read at this checkpoint. The
        # bundle is derived from the suite, the allowlist and this checkpoint's
        # flags, so hashing it covers all three: regenerated goldens, an edited
        # allowlist and a changed flag list each move the fingerprint, and a
        # resume across any of them is refused rather than silently mixed.
        entry["test_bundle_fingerprint"] = stage_test_bundle.fingerprint(
            repo, test_dir, entry, utility
        )
        resolved.append(entry)

    base_test_command = manifest.get("base_test_command", "")
    extra_test_command = manifest.get("extra_test_command", "")
    for label, command in (
        ("base_test_command", base_test_command),
        ("extra_test_command", extra_test_command),
    ):
        if not isinstance(command, str):
            raise ManifestError(f"{manifest_path}: '{label}' must be a string")
        if "\t" in command:
            raise ManifestError(f"{manifest_path}: '{label}' must not contain a tab")

    plan = {
        "schema_version": SCHEMA_VERSION,
        "manifest": str(manifest_path.relative_to(repo).as_posix()),
        "utility": utility,
        "program": manifest["program"],
        "source_path": source_path,
        "source_basename": PurePosixPath(source_path).name,
        "executable_path": executable_path,
        "build_command": manifest["build_command"],
        "test_dir": test_dir,
        "judge": judge,
        "judge_sha256": sha256_file(judge_file),
        "base_test_command": base_test_command,
        "extra_test_command": extra_test_command,
        "checkpoints": resolved,
        "model": model,
        "temperature": float(temperature),
        "agent": agent,
        "max_loops": max_loops,
        "timeout_seconds": timeout_seconds,
    }
    plan["config_fingerprint"] = fingerprint(plan)
    return plan


def fingerprint(plan: dict[str, Any]) -> str:
    """Hash everything that must not change between resumed stage runs.

    The plan carries all of it, so hashing the plan covers: the resolved
    manifest (utility, program, source path, executable path, build command,
    test directory, judge path, ordered checkpoint list); the *contents* of
    every checkpoint prompt and of the judge script, via their SHA-256; each
    checkpoint's cumulative implemented flags and its resolved judge command;
    each checkpoint's visible test bundle, via its bundle fingerprint; and the
    model, agent, temperature, repair budget and per-session timeout the stages
    run under.

    Deliberately excluded: the number of lineages (extending a run is a valid
    resume) and the output directory (relocating results is not a condition
    change).
    """
    material = {key: value for key, value in plan.items() if key != "config_fingerprint"}
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def emit_stages(plan: dict[str, Any]) -> str:
    lines = []
    for checkpoint in plan["checkpoints"]:
        lines.append(
            "\t".join(
                [
                    checkpoint["id"],
                    checkpoint["name"],
                    checkpoint["prompt"],
                    checkpoint["source_mode"],
                    checkpoint["feature_test_command"],
                    ",".join(checkpoint["implemented_flags"]),
                    checkpoint["test_bundle_fingerprint"],
                ]
            )
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--utility")
    parser.add_argument("--model", default="")
    parser.add_argument("--temperature", default="0")
    parser.add_argument("--agent", default="build")
    parser.add_argument("--max-loops", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--emit",
        choices=("plan", "stages", "utilities", "fingerprint"),
        default="plan",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()

    if args.emit == "utilities":
        print("\n".join(available_utilities(repo)))
        return 0

    if not args.utility:
        raise ManifestError("--utility is required")

    plan = resolve_plan(
        repo,
        args.utility,
        args.model,
        args.temperature,
        args.agent,
        args.max_loops,
        args.timeout_seconds,
    )

    if args.emit == "stages":
        print(emit_stages(plan))
    elif args.emit == "fingerprint":
        print(plan["config_fingerprint"])
    else:
        print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ManifestError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
