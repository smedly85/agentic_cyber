"""Unit tests for `python -m src lineage` config, script wiring and the Aider shim."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from src.config import ConfigError, check_ready_for_lineage, lineage_roles, load_config
from src.lineage import runner, shim


def cfg(environ=None, **cli):
    base = {"lineage.utility": "c-sort"}
    base.update(cli)
    return load_config(None, None, base, environ=environ or {"AGENT_WORKER_MODEL": "ollama_chat/w"})


def flag(args, name):
    return args[args.index(name) + 1]


# ------------------------------------------------------------------ config

def test_lineage_defaults_and_roles():
    c = cfg()
    assert c["lineage"]["generator"] == "minisweagent"
    assert c["lineage"]["sampling"]["temperature"] == 0.0
    assert lineage_roles(c) == ("worker",)
    assert lineage_roles(cfg(**{"agent.topology": "orchestrator"})) == ("orchestrator", "worker")
    assert lineage_roles(cfg(**{"lineage.generator": "aider"})) == ("architect", "editor")


def test_aider_roles_come_from_env():
    c = cfg(environ={"AGENT_ARCHITECT_MODEL": "ollama_chat/a", "AGENT_API_BASE": "http://h:1"}, **{"lineage.generator": "aider"})
    assert c["models"]["architect"] == {"model": "ollama_chat/a", "api_base": "http://h:1", "api_key": None}
    assert check_ready_for_lineage(c) == []  # editor is optional (script default)
    assert check_ready_for_lineage(cfg(environ={}, **{"lineage.generator": "aider"})) == ["AGENT_ARCHITECT_MODEL is not set in .env"]


@pytest.mark.parametrize("override", [
    {"lineage.generator": "opencode"},
    {"lineage.lineages": 0},
    {"lineage.sampling.sampling_seed": 1, "lineage.sampling.lineage_seed_base": 1},
    {"lineage.sampling.architect_think": "extreme"},
    {"lineage.aider.editor_edit_format": "diff"},
])
def test_lineage_validation(override):
    with pytest.raises(ConfigError):
        cfg(**override)


def test_ready_requires_utility():
    c = load_config(None, None, {}, environ={"AGENT_WORKER_MODEL": "m"})
    assert "lineage.utility is not set" in check_ready_for_lineage(c)


# ------------------------------------------------------------------ script wiring

def test_script_args_minisweagent(tmp_path):
    c = cfg(**{"lineage.sampling.top_p": 0.9, "lineage.sampling.lineage_seed_base": 7, "lineage.lineages": 3,
               "retry.max_loops": 2, "lineage.security.enabled": False, "agent.topology": "planner_worker"},
            environ={"AGENT_WORKER_MODEL": "ollama_chat/w", "AGENT_PLANNER_MODEL": "ollama_chat/p"})
    args, env = runner.script_args(c, tmp_path, "agent-c:latest", "sha256:abc")
    assert env == {}
    assert flag(args, "--model") == "ollama_chat/w"
    assert flag(args, "--editor-model") == "minisweagent/planner_worker"
    assert flag(args, "--top-p") == "0.9"
    assert flag(args, "--lineage-seed-base") == "7"
    assert flag(args, "--lineages") == "3"
    assert flag(args, "--max-loops") == "2"
    assert flag(args, "--output-dir") == str(tmp_path)
    assert "--no-security-evaluation" in args and "--sampling-seed" not in args
    assert "--remote-base-url" not in args  # the shim talks to the endpoint itself
    prov = json.loads(flag(args, "--model-provenance-json"))["pipeline"]
    assert prov["roles"] == {"planner": "ollama_chat/p", "worker": "ollama_chat/w"}
    assert prov["image"] == {"tag": "agent-c:latest", "id": "sha256:abc"}


def test_script_args_aider_endpoint_and_key(tmp_path):
    env_in = {"AGENT_ARCHITECT_MODEL": "ollama_chat/a", "AGENT_EDITOR_MODEL": "ollama_chat/e",
              "AGENT_API_BASE": "http://h:11434", "AGENT_API_KEY": "sekret"}
    c = cfg(environ=env_in, **{"lineage.generator": "aider", "lineage.sampling.architect_think": "false"})
    args, env = runner.script_args(c, tmp_path)
    assert flag(args, "--model") == "ollama_chat/a" and flag(args, "--editor-model") == "ollama_chat/e"
    assert flag(args, "--remote-base-url") == "http://h:11434"
    assert flag(args, "--remote-api-key-env") == runner.KEY_ENV and env == {runner.KEY_ENV: "sekret"}
    assert "sekret" not in " ".join(args)
    assert flag(args, "--architect-think") == "false"
    assert "--model-provenance-json" not in args


def test_script_args_aider_rejects_two_endpoints(tmp_path):
    c = cfg(environ={"AGENT_ARCHITECT_MODEL": "a", "AGENT_EDITOR_MODEL": "e", "AGENT_EDITOR_API_BASE": "http://x"},
            **{"lineage.generator": "aider"})
    with pytest.raises(ConfigError):
        runner.script_args(c, tmp_path)


def test_default_output_dir_and_manifest():
    c = cfg(**{"lineage.sampling.temperature": 0.2})
    out = runner.default_output_dir(c)
    assert out.parts[-3:] == ("c-sort", "msa-single-ollama_chat-w", "temp-0p2")
    assert runner.source_language(runner.load_manifest("rust-sort")) == "rust"
    assert runner.image_language("python") == "c"
    with pytest.raises(ConfigError):
        runner.load_manifest("no-such-utility")


def test_write_shim_is_private(tmp_path):
    c = cfg(environ={"AGENT_WORKER_MODEL": "w", "AGENT_WORKER_API_KEY": "k"})
    wrapper = runner.write_shim(tmp_path, c)
    cfg_file = tmp_path / "shim-config.json"
    assert stat.S_IMODE(cfg_file.stat().st_mode) == 0o600
    assert json.loads(cfg_file.read_text())["models"]["worker"]["api_key"] == "k"
    assert os.access(wrapper, os.X_OK) and "src.lineage.shim" in wrapper.read_text()


# ------------------------------------------------------------------ shim

AIDER_ARGV = [
    "--architect", "--auto-accept-architect", "--model", "ollama_chat/w", "--editor-model", "minisweagent/single",
    "--weak-model", "minisweagent/single", "--editor-edit-format", "editor-diff",
    "--model-settings-file", "SETTINGS", "--message-file", "prompt.md", "--file", "src/x.c", "--no-git",
    "--config", "aider.conf.yml", "--read", "tests/a.md", "--read", "tests/b.py", "--chat-history-file", "/dev/null",
]


def test_parse_aider_args():
    a = shim.parse_aider_args(["--agent-config", "C"] + AIDER_ARGV)
    assert a.agent_config == "C" and a.model == "ollama_chat/w"
    assert a.message_file == "prompt.md" and a.file == ["src/x.c"]
    assert a.read == ["tests/a.md", "tests/b.py"] and not a.version


def test_sampling_from_settings(tmp_path):
    settings = tmp_path / "s.yml"
    settings.write_text(json.dumps([
        {"name": "ollama_chat/w", "extra_params": {"temperature": 0.4, "top_p": 0.9, "num_ctx": 8192, "think": False}},
        {"name": "minisweagent/single", "extra_params": {"temperature": 0.0, "seed": 0}},
    ]))
    assert shim.sampling_from_settings(str(settings), "ollama_chat/w") == {"temperature": 0.4, "top_p": 0.9, "num_ctx": 8192, "think": False}
    assert shim.sampling_from_settings(str(tmp_path / "missing"), "x") == {}


def test_version_and_changed_files(tmp_path, capsys):
    assert shim.main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("minisweagent-shim ")
    before, after = tmp_path / "b", tmp_path / "a"
    for d in (before, after):
        (d / "src").mkdir(parents=True)
        (d / "same").write_text("1")
    (before / "src" / "x.c").write_text("old")
    (after / "src" / "x.c").write_text("new")
    (before / "gone").write_text("x")
    (after / "new").write_text("x")
    assert shim.changed_files(before, after) == ["new", "src/x.c", "gone (deleted)"]
