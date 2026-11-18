"""Configuration loading and merging.

Sources, lowest to highest precedence:
  1. built-in DEFAULTS
  2. config.toml (repo root by default)
  3. environment: process environment over the .env file (model roles only)
  4. CLI overrides (dotted keys)

`.env` carries per-role model settings only:
  AGENT_<ROLE>_MODEL, AGENT_<ROLE>_API_BASE, AGENT_<ROLE>_API_KEY
with AGENT_API_BASE / AGENT_API_KEY as fallbacks for every role. Roles are the
mini-swe-agent roles (worker, planner, orchestrator) plus the Aider roles
used by `python -m src lineage` with generator = "aider" (architect, editor).
Everything else (including sampling) lives in config.toml.
"""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

LLM_MODES = ("off", "record", "auto", "replay")
LLM_MATCH = ("exact", "sequence")
ROLES = ("worker", "planner", "orchestrator")  # mini-swe-agent roles (have per-role sampling)
AIDER_ROLES = ("architect", "editor")  # lineage mode, generator = "aider"
MODEL_ROLES = ROLES + AIDER_ROLES
LINEAGE_GENERATORS = ("minisweagent", "aider")
ARCHITECT_THINK = ("false", "low", "medium", "high")
EDITOR_EDIT_FORMATS = ("whole", "editor-diff")
DEPTH_RULES = ("eq", "le", "ge")
ORDERS = ("shallow_first", "deep_first", "source", "random")
ACCUMULATIONS = ("cumulative", "independent")
TOPOLOGIES = ("single", "planner_worker", "orchestrator")
LANGUAGES = ("c", "rust")

_SAMPLING_DEFAULTS: dict[str, Any] = {
    "temperature": None,
    "top_p": None,
    "seed": None,
    "max_tokens": None,
    "num_ctx": None,
}

DEFAULTS: dict[str, Any] = {
    "depth": {
        "language": None,  # "c" | "rust"; required
        "input": None,  # path to a .c/.rs file or a project directory; required
        "depth": None,  # None -> select every eligible reachable function
        "rule": "le",
        "include_unreachable": False,
        "order": "shallow_first",
        "seed": 0,
        "accumulation": "cumulative",
        "selector": "depth",  # name or module:Class
        "output_dir": "runs/depth",
        "parallel": 1,  # functions diversified concurrently (see src/depth/runner.py)
    },
    "callgraph": {
        "c_backend": "svf",
        "rust_backend": "rupta",
        "options": {},
    },
    "edit": {
        "allow_new_helpers": True,
        "allow_new_includes": True,
        "allow_new_globals_types": True,
    },
    "agent": {
        "generator": "minisweagent",
        "topology": "single",
        "model_class": "litellm",  # mini-swe-agent model class: litellm | litellm_textbased | litellm_response | module path
        "step_limit": 0,  # 0 = harness default / unlimited
        "command_timeout_s": 900,  # per bash command inside the agent session
        "sampling": {role: dict(_SAMPLING_DEFAULTS) for role in ROLES},
    },
    "retry": {
        "max_loops": 3,
        "session_timeout_s": 1800,
        "token_budget": {"enabled": False, "limit": 0},
    },
    "tests": {
        "visible_suite": None,  # required
        "hidden_suite": None,  # required
        "feedback": {"max_failures": 25, "max_detail_chars": 300},
    },
    "build": {
        "cmd": None,  # None -> the pipeline builds automatically
        "flags": [],
    },
    "lineage": {
        # Drives src/harness/run_lineage_experiment.sh -> src/harness/run_experiment.sh
        # (stage plan, test bundles, controller repair loop, Docker build/judge,
        # held-out judge, security evaluation, fingerprints) unchanged.
        "utility": None,  # selector <language>-<utility> (coreutils/<utility>/manifests/<language>.json); required
        "generator": "minisweagent",  # minisweagent (shim in Docker) | aider (host Aider)
        "lineages": 1,
        "lineage_start": 1,
        "parallel": 1,  # lineages run concurrently (one script process each)
        "output_root": "runs/lineage",  # used when output_dir is unset
        "output_dir": None,  # explicit lineage root (resume target)
        "force": False,
        "keep_workdir": False,
        "allow_no_progress": False,
        "repair_prompt": None,  # continuation template; None -> the script's default
        "analyze": False,  # run src/harness/analyze_lineages.py afterwards
        "check_cmd": None,  # agent-side compile check (agent-build); None -> by source language
        "sampling": {
            # Forwarded to the scripts and fingerprinted. With the minisweagent
            # generator they apply to every agent role.
            "temperature": 0.0,
            "top_p": None,
            "sampling_seed": None,
            "lineage_seed_base": None,
            "max_tokens": None,
            "num_ctx": None,
            "architect_think": None,
        },
        "security": {
            "enabled": True,
            "fuzz_seconds": 10,
            "seed": 1,
            "timeout": 2,
            "max_inputs": 100,
        },
        "aider": {
            "bin": "aider",
            "editor_edit_format": "editor-diff",
        },
        "model_provenance": {},  # extra metadata-only JSON (fingerprinted, never sent)
    },
    "cache": {
        "enabled": True,
        "dir": "runs/cache",
        "steps": True,  # call graphs, locate, baseline/verification/hidden evaluations
        "llm": "record",  # off | record | auto | replay
        "match": "exact",  # exact | sequence (how auto/replay look responses up)
        "namespace": "",  # separates independent repeats that share a cache
    },
    "docker": {
        "c_image": "agent-c:latest",
        "rust_image": "agent-rust:latest",
        "cpus": 2,
        "memory": "4g",
        "pids": 512,
        "agent_network": "auto",  # auto | host | bridge (agent sessions only; all other steps run without network)
    },
    "plugins": {
        # In-container plugins, referenced by import path and loaded inside the image:
        #   language     -> module with list_functions/locate/splice (default: built-in per language)
        #   test_runner  -> "module:Class" with run(suite, project, report)
        #   feedback     -> "module:Class" with format(result)
        "language": None,
        "test_runner": None,
        "feedback": None,
    },
    # Filled from the environment, never from TOML.
    "models": {role: {"model": None, "api_base": None, "api_key": None} for role in MODEL_ROLES},
}

