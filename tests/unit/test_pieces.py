"""Pure helpers: feedback formatting, language text utilities, docker argv, agent networking."""

from __future__ import annotations

from src.agents.minisweagent import agent_network, function_file_name
from src.incontainer import c_lang, rs_lang
from src.sandbox import docker
from src.suite import SummaryFormatter


def test_summary_formatter_caps_failures():
    result = {
        "ok": False,
        "passed": 1,
        "failed": 3,
        "cases": [
            {"name": "ok", "status": "pass"},
            {"name": "a", "status": "fail", "detail": "x" * 50},
            {"name": "b", "status": "timeout", "detail": ""},
            {"name": "c", "status": "fail", "detail": "z"},
        ],
    }
    text = SummaryFormatter(max_failures=2, max_detail_chars=10).format(result)
    assert text.splitlines()[0] == "TESTS: FAIL (1/4 passed)"
    assert "FAIL a: xxxxxxxxxx..." in text and "TIMEOUT b" in text
    assert "1 more failing cases omitted" in text and " c:" not in text


def test_summary_formatter_uses_output_tail_without_report():
    text = SummaryFormatter().format({"ok": False, "passed": 0, "failed": 0, "cases": [], "stderr_tail": "Traceback boom"})
    assert "Traceback boom" in text


def test_c_signature_diff_and_include_hoist():
    want = {"name": "f", "type": "int (int)", "param_names": ["x"], "storage_class": "none", "inline": False, "variadic": False, "attributes": []}
    got = dict(want, param_names=["y"], storage_class="static")
    diff = c_lang.signature_diff(want, got)
    assert len(diff) == 2 and any("param_names" in d for d in diff)
    src = b'#include <stdio.h>\n#include "a.h"\n\nint f(int x) { return x; }\n'
    out = c_lang._hoist_includes(src, ["#include <ctype.h>", "#include <stdio.h>"]).decode()
    assert out.index("<ctype.h>") > out.index('"a.h"') and out.count("<stdio.h>") == 1


def test_rust_use_split_and_attribute_extension():
    uses, body = rs_lang._split_uses("use std::fmt;\nuse a::{\n    b,\n    c,\n};\nfn f() {}\n")
    assert uses == ["use std::fmt;", "use a::{\n    b,\n    c,\n};"]
    assert body.strip() == "fn f() {}"
    src = b"struct S;\n\n/// doc\n#[inline]\nfn f() {}\n"
    lo = src.index(b"fn f")
    assert src[rs_lang._extend_over_attributes(src, lo) :].startswith(b"/// doc")
    text, shift = rs_lang._hoist_uses("#![allow(x)]\nuse std::io;\nfn main() {}\n", ["use std::io;", "use std::fmt;"])
    assert text.startswith("#![allow(x)]\nuse std::fmt;\n") and shift == len("use std::fmt;\n")


def test_function_file_names():
    assert function_file_name({"name": "<Square as Transform>::transform", "language": "rust"}) == "Square_as_Transform_transform.rs"
    assert function_file_name({"name": "parse_number", "language": "c"}) == "parse_number.c"


def test_agent_network_modes():
    assert agent_network("auto", ["http://localhost:11434"]) == ("host", {})
    assert agent_network("auto", ["https://api.example.com/v1"]) == ("bridge", {})
    mode, rewrites = agent_network("bridge", ["http://127.0.0.1:11434"])
    assert mode == "bridge" and rewrites["http://127.0.0.1:11434"] == "http://host.docker.internal:11434"


def test_docker_argv_is_hardened_and_redacts_secrets():
    spec = docker.ContainerSpec(image="img", command=["true"], env={"AGENT_WORKER_API_KEY": "s3cret"})
    argv = docker.build_argv(spec)
    for flag in ("--cap-drop", "--pids-limit", "--memory", "--security-opt"):
        assert flag in argv
    assert argv[argv.index("--network") + 1] == "none"
    assert "AGENT_WORKER_API_KEY=<redacted>" in docker.redact_env(argv)
    assert "s3cret" not in " ".join(docker.redact_env(argv))
