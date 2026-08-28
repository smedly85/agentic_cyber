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
checkpoint's visible test bundle, the Aider/model-pair/repair settings the stages run
under, the editor edit format, the whole sampling configuration (temperature,
architect_think, top_p, sampling_seed, max_tokens), explicit model-definition
provenance, and the shared automation notice that is expanded into every
prompt. The number of lineages is deliberately excluded, so extending an
existing run from 10 lineages to 15 is allowed while editing a prompt, changing
a sampling knob or rewording the notice is not.

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
import platform
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompt_render  # noqa: E402
import aider_settings  # noqa: E402
import stage_test_bundle  # noqa: E402
import temperature_value  # noqa: E402

SCHEMA_VERSION = 1

# ASCII unit separator. Chosen for `--emit stages` because it is not IFS
# whitespace in Bash: adjacent separators therefore delimit an empty field
# rather than collapsing, and fields are not whitespace-trimmed. See
# emit_stages for the bug that motivated it.
RECORD_SEPARATOR = "\x1f"


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


def optional_float(value: Any, label: str) -> float | None:
    """A sampling knob that may be unset. Unset stays None -- a real JSON null
    in the plan -- rather than 0 or "", so "left to the server default" and
    "explicitly set to zero" never collapse into the same recorded condition."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ManifestError(f"{label} must be numeric, got {value!r}") from None


def optional_int(value: Any, label: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ManifestError(f"{label} must be an integer, got {value!r}") from None


def optional_json_object(value: Any, label: str) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as error:
        raise ManifestError(f"{label} must be valid JSON: {error}") from None
    if not isinstance(parsed, dict):
        raise ManifestError(f"{label} must be a JSON object")
    return parsed


def resolve_plan(
    repo: Path,
    utility: str,
    model: str,
    temperature: str,
    agent: str | None,
    max_loops: int,
    timeout_seconds: int,
    top_p: Any = None,
    sampling_seed: Any = None,
    max_tokens: Any = None,
    model_provenance_json: Any = None,
    editor_model: str = "ollama_chat/qwen3-coder-next:latest",
    aider_version: str = "unknown",
    remote_base_url: str = "",
    remote_api_key_env: str = "",
    architect_think: Any = None,
    editor_edit_format: str = aider_settings.EDITOR_EDIT_FORMAT,
) -> dict[str, Any]:
    # `agent` remains only as a Python-call compatibility slot for older test
    # and analysis helpers. It is not emitted, fingerprinted or exposed by the
    # shell CLIs; Aider always uses architect mode.
    del agent
    architect_model = model
    temperature = temperature_value.canonicalize(temperature)
    if architect_think in (None, ""):
        architect_think = None
    elif architect_think not in aider_settings.ARCHITECT_THINK_VALUES:
        raise ManifestError(
            "architect_think must be one of "
            + ", ".join(aider_settings.ARCHITECT_THINK_VALUES)
        )
    if editor_edit_format not in aider_settings.EDITOR_EDIT_FORMATS:
        raise ManifestError(
            "editor_edit_format must be one of "
            + ", ".join(aider_settings.EDITOR_EDIT_FORMATS)
        )
    if not remote_base_url:
        remote_transport = "default"
    elif architect_model.startswith("ollama_chat/") and editor_model.startswith(
        "ollama_chat/"
    ):
        remote_transport = "ollama_native"
    elif architect_model.startswith("openai/") and editor_model.startswith("openai/"):
        remote_transport = "openai_compatible"
    else:
        raise ManifestError(
            "remote model pair must use matching ollama_chat/* or openai/* prefixes"
        )
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
        if any(RECORD_SEPARATOR in flag or "\n" in flag or not flag
               for flag in flags):
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
        if (RECORD_SEPARATOR in feature_test_command
                or "\n" in feature_test_command):
            raise ManifestError(
                f"{manifest_path}: checkpoint {checkpoint_id} "
                "feature_test_command must not contain the record separator "
                "or a newline"
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

    # Long-form spellings of the checkpoint flags. The boundary gate probes
    # these alongside the short forms, so a candidate cannot slip a future
    # feature in under its long name. Declared here rather than discovered, and
    # validated against the ladder so an alias can never name a flag no
    # checkpoint introduces.
    # The suite's own config.json owns the platform contract; the manifest
    # simply inherits it, so there is one place to change it.
    manifest_platform = None
    suite_config = repo / test_dir / "config.json"
    if suite_config.is_file():
        try:
            manifest_platform = json.loads(
                suite_config.read_text(encoding="utf-8")
            ).get("required_platform")
        except (OSError, UnicodeError, json.JSONDecodeError):
            manifest_platform = None

    flag_aliases = manifest.get("flag_aliases", {})
    if not isinstance(flag_aliases, dict):
        raise ManifestError(f"{manifest_path}: 'flag_aliases' must be an object")
    ladder = {flag for entry in resolved for flag in entry["implemented_flags"]}
    for flag, aliases in sorted(flag_aliases.items()):
        if flag not in ladder:
            raise ManifestError(
                f"{manifest_path}: flag_aliases names {flag!r}, which no "
                "checkpoint introduces"
            )
        if not isinstance(aliases, list) or not aliases:
            raise ManifestError(
                f"{manifest_path}: flag_aliases[{flag!r}] must be a non-empty list"
            )
        for alias in aliases:
            if not isinstance(alias, str) or not alias.startswith("--"):
                raise ManifestError(
                    f"{manifest_path}: {alias!r} is not a long option"
                )
    duplicates = [
        alias for alias in
        [a for aliases in flag_aliases.values() for a in aliases]
        if [a for aliases in flag_aliases.values() for a in aliases].count(alias) > 1
    ]
    if duplicates:
        raise ManifestError(
            f"{manifest_path}: alias {sorted(set(duplicates))} is claimed by "
            "more than one flag"
        )

    base_test_command = manifest.get("base_test_command", "")
    extra_test_command = manifest.get("extra_test_command", "")
    for label, command in (
        ("base_test_command", base_test_command),
        ("extra_test_command", extra_test_command),
    ):
        if not isinstance(command, str):
            raise ManifestError(f"{manifest_path}: '{label}' must be a string")
        if RECORD_SEPARATOR in command or "\n" in command:
            raise ManifestError(
                f"{manifest_path}: '{label}' must not contain the record "
                "separator or a newline"
            )

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
        "flag_aliases": {k: list(v) for k, v in sorted(flag_aliases.items())},
        # Platform contract. Some frozen suites are only valid on one OS, so
        # the requirement and the host actually running are both part of the
        # configuration: resuming a run on a different platform must not
        # silently mix results produced under different expectations.
        "required_platform": manifest_platform,
        "host_platform": platform.system(),
        "base_test_command": base_test_command,
        "extra_test_command": extra_test_command,
        "checkpoints": resolved,
        "agent_backend": "aider",
        "aider_version": aider_version,
        "architect_model": architect_model,
        "editor_model": editor_model,
        "architect_mode": True,
        # Kept as an architect alias for generic/legacy analysis readers.
        "model": architect_model,
        # Explicit metadata only. In particular, top_k is never inferred from
        # a derived Ollama model alias and is not sent as a request parameter.
        "model_provenance": optional_json_object(
            model_provenance_json, "model_provenance_json"
        ),
        "temperature": float(temperature),
        # The rest of the sampling configuration, carried the same way
        # temperature is. Null means the flag was not passed, so the server's
        # own default applied; a number means this run pinned it. Both are
        # conditions a resume must not cross, which is why they are in the
        # fingerprint rather than only in the console output.
        "top_p": optional_float(top_p, "top_p"),
        "sampling_seed": optional_int(sampling_seed, "sampling_seed"),
        "max_tokens": optional_int(max_tokens, "max_tokens"),
        # Native Ollama/Qwen architect thinking control. This is deliberately a
        # string, not reasoning_effort and not a boolean.
        "architect_think": architect_think,
        "editor_temperature": aider_settings.EDITOR_TEMPERATURE,
        "editor_sampling_seed": aider_settings.EDITOR_SEED,
        "editor_edit_format": editor_edit_format,
        # Bundle-only callers resolve checkpoints with an empty model because
        # they need no inference configuration. Formal shell entry points
        # require --model before resolving a runnable plan.
        "aider_model_settings": (
            aider_settings.build_model_settings(
                architect_model,
                editor_model,
                temperature,
                top_p=top_p,
                sampling_seed=sampling_seed,
                max_tokens=max_tokens,
                architect_think=architect_think,
                editor_edit_format=editor_edit_format,
            )
            if architect_model
            else []
        ),
        "remote_base_url": remote_base_url or None,
        "remote_api_key_env": remote_api_key_env or None,
        "remote_transport": remote_transport,
        "max_loops": max_loops,
        "timeout_seconds": timeout_seconds,
        # The shared automation notice is expanded into every prompt the model
        # sees (scripts/prompt_render.py). It is therefore part of the prompt
        # configuration even though no checkpoint prompt file contains it, so
        # its hash is carried here: editing the notice moves the fingerprint
        # exactly as editing a checkpoint prompt does.
        "automation_notice_sha256": prompt_render.notice_sha256(repo),
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
    each checkpoint's visible test bundle, via its bundle fingerprint; the
    Aider version, architect/editor model pair, architect mode, fixed editor
    sampling, repair budget and per-invocation timeout the stages run under;
    the selected editor edit format; the full sampling configuration (temperature, architect_think, top_p,
    sampling_seed, max_tokens -- a null among them is itself a condition, meaning the server
    default applied); explicit model-definition provenance such as an Ollama
    Modelfile top_k value; and the shared automation notice, via
    automation_notice_sha256, since it is expanded into every prompt the model
    sees without appearing in any prompt file.

    Deliberately excluded: the number of lineages (extending a run is a valid
    resume) and the output directory (relocating results is not a condition
    change).
    """
    material = {key: value for key, value in plan.items() if key != "config_fingerprint"}
    # Historical plans predate this optional key. Omitting the new control is
    # the same request condition as those plans, so preserve their fingerprint;
    # explicit low/medium/high values remain covered both here and in the
    # generated Aider settings.
    if material.get("architect_think") is None:
        material.pop("architect_think", None)
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def emit_stages(plan: dict[str, Any]) -> str:
    """One record per checkpoint, fields separated by ASCII US (0x1f).

    NOT tab. Tab is IFS *whitespace* in Bash, so `IFS=$'\\t' read` collapses runs
    of tabs and drops empty fields entirely. Checkpoint 000 has an empty
    cumulative flag list, so its record ended `...\\t\\t<fingerprint>`: the two
    adjacent tabs collapsed into one, the fingerprint slid into `stage_flags`,
    and `stage_bundle_fingerprint` came back empty. The controller then compared
    an empty planned fingerprint against the freshly built one and aborted every
    run at stage 000 with "test bundle ... changed since the run was planned".

    0x1f is not IFS whitespace, so adjacent separators delimit an empty field
    exactly as they should, and no field is whitespace-trimmed -- which also
    keeps paths and commands containing spaces intact.
    """
    lines = []
    for checkpoint in plan["checkpoints"]:
        fields = [
            checkpoint["id"],
            checkpoint["name"],
            checkpoint["prompt"],
            checkpoint["source_mode"],
            checkpoint["feature_test_command"],
            ",".join(checkpoint["implemented_flags"]),
            checkpoint["test_bundle_fingerprint"],
        ]
        for field in fields:
            if RECORD_SEPARATOR in field or "\n" in field:
                raise ManifestError(
                    f"checkpoint {checkpoint['id']} field {field!r} contains "
                    "the record separator or a newline; it cannot be passed to "
                    "the controller unambiguously"
                )
        lines.append(RECORD_SEPARATOR.join(fields))
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--utility")
    parser.add_argument("--model", default="")
    parser.add_argument("--editor-model", default="")
    parser.add_argument("--aider-version", default="unknown")
    parser.add_argument("--temperature", default="0")
    parser.add_argument("--max-loops", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    # Passed through as strings so "unset" survives the shell as an empty
    # argument and becomes a JSON null rather than 0.
    parser.add_argument("--top-p", default="")
    parser.add_argument("--sampling-seed", default="")
    parser.add_argument("--max-tokens", default="")
    parser.add_argument("--architect-think", default="")
    parser.add_argument(
        "--editor-edit-format", default=aider_settings.EDITOR_EDIT_FORMAT
    )
    parser.add_argument("--model-provenance-json", default="")
    parser.add_argument("--remote-base-url", default="")
    parser.add_argument("--remote-api-key-env", default="")
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
        None,
        args.max_loops,
        args.timeout_seconds,
        top_p=args.top_p,
        sampling_seed=args.sampling_seed,
        max_tokens=args.max_tokens,
        architect_think=args.architect_think,
        editor_edit_format=args.editor_edit_format,
        model_provenance_json=args.model_provenance_json,
        editor_model=args.editor_model,
        aider_version=args.aider_version,
        remote_base_url=args.remote_base_url,
        remote_api_key_env=args.remote_api_key_env,
    )

    if args.emit == "stages":
        # LF explicitly. On Windows `print` would translate to CRLF, and the
        # shell reader would then carry a trailing carriage return into the last
        # field of every record -- silently corrupting the test-bundle
        # fingerprint it parses out.
        try:
            sys.stdout.reconfigure(newline="\n")
        except (AttributeError, ValueError):        # pragma: no cover
            pass
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
