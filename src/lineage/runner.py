"""`python -m src lineage`: resolve the config into src/harness/run_lineage_experiment.sh.

Nothing in the single-stage or lineage mechanism is reimplemented here. This
module only:

  * reads the utility manifest (to pick the agent image by source language),
  * maps config.toml [lineage]/[retry]/[agent]/[docker] and .env roles to the
    script's flags,
  * for generator = "minisweagent", writes a private (0600) shim config and an
    AIDER_BIN wrapper, and records the generator in the script's
    fingerprinted --model-provenance-json,
  * writes <output-dir>/pipeline/invocation-<stamp>.json (redacted),
  * runs the script, then optionally src/harness/analyze_lineages.py.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from src import REPO_ROOT, __version__
from src.cache import cache_root
from src.config import ConfigError, lineage_roles, redacted, required_roles
from src.depth.runner import git_commit
from src.lineage.shim import version_string
from src.sandbox import docker

LINEAGE_SCRIPT = REPO_ROOT / "src" / "harness" / "run_lineage_experiment.sh"
ANALYZE_SCRIPT = REPO_ROOT / "src" / "harness" / "analyze_lineages.py"
COREUTILS_DIR = REPO_ROOT / "coreutils"  # coreutils/<utility>/manifests/<language>.json
KEY_ENV = "AGENT_LINEAGE_API_KEY"  # the script reads the endpoint key from this variable (aider only)


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-").lower() or "x"


def temperature_slug(value: Any) -> str:
    text = repr(float(value))
    return text.replace("-", "m").replace(".", "p")


def manifest_path(selector: str) -> Path:
    """`c-sort` -> coreutils/sort/manifests/c.json (see src/harness/linux_utilities_catalog.py)."""
    language, _, utility = selector.partition("-")
    return COREUTILS_DIR / utility / "manifests" / f"{language}.json"


def available_utilities() -> list[str]:
    return sorted(f"{p.stem}-{p.parent.parent.name}" for p in COREUTILS_DIR.glob("*/manifests/*.json"))


def load_manifest(utility: str) -> dict[str, Any]:
    path = manifest_path(utility)
    if "/" in utility or not path.is_file():
        raise ConfigError(f"unknown utility {utility!r}; available: {', '.join(available_utilities())}")
    return json.loads(path.read_text())


def source_language(manifest: Mapping[str, Any]) -> str:
    suffix = Path(manifest["source_path"]).suffix
    return {".c": "c", ".rs": "rust", ".py": "python"}.get(suffix, suffix.lstrip("."))


def image_language(language: str) -> str:
    """agent-rust for Rust; agent-c (gcc, clang, python3) for C and Python."""
    return "rust" if language == "rust" else "c"


def default_output_dir(config: Mapping[str, Any]) -> Path:
    lin = config["lineage"]
    models = config["models"]
    if lin["generator"] == "aider":
        label = f"aider-{slug(models['architect']['model'] or 'unset')}"
    else:
        topology = config["agent"]["topology"]
        label = f"msa-{topology}-{slug(models['worker']['model'] or 'unset')}"
    root = Path(lin["output_root"])
    root = root if root.is_absolute() else REPO_ROOT / root
    return root / lin["utility"] / label / f"temp-{temperature_slug(lin['sampling']['temperature'])}"


def provenance(config: Mapping[str, Any], image: str | None, image_id: str | None) -> dict[str, Any]:
    lin = config["lineage"]
    data = dict(lin["model_provenance"])
    if lin["generator"] == "minisweagent":
        agent = config["agent"]
        data["pipeline"] = {
            "generator": "minisweagent",
            "harness": version_string({"topology": agent["topology"]}),
            "topology": agent["topology"],
            "model_class": agent["model_class"],
            "roles": {r: config["models"][r]["model"] for r in required_roles(agent["topology"])},
            "step_limit": agent["step_limit"],
            "command_timeout_s": agent["command_timeout_s"],
            "token_budget": config["retry"]["token_budget"],
            "check_cmd": lin["check_cmd"],
            "image": {"tag": image, "id": image_id},
        }
    return data


def script_args(config: Mapping[str, Any], output_dir: Path, image: str | None = None, image_id: str | None = None) -> tuple[list[str], dict[str, str]]:
    """Return (argv tail for run_lineage_experiment.sh, extra environment)."""
    lin = config["lineage"]
    sampling = lin["sampling"]
    models = config["models"]
    env: dict[str, str] = {}
    args = ["--utility", lin["utility"]]

    if lin["generator"] == "aider":
        architect, editor = models["architect"], models["editor"]
        args += ["--model", architect["model"]]
        if editor["model"]:
            args += ["--editor-model", editor["model"]]
        args += ["--editor-edit-format", lin["aider"]["editor_edit_format"]]
        base = architect["api_base"]
        if editor["model"] and editor["api_base"] != base:
            raise ConfigError("the Aider generator supports one endpoint: AGENT_ARCHITECT_API_BASE and AGENT_EDITOR_API_BASE must match")
        if base:
            args += ["--remote-base-url", base]
        key = architect["api_key"]
        if key:
            env[KEY_ENV] = key
            args += ["--remote-api-key-env", KEY_ENV]
    else:
        worker = models["worker"]["model"]
        # The script requires two distinct model names and fingerprints both.
        # The architect slot carries the worker model; the editor slot names
        # the generator. Every role's model is in --model-provenance-json.
        args += ["--model", worker, "--editor-model", f"minisweagent/{config['agent']['topology']}"]

    args += ["--temperature", str(sampling["temperature"])]
    flag_for = {
        "top_p": "--top-p",
        "sampling_seed": "--sampling-seed",
        "lineage_seed_base": "--lineage-seed-base",
        "max_tokens": "--max-tokens",
        "num_ctx": "--num-ctx",
        "architect_think": "--architect-think",
    }
    for key, flag in flag_for.items():
        value = sampling[key]
        if value is not None:
            args += [flag, str(value).lower() if isinstance(value, bool) else str(value)]
    prov = provenance(config, image, image_id)
    if prov:
        args += ["--model-provenance-json", json.dumps(prov, sort_keys=True, separators=(",", ":"))]

    args += [
        "--lineages", str(lin["lineages"]),
        "--lineage-start", str(lin["lineage_start"]),
        "--max-loops", str(config["retry"]["max_loops"]),
        "--timeout", str(int(config["retry"]["session_timeout_s"])),
        "--output-dir", str(output_dir),
    ]
    if lin["allow_no_progress"]:
        args.append("--allow-no-progress")
    if lin["repair_prompt"]:
        args += ["--repair-prompt", str(lin["repair_prompt"])]
    if lin["keep_workdir"]:
        args.append("--keep-workdir")
    if lin["force"]:
        args.append("--force")
    sec = lin["security"]
    if sec["enabled"]:
        args += [
            "--security-fuzz-seconds", str(sec["fuzz_seconds"]),
            "--security-seed", str(sec["seed"]),
            "--security-timeout", str(sec["timeout"]),
            "--security-max-inputs", str(sec["max_inputs"]),
        ]
    else:
        args.append("--no-security-evaluation")
    return args, env


def shim_config(config: Mapping[str, Any]) -> dict[str, Any]:
    agent, dock = config["agent"], config["docker"]
    roles = required_roles(agent["topology"])
    return {
        "topology": agent["topology"],
        "model_class": agent["model_class"],
        "models": {r: dict(config["models"][r]) for r in roles},
        "step_limit": agent["step_limit"],
        "command_timeout_s": agent["command_timeout_s"],
        "token_budget": config["retry"]["token_budget"],
        "session_timeout_s": config["retry"]["session_timeout_s"],
        "check_cmd": config["lineage"]["check_cmd"],
        "c_image": dock["c_image"],
        "rust_image": dock["rust_image"],
        "agent_network": dock.get("agent_network", "auto"),
        "limits": {k: dock[k] for k in ("cpus", "memory", "pids")},
        "utility": config["lineage"]["utility"],
        "llm_cache": llm_cache_config(config),
        "cache_dir": str(cache_root(config)),
    }


def llm_cache_config(config: Mapping[str, Any]) -> dict[str, Any] | None:
    c = config["cache"]
    if not c["enabled"] or c["llm"] == "off":
        return None
    return {"mode": c["llm"], "match": c["match"], "namespace": c["namespace"]}


def write_shim(private_dir: Path, config: Mapping[str, Any], mock_outputs: Mapping[str, Any] | None = None) -> Path:
    """Write the 0600 shim config (it holds API keys) and the AIDER_BIN wrapper."""
    cfg = shim_config(config)
    if mock_outputs is not None:
        cfg["mock_outputs"] = mock_outputs
    cfg_path = private_dir / "shim-config.json"
    fd = os.open(cfg_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(cfg, fh)
    lines = ["#!/bin/sh", f"export PYTHONPATH={shlex.quote(str(REPO_ROOT))}", "export PYTHONDONTWRITEBYTECODE=1"]
    for var in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"):
        if os.environ.get(var):  # run_experiment.sh runs the generator under `env -i`
            lines.append(f"export {var}={shlex.quote(os.environ[var])}")
    lines.append(f"exec {shlex.quote(sys.executable)} -m src.lineage.shim --agent-config {shlex.quote(str(cfg_path))} \"$@\"")
    wrapper = private_dir / "aider"
    wrapper.write_text("\n".join(lines) + "\n")
    wrapper.chmod(0o700)
    return wrapper


def check_ready(config: Mapping[str, Any]) -> list[str]:
    problems = []
    if config["lineage"]["generator"] == "aider":
        if shutil.which(config["lineage"]["aider"]["bin"]) is None:
            problems.append(f"Aider executable {config['lineage']['aider']['bin']!r} not found (lineage.aider.bin)")
    return problems


def run_lineage(config: dict[str, Any], mode: str = "run", mock_outputs: Mapping[str, Any] | None = None) -> int:
    """mode: run | dry-run (print every stage command) | print-plan."""
    lin = config["lineage"]
    manifest = load_manifest(lin["utility"])
    language = source_language(manifest)
    output_dir = Path(lin["output_dir"]) if lin["output_dir"] else default_output_dir(config)
    output_dir = output_dir if output_dir.is_absolute() else (Path.cwd() / output_dir)

    image = image_id = None
    if lin["generator"] == "minisweagent":
        image_lang = image_language(language)
        image = config["docker"][f"{image_lang}_image"]
        if mode == "run":
            image_id = docker.require_image(image)
        else:
            image_id = docker.image_id(image)

    args, extra_env = script_args(config, output_dir, image, image_id)
    if mode == "dry-run":
        args.append("--dry-run")
    elif mode == "print-plan":
        args.append("--print-plan")

    env = dict(os.environ)
    env.update(extra_env)
    private = Path(tempfile.mkdtemp(prefix="agent-lineage-"))
    try:
        if lin["generator"] == "minisweagent":
            env["AIDER_BIN"] = str(write_shim(private, config, mock_outputs))
        else:
            env["AIDER_BIN"] = lin["aider"]["bin"]
        argv = ["bash", str(LINEAGE_SCRIPT), *args]

        if mode == "run":
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            record = {
                "tool_version": __version__,
                "mode": "lineage",
                "started": dt.datetime.now().isoformat(timespec="seconds"),
                "git_commit": git_commit(),
                "argv": sys.argv,
                "script_argv": argv,
                "generator": lin["generator"],
                "aider_bin": env["AIDER_BIN"] if lin["generator"] == "aider" else "src.lineage.shim",
                "utility": lin["utility"],
                "language": language,
                "image": {"tag": image, "id": image_id},
                "roles": list(lineage_roles(config)),
                "config": redacted(config),
            }
            out = output_dir / "pipeline" / f"invocation-{stamp}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(record, indent=2, default=str) + "\n")
            print(f"[pipeline] lineage {lin['utility']} ({language}) generator={lin['generator']} -> {output_dir}", flush=True)

        if mode == "run" and lin["parallel"] > 1 and lin["lineages"] > 1:
            status = run_parallel(argv, env, output_dir, lin["lineage_start"], lin["lineages"], lin["parallel"])
        else:
            status = subprocess.run(argv, cwd=REPO_ROOT, env=env).returncode
    finally:
        shutil.rmtree(private, ignore_errors=True)

    if mode == "run":
        summarize(output_dir)
        if lin["analyze"] and status == 0:
            status = subprocess.run([sys.executable, str(ANALYZE_SCRIPT), "--lineage-root", str(output_dir)], cwd=REPO_ROOT).returncode
    return status


def with_lineages(argv: list[str], start: int, count: int) -> list[str]:
    out = list(argv)
    out[out.index("--lineage-start") + 1] = str(start)
    out[out.index("--lineages") + 1] = str(count)
    return out


def run_parallel(argv: list[str], env: Mapping[str, str], output_dir: Path, start: int, count: int, parallel: int) -> int:
    """One script process per lineage, at most `parallel` at once.

    run_lineage_experiment.sh read-modify-writes <output-dir>/lineages.json once,
    before its lineage loop prints `=== lineage-NNN ===`. Each process is
    therefore started only after the previous one printed that marker (or
    exited), so the shared run record is never written concurrently.
    """
    logs = output_dir / "pipeline" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    queue = list(range(start, start + count))
    running: dict[int, tuple[subprocess.Popen, Any]] = {}
    status = 0
    print(f"[pipeline] {count} lineages, {parallel} in parallel; per-lineage logs in {logs}", flush=True)

    def reap() -> None:
        nonlocal status
        for number, (proc, fh) in list(running.items()):
            code = proc.poll()
            if code is not None:
                fh.close()
                status = status or code
                del running[number]
                print(f"[pipeline] lineage-{number:03d} finished (exit {code})", flush=True)

    while queue or running:
        reap()
        if queue and len(running) < parallel:
            number = queue.pop(0)
            log_path = logs / f"lineage-{number:03d}.log"
            fh = log_path.open("w")
            proc = subprocess.Popen(with_lineages(argv, number, 1), cwd=REPO_ROOT, env=dict(env), stdout=fh, stderr=subprocess.STDOUT)
            running[number] = (proc, fh)
            print(f"[pipeline] lineage-{number:03d} started", flush=True)
            marker = f"=== lineage-{number:03d} ==="
            while proc.poll() is None and marker not in log_path.read_text(errors="replace"):
                time.sleep(0.5)
            continue
        time.sleep(1)
    return status


def summarize(output_dir: Path) -> None:
    rows = []
    for path in sorted(output_dir.glob("lineage-*/lineage.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        row = {
            "lineage": path.parent.name,
            "state": data.get("state"),
            "checkpoints_completed": data.get("checkpoints_completed"),
            "checkpoint_count": data.get("checkpoint_count"),
            "failure_stage": data.get("failure_stage"),
            "failure_reason": data.get("failure_reason"),
            "final_source": data.get("final_source"),
        }
        rows.append(row)
        detail = f" at {row['failure_stage']} ({row['failure_reason']})" if row["failure_stage"] else ""
        print(f"[pipeline] {row['lineage']}: {row['state']} {row['checkpoints_completed']}/{row['checkpoint_count']}{detail}", flush=True)
    if rows:
        (output_dir / "pipeline" / "summary.json").write_text(json.dumps(rows, indent=2, default=str) + "\n")
