"""One agent session inside a language image, driven by mini-swe-agent.

    /opt/agent/bin/python -m src.incontainer.agent_session run
    /opt/agent/bin/python -m src.incontainer.agent_session worker "<instructions>"   (agent-worker)

Reads /src/session/session.json (written by the host), renders the
prompts with Jinja2, builds per-role models from the session's model specs
(API keys come from AGENT_<ROLE>_API_KEY in the environment) and runs the
configured topology:

  single          worker
  planner_worker  planner -> plan.md -> worker
  orchestrator    orchestrator, which calls `agent-worker` (a nested worker)

Trajectories and a session record are written to /src/out.

session["kind"] selects the task family and its prompt set:
  "depth"    (default) one function file, checked with `agent-test`
             (src/prompts/*.md)
  "lineage"  one checkpoint of a utility lineage, driven through the Aider
             shim by src/harness/run_experiment.sh; the agent edits the source
             in /work and may compile it with `agent-build`
             (src/prompts/lineage/*.md)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined, Template

import minisweagent
from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment
from minisweagent.exceptions import LimitsExceeded
from minisweagent.models import get_model_class

SESSION = Path("/src/session/session.json")
OUT = Path("/src/out")
PROMPTS = Path(os.environ.get("PYTHONPATH", "/agent-src").split(":")[0]) / "src" / "prompts"


def load_session() -> dict[str, Any]:
    return json.loads(SESSION.read_text())


def render(name: str, **values: Any) -> str:
    text = (PROMPTS / _prompt_prefix() / name).read_text()
    return Template(text, undefined=StrictUndefined, trim_blocks=False).render(**values).strip() + "\n"


_KIND: list[str] = []


def _prompt_prefix() -> str:
    return "lineage" if _KIND and _KIND[0] == "lineage" else ""


def mini_config(model_class: str) -> dict[str, Any]:
    name = "default.yaml" if model_class.endswith("textbased") or model_class == "mock" else "mini.yaml"
    return yaml.safe_load((Path(minisweagent.__file__).parent / "config" / name).read_text())


# ------------------------------------------------------------------ models

def make_model(session: dict[str, Any], role: str):
    spec = session["models"][role]
    cfg = mini_config(session["model_class"])
    model_cfg = dict(cfg.get("model", {}))
    if session["model_class"] == "mock":
        from minisweagent.models.test_models import DeterministicModel

        outputs = session["mock_outputs"].get(role, [])  # empty: replay tests (any real call fails)
        state_file = OUT / f".mock-{role}.idx"
        start = int(state_file.read_text()) if state_file.is_file() else 0  # nested workers continue the script
        model = DeterministicModel(outputs=outputs[start:], observation_template=_obs_template(model_cfg))
        model._session_state = (state_file, start)
        return model
    kwargs = dict(model_cfg.get("model_kwargs", {}))
    kwargs.update({k: v for k, v in session["sampling"].get(role, {}).items() if v is not None})
    if "num_ctx" in kwargs:
        kwargs["num_ctx"] = int(kwargs["num_ctx"])
    if spec.get("api_base"):
        kwargs["api_base"] = spec["api_base"]
    key = os.environ.get(f"AGENT_{role.upper()}_API_KEY")
    if key:
        kwargs["api_key"] = key
    model_class = get_model_class(spec["model"], session["model_class"])
    extra = {k: v for k, v in model_cfg.items() if k in ("observation_template", "format_error_template")}
    return model_class(model_name=spec["model"], model_kwargs=kwargs, cost_tracking="ignore_errors", **extra)


def _obs_template(model_cfg: dict[str, Any]) -> str:
    return model_cfg.get(
        "observation_template",
        "<returncode>{{output.returncode}}</returncode>\n<output>\n{{output.output}}</output>",
    )


class SessionAgent(DefaultAgent):
    """DefaultAgent + optional token budget; records token usage."""

    def __init__(self, *args, token_limit: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        self.token_limit = token_limit
        self.tokens = 0

    def query(self) -> dict:
        if self.token_limit and self.tokens >= self.token_limit:
            raise LimitsExceeded({"role": "exit", "content": "TokenBudgetExceeded", "extra": {"exit_status": "TokenBudgetExceeded", "submission": ""}})
        message = super().query()
        usage = (message.get("extra", {}).get("response") or {}).get("usage") or {}
        self.tokens += int(usage.get("total_tokens") or 0)
        model = self.model
        if hasattr(model, "_session_state"):
            state_file, start = model._session_state
            state_file.write_text(str(start + model.current_index + 1))
        return message


def make_agent(session: dict[str, Any], role: str, label: str) -> SessionAgent:
    cfg = mini_config(session["model_class"])
    agent_cfg = dict(cfg["agent"])
    agent_cfg.update(
        step_limit=session.get("step_limit", 0),
        cost_limit=0,
        wall_time_limit_seconds=int(session.get("wall_time_s", 0)),
        output_path=OUT / f"trajectory-{label}.json",
    )
    env_cfg = dict(cfg.get("environment", {}).get("env", {}))
    env = LocalEnvironment(cwd=session.get("cwd", "/src/edit"), env=env_cfg, timeout=int(session.get("command_timeout_s", 900)))
    budget = session.get("token_budget", {})
    from src.incontainer.llm_cache import wrap

    model = wrap(make_model(session, role), session, role, label)
    return SessionAgent(model, env, token_limit=int(budget.get("limit", 0)) if budget.get("enabled") else 0, **agent_cfg)


def agent_record(agent: SessionAgent, result: dict[str, Any], label: str, started: float) -> dict[str, Any]:
    return {
        "label": label,
        "exit_status": result.get("exit_status"),
        "submission": result.get("submission", "")[-4000:],
        "api_calls": agent.n_calls,
        "tokens": agent.tokens,
        "cost": agent.cost,
        "elapsed_s": round(time.time() - started, 3),
        "cache_hits": getattr(agent.model, "hits", 0),
        "cache_misses": getattr(agent.model, "misses", 0),
    }


def run_role(session: dict[str, Any], role: str, label: str, task: str) -> dict[str, Any]:
    agent = make_agent(session, role, label)
    started = time.time()
    try:
        result = agent.run(task)
    except Exception as exc:  # recorded; the controller decides what it means
        result = {"exit_status": f"error:{type(exc).__name__}", "submission": str(exc)}
    return agent_record(agent, result, label, started)


def base_task(session: dict[str, Any]) -> str:
    v = session["prompt_vars"]
    if session.get("kind") == "lineage":
        # The message already is the full task (or the controller's repair
        # continuation, which embeds the task and the failures).
        return render("task.md", **v)
    task = render("task.md", **v)
    if session.get("repair"):
        task = render("repair.md", task=task, **v, **session["repair"])
    return task


def append_record(record: dict[str, Any]) -> None:
    with (OUT / "agents.jsonl").open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def cmd_run() -> int:
    session = load_session()
    task = base_task(session)
    (OUT / "task.md").write_text(task)
    topology = session["topology"]
    if topology == "single":
        append_record(run_role(session, "worker", "worker", task))
    elif topology == "planner_worker":
        v = session["prompt_vars"]
        append_record(run_role(session, "planner", "planner", render("planner.md", task=task, **v)))
        plan_path = Path("/src/session/plan.md")
        plan = plan_path.read_text() if plan_path.is_file() else "(the planner produced no plan)"
        (OUT / "plan.md").write_text(plan)
        append_record(run_role(session, "worker", "worker", render("worker_with_plan.md", task=task, plan=plan)))
    elif topology == "orchestrator":
        v = session["prompt_vars"]
        append_record(run_role(session, "orchestrator", "orchestrator", render("orchestrator.md", task=task, **v)))
    else:
        print(f"unknown topology {topology}", file=sys.stderr)
        return 2
    return 0


def cmd_worker(instructions: str) -> int:
    session = load_session()
    count_file = OUT / ".worker-count"
    n = int(count_file.read_text()) + 1 if count_file.is_file() else 1
    count_file.write_text(str(n))
    task = render("worker_delegated.md", task=base_task(session), instructions=instructions)
    record = run_role(session, "worker", f"worker-{n}", task)
    append_record(record)
    print(f"WORKER {n} finished: exit_status={record['exit_status']}")
    check = session.get("check_command", "agent-test")
    test = subprocess.run([check], capture_output=True, text=True, cwd=session.get("cwd", "/src/edit"))
    print(f"Latest {check}:\n" + (test.stdout + test.stderr)[-4000:])
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if SESSION.is_file():
        _KIND[:] = [load_session().get("kind", "depth")]
    if argv[:1] == ["run"]:
        return cmd_run()
    if argv[:1] == ["worker"]:
        return cmd_worker(" ".join(argv[1:]))
    print("usage: agent_session run | worker <instructions>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