SECRET_KEYS = frozenset({"api_key"})


class ConfigError(ValueError):
    pass


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE, '#' comments, optional 'export ', quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise ConfigError(f"{path}:{lineno}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def set_dotted(config: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = config
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise ConfigError(f"cannot set {dotted}: {part} is not a table")
    node[parts[-1]] = value


def models_from_env(env: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    base = env.get("AGENT_API_BASE") or None
    key = env.get("AGENT_API_KEY") or None
    models: dict[str, dict[str, Any]] = {}
    for role in MODEL_ROLES:
        prefix = f"AGENT_{role.upper()}_"
        models[role] = {
            "model": env.get(prefix + "MODEL") or None,
            "api_base": env.get(prefix + "API_BASE") or base,
            "api_key": env.get(prefix + "API_KEY") or key,
        }
    return models


def load_config(
    config_path: Path | None,
    env_path: Path | None,
    cli_overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    require_config_file: bool = False,
) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULTS)

    if config_path is not None:
        if config_path.is_file():
            with config_path.open("rb") as handle:
                data = tomllib.load(handle)
            if "models" in data:
                raise ConfigError("models are configured in .env, not in config.toml")
            config = deep_merge(config, data)
        elif require_config_file:
            raise ConfigError(f"config file not found: {config_path}")

    env: dict[str, str] = {}
    if env_path is not None:
        env.update(parse_env_file(env_path))
    env.update({k: v for k, v in (environ if environ is not None else os.environ).items() if k.startswith("AGENT_")})
    config["models"] = models_from_env(env)

    for dotted, value in (cli_overrides or {}).items():
        if value is not None:
            set_dotted(config, dotted, value)

    validate(config)
    return config


def validate(config: Mapping[str, Any]) -> None:
    depth = config["depth"]
    if depth["language"] is not None and depth["language"] not in LANGUAGES:
        raise ConfigError(f"depth.language must be one of {LANGUAGES}")
    if depth["rule"] not in DEPTH_RULES:
        raise ConfigError(f"depth.rule must be one of {DEPTH_RULES}")
    if depth["order"] not in ORDERS:
        raise ConfigError(f"depth.order must be one of {ORDERS}")
    if depth["accumulation"] not in ACCUMULATIONS:
        raise ConfigError(f"depth.accumulation must be one of {ACCUMULATIONS}")
    if depth["depth"] is not None and (not isinstance(depth["depth"], int) or depth["depth"] < 0):
        raise ConfigError("depth.depth must be a non-negative integer")
    if config["docker"].get("agent_network", "auto") not in ("auto", "host", "bridge"):
        raise ConfigError("docker.agent_network must be auto, host or bridge")
    if config["agent"]["topology"] not in TOPOLOGIES:
        raise ConfigError(f"agent.topology must be one of {TOPOLOGIES}")
    retry = config["retry"]
    if not isinstance(retry["max_loops"], int) or retry["max_loops"] < 0:
        raise ConfigError("retry.max_loops must be a non-negative integer")
    if not isinstance(retry["session_timeout_s"], (int, float)) or retry["session_timeout_s"] <= 0:
        raise ConfigError("retry.session_timeout_s must be positive")
    validate_lineage(config["lineage"])
    for key in ("parallel",):
        for section in ("depth", "lineage"):
            value = config[section][key]
            if not isinstance(value, int) or value < 1:
                raise ConfigError(f"{section}.{key} must be a positive integer")
    cache = config["cache"]
    if cache["llm"] not in LLM_MODES:
        raise ConfigError(f"cache.llm must be one of {LLM_MODES}")
    if cache["match"] not in LLM_MATCH:
        raise ConfigError(f"cache.match must be one of {LLM_MATCH}")


def validate_lineage(lineage: Mapping[str, Any]) -> None:
    if lineage["generator"] not in LINEAGE_GENERATORS:
        raise ConfigError(f"lineage.generator must be one of {LINEAGE_GENERATORS}")
    for key in ("lineages", "lineage_start"):
        if not isinstance(lineage[key], int) or lineage[key] < 1:
            raise ConfigError(f"lineage.{key} must be a positive integer")
    sampling = lineage["sampling"]
    if sampling["sampling_seed"] is not None and sampling["lineage_seed_base"] is not None:
        raise ConfigError("lineage.sampling.sampling_seed and lineage_seed_base are mutually exclusive")
    think = sampling["architect_think"]
    if think is not None and str(think).lower() not in ARCHITECT_THINK:
        raise ConfigError(f"lineage.sampling.architect_think must be one of {ARCHITECT_THINK}")
    if lineage["aider"]["editor_edit_format"] not in EDITOR_EDIT_FORMATS:
        raise ConfigError(f"lineage.aider.editor_edit_format must be one of {EDITOR_EDIT_FORMATS}")
    if not isinstance(lineage["model_provenance"], Mapping):
        raise ConfigError("lineage.model_provenance must be a table")


def required_roles(topology: str) -> tuple[str, ...]:
    return {
        "single": ("worker",),
        "planner_worker": ("planner", "worker"),
        "orchestrator": ("orchestrator", "worker"),
    }[topology]


def check_ready_for_run(config: Mapping[str, Any]) -> list[str]:
    """Problems that block a real (non-dry) run."""
    problems = []
    depth = config["depth"]
    if not depth["input"]:
        problems.append("depth.input is not set")
    for key in ("visible_suite", "hidden_suite"):
        if not config["tests"][key]:
            problems.append(f"tests.{key} is not set")
    replay = config["cache"]["enabled"] and config["cache"]["llm"] == "replay"
    for role in required_roles(config["agent"]["topology"]):
        if not config["models"][role]["model"] and not replay:
            problems.append(f"AGENT_{role.upper()}_MODEL is not set in .env")
    return problems


def lineage_roles(config: Mapping[str, Any]) -> tuple[str, ...]:
    if config["lineage"]["generator"] == "aider":
        return AIDER_ROLES
    return required_roles(config["agent"]["topology"])


def check_ready_for_lineage(config: Mapping[str, Any]) -> list[str]:
    problems = []
    if not config["lineage"]["utility"]:
        problems.append("lineage.utility is not set")
    for role in lineage_roles(config):
        if role == "editor":
            continue  # optional: run_lineage_experiment.sh has its own default editor model
        replay = config["cache"]["enabled"] and config["cache"]["llm"] == "replay" and config["lineage"]["generator"] == "minisweagent"
        if not config["models"][role]["model"] and not replay:
            problems.append(f"AGENT_{role.upper()}_MODEL is not set in .env")
    return problems


def redacted(config: Mapping[str, Any]) -> dict[str, Any]:
    def walk(node: Any) -> Any:
        if isinstance(node, Mapping):
            return {
                k: ("<redacted>" if k in SECRET_KEYS and v else walk(v)) for k, v in node.items()
            }
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(config)
