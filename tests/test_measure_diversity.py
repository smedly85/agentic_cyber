"""Tests for the canonical experiment analysis and affected controllers."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
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
from analysis import diversity_metrics as dm  # noqa: E402
from analysis import diversity_validation as dv  # noqa: E402
from analysis import security_diagnostics as sd  # noqa: E402


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


class CanonicalAnalysisUnitTests(unittest.TestCase):
    def test_cluster_statistics_and_duplicates(self):
        stats = dm.cluster_statistics([0, 0, 1, 1])
        self.assertEqual(stats["raw_family_count"], 2)
        self.assertAlmostEqual(stats["effective_family_count"], 2.0)
        self.assertEqual(stats["dominant_family_share"], 0.5)
        self.assertEqual(stats["singleton_rate"], 0.0)
        skewed = dm.cluster_statistics([0, 0, 0, 1, 2])
        self.assertLess(skewed["effective_family_count"], skewed["raw_family_count"])
        repeated = dm.cluster_statistics([0, 0, 0, 1])
        self.assertEqual(sum(repeated["family_sizes"].values()), 4)
        np = pytest.importorskip("numpy")
        features = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        labels = dm.agglomerative_labels(dm.cosine_distance_matrix(features), 0.3)
        clustered = dm.cluster_statistics(labels.tolist())
        self.assertEqual(sum(clustered["family_sizes"].values()), 3)
        self.assertIn(2, clustered["family_sizes"].values())

    def test_exact_da_at_k(self):
        labels = [0, 0, 1, 1]
        self.assertEqual(dm.da_at_k(labels, 1), 1.0)
        self.assertAlmostEqual(dm.da_at_k(labels, 2), 5 / 3)
        self.assertEqual(dm.da_at_k(labels, 4), 2.0)
        self.assertTrue(all(dm.da_at_k([0, 0, 0], k) == 1 for k in range(1, 4)))
        self.assertEqual([dm.da_at_k(range(4), k) for k in range(1, 5)], [1, 2, 3, 4])
        with self.assertRaises(ValueError):
            dm.da_at_k(labels, 0)
        with self.assertRaises(ValueError):
            dm.da_at_k(labels, 5)

    def test_nauadc_fixed_budget(self):
        self.assertEqual(dm.nauadc([1, 1, 1, 1]), 1.0)
        self.assertEqual(dm.nauadc([1, 2, 3, 4]), 2.5)
        curve = dm.da_curve([0, 1, 2, 3])
        self.assertEqual(dm.nauadc_summary(curve, 3)["nauadc_at_kmax"], 2.0)
        insufficient = dm.nauadc_summary(curve[:2], 3)
        self.assertIsNone(insufficient["nauadc_at_kmax"])
        self.assertIn("smaller", insufficient["nauadc_at_kmax_reason"])

    def test_exact_repetition(self):
        result = dm.exact_repetition_summary(["A", "A", "B", "C"])
        self.assertEqual(result["exact_unique_rate"], 0.75)
        self.assertEqual(result["exact_modal_share"], 0.5)

    def test_vendi(self):
        np = pytest.importorskip("numpy")
        self.assertEqual(dm.vendi_score(np.array([[1.0, 0.0]])), 1.0)
        self.assertAlmostEqual(dm.vendi_score(np.array([[1.0, 0.0], [1.0, 0.0]])), 1.0)
        self.assertAlmostEqual(dm.vendi_score(np.eye(4)), 4.0)
        self.assertIsNone(dm.vendi_score(np.empty((0, 0))))

    def test_ari_and_threshold_grid(self):
        from sklearn.metrics import adjusted_rand_score
        np = pytest.importorskip("numpy")
        self.assertEqual(adjusted_rand_score([0, 0, 1, 1], [7, 7, 4, 4]), 1.0)
        self.assertEqual(
            dm.deterministic_threshold_grid(0.30),
            [0.2, 0.25, 0.275, 0.3, 0.325, 0.35, 0.4],
        )
        self.assertEqual(dm.deterministic_threshold_grid(0.3, "0.1,0.4"), [0.1, 0.4])
        distance = np.array([[0, .1, .9], [.1, 0, .8], [.9, .8, 0]])
        rows = dm.threshold_sensitivity(distance, 0.3, [0.2, 0.3, 0.4])
        self.assertIn("adjusted_rand_vs_primary", rows[0])
        self.assertEqual(rows[1]["adjusted_rand_vs_primary"], 1.0)

    def test_population_has_no_fallback(self):
        rows = [
            {"run_id": "ok-complete", "overall_success": True, "arch": True, "strategy": False},
            {"run_id": "ok-incomplete", "overall_success": True, "arch": False, "strategy": True},
            {"run_id": "failed", "overall_success": False, "arch": True, "strategy": True},
        ]
        architecture = dm.primary_population(rows, "arch")
        strategy = dm.primary_population(rows, "strategy")
        self.assertEqual(architecture["run_ids"], ["ok-complete"])
        self.assertEqual(strategy["run_ids"], ["ok-incomplete"])
        self.assertEqual(architecture["measurement_coverage"], 0.5)

    def test_wilson_and_bootstrap_determinism(self):
        np = pytest.importorskip("numpy")
        self.assertIsNone(dm.wilson_interval(0, 0)["estimate"])
        self.assertGreater(dm.wilson_interval(0, 10)["upper"], 0)
        self.assertLess(dm.wilson_interval(10, 10)["lower"], 1)
        matrix = np.eye(3)
        first = dm.bootstrap_diversity_ci(matrix, 0.3, 20, 17, 2)
        second = dm.bootstrap_diversity_ci(matrix, 0.3, 20, 17, 2)
        self.assertEqual(first, second)
        self.assertEqual(first["sampling_unit"], "implementation")

    def test_validation_distances(self):
        for dependency in ("tree_sitter", "tree_sitter_c", "rapidfuzz", "apted"):
            pytest.importorskip(dependency)
        dv._PARSE_CACHE.clear()
        a = dv.parse_source(FIXTURE_A + b"// comment\n")
        plain = dv.parse_source(FIXTURE_A)
        renamed = dv.parse_source(FIXTURE_B)
        different = dv.parse_source(FIXTURE_C)
        self.assertEqual(dv.lexical_distance(a, plain), 0.0)
        self.assertEqual(dv.token_winnowing_distance(plain, renamed), 0.0)
        self.assertEqual(dv.apted_distance(plain, plain), 0.0)
        self.assertEqual(dv.api_callset_distance(plain, plain), 0.0)
        self.assertGreater(dv.api_callset_distance(plain, different), 0.0)

    def test_security_profile_is_separate_diagnostic(self):
        for dependency in ("tree_sitter", "tree_sitter_c"):
            pytest.importorskip(dependency)
        source = FIXTURE_C.replace(b"return 0;", b"buf[0] = '5'; return 0;")
        profile = sd.security_profile(source)
        self.assertGreaterEqual(profile["unsafe_call_count"], 1)
        self.assertGreaterEqual(profile["fixed_size_stack_buffer_count"], 1)
        self.assertGreaterEqual(profile["indexing_operation_count"], 1)

    def test_correlations_use_pairwise_complete_distances(self):
        pytest.importorskip("scipy")
        rows = [{"a_distance": 0.1, "b_distance": 0.2}, {"a_distance": 0.8, "b_distance": 0.9}, {"a_distance": None, "b_distance": 0.4}]
        result = dv.pairwise_spearman_correlations(rows, ["a_distance", "b_distance"])
        cross = next(row for row in result if row["left_metric"] == "a_distance" and row["right_metric"] == "b_distance")
        self.assertEqual(cross["supporting_pairs"], 2)
        self.assertAlmostEqual(cross["spearman_correlation"], 1.0)

    def test_canonical_removals(self):
        analyzer_text = ANALYZER.read_text(encoding="utf-8").lower()
        for forbidden in ("import torch", "import transformers", "codebleu", "jplag", "lizard", "difftastic"):
            self.assertNotIn(forbidden, analyzer_text)
        self.assertFalse((REPO_ROOT / "scripts" / "measure_diversity.py").exists())
        self.assertFalse((REPO_ROOT / "scripts" / "diversity_pipeline.py").exists())
        module = load_analyzer()
        forbidden_columns = {
            "Mean LLM Total Tokens", "Mean Source Tokens", "entropy_nats",
            "entropy_bits", "singleton rate", "CodeBLEU", "JPlag",
        }
        self.assertTrue(forbidden_columns.isdisjoint(module.PAPER_METRICS_COLUMNS))
        self.assertTrue(forbidden_columns.isdisjoint(module.PAPER_DESCRIPTIVE_COLUMNS))


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


def test_sort_stdin_only_scope_uses_only_stdin_execution_modes():
    runner = load_sort_runner()
    case = {"flags": [], "stdin_b64": ""}

    assert runner.modes_for(case, stdin_only=True) == [
        ("pipe", ".p"),
        ("redirect", ".r"),
    ]
    assert runner.modes_for(
        {**case, "stdin_modes": ["file", "pipe", "redirect"]},
        stdin_only=True,
    ) == [("pipe", ".p"), ("redirect", ".r")]
    assert runner.modes_for(
        {**case, "stdin_modes": ["file"]}, stdin_only=True
    ) == []


def test_sort_obsolete_and_future_options_are_excluded():
    runner = load_sort_runner()
    manifest = {
        "implemented": ["-r"],
        "excluded_tags": ["obsolete"],
        "scope": {"stdin_only": True},
    }

    selected, reason = runner.case_selected(
        {"args": ["+1", "-2"], "flags": [], "stdin_b64": "", "tags": ["obsolete"]},
        manifest,
    )
    assert selected is False
    assert reason == "excluded tag ['obsolete']"

    # Legacy frozen suites omitted the obsolete tag from GNU's -y[SIZE] case.
    assert not runner.case_selected(
        {"args": ["-y0"], "flags": [], "stdin_b64": "", "tags": ["curated"]},
        manifest,
    )[0]

    selected, reason = runner.case_selected(
        {"args": ["-f"], "flags": ["-f"], "stdin_b64": ""}, manifest
    )
    assert selected is False
    assert reason == "unimplemented ['-f']"


@pytest.mark.parametrize("target", ["/dev/full", "closed-pipe"])
def test_sort_output_fault_accepts_non_gnu_diagnostic(monkeypatch, target: str):
    runner = load_sort_runner()
    result = runner.engine.Result(
        exit_code=1,
        signal=None,
        signal_name=None,
        stdout=b"",
        stderr=b"new_sort: output error\n",
    )
    monkeypatch.setattr(runner.engine, "execute", lambda *args, **kwargs: result)
    case = {
        "faults": {"stdout": target},
        "exit_code": 2,
        "stderr": "sort: write failed: GNU-specific text\n",
        "check": "none",
    }

    assert runner.run_one(case, ["candidate"], "pipe", False, False) == (
        runner.PASS,
        "",
    )


def test_sort_output_fault_rejects_silent_success(monkeypatch):
    runner = load_sort_runner()
    result = runner.engine.Result(
        exit_code=0,
        signal=None,
        signal_name=None,
        stdout=b"",
        stderr=b"",
    )
    monkeypatch.setattr(runner.engine, "execute", lambda *args, **kwargs: result)
    case = {
        "faults": {"stdout": "/dev/full"},
        "exit_code": 2,
        "stderr_class": "nonempty",
        "check": "none",
    }

    verdict, detail = runner.run_one(
        case, ["candidate"], "pipe", False, False
    )
    assert verdict == runner.FAIL
    assert "silently succeeded" in detail
    assert "no diagnostic" in detail


@pytest.mark.parametrize(
    "result,sanitizer,expected",
    [
        (
            {"exit_code": None, "signal": None, "signal_name": None,
             "timed_out": True},
            False,
            "TIMEOUT",
        ),
        (
            {"exit_code": None, "signal": 11, "signal_name": "SIGSEGV"},
            False,
            "CRASH",
        ),
        (
            {"exit_code": 1, "signal": None, "signal_name": None,
             "sanitizer": "AddressSanitizer: heap-buffer-overflow"},
            True,
            "SANITIZER",
        ),
        (
            {"exit_code": None, "signal": 13, "signal_name": "SIGPIPE",
             "sanitizer": "AddressSanitizer: deadly signal"},
            True,
            "SANITIZER",
        ),
    ],
)
def test_sort_output_fault_keeps_runtime_failures_strict(
    monkeypatch, result: dict, sanitizer: bool, expected: str
):
    runner = load_sort_runner()
    execution = runner.engine.Result(
        stdout=b"",
        stderr=b"diagnostic\n",
        **result,
    )
    monkeypatch.setattr(runner.engine, "execute", lambda *args, **kwargs: execution)
    case = {
        "faults": {"stdout": "closed-pipe"},
        "allow_signals": ["SIGPIPE"],
        "check": "none",
    }

    verdict, _ = runner.run_one(
        case, ["candidate"], "pipe", sanitizer, False
    )
    assert verdict == expected


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

    assert summary["initial_public_success_rate"] == pytest.approx(1 / 3)
    assert summary["final_public_success_rate"] == pytest.approx(2 / 3)
    assert summary["repair_recovery_rate"] == pytest.approx(1 / 2)
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
    assert summary["repair"]["initial_public_success_rate"] == pytest.approx(0.5)
    assert summary["repair"]["final_public_success_rate"] == 1.0
    assert summary["repair"]["mean_llm_invocations"] == 2.0
    assert summary["successful_runs"] == 1
    assert summary["exact_generation_convergence"]["exact_unique_rate"] == 1.0
    assert summary["clustering"]["primary_population"] == {
        "architecture": "passing_complete_runs",
        "strategy": "passing_complete_runs",
    }
    for relative in (
        "runs.csv",
        "paper_metrics.csv",
        "paper_descriptive_metrics.csv",
        "diversity/architecture_da_curve.csv",
        "diversity/strategy_da_curve.csv",
        "diversity/exact_repetition.csv",
        "diagnostics/uncertainty.csv",
    ):
        assert (experiment / "analysis" / relative).exists()
    primary_header = (experiment / "analysis" / "paper_metrics.csv").read_text().splitlines()[0]
    assert "Mean LLM Total Tokens" not in primary_header
    assert "entropy" not in primary_header.lower()
    assert "singleton" not in primary_header.lower()


def test_full_analyzer_accepts_sandbox_run_metadata(tmp_path: Path):
    pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    run_root = tmp_path / "sandbox"
    condition = run_root / "temp-0p5"
    repository = tmp_path / "repository"
    repository.mkdir()
    run_root.mkdir()
    (run_root / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": str(repository),
                "model": "fake/model",
                "prompt": "prompts/mkdir/checkpoint.md",
                "seed_files": "",
            }
        ),
        encoding="utf-8",
    )
    for repeat, success in ((1, True), (2, False)):
        attempt = condition / f"rep-{repeat}"
        source = attempt / "workdir" / "src" / "tool.c"
        source.parent.mkdir(parents=True)
        source.write_text(f"int helper_{repeat}(void) {{ return {repeat}; }}\n", encoding="utf-8")
        (attempt / "metadata.json").write_text(
            json.dumps(
                {
                    "model": "fake/model",
                    "temperature": 0.5,
                    "repeat": repeat,
                    "opencode_exit_code": 0,
                    "opencode_permission_rejected": False,
                    "test_exit_code": 0 if success else 1,
                    "opencode_runtime_ms": 10,
                    "test_runtime_ms": 5,
                    "total_runtime_ms": 15,
                    "overall_success": success,
                }
            ),
            encoding="utf-8",
        )
        (attempt / "opencode.log").write_text("", encoding="utf-8")
        (attempt / "test.log").write_text("", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ANALYZER),
            "--experiment",
            str(condition),
            "--source-path",
            "src/tool.c",
            "--bootstrap-repetitions",
            "5",
            "--clean-output",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads((condition / "analysis" / "summary.json").read_text())
    assert summary["experiment_format"] == "sandbox_run"
    assert summary["baseline_kind"] == "empty_from_scratch"
    assert summary["source_path"] == "src/tool.c"
    assert summary["runs_analyzed"] == 2
    assert summary["successful_runs"] == 1
    assert summary["temperature"] == 0.5
