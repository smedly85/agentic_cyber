"""Unit tests for scripts/measure_diversity.py.

Focus: metric *properties* rather than exact values - symmetry,
self-similarity, and (for the levels that claim it) invariance to
identifier renaming - on small fixture programs, per the plan's
validity-controls section (docs/diversity_methodology.md).

Run with: python3 -m pytest tests/test_measure_diversity.py -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "scripts" / "run_llm_experiment.sh"
ANALYZER = REPO_ROOT / "scripts" / "analyze_experiment.py"
SORT_SUITE = REPO_ROOT / "tests" / "sort-test-suite"
SORT_SANITIZER_CC_FLAGS = [
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-pedantic",
    "-O1",
    "-g",
    "-D_POSIX_C_SOURCE=200809L",
]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import measure_diversity as md  # noqa: E402

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_c")
pytest.importorskip("rapidfuzz")
pytest.importorskip("apted")


FIXTURE_A = b"""\
#include <stdio.h>
int add(int a, int b) {
    int result = a + b;
    return result;
}
int main(void) {
    printf("%d\\n", add(2, 3));
    return 0;
}
"""

# Same logic, different variable/function names and formatting - a
# Type-2/near-Type-3 clone of FIXTURE_A.
FIXTURE_B = b"""\
#include <stdio.h>
int sum_two(int x, int y) {
    int total = x + y;
    return total;
}
int main(void) {
    printf("%d\\n", sum_two(2, 3));
    return 0;
}
"""

# Genuinely different implementation of "print a number": different
# control flow, different calls, different constructs entirely.
FIXTURE_C = b"""\
#include <stdio.h>
#include <string.h>
int main(void) {
    char buf[32];
    strcpy(buf, "5");
    for (int i = 0; i < 1; i++) {
        printf("%s\\n", buf);
    }
    return 0;
}
"""


def _variant(label: str, source: bytes) -> md.Variant:
    return md.Variant(label=label, path=Path(f"<fixture:{label}>"), source=source)


@pytest.fixture(autouse=True)
def _clear_parse_cache():
    md._PARSE_CACHE.clear()
    yield
    md._PARSE_CACHE.clear()


CLASSICAL_METRIC_FACTORIES = {
    "lexical_levenshtein": md._metric_lexical_levenshtein,
    "lexical_winnowing": md._metric_lexical_winnowing,
    "ast_ted": md._metric_ast_ted,
    "api_callset": md._metric_api_callset,
    "attack_surface": md._metric_attack_surface,
}


@pytest.mark.parametrize("name,fn", CLASSICAL_METRIC_FACTORIES.items())
def test_self_similarity_is_one(name, fn):
    a = _variant("a", FIXTURE_A)
    a_copy = _variant("a_copy", FIXTURE_A)
    sim = fn(a, a_copy)
    assert sim == pytest.approx(1.0, abs=1e-9), f"{name} self-similarity != 1.0"


@pytest.mark.parametrize("name,fn", CLASSICAL_METRIC_FACTORIES.items())
def test_symmetry(name, fn):
    a = _variant("a", FIXTURE_A)
    c = _variant("c", FIXTURE_C)
    assert fn(a, c) == pytest.approx(fn(c, a), abs=1e-9), f"{name} is not symmetric"


@pytest.mark.parametrize("name,fn", CLASSICAL_METRIC_FACTORIES.items())
def test_similarity_bounded_in_unit_interval(name, fn):
    a = _variant("a", FIXTURE_A)
    c = _variant("c", FIXTURE_C)
    sim = fn(a, c)
    assert -1e-9 <= sim <= 1.0 + 1e-9, f"{name} out of [0,1]: {sim}"


def test_renamed_clone_is_ast_and_winnowing_invariant():
    """FIXTURE_B is FIXTURE_A with every identifier renamed (Type-2 clone).
    The AST-shape and Type-2-token-normalized metrics must not notice;
    the raw-text metric must."""
    a = _variant("a", FIXTURE_A)
    b = _variant("b", FIXTURE_B)

    assert md._metric_ast_ted(a, b) == pytest.approx(1.0, abs=1e-9)
    assert md._metric_lexical_winnowing(a, b) == pytest.approx(1.0, abs=1e-9)
    assert md._metric_lexical_levenshtein(a, b) < 0.999


def test_different_implementation_is_less_similar_than_renamed_clone():
    """A genuinely different implementation (FIXTURE_C) should score lower
    on every structural metric than a mere renamed clone (FIXTURE_B) of
    the same program - the core sanity property the whole tool rests on."""
    a = _variant("a", FIXTURE_A)
    b = _variant("b", FIXTURE_B)
    c = _variant("c", FIXTURE_C)

    for name, fn in CLASSICAL_METRIC_FACTORIES.items():
        renamed_sim = fn(a, b)
        different_sim = fn(a, c)
        assert different_sim <= renamed_sim + 1e-9, (
            f"{name}: differently-implemented pair scored more similar "
            f"({different_sim}) than a renamed clone ({renamed_sim})"
        )


def test_attack_surface_detects_unsafe_construct_divergence():
    """FIXTURE_C uses strcpy into a fixed-size stack buffer; FIXTURE_A/B
    use neither. The attack-surface vector must reflect that difference -
    this is the property the security-diversity claim depends on."""
    a_parsed = md.parse_source(FIXTURE_A)
    c_parsed = md.parse_source(FIXTURE_C)
    va = md.attack_surface_vector(a_parsed)
    vc = md.attack_surface_vector(c_parsed)
    assert va["unsafe_calls"] == 0
    assert vc["unsafe_calls"] >= 1
    assert va["fixed_stack_buffers"] == 0
    assert vc["fixed_stack_buffers"] >= 1


def test_call_set_extraction():
    parsed = md.parse_source(FIXTURE_C)
    calls = md.call_set(parsed)
    assert "strcpy" in calls
    assert "printf" in calls


def test_winnowing_fingerprints_nonempty_for_nontrivial_input():
    parsed = md.parse_source(FIXTURE_A)
    tokens = md.type2_token_stream(parsed)
    assert len(tokens) > 10
    fps = md.winnowing_fingerprints(tokens)
    assert len(fps) > 0


def test_jaccard_edge_cases():
    assert md.jaccard(set(), set()) == 1.0
    assert md.jaccard({1, 2}, {1, 2}) == 1.0
    assert md.jaccard({1}, {2}) == 0.0


def test_load_variants_derives_temp_dir_label(tmp_path):
    run_dir = tmp_path / "runs" / "mkdir" / "temp-0p2" / "workdir" / "src"
    run_dir.mkdir(parents=True)
    f = run_dir / "new_mkdir.c"
    f.write_bytes(FIXTURE_A)
    variants = md.load_variants([str(f)])
    assert len(variants) == 1
    assert variants[0].label == "temp-0p2"


def test_calibration_passes():
    assert md.run_calibration() is True


# ---------------------------------------------------------------------------
# Sort evaluator, repair-loop runner, and analyzer regressions
# ---------------------------------------------------------------------------


def load_sort_runner():
    spec = importlib.util.spec_from_file_location(
        "sort_suite_runner", SORT_SUITE / "runner.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SORT_SUITE))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def load_sort_diff_fuzz():
    spec = importlib.util.spec_from_file_location(
        "sort_suite_diff_fuzz", SORT_SUITE / "diff_fuzz.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SORT_SUITE))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def initialize_sort_suite_harness(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    suite = tmp_path / "sort-suite"
    (suite / "suites").mkdir(parents=True)
    shutil.copy2(SORT_SUITE / "run_all.sh", suite / "run_all.sh")
    shutil.copy2(SORT_SUITE / "config.py", suite / "config.py")
    (suite / "suites" / "cases.json").write_text('{"cases": []}\n')

    candidate = tmp_path / "candidate"
    candidate.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    candidate.chmod(0o755)
    source = tmp_path / "candidate.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    config = suite / "config.json"
    runtime_config = json.loads((SORT_SUITE / "config.json").read_text())
    runtime_config["paths"].update(
        {
            "oracle_bin": "/bin/true",
            "candidate_bin": "/tracked/example/candidate",
            "candidate_asan_bin": str(tmp_path / "unused-asan"),
            "candidate_src": "",
        }
    )
    runtime_config["implemented"] = ["-n", "-k"]
    config.write_text(
        json.dumps(runtime_config, indent=2) + "\n",
        encoding="utf-8",
    )

    (suite / "runner.py").write_text(
        """\
