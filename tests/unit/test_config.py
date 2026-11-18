from __future__ import annotations

import pytest

from src.config import (
    ConfigError,
    check_ready_for_run,
    load_config,
    parse_env_file,
    redacted,
)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_without_files(tmp_path):
    cfg = load_config(tmp_path / "missing.toml", tmp_path / "missing.env", environ={})
    assert cfg["depth"]["rule"] == "le"
    assert cfg["depth"]["depth"] is None
    assert cfg["edit"] == {
        "allow_new_helpers": True,
        "allow_new_includes": True,
        "allow_new_globals_types": True,
    }
    assert cfg["callgraph"]["rust_backend"] == "rupta"
    assert cfg["retry"]["token_budget"]["enabled"] is False


def test_missing_explicit_config_is_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml", None, environ={}, require_config_file=True)


def test_precedence_cli_over_toml_over_defaults(tmp_path):
    toml = write(tmp_path / "config.toml", '[depth]\nrule = "eq"\ndepth = 2\norder = "deep_first"\n')
    cfg = load_config(toml, None, {"depth.depth": 5}, environ={})
    assert cfg["depth"]["rule"] == "eq"  # toml over default
    assert cfg["depth"]["order"] == "deep_first"
    assert cfg["depth"]["depth"] == 5  # cli over toml


def test_env_process_over_file_and_role_fallbacks(tmp_path):
    env = write(
        tmp_path / ".env",
        'AGENT_API_BASE="http://file:1"\nAGENT_API_KEY=filekey\nexport AGENT_WORKER_MODEL=ollama_chat/a # comment\n'
        "AGENT_PLANNER_API_BASE=http://planner\n",
    )
    cfg = load_config(None, env, environ={"AGENT_WORKER_MODEL": "openai/b", "UNRELATED": "x"})
    worker = cfg["models"]["worker"]
    assert worker == {"model": "openai/b", "api_base": "http://file:1", "api_key": "filekey"}
    assert cfg["models"]["planner"]["api_base"] == "http://planner"
    assert cfg["models"]["orchestrator"]["model"] is None


def test_models_rejected_in_toml(tmp_path):
    toml = write(tmp_path / "config.toml", '[models.worker]\nmodel = "x"\n')
    with pytest.raises(ConfigError):
        load_config(toml, None, environ={})


@pytest.mark.parametrize(
    "snippet",
    ['[depth]\nrule = "lt"\n', '[depth]\ndepth = -1\n', '[agent]\ntopology = "swarm"\n', "[retry]\nmax_loops = -2\n"],
)
def test_validation_errors(tmp_path, snippet):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path / "g.toml", snippet), None, environ={})


def test_env_parser_rejects_garbage(tmp_path):
    with pytest.raises(ConfigError):
        parse_env_file(write(tmp_path / ".env", "NOEQUALS\n"))


def test_ready_check_lists_roles_for_topology(tmp_path):
    cfg = load_config(None, None, {"agent.topology": "orchestrator"}, environ={"AGENT_WORKER_MODEL": "m"})
    problems = check_ready_for_run(cfg)
    assert "AGENT_ORCHESTRATOR_MODEL is not set in .env" in problems
    assert not any("WORKER" in p for p in problems)
    assert "tests.hidden_suite is not set" in problems


def test_redaction_hides_keys():
    cfg = load_config(None, None, environ={"AGENT_API_KEY": "secret"})
    out = redacted(cfg)
    assert out["models"]["worker"]["api_key"] == "<redacted>"
    assert "secret" not in repr(out)


def test_repo_config_toml_loads():
    from src import DEFAULT_CONFIG_PATH

    cfg = load_config(DEFAULT_CONFIG_PATH, None, environ={}, require_config_file=True)
    assert cfg["agent"]["generator"] == "minisweagent"
