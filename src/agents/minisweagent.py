"""Generator plugin: one mini-swe-agent session in a fresh language container.

Layout inside the container
  /work/project      current program (read-only)
  /src/suite        visible test suite (read-only); the hidden suite is never mounted
  /src/edit/<f>     the function file (the only file whose contents are harvested)
  /src/session      session.json, context.json, target.json, bin/{agent-test,agent-worker}, plan.md
  /src/out          trajectories, agents.jsonl, agent-test.jsonl
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse

from src.config import required_roles
from src.sandbox import docker

AGENT_TEST = """#!/bin/sh
exec python3 -m src.incontainer.run_tests "$@"
"""
AGENT_WORKER = """#!/bin/sh
exec /opt/agent/bin/python -m src.incontainer.agent_session worker "$@"
"""
REPLAY_MODEL = "src/replay-only"  # placeholder when cache.llm = "replay" and no model is configured
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def function_file_name(target: Mapping[str, Any]) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", target["name"]).strip("_") or "function"
    return f"{stem}.{'rs' if target['language'] == 'rust' else 'c'}"


def llm_cache_mounts(settings: Mapping[str, Any] | None, cache_dir: Path | str | None) -> list[docker.Mount]:
    """Mount <cache dir>/llm at /src/cache when LLM caching is on."""
    if not settings or not cache_dir:
        return []
    llm = Path(cache_dir) / "llm"
    llm.mkdir(parents=True, exist_ok=True)
    return [docker.Mount(llm, "/src/cache", False)]


def is_host_local(api_base: str | None) -> bool:
    return bool(api_base) and urlparse(api_base).hostname in LOCAL_HOSTS


def agent_network(mode: str, api_bases: list[str | None]) -> tuple[str, dict[str, str]]:
    """Pick the agent container's network and any endpoint rewrites.

    auto:   host networking iff some endpoint is host-local (e.g. Ollama on
            127.0.0.1), otherwise bridge.
    host:   always host networking.
    bridge: bridge networking; host-local endpoints are rewritten to
            host.docker.internal (the service must listen beyond 127.0.0.1).
    """
    local = any(is_host_local(b) for b in api_bases)
    if mode == "auto":
        mode = "host" if local else "bridge"
    rewrites: dict[str, str] = {}
    if mode == "bridge":
        for base in api_bases:
            if is_host_local(base):
                parsed = urlparse(base)
                netloc = "host.docker.internal" + (f":{parsed.port}" if parsed.port else "")
                rewrites[base] = urlunparse(parsed._replace(netloc=netloc))
    return mode, rewrites


class MiniSweAgentGenerator:
    name = "minisweagent"

    def __init__(self, config: Mapping[str, Any]):
        self.config = config

    def run_session(self, request: Mapping[str, Any]) -> dict[str, Any]:
        cfg = self.config
        sdir = Path(request["session_dir"])
        if sdir.exists():
            shutil.rmtree(sdir)
        session, edit, out = sdir / "session", sdir / "edit", sdir / "out"
        for d in (session / "bin", edit, out):
            d.mkdir(parents=True)
        target = request["target"]
        fname = function_file_name(target)
        (edit / fname).write_text(request["start_text"])
        (session / "context.json").write_text(json.dumps(request["context"], indent=2))
        (session / "target.json").write_text(json.dumps(target, indent=2))
        for name, body in (("agent-test", AGENT_TEST), ("agent-worker", AGENT_WORKER)):
            (session / "bin" / name).write_text(body)
            (session / "bin" / name).chmod(0o755)

        topology = cfg["agent"]["topology"]
        roles = required_roles(topology)
        network, rewrites = agent_network(cfg["docker"].get("agent_network", "auto"), [cfg["models"][r]["api_base"] for r in roles])
        models, env = {}, {}
        for role in roles:
            spec = cfg["models"][role]
            models[role] = {"model": spec["model"] or REPLAY_MODEL, "api_base": rewrites.get(spec["api_base"], spec["api_base"])}
            if spec.get("api_key"):
                env[f"AGENT_{role.upper()}_API_KEY"] = spec["api_key"]
        timeout = float(cfg["retry"]["session_timeout_s"])
        session_doc = {
            "topology": topology,
            "model_class": request.get("model_class") or cfg["agent"].get("model_class", "litellm"),
            "models": models,
            "sampling": cfg["agent"]["sampling"],
            "step_limit": cfg["agent"]["step_limit"],
            "wall_time_s": int(timeout),
            "command_timeout_s": int(cfg["agent"].get("command_timeout_s", 900)),
            "token_budget": cfg["retry"]["token_budget"],
            "project": "/work/project",
            "context": "/src/session/context.json",
            "target": "/src/session/target.json",
            "suite": "/src/suite",
            "function_file": f"/src/edit/{fname}",
            "log_dir": "/src/out",
            "feedback": cfg["tests"].get("feedback", {}),
            "prompt_vars": {**request["prompt_vars"], "function_file": f"/src/edit/{fname}"},
            "repair": request.get("repair"),
            "llm_cache": request.get("llm_cache"),
        }
        if request.get("mock_outputs") is not None:
            session_doc["model_class"] = "mock"
            session_doc["mock_outputs"] = request["mock_outputs"]
        (session / "session.json").write_text(json.dumps(session_doc, indent=2))

        env.update({
            "PATH": "/src/session/bin:/opt/agent/bin:/opt/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "CARGO_HOME": "/tmp/cargo-home",
            "MSWEA_CONFIGURED": "true",
            "MSWEA_SILENT_STARTUP": "1",
            "MSWEA_COST_TRACKING": "ignore_errors",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        })
        spec = docker.ContainerSpec(
            image=request["image"],
            command=["/opt/agent/bin/python", "-m", "src.incontainer.agent_session", "run"],
            mounts=[
                docker.Mount(Path(request["project"]), "/work/project", True),
                docker.Mount(Path(request["suite"]), "/src/suite", True),
                docker.Mount(session, "/src/session", False),
                docker.Mount(edit, "/src/edit", False),
                docker.Mount(out, "/src/out", False),
                *llm_cache_mounts(request.get("llm_cache"), request.get("cache_dir")),
            ],
            env=env,
            workdir="/src/edit",
            # A replay needs no model endpoint: run it offline.
            network="none" if request.get("mock_outputs") is not None or (request.get("llm_cache") or {}).get("mode") == "replay" else network,
            limits=docker.Limits.from_config(cfg["docker"]),
            extra_args=["--add-host", "host.docker.internal:host-gateway"] if rewrites else [],
        )
        result = docker.run(spec, timeout=timeout + 300)
        (out / "container.log").write_text(result.stdout + "\n--- stderr ---\n" + result.stderr)
        agents = []
        if (out / "agents.jsonl").is_file():
            agents = [json.loads(l) for l in (out / "agents.jsonl").read_text().splitlines() if l.strip()]
        final_path = edit / fname
        return {
            "final_text": final_path.read_text() if final_path.is_file() else "",
            "function_file": fname,
            "agents": agents,
            "container": result.to_json(),
            "timed_out": result.timed_out,
            "infrastructure_error": result.returncode not in (0,) and not agents,
            "stderr_tail": result.stderr[-3000:],
        }