import json
import os
import sys

config_path = sys.argv[sys.argv.index("--config") + 1]
report_path = sys.argv[sys.argv.index("--json-report") + 1]
with open(config_path, encoding="utf-8") as handle:
    config = json.load(handle)
with open(os.environ["CONFIG_CAPTURE"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({
        "config": config,
        "config_path": config_path,
        "candidate": sys.argv[sys.argv.index("--") + 1],
        "sanitizer": "--sanitizer" in sys.argv,
    }) + "\\n")
with open(report_path, "w", encoding="utf-8") as handle:
    json.dump({"counts": {"PASS": 1}, "per_suite": {}, "failures": []}, handle)
""",
        encoding="utf-8",
    )
    (suite / "diff_fuzz.py").write_text(
        """\
import json
import os
import sys

budget = sys.argv[sys.argv.index("--time-budget") + 1]
with open(os.environ["FUZZ_CAPTURE"], "w", encoding="utf-8") as handle:
    handle.write(budget)
report_path = sys.argv[sys.argv.index("--json-report") + 1]
with open(report_path, "w", encoding="utf-8") as handle:
    json.dump({
        "rounds": 0, "pass": 0, "fail": 0,
        "pass_pct": 100.0, "fail_pct": 0.0,
        "distinct_issues": 0, "new_regressions": 0,
    }, handle)
raise SystemExit(0 if float(budget) == 0 else 1)
""",
        encoding="utf-8",
    )
    (suite / "report_summary.py").write_text("pass\n", encoding="utf-8")
    (suite / "build_asan.sh").write_text(
        """\
#!/usr/bin/env bash
set -eu
out=$(python3 config.py "$1" paths.candidate_asan_bin)
cp /bin/true "$out"
""",
        encoding="utf-8",
    )
    (suite / "build_asan.sh").chmod(0o755)
    return suite, config, candidate, source


def test_sort_sanitizer_config_uses_strict_c11_contract():
    config = json.loads((SORT_SUITE / "config.json").read_text())
    assert config["paths"]["cc_flags"] == SORT_SANITIZER_CC_FLAGS
    assert "-std=c99" not in config["paths"]["cc_flags"]


@pytest.mark.parametrize(
    "implemented_csv, expected",
    [("-r", ["-r"]), ("-r,-f", ["-r", "-f"]), ("", [])],
)
def test_sort_runtime_overrides_use_temporary_config(
    tmp_path: Path, implemented_csv: str, expected: list[str]
):
    suite, config, candidate, source = initialize_sort_suite_harness(tmp_path)
    original_config = config.read_bytes()
    config_capture = tmp_path / "captured-configs.jsonl"
    fuzz_capture = tmp_path / "fuzz-seconds.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "CONFIG_CAPTURE": str(config_capture),
            "FUZZ_CAPTURE": str(fuzz_capture),
        }
    )

    result = subprocess.run(
        [
            "bash",
            str(suite / "run_all.sh"),
            "--candidate",
            str(candidate),
            "--candidate-src",
            str(source),
            f"--implemented-flags={implemented_csv}",
            "--stdin-only",
            "--fuzz-seconds",
            "0",
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert config.read_bytes() == original_config
    records = [json.loads(line) for line in config_capture.read_text().splitlines()]
    assert len(records) == 2
    assert [record["sanitizer"] for record in records] == [False, True]
    assert records[0]["candidate"] == str(candidate)
    for record in records:
        runtime_config = record["config"]
        assert not Path(record["config_path"]).exists()
        assert runtime_config["paths"]["candidate_bin"] == str(candidate)
        assert runtime_config["paths"]["candidate_src"] == str(source)
        assert runtime_config["paths"]["cc_flags"] == SORT_SANITIZER_CC_FLAGS
        assert runtime_config["implemented"] == expected
        assert runtime_config["scope"] == {"stdin_only": True}
    assert not Path(records[1]["candidate"]).exists()
    assert fuzz_capture.read_text() == "0"


def test_sort_stdin_scope_and_implemented_flag_filtering():
    runner = load_sort_runner()
    manifest = {
        "implemented": ["-r"],
        "excluded_tags": [],
        "scope": {"stdin_only": True},
    }

    assert runner.case_selected({"flags": [], "stdin_b64": "YQo="}, manifest)[0]
    assert runner.case_selected({"flags": [], "stdin_b64": ""}, manifest)[0]
    selected, reason = runner.case_selected({"flags": []}, manifest)
    assert selected is False
    assert reason == "outside stdin-only scope"
    selected, reason = runner.case_selected(
        {"flags": ["-f"], "stdin_b64": ""}, manifest
    )
    assert selected is False
    assert reason == "unimplemented ['-f']"

    empty_manifest = {**manifest, "implemented": []}
    assert runner.case_selected({"flags": [], "stdin_b64": ""}, empty_manifest)[0]
    assert not runner.case_selected(
        {"flags": ["-r"], "stdin_b64": ""}, empty_manifest
    )[0]


def test_sort_diff_fuzz_preserves_empty_and_restricted_manifests(tmp_path: Path):
    diff_fuzz = load_sort_diff_fuzz()
    missing = tmp_path / "missing.json"
    null = tmp_path / "null.json"
    empty = tmp_path / "empty.json"
    reverse = tmp_path / "reverse.json"
    missing.write_text("{}\n", encoding="utf-8")
    null.write_text('{"implemented": null}\n', encoding="utf-8")
    empty.write_text('{"implemented": []}\n', encoding="utf-8")
    reverse.write_text('{"implemented": ["-r"]}\n', encoding="utf-8")

    assert diff_fuzz.load_manifest(missing) is None
    assert diff_fuzz.load_manifest(null) is None
    assert diff_fuzz.load_manifest(empty) == set()
    assert diff_fuzz.load_manifest(reverse) == {"-r"}
    assert diff_fuzz.sample_combo(diff_fuzz.random.Random(1), set()) == ([], [])
    chosen, argv = diff_fuzz.sample_combo(
        diff_fuzz.random.Random(1), {"-r"}
    )
    assert chosen == ["-r"]
    assert argv == ["-r"]


def load_analyzer():
    spec = importlib.util.spec_from_file_location("analyze_experiment", ANALYZER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def analyzer():
    return load_analyzer()


def initialize_experiment_repo(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    (repository / "scripts").mkdir(parents=True)
    (repository / "src").mkdir()
    shutil.copy2(RUNNER, repository / "scripts" / RUNNER.name)
    (repository / "scripts" / "analyze_experiment.py").write_text(
        """\
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--experiment", type=Path, required=True)
args, _ = parser.parse_known_args()
(args.experiment / "analysis").mkdir(exist_ok=True)
(args.experiment / "analysis" / "AUTOMATIC").write_text("ran\\n")
""",
        encoding="utf-8",
    )
    (repository / "src" / "tool.c").write_text("baseline\n", encoding="utf-8")
    (repository / "prompt.md").write_text("Implement the checkpoint.\n", encoding="utf-8")
    (repository / ".gitignore").write_text("runs/\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "add", "."],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "baseline",
        ],
        cwd=repository,
        check=True,
    )

    fake_opencode = tmp_path / "fake-opencode"
    fake_opencode.write_text(
        """\
#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

counter = Path(os.environ["FAKE_COUNTER"])
invocation = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(invocation + 1))
prompt = sys.argv[-1]
with Path(os.environ["FAKE_PROMPTS"]).open("a", encoding="utf-8") as handle:
    handle.write(f"\\n===== PROMPT {invocation} =====\\n{prompt}\\n")
worktree = Path(sys.argv[sys.argv.index("--dir") + 1])
scenario = os.environ["FAKE_SCENARIO"]
if scenario == "repair-success" and invocation > 0:
    value = "repaired"
else:
    value = "broken"
(worktree / "src" / "tool.c").write_text(value + "\\n")
print(json.dumps({"total_tokens": invocation + 10}))
if scenario == "infrastructure-failure":
    raise SystemExit(42)
""",
        encoding="utf-8",
    )
    fake_opencode.chmod(0o755)
    return repository, fake_opencode


def run_experiment(
    tmp_path: Path,
    *,
    scenario: str,
    max_loops: int | str | None,
    extra_test_cmd: str = 'printf x >> "$EXTRA_COUNT"',
) -> tuple[Path, subprocess.CompletedProcess[str], int, str]:
    repository, fake_opencode = initialize_experiment_repo(tmp_path)
    counter = tmp_path / "counter.txt"
    prompts = tmp_path / "prompts.txt"
    extra_count = tmp_path / "extra-count.txt"
    output = repository / "runs" / "experiment"
    command = [
        "bash",
        str(repository / "scripts" / "run_llm_experiment.sh"),
        "--model",
        "fake/model",
        "--temperature",
        "0",
        "--runs",
        "1",
        "--prompt",
        "prompt.md",
        "--source",
        "src/tool.c",
        "--output-dir",
        str(output),
        "--build-cmd",
        "if test \"$(tr -d '\\n' < src/tool.c)\" = repaired; then exit 0; else echo broken-build; exit 1; fi",
        "--base-test-cmd",
        "true",
        "--feature-test-cmd",
        "true",
        "--extra-test-cmd",
        extra_test_cmd,
        "--timeout",
        "0",
    ]
    if max_loops is not None:
        command.extend(["--max-loops", str(max_loops)])

    environment = os.environ.copy()
    environment.update(
        {
            "OPENCODE_BIN": str(fake_opencode),
            "PYTHON_BIN": sys.executable,
            "FAKE_COUNTER": str(counter),
            "FAKE_PROMPTS": str(prompts),
            "FAKE_SCENARIO": scenario,
            "EXTRA_COUNT": str(extra_count),
        }
    )
    result = subprocess.run(
        command,
        cwd=repository,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    invocations = int(counter.read_text())
    return output, result, invocations, prompts.read_text(encoding="utf-8")


def test_default_max_loops_is_one_shot(tmp_path: Path):
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="always-fail",
        max_loops=None,
    )

    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert json.loads((output / "experiment.json").read_text())["max_loops"] == 0
    assert invocations == 1
    assert metadata["repair_loops"] == 0
    assert metadata["llm_invocations"] == 1
    assert metadata["loop_limit_reached"] is True
    assert len(metadata["loops"]) == 1


def test_successful_repair_stops_and_captures_final_candidate(tmp_path: Path):
    output, result, invocations, prompts = run_experiment(
        tmp_path,
        scenario="repair-success",
        max_loops="03",
    )

    assert result.returncode == 0, result.stderr
    attempt = output / "attempt-001"
    metadata = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
    assert json.loads((output / "experiment.json").read_text())["max_loops"] == 3
    assert invocations == 2
    assert metadata["initial_success"] is False
    assert metadata["repair_loops"] == 1
    assert metadata["llm_invocations"] == 2
    assert metadata["success_loop"] == 1
    assert metadata["loop_limit_reached"] is False
    assert metadata["public_validation_success"] is True
    assert [loop["validation_success"] for loop in metadata["loops"]] == [
        False,
        True,
    ]
    assert (attempt / "candidate" / "src" / "tool.c").read_text() == "repaired\n"
    assert "+repaired" in (attempt / "patch.diff").read_text()
    assert "LLM INVOCATION 0: INITIAL" in (attempt / "opencode.log").read_text()
    assert "LLM INVOCATION 1: REPAIR LOOP 1" in (attempt / "opencode.log").read_text()
    assert "VALIDATION LOOP 0" in (attempt / "build.log").read_text()
    assert "VALIDATION LOOP 1" in (attempt / "build.log").read_text()
    assert "Continue working on the CURRENT implementation" in prompts
    assert "broken-build" in prompts
    assert (tmp_path / "extra-count.txt").read_text() == "x"
    assert (output / "analysis" / "AUTOMATIC").exists()
    forbidden = {"loop-001", "repair", "initial", "final"}
    assert forbidden.isdisjoint(path.name for path in attempt.iterdir() if path.is_dir())


def test_hidden_evaluator_failure_is_final_and_never_repairs(tmp_path: Path):
    marker = "HIDDEN-EVALUATOR-OUTPUT"
    output, result, invocations, prompts = run_experiment(
        tmp_path,
        scenario="repair-success",
        max_loops=3,
        extra_test_cmd=(
            f'printf x >> "$EXTRA_COUNT"; printf "{marker}\\n"; exit 7'
        ),
    )

    assert result.returncode == 0, result.stderr
    attempt = output / "attempt-001"
    metadata = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
    assert invocations == 2
    assert metadata["repair_loops"] == 1
    assert metadata["llm_invocations"] == 2
    assert metadata["public_validation_success"] is True
    assert metadata["extra_test_exit_code"] == 7
    assert metadata["overall_success"] is False
    assert (tmp_path / "extra-count.txt").read_text() == "x"
    assert marker in (attempt / "extra-tests.log").read_text()
    assert marker not in prompts


def test_repair_budget_exhaustion_is_recorded(tmp_path: Path):
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="always-fail",
        max_loops=2,
    )

    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert invocations == 3
    assert metadata["repair_loops"] == 2
    assert metadata["llm_invocations"] == 3
    assert metadata["success_loop"] is None
    assert metadata["loop_limit_reached"] is True
    assert metadata["public_validation_success"] is False
    assert len(metadata["loops"]) == 3


def test_infrastructure_failure_does_not_trigger_or_exhaust_repairs(tmp_path: Path):
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="infrastructure-failure",
        max_loops=3,
    )

    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert invocations == 1
    assert metadata["opencode_exit_code"] == 42
    assert metadata["repair_loops"] == 0
    assert metadata["loop_limit_reached"] is False
    assert metadata["overall_success"] is False


def test_max_loops_requires_a_value():
    result = subprocess.run(
        [
            "bash",
            str(RUNNER),
            "--model",
            "fake/model",
            "--temperature",
            "0",
            "--prompt",
            "prompts/new_sort/001_reverse.md",
            "--max-loops",
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "--max-loops requires a value" in result.stderr


def test_max_loops_rejects_arithmetic_overflow():
    result = subprocess.run(
        [
            "bash",
            str(RUNNER),
            "--model",
            "fake/model",
            "--temperature",
            "0",
            "--prompt",
            "prompts/new_sort/001_reverse.md",
            "--max-loops",
            "999999999999999999999999999999999999999",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "OPENCODE_BIN": "true", "PYTHON_BIN": sys.executable},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "--max-loops is too large" in result.stderr


def test_analyzer_normalizes_old_and_new_metadata(analyzer):
    old = analyzer.normalize_repair_metadata(
        {
            "build_exit_code": 0,
            "base_test_exit_code": 0,
            "feature_test_exit_code": 0,
            "opencode_runtime_ms": 125,
            "overall_success": True,
        }
    )
    new = analyzer.normalize_repair_metadata(
        {
            "initial_success": False,
            "repair_loops": 2,
            "llm_invocations": 3,
            "success_loop": 2,
            "public_validation_success": True,
            "repair_opencode_runtime_ms": 250,
        }
    )

    assert old["repair_loops"] == 0
    assert old["llm_invocations"] == 1
    assert old["initial_success"] is True
    assert old["success_loop"] == 0
    assert old["total_opencode_runtime_ms"] == 125
    assert new["repair_loops"] == 2
    assert new["llm_invocations"] == 3
    assert new["success_loop"] == 2

    old_setup_failure = analyzer.normalize_repair_metadata(
        {"setup_exit_code": 1, "overall_success": False}
    )
    assert old_setup_failure["llm_invocations"] == 0
    assert old_setup_failure["loop_limit_reached"] is False


def test_repair_summary_and_pass_at_k_use_attempts(analyzer):
    rows = [
        analyzer.normalize_repair_metadata(
            {
                "initial_success": True,
                "repair_loops": 0,
                "llm_invocations": 1,
                "success_loop": 0,
                "public_validation_success": True,
                "repair_opencode_runtime_ms": 0,
            }
        ),
        analyzer.normalize_repair_metadata(
            {
                "initial_success": False,
                "repair_loops": 2,
                "llm_invocations": 3,
                "success_loop": 2,
                "public_validation_success": True,
                "repair_opencode_runtime_ms": 4000,
            }
        ),
        analyzer.normalize_repair_metadata(
            {
                "initial_success": False,
                "repair_loops": 3,
                "llm_invocations": 4,
                "success_loop": None,
                "public_validation_success": False,
                "repair_opencode_runtime_ms": 5000,
            }
        ),
    ]
    summary = analyzer.build_repair_summary(rows, configured_max_loops=3)

    assert summary["initial_success_rate"] == pytest.approx(1 / 3)
    assert summary["public_validation_success_rate"] == pytest.approx(2 / 3)
    assert summary["mean_repair_loops"] == pytest.approx(5 / 3)
    assert summary["median_repair_loops"] == 2
    assert summary["max_repair_loops"] == 3
    assert summary["mean_llm_invocations"] == pytest.approx(8 / 3)
    assert [point["successful_runs"] for point in summary["success_curve"]] == [
        1,
        1,
        2,
        2,
    ]
    assert analyzer.pass_at_k(3, 2, 1) == pytest.approx(2 / 3)


def test_analyzer_reads_final_appended_tests_and_sums_invocation_tokens(
    analyzer,
    tmp_path: Path,
):
    test_log = tmp_path / "tests.log"
    test_log.write_text(
        """\
===== VALIDATION LOOP 0: BASE TESTS =====
Ran 2 tests
FAILED (failures=1)
===== VALIDATION LOOP 1: BASE TESTS =====
Ran 3 tests
OK
""",
        encoding="utf-8",
    )
    opencode_log = tmp_path / "opencode.log"
    opencode_log.write_text(
        """\
===== LLM INVOCATION 0: INITIAL =====
{"total_tokens": 10}
===== LLM INVOCATION 1: REPAIR LOOP 1 =====
{"total_tokens": 7}
""",
        encoding="utf-8",
    )

    tests = analyzer.parse_test_log(test_log)
    tokens = analyzer.parse_llm_tokens(opencode_log)
    assert tests == {
        "tests_run": 3,
        "failures": 0,
        "errors": 0,
        "tests_passed": 3,
    }
    assert tokens["total_tokens"] == 17


def test_full_analyzer_accepts_mixed_old_and_repair_metadata(tmp_path: Path):
    pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    repository = tmp_path / "repository"
    experiment = tmp_path / "experiment"
    source_path = Path("src/tool.c")
    repository.mkdir()
    (experiment / "baseline" / source_path.parent).mkdir(parents=True)
    baseline_source = "int main(void) { return 0; }\n"
    (experiment / "baseline" / source_path).write_text(baseline_source)
    (experiment / "experiment.json").write_text(
        json.dumps(
            {
                "repository": str(repository),
                "source_path": str(source_path),
                "model": "fake/model",
                "temperature": 0,
                "max_loops": 3,
            }
        ),
        encoding="utf-8",
    )

    metadata_rows = [
        {
            "run_id": "attempt-001",
            "build_exit_code": 0,
            "base_test_exit_code": 0,
            "feature_test_exit_code": 0,
            "extra_test_exit_code": 0,
            "opencode_runtime_ms": 100,
            "total_runtime_ms": 200,
            "overall_success": True,
        },
        {
            "run_id": "attempt-002",
            "build_exit_code": 0,
            "base_test_exit_code": 0,
            "feature_test_exit_code": 0,
            "extra_test_exit_code": 1,
            "initial_success": False,
            "repair_loops": 2,
            "llm_invocations": 3,
            "success_loop": 2,
            "loop_limit_reached": False,
            "public_validation_success": True,
            "initial_opencode_runtime_ms": 100,
            "repair_opencode_runtime_ms": 200,
            "total_opencode_runtime_ms": 300,
            "total_runtime_ms": 500,
            "overall_success": False,
            "loops": [],
        },
    ]
    for index, metadata in enumerate(metadata_rows, start=1):
        attempt = experiment / f"attempt-{index:03d}"
        (attempt / "candidate" / source_path.parent).mkdir(parents=True)
        candidate = (
            baseline_source
            if index == 1
            else "int main(void) { int repaired = 1; return repaired - 1; }\n"
        )
        (attempt / "candidate" / source_path).write_text(candidate)
        (attempt / "metadata.json").write_text(json.dumps(metadata))
        for name in (
            "diff-numstat.txt",
            "untracked-files.txt",
            "base-tests.log",
            "feature-tests.log",
            "extra-tests.log",
            "opencode.log",
        ):
            (attempt / name).write_text("", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ANALYZER),
            "--experiment",
            str(experiment),
            "--clean-output",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(
        (experiment / "analysis" / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["runs_analyzed"] == 2
    assert summary["pass_at_k"]["pass@1"] == pytest.approx(0.5)
    assert summary["repair"]["initial_success_rate"] == pytest.approx(0.5)
    assert summary["repair"]["public_validation_success_rate"] == 1.0
    assert summary["repair"]["mean_llm_invocations"] == 2.0
