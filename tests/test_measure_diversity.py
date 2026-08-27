"""Tests for the canonical experiment analysis and affected controllers."""

from __future__ import annotations

import importlib.util
import ast
import csv
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "scripts" / "run_experiment.sh"
RUNNER_HELPERS = (
    REPO_ROOT / "scripts" / "capture_candidate.py",
    REPO_ROOT / "scripts" / "repair_prompt.py",
    REPO_ROOT / "scripts" / "aider_settings.py",
    REPO_ROOT / "scripts" / "opencode_stats.py",
    REPO_ROOT / "scripts" / "prompt_render.py",
)
REPAIR_TEMPLATE = REPO_ROOT / "prompts" / "repair_continuation_template.md"
AUTOMATION_NOTICE = REPO_ROOT / "prompts" / "_shared" / "automation_notice.md"
ANALYZER = REPO_ROOT / "scripts" / "analyze_experiment.py"
# `true` lives in /bin on Linux but /usr/bin on macOS; resolve it instead of
# hardcoding either, so suite fixtures that need a stub binary work on both.
TRUE_BIN = shutil.which("true") or "/usr/bin/true"
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

    def test_distinct_families_at_k(self):
        labels = [0, 0, 1, 1]
        self.assertEqual(dm.distinct_families_at_k(labels, 1), 1.0)
        self.assertAlmostEqual(dm.distinct_families_at_k(labels, 2), 5 / 3)
        self.assertEqual(dm.distinct_families_at_k(labels, 4), 2.0)
        self.assertTrue(
            all(
                dm.distinct_families_at_k([0, 0, 0], k) == 1
                for k in range(1, 4)
            )
        )
        self.assertEqual(
            [dm.distinct_families_at_k(range(4), k) for k in range(1, 5)],
            [1, 2, 3, 4],
        )
        with self.assertRaises(ValueError):
            dm.distinct_families_at_k(labels, 0)
        with self.assertRaises(ValueError):
            dm.distinct_families_at_k(labels, 5)
        curve = dm.family_discovery_curve(labels)
        self.assertEqual(
            list(curve[0]), ["k", "expected_distinct_families"]
        )

    def test_family_discovery_auc_fixed_budget(self):
        self.assertEqual(dm.normalized_family_discovery_auc([1, 1, 1, 1]), 1.0)
        self.assertEqual(dm.normalized_family_discovery_auc([1, 2, 3, 4]), 2.5)
        curve = dm.family_discovery_curve([0, 1, 2, 3])
        summary = dm.family_discovery_auc_summary(curve, 3)
        self.assertEqual(summary["family_discovery_auc_at_kmax"], 2.0)
        insufficient = dm.family_discovery_auc_summary(curve[:2], 3)
        self.assertIsNone(insufficient["family_discovery_auc_at_kmax"])
        self.assertIn(
            "smaller", insufficient["family_discovery_auc_at_kmax_reason"]
        )

    def test_exact_repetition(self):
        result = dm.exact_repetition_summary(["A", "A", "B", "C"])
        self.assertEqual(result["exact_unique_rate"], 0.75)
        self.assertEqual(result["exact_modal_share"], 0.5)

    def test_vendi(self):
        np = pytest.importorskip("numpy")
        self.assertEqual(dm.vendi_score(np.array([[1.0, 0.0]])), 1.0)
        self.assertAlmostEqual(dm.vendi_score(np.array([[1.0, 0.0], [1.0, 0.0]])), 1.0)
        self.assertAlmostEqual(dm.vendi_score(np.eye(4)), 4.0)
        self.assertEqual(dm.vendi_score(np.array([[0.0, 0.0]])), 1.0)
        self.assertEqual(dm.vendi_score(np.zeros((1, 0))), 1.0)
        self.assertAlmostEqual(
            dm.vendi_score(np.array([[0.0, 0.0], [0.0, 0.0]])), 1.0
        )
        self.assertAlmostEqual(
            dm.vendi_score(np.array([[0.0, 0.0], [1.0, 0.0]])), 2.0
        )
        self.assertAlmostEqual(
            dm.vendi_score(
                np.array(
                    [[0.0, 0.0], [0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
                )
            ),
            2.0 * 2.0**0.5,
        )
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

    def test_primary_strategy_includes_main_and_excludes_helpers(self):
        module = load_analyzer()
        regex = module.re.compile(module.DEFAULT_STRATEGY_EXCLUDE_REGEX, module.re.I)
        self.assertIsNone(regex.search("main"))
        for name in (
            "parse_args",
            "argument_parser",
            "process_argv",
            "read_options",
            "print_usage",
            "show_help",
            "set_flag",
            "report_error",
            "emit_diagnostic",
        ):
            self.assertIsNotNone(regex.search(name), name)

        baseline_functions = {
            "main": module.FunctionInfo("main", 1, 1, 0, 1, "old", ()),
            "parse_args": module.FunctionInfo(
                "parse_args", 2, 2, 2, 3, "old-parser", ()
            ),
        }
        candidate_functions = {
            "main": module.FunctionInfo("main", 1, 2, 0, 2, "new", ()),
            "parse_args": module.FunctionInfo(
                "parse_args", 3, 3, 3, 4, "new-parser", ()
            ),
        }
        baseline_behavior, _, edited = module.strategy_function_names(
            baseline_functions, candidate_functions, regex, set()
        )
        self.assertEqual(baseline_behavior, {"main"})
        self.assertEqual(edited, {"main"})

        main_delta = module.filter_strategy_delta(
            {"function.main.kind.IfStmt": 1.0},
            baseline_behavior,
            {},
        )
        excluded_delta = module.filter_strategy_delta(
            {"function.main.kind.IfStmt": 1.0},
            baseline_behavior - {"main"},
            {},
        )
        self.assertEqual(main_delta, {"function.main.kind.IfStmt": 1.0})
        self.assertEqual(excluded_delta, {})

        np = pytest.importorskip("numpy")
        module.np = np
        blocks = {
            "unchanged": {"clang": {}, "tree_sitter": {}},
            "changed": {
                "clang": module.split_signed_delta(main_delta, "clang"),
                "tree_sitter": {},
            },
        }
        matrix, _, _ = module.build_feature_matrix(
            ["unchanged", "changed"], blocks, ("clang", "tree_sitter")
        )
        distance = dm.cosine_distance_matrix(matrix)
        self.assertGreater(distance[0, 1], 0.0)

    def test_new_source_main_identity_is_not_helper_canonicalized(self):
        module = load_analyzer()
        regex = module.re.compile(module.DEFAULT_STRATEGY_EXCLUDE_REGEX, module.re.I)

        def function(name: str, start: int) -> object:
            return module.FunctionInfo(name, 1, 1, start, start + 1, name, ())

        candidate_helper_first = {
            "worker_alpha": function("worker_alpha", 0),
            "main": function("main", 100),
            "parse_args": function("parse_args", 200),
        }
        candidate_main_first = {
            "main": function("main", 0),
            "worker_beta": function("worker_beta", 100),
            "parse_options": function("parse_options", 200),
        }
        first_architecture, first_strategy = module.created_function_mapping(
            {}, candidate_helper_first, regex, set()
        )
        second_architecture, second_strategy = module.created_function_mapping(
            {}, candidate_main_first, regex, set()
        )

        self.assertEqual(first_architecture["main"], "main")
        self.assertEqual(first_strategy["main"], "main")
        self.assertEqual(second_architecture["main"], "main")
        self.assertEqual(second_strategy["main"], "main")
        self.assertEqual(
            first_architecture["worker_alpha"], "created_behavior_helper_1"
        )
        self.assertEqual(
            second_architecture["worker_beta"], "created_behavior_helper_1"
        )
        self.assertEqual(
            first_architecture["parse_args"], "created_parser_helper_1"
        )
        self.assertEqual(
            second_architecture["parse_options"], "created_parser_helper_1"
        )

        raw_delta = {
            "function.main.kind.CompoundStmt": 1.0,
            "function.worker_alpha.kind.ReturnStmt": 1.0,
        }
        _, created_behavior, _ = module.strategy_function_names(
            {}, candidate_helper_first, regex, set()
        )
        included = module.filter_strategy_delta(
            raw_delta, created_behavior, first_strategy
        )
        self.assertIn("function.main.kind.CompoundStmt", included)

        exclude_main = module.re.compile(r"^main$", module.re.I)
        main_excluded_architecture, main_excluded_strategy = (
            module.created_function_mapping(
                {}, candidate_helper_first, exclude_main, set()
            )
        )
        _, created_without_main, _ = module.strategy_function_names(
            {}, candidate_helper_first, exclude_main, set()
        )
        excluded = module.filter_strategy_delta(
            raw_delta, created_without_main, main_excluded_strategy
        )
        self.assertEqual(main_excluded_architecture["main"], "main")
        self.assertEqual(main_excluded_strategy["main"], "main")
        self.assertNotIn("function.main.kind.CompoundStmt", excluded)
        self.assertIn("function.created_behavior_helper_1.kind.ReturnStmt", excluded)

    def test_distance_and_clustering_have_one_canonical_implementation(self):
        tree = ast.parse(ANALYZER.read_text(encoding="utf-8"))
        local_functions = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        self.assertNotIn("cosine_distance_matrix", local_functions)
        self.assertNotIn("agglomerative_labels", local_functions)
        analyzer_text = ANALYZER.read_text(encoding="utf-8")
        self.assertNotIn("AgglomerativeClustering", analyzer_text)
        self.assertNotIn("silhouette_score", analyzer_text)
        self.assertIn(
            "diversity_metrics.cosine_distance_matrix(\n        architecture_matrix",
            analyzer_text,
        )
        self.assertIn(
            "diversity_metrics.agglomerative_labels(distance, threshold)",
            analyzer_text,
        )

        np = pytest.importorskip("numpy")
        features = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        primary_distance = dm.cosine_distance_matrix(features)
        primary_labels = dm.agglomerative_labels(primary_distance, 0.3)
        with mock.patch.object(
            dm,
            "cosine_distance_matrix",
            wraps=dm.cosine_distance_matrix,
        ) as distance_mock, mock.patch.object(
            dm,
            "agglomerative_labels",
            wraps=dm.agglomerative_labels,
        ) as cluster_mock:
            dm.bootstrap_diversity_ci(features, 0.3, 2, 7)
        self.assertTrue(distance_mock.called)
        self.assertTrue(cluster_mock.called)
        self.assertEqual(
            primary_labels.tolist(),
            dm.agglomerative_labels(primary_distance, 0.3).tolist(),
        )

    def test_representation_ablation_uses_fixed_population_and_threshold(self):
        module = load_analyzer()
        module.np = pytest.importorskip("numpy")
        run_ids = ["a", "b", "c"]
        blocks = {
            "a": {"clang": {"x": 1.0}, "tree_sitter": {"y": 1.0}},
            "b": {"clang": {"x": 1.0}, "tree_sitter": {"z": 1.0}},
            "c": {"clang": {"q": 1.0}, "tree_sitter": {"z": 1.0}},
        }
        without_main_blocks = {
            run_id: {"clang": {}, "tree_sitter": {}} for run_id in run_ids
        }
        rows = module.representation_ablation_rows(
            space_name="strategy",
            population_run_ids=run_ids,
            all_run_ids=run_ids,
            representations=(
                ("clang_only", blocks, ("clang",)),
                ("tree_sitter_only", blocks, ("tree_sitter",)),
                ("clang_plus_tree_sitter", blocks, ("clang", "tree_sitter")),
                (
                    "clang_plus_tree_sitter_without_main",
                    without_main_blocks,
                    ("clang", "tree_sitter"),
                ),
            ),
            primary_representation="clang_plus_tree_sitter",
            threshold=0.37,
        )
        self.assertEqual(
            [row["representation"] for row in rows],
            [
                "clang_only",
                "tree_sitter_only",
                "clang_plus_tree_sitter",
                "clang_plus_tree_sitter_without_main",
            ],
        )
        self.assertEqual({row["population_n"] for row in rows}, {3})
        self.assertEqual({row["threshold_used"] for row in rows}, {0.37})
        primary = next(
            row for row in rows if row["representation"] == "clang_plus_tree_sitter"
        )
        self.assertEqual(primary["adjusted_rand_vs_primary"], 1.0)
        without_main = next(
            row
            for row in rows
            if row["representation"] == "clang_plus_tree_sitter_without_main"
        )
        self.assertNotEqual(
            primary["raw_family_count"], without_main["raw_family_count"]
        )
        self.assertRegex(
            ANALYZER.read_text(encoding="utf-8"),
            r'"clang_plus_tree_sitter_without_main",\s*strategy_without_main_blocks',
        )

        architecture_blocks = {
            run_id: {**run_blocks, "gumtree": {f"g-{run_id}": 1.0}}
            for run_id, run_blocks in blocks.items()
        }
        architecture_rows = module.representation_ablation_rows(
            space_name="architecture",
            population_run_ids=run_ids,
            all_run_ids=run_ids,
            representations=(
                ("clang_only", architecture_blocks, ("clang",)),
                ("tree_sitter_only", architecture_blocks, ("tree_sitter",)),
                ("gumtree_only", architecture_blocks, ("gumtree",)),
                (
                    "clang_plus_tree_sitter",
                    architecture_blocks,
                    ("clang", "tree_sitter"),
                ),
                (
                    "clang_plus_tree_sitter_plus_gumtree",
                    architecture_blocks,
                    ("clang", "tree_sitter", "gumtree"),
                ),
            ),
            primary_representation="clang_plus_tree_sitter_plus_gumtree",
            threshold=0.29,
        )
        self.assertEqual(
            [row["representation"] for row in architecture_rows],
            [
                "clang_only",
                "tree_sitter_only",
                "gumtree_only",
                "clang_plus_tree_sitter",
                "clang_plus_tree_sitter_plus_gumtree",
            ],
        )
        self.assertEqual({row["population_n"] for row in architecture_rows}, {3})
        self.assertEqual({row["threshold_used"] for row in architecture_rows}, {0.29})


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
            "oracle_bin": TRUE_BIN,
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
        f"""\
#!/usr/bin/env bash
set -eu
out=$(python3 config.py "$1" paths.candidate_asan_bin)
cp {TRUE_BIN} "$out"
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
    (repository / "prompts").mkdir(parents=True)
    (repository / "prompts" / "_shared").mkdir()
    (repository / "src").mkdir()
    shutil.copy2(RUNNER, repository / "scripts" / RUNNER.name)
    for helper in RUNNER_HELPERS:
        shutil.copy2(helper, repository / "scripts" / helper.name)
    shutil.copy2(REPAIR_TEMPLATE, repository / "prompts" / REPAIR_TEMPLATE.name)
    shutil.copy2(
        AUTOMATION_NOTICE,
        repository / "prompts" / "_shared" / AUTOMATION_NOTICE.name,
    )
    (repository / "scripts" / "analyze_experiment.py").write_text(
        """\
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--experiment", type=Path, required=True)
args, _ = parser.parse_known_args()
(args.experiment / "analysis").mkdir(exist_ok=True)
(args.experiment / "analysis" / "AUTOMATIC").write_text("ran\\n")
(args.experiment / "analysis" / "ARGS.json").write_text(
    __import__("json").dumps(__import__("sys").argv[1:])
)
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

    fake_aider = tmp_path / "fake-aider"
    fake_aider.write_text(
        """\
#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

if "--version" in sys.argv:
    print("aider 0.test")
    raise SystemExit(0)

fixture_root = Path(__file__).parent
counter = fixture_root / "counter.txt"
invocation = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(invocation + 1))
with (fixture_root / "aider-args.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
prompt_file = Path(sys.argv[sys.argv.index("--message-file") + 1])
prompt = prompt_file.read_text(encoding="utf-8")
with (fixture_root / "prompts.txt").open("a", encoding="utf-8") as handle:
    handle.write(f"\\n===== PROMPT {invocation} =====\\n{prompt}\\n")
worktree = Path.cwd()
# Aider is run with --no-git and GIT_CEILING_DIRECTORIES at the workdir.
# Record that ordinary Git discovery cannot reach the surrounding repository.
(fixture_root / "sandbox-root.txt").write_text(
    subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    ).stdout.strip()
)
scenario = (fixture_root / "scenario.txt").read_text(encoding="utf-8")
source = worktree / sys.argv[sys.argv.index("--file") + 1]
(fixture_root / "source-preexisted.txt").write_text(str(source.exists()).lower())
if (scenario == "repair-success" and invocation > 0) or scenario in {"valid", "permission"}:
    value = "repaired"
else:
    value = "broken"
source.parent.mkdir(parents=True, exist_ok=True)
source.write_text(value + "\\n")
print(json.dumps({"total_tokens": invocation + 10}))
if scenario in {"agent-error", "infrastructure-failure"}:
    raise SystemExit(42)
if scenario == "timeout":
    raise SystemExit(124)
if scenario == "permission":
    print("permission requested: external_directory")
""",
        encoding="utf-8",
    )
    fake_aider.chmod(0o755)
    return repository, fake_aider


def run_experiment(
    tmp_path: Path,
    *,
    scenario: str,
    max_loops: int | str | None,
    extra_test_cmd: str = 'printf x >> "$EXTRA_COUNT"',
    source_mode: str = "existing",
    source_path: str = "src/tool.c",
    base_test_cmd: str = "true",
    analysis_args: list[str] | None = None,
    extra_args: list[str] | None = None,
    temperature: str | None = "0",
    runs: int = 1,
) -> tuple[Path, subprocess.CompletedProcess[str], int, str]:
    repository, fake_aider = initialize_experiment_repo(tmp_path)
    counter = tmp_path / "counter.txt"
    prompts = tmp_path / "prompts.txt"
    extra_count = tmp_path / "extra-count.txt"
    sweep = repository / "runs" / "experiment"
    command = [
        "bash",
        str(repository / "scripts" / RUNNER.name),
        "--model",
        "fake/model",
        *(["--temperature", temperature] if temperature is not None else []),
        "--runs",
        str(runs),
        "--prompt",
        "prompt.md",
        "--source",
        source_path,
        "--source-mode",
        source_mode,
        "--output-dir",
        str(sweep),
        "--build-cmd",
        f"if test \"$(tr -d '\\n' < {source_path})\" = repaired; then exit 0; else echo broken-build; exit 1; fi",
        "--base-test-cmd",
        base_test_cmd,
        "--feature-test-cmd",
        "true",
        "--extra-test-cmd",
        extra_test_cmd,
        "--timeout",
        "0",
    ]
    # `existing` mode now seeds the workspace from a file rather than from a
    # baseline commit; the seed matching --source is also the analysis baseline.
    if source_mode == "existing":
        command.extend(["--seed-file", source_path])
    if max_loops is not None:
        command.extend(["--max-loops", str(max_loops)])
    if analysis_args:
        command.extend(analysis_args)
    if extra_args:
        command.extend(extra_args)

    environment = os.environ.copy()
    (tmp_path / "scenario.txt").write_text(scenario, encoding="utf-8")
    environment.update(
        {
            "AIDER_BIN": str(fake_aider),
            "PYTHON_BIN": sys.executable,
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
    invocations = int(counter.read_text()) if counter.exists() else 0
    # --output-dir is the sweep root; each temperature is its own experiment.
    output = sweep / "temp-0p0"
    prompt_text = prompts.read_text(encoding="utf-8") if prompts.is_file() else ""
    return output, result, invocations, prompt_text


def test_temp_list_runs_an_unequally_spaced_grid(tmp_path: Path):
    """--temp-list covers grids --temp-points cannot express.

    A doubling grid like 0, 0.125, 0.25, 0.5, 1, 2 is not equally spaced, so
    without this it takes one runner invocation per point and each one
    overwrites the previous sweep.json.
    """
    _, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="valid",
        max_loops=0,
        temperature=None,
        extra_args=["--temp-list", "0.0,0.125,0.25,0.5,1.0,2.0", "--no-analysis"],
    )

    assert result.returncode == 0, result.stderr
    sweep = tmp_path / "repository" / "runs" / "experiment"
    produced = sorted(path.name for path in sweep.glob("temp-*"))
    assert produced == [
        "temp-0p0",
        "temp-0p125",
        "temp-0p25",
        "temp-0p5",
        "temp-1p0",
        "temp-2p0",
    ]
    # One attempt per point, and a single sweep manifest describing all of them.
    assert invocations == 6
    manifest = json.loads((sweep / "sweep.json").read_text())
    assert manifest["temp_list"] == "0.0,0.125,0.25,0.5,1.0,2.0"
    assert manifest["temp_points"] == 6
    for point, directory in zip(
        [0.0, 0.125, 0.25, 0.5, 1.0, 2.0], produced, strict=True
    ):
        experiment = json.loads((sweep / directory / "experiment.json").read_text())
        assert experiment["temperature"] == point


def test_aider_cannot_discover_the_parent_repository(tmp_path: Path):
    """Git discovery is cut off before the surrounding checkout."""
    output, result, _, _ = run_experiment(
        tmp_path,
        scenario="valid",
        max_loops=0,
    )

    assert result.returncode == 0, result.stderr
    observed = (tmp_path / "sandbox-root.txt").read_text().strip()
    assert observed == "", f"Aider could discover parent repository {observed}"
    workdir = output / "attempt-001" / "workdir"
    assert not workdir.exists()
    assert not (output / "attempt-001" / "candidate" / ".git").exists()


def test_kept_workdir_drops_the_sandbox_marker(tmp_path: Path):
    """--keep-workdir keeps the tree for inspection but not the marker repo."""
    output, result, _, _ = run_experiment(
        tmp_path,
        scenario="valid",
        max_loops=0,
        extra_args=["--keep-workdir"],
    )

    assert result.returncode == 0, result.stderr
    workdir = output / "attempt-001" / "workdir"
    assert workdir.is_dir()
    assert not (workdir / ".git").exists()


def test_attempt_records_aider_model_settings(tmp_path: Path):
    """Both role-specific inference configurations are durable and hashed."""
    output, result, _, _ = run_experiment(
        tmp_path,
        scenario="valid",
        max_loops=0,
    )

    assert result.returncode == 0, result.stderr
    attempt = output / "attempt-001"
    settings = json.loads((attempt / "aider-model-settings.yml").read_text())
    metadata = json.loads((attempt / "metadata.json").read_text())
    assert settings[0]["name"] == "fake/model"
    assert settings[0]["extra_params"]["temperature"] == 0
    assert settings[1]["name"] == "ollama_chat/qwen3-coder-next:latest"
    assert settings[1]["extra_params"] == {"temperature": 0.0, "seed": 0}
    assert metadata["aider_model_settings"] == settings
    assert metadata["aider_model_settings_sha256"] == (
        attempt / "aider-model-settings.sha256"
    ).read_text().strip()
    assert metadata["agent_backend"] == "aider"
    assert metadata["aider_version"] == "aider 0.test"
    assert metadata["architect_model"] == "fake/model"
    assert metadata["editor_model"] == "ollama_chat/qwen3-coder-next:latest"
    assert metadata["architect_mode"] is True
    assert (attempt / "aider.log").is_file()
    assert not (attempt / "opencode.log").exists()


def test_aider_invocation_is_one_shot_scoped_and_noninteractive(tmp_path: Path):
    _, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="valid",
        max_loops=0,
        extra_args=["--editor-model", "fixed/editor"],
    )

    assert result.returncode == 0, result.stderr
    assert invocations == 1
    args = json.loads((tmp_path / "aider-args.jsonl").read_text().splitlines()[0])
    for flag in (
        "--architect", "--auto-accept-architect", "--message-file", "--file",
        "--no-git", "--no-auto-commits", "--no-dirty-commits",
        "--no-auto-lint", "--no-auto-test", "--no-suggest-shell-commands",
        "--no-analytics", "--no-check-update", "--no-show-release-notes",
    ):
        assert flag in args
    assert args[args.index("--model") + 1] == "fake/model"
    assert args[args.index("--editor-model") + 1] == "fixed/editor"
    assert "--yes-always" not in args
    assert "--test" not in args


def test_default_max_loops_allows_repair(tmp_path: Path):
    """The controller repairs by default; --max-loops 0 opts out."""
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="always-fail",
        max_loops=None,
    )

    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert json.loads((output / "experiment.json").read_text())["max_loops"] == 3
    # The fake agent rewrites the same failing source every time, so the
    # controller stops early rather than spending the whole budget.
    assert metadata["stop_reason"] == "no_progress"
    assert invocations == 2
    assert metadata["repair_loops"] == 1
    assert metadata["llm_invocations"] == 2
    assert metadata["loop_limit_reached"] is False


def test_max_loops_zero_is_one_shot(tmp_path: Path):
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="always-fail",
        max_loops=0,
    )

    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert json.loads((output / "experiment.json").read_text())["max_loops"] == 0
    assert invocations == 1
    assert metadata["repair_loops"] == 0
    assert metadata["llm_invocations"] == 1
    assert metadata["stop_reason"] == "loop_limit"
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
    # Sources are captured flattened to their basename.
    assert (attempt / "candidate" / "tool.c").read_text() == "repaired\n"
    assert "tool.c" in (attempt / "changed-files.txt").read_text()
    assert "LLM INVOCATION 0: INITIAL" in (attempt / "aider.log").read_text()
    assert "LLM INVOCATION 1: REPAIR LOOP 1" in (attempt / "aider.log").read_text()
    assert "VALIDATION LOOP 0" in (attempt / "build.log").read_text()
    assert "VALIDATION LOOP 1" in (attempt / "build.log").read_text()
    assert "Continue the current implementation" in prompts
    assert "broken-build" in prompts
    # The rendered continuation prompt is kept for reproducibility.
    assert (attempt / "repair-prompt-1.md").exists()
    assert "broken-build" in (attempt / "repair-prompt-1.md").read_text()
    assert (tmp_path / "extra-count.txt").read_text() == "x"
    assert (output / "analysis" / "AUTOMATIC").exists()
    # The working directory is reclaimed once the attempt finishes.
    assert not (attempt / "workdir").exists()
    assert metadata["workdir_pruned"] is True
    forbidden = {"loop-001", "repair", "initial", "final", "workdir"}
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
    # The fake agent rewrites identical failing source, which would normally
    # trip the no-progress stop; opt out so the budget itself is exercised.
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="always-fail",
        max_loops=2,
        extra_args=["--allow-no-progress"],
    )

    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert invocations == 3
    assert metadata["repair_loops"] == 2
    assert metadata["llm_invocations"] == 3
    assert metadata["success_loop"] is None
    assert metadata["stop_reason"] == "loop_limit"
    assert metadata["loop_limit_reached"] is True
    assert metadata["public_validation_success"] is False
    assert len(metadata["loops"]) == 3


def test_aider_error_is_failed_valid_agent_trial(tmp_path: Path):
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="agent-error",
        max_loops=3,
    )

    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert invocations == 1
    assert metadata["agent_exit_code"] == 42
    assert metadata["repair_loops"] == 0
    assert metadata["loop_limit_reached"] is False
    assert metadata["overall_success"] is False
    assert metadata["infrastructure_failure"] is False
    assert metadata["infrastructure_failure_stage"] is None
    assert metadata["agent_execution_failure"] is True
    assert metadata["agent_execution_failure_stage"] == "aider"


def test_timeout_is_failed_valid_agent_trial(tmp_path: Path):
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="timeout",
        max_loops=3,
    )
    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    # The timed-out initial invocation left a candidate. The controller
    # independently validates it, then permits one repair invocation before
    # the unchanged candidate triggers the existing no-progress guard.
    assert invocations == 2
    assert metadata["agent_exit_code"] == 124
    assert metadata["initial_agent_exit_code"] == 124
    assert metadata["initial_session_completed"] is False
    assert metadata["candidate_available_after_timeout"] is True
    assert metadata["validation_completed_after_timeout"] is True
    assert metadata["infrastructure_failure"] is False
    assert metadata["agent_execution_failure"] is False
    assert metadata["agent_execution_failure_stage"] is None
    assert metadata["repair_eligible"] is True
    assert metadata["repair_eligibility_reason"] == (
        "controller_validation_after_timeout"
    )
    assert metadata["repair_loops"] == 1
    assert metadata["stop_reason"] == "no_progress"
    assert metadata["loop_limit_reached"] is False
    assert metadata["initial_success"] is False
    assert metadata["public_validation_success"] is False
    assert metadata["overall_success"] is False


def test_aider_log_text_cannot_create_an_opencode_permission_failure(tmp_path: Path):
    output, result, invocations, _ = run_experiment(
        tmp_path,
        scenario="permission",
        max_loops=3,
    )
    assert result.returncode == 0, result.stderr
    metadata = json.loads(
        (output / "attempt-001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert invocations == 1
    assert metadata["infrastructure_failure"] is False
    assert metadata["infrastructure_failure_stage"] is None
    assert metadata["agent_execution_failure"] is False
    assert metadata["agent_execution_failure_stage"] is None
    assert metadata["loop_limit_reached"] is False
    assert metadata["initial_success"] is True
    assert metadata["public_validation_success"] is True
    assert metadata["overall_success"] is True


def test_candidate_validation_failures_are_not_infrastructure(tmp_path: Path):
    build_output, result, _, _ = run_experiment(
        tmp_path / "build",
        scenario="always-fail",
        max_loops=0,
    )
    assert result.returncode == 0, result.stderr
    build_metadata = json.loads(
        (build_output / "attempt-001" / "metadata.json").read_text()
    )
    assert build_metadata["build_exit_code"] != 0
    assert build_metadata["infrastructure_failure"] is False
    assert build_metadata["agent_execution_failure"] is False

    public_output, result, _, _ = run_experiment(
        tmp_path / "public",
        scenario="valid",
        max_loops=0,
        base_test_cmd="false",
    )
    assert result.returncode == 0, result.stderr
    public_metadata = json.loads(
        (public_output / "attempt-001" / "metadata.json").read_text()
    )
    assert public_metadata["base_test_exit_code"] != 0
    assert public_metadata["infrastructure_failure"] is False
    assert public_metadata["agent_execution_failure"] is False

    hidden_output, result, _, _ = run_experiment(
        tmp_path / "hidden",
        scenario="valid",
        max_loops=0,
        extra_test_cmd="false",
    )
    assert result.returncode == 0, result.stderr
    hidden_metadata = json.loads(
        (hidden_output / "attempt-001" / "metadata.json").read_text()
    )
    assert hidden_metadata["extra_test_exit_code"] != 0
    assert hidden_metadata["infrastructure_failure"] is False
    assert hidden_metadata["agent_execution_failure"] is False


def test_visible_test_tampering_is_recorded_and_preserved(tmp_path: Path):
    """Every prompt forbids editing the visible tests.

    The per-attempt copies are deleted to reclaim space, so the integrity
    record and the preserved files are the only remaining evidence that the
    instruction was violated.
    """
    repository, fake_aider = initialize_experiment_repo(tmp_path)
    suite = repository / "tests" / "suite"
    suite.mkdir(parents=True)
    (suite / "check.py").write_text("assert True\n", encoding="utf-8")
    (suite / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")

    tampering_agent = tmp_path / "tampering-aider"
    tampering_agent.write_text(
        """\
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

if "--version" in sys.argv:
    print("aider 0.test")
    raise SystemExit(0)
workdir = Path.cwd()
source = workdir / sys.argv[sys.argv.index("--file") + 1]
source.parent.mkdir(parents=True, exist_ok=True)
source.write_text("repaired\\n")
# Weaken one visible test and smuggle in another file.
(workdir / "tests" / "suite" / "check.py").write_text("pass\\n")
(workdir / "tests" / "suite" / "EXTRA.txt").write_text("bypass\\n")
""",
        encoding="utf-8",
    )
    tampering_agent.chmod(0o755)

    sweep = repository / "runs" / "tamper"
    result = subprocess.run(
        [
            "bash",
            str(repository / "scripts" / RUNNER.name),
            "--model", "fake/model",
            "--temperature", "0",
            "--runs", "1",
            "--max-loops", "0",
            "--timeout", "0",
            "--prompt", "prompt.md",
            "--source", "src/tool.c",
            "--source-mode", "new",
            "--test-dir", "tests/suite",
            "--output-dir", str(sweep),
            "--feature-test-cmd", "true",
        ],
        cwd=repository,
        env={
            **os.environ,
            "AIDER_BIN": str(tampering_agent),
            "PYTHON_BIN": sys.executable,
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    attempt = sweep / "temp-0p0" / "attempt-001"
    metadata = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
    integrity = metadata["test_dir_integrity"]
    assert integrity["clean"] is False
    assert integrity["tampered_file_count"] == 2
    directory = integrity["directories"]["tests/suite"]
    assert directory["modified"] == ["check.py"]
    assert directory["added"] == ["EXTRA.txt"]
    assert directory["deleted"] == []

    # The touched files survive; the untouched bulk of the suite does not.
    preserved = attempt / "tampered-tests" / "tests" / "suite"
    assert (preserved / "check.py").read_text() == "pass\n"
    assert (preserved / "EXTRA.txt").read_text() == "bypass\n"
    assert not (preserved / "helper.py").exists()
    assert not (attempt / "workdir").exists()


def test_runner_existing_and_new_source_modes(tmp_path: Path):
    existing_output, result, _, _ = run_experiment(
        tmp_path / "existing",
        scenario="valid",
        max_loops=0,
    )
    assert result.returncode == 0, result.stderr
    existing = json.loads((existing_output / "experiment.json").read_text())
    assert existing["source_mode"] == "existing"
    assert existing["baseline_source_kind"] == "existing_source_snapshot"
    # Baseline and candidates share the flattened source name.
    assert existing["source_path"] == "tool.c"
    assert existing["source_workdir_path"] == "src/tool.c"
    assert (existing_output / "baseline" / "tool.c").read_text() == "baseline\n"

    new_output, result, _, _ = run_experiment(
        tmp_path / "new",
        scenario="valid",
        max_loops=0,
        source_mode="new",
        source_path="src/new_tool.c",
    )
    assert result.returncode == 0, result.stderr
    experiment = json.loads((new_output / "experiment.json").read_text())
    attempt = new_output / "attempt-001"
    assert experiment["source_mode"] == "new"
    assert experiment["baseline_source_kind"] == "empty_new_source"
    assert (new_output / "baseline" / "new_tool.c").read_bytes() == b""
    # Aider needs the sole editable path to exist, so new mode supplies an
    # empty file while retaining the same empty analysis baseline.
    assert (tmp_path / "new" / "source-preexisted.txt").read_text() == "true"
    assert (attempt / "candidate" / "new_tool.c").read_text() == "repaired\n"
    # An empty baseline exists for new-source mode, so churn is a tracked edit.
    assert "new_tool.c" in (attempt / "diff-numstat.txt").read_text()


@pytest.mark.parametrize(
    "source_mode,source_path,seed_files,expected",
    [
        # `existing` needs a seed for the source; without one there would be no
        # analysis baseline to measure churn against.
        ("existing", "src/tool.c", [], "requires a --seed-file whose destination is"),
        # `new` means from scratch, so seeding the source contradicts it.
        (
            "new",
            "src/tool.c",
            ["src/tool.c"],
            "conflicts with a --seed-file targeting",
        ),
        ("existing", "src/missing.c", ["src/missing.c"], "--seed-file source not found"),
    ],
)
def test_runner_source_mode_rejects_seed_mismatch(
    tmp_path: Path,
    source_mode: str,
    source_path: str,
    seed_files: list[str],
    expected: str,
):
    repository, fake_aider = initialize_experiment_repo(tmp_path)
    seed_arguments: list[str] = []
    for seed in seed_files:
        seed_arguments.extend(["--seed-file", seed])
    result = subprocess.run(
        [
            "bash",
            str(repository / "scripts" / RUNNER.name),
            "--model",
            "fake/model",
            "--temperature",
            "0",
            "--prompt",
            "prompt.md",
            "--source",
            source_path,
            "--source-mode",
            source_mode,
            "--runs",
            "1",
            *seed_arguments,
        ],
        cwd=repository,
        env={
            **os.environ,
            "AIDER_BIN": str(fake_aider),
            "PYTHON_BIN": sys.executable,
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    assert result.returncode == 2
    assert expected in result.stderr


def test_runner_resolves_and_passes_analysis_configuration(tmp_path: Path):
    output, result, _, _ = run_experiment(
        tmp_path,
        scenario="valid",
        max_loops=0,
        analysis_args=[
            "--analysis-threshold",
            "0.41",
            "--analysis-architecture-threshold",
            "0.23",
            "--analysis-diversity-k-max",
            "7",
        ],
    )
    assert result.returncode == 0, result.stderr
    experiment = json.loads((output / "experiment.json").read_text())
    assert experiment["analysis_architecture_threshold"] == 0.23
    assert experiment["analysis_strategy_threshold"] == 0.41
    assert experiment["analysis_diversity_k_max"] == 7
    analyzer_args = json.loads((output / "analysis" / "ARGS.json").read_text())
    assert analyzer_args[analyzer_args.index("--cluster-threshold") + 1] == "0.23"
    assert analyzer_args[analyzer_args.index("--strategy-threshold") + 1] == "0.41"
    assert analyzer_args[analyzer_args.index("--diversity-k-max") + 1] == "7"

    default_output, result, _, _ = run_experiment(
        tmp_path / "default",
        scenario="valid",
        max_loops=0,
        analysis_args=["--analysis-architecture-threshold", "0.27"],
    )
    assert result.returncode == 0, result.stderr
    default_experiment = json.loads((default_output / "experiment.json").read_text())
    assert default_experiment["analysis_architecture_threshold"] == 0.27
    assert default_experiment["analysis_strategy_threshold"] == 0.27
    assert default_experiment["analysis_diversity_k_max"] is None
    default_args = json.loads((default_output / "analysis" / "ARGS.json").read_text())
    assert "--diversity-k-max" not in default_args


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


@pytest.mark.parametrize(
    "option",
    [
        "--source",
        "--source-mode",
        "--analysis-threshold",
        "--analysis-architecture-threshold",
        "--analysis-strategy-threshold",
        "--analysis-diversity-k-max",
    ],
)
def test_new_runner_options_require_values(option: str):
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
            option,
        ],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert f"{option} requires a value" in result.stderr


@pytest.mark.parametrize("source", ["/tmp/tool.c", "../tool.c", "src/../tool.c"])
def test_runner_rejects_unsafe_source_paths(source: str):
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
            "--source",
            source,
            "--source-mode",
            "new",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "AIDER_BIN": "true", "PYTHON_BIN": sys.executable},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "normalized relative path" in result.stderr


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
            "--source",
            "src/new_sort/new_sort.c",
            "--source-mode",
            "new",
            "--max-loops",
            "999999999999999999999999999999999999999",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "AIDER_BIN": "true", "PYTHON_BIN": sys.executable},
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

    aider = analyzer.normalize_repair_metadata(
        {
            "agent_backend": "aider",
            "agent_exit_code": 0,
            "agent_runtime_ms": 150,
            "initial_agent_runtime_ms": 100,
            "repair_agent_runtime_ms": 50,
            "total_agent_runtime_ms": 150,
            "agent_isolation_rejected": False,
            "public_validation_success": True,
            "overall_success": True,
        }
    )
    assert aider["agent_backend"] == "aider"
    assert aider["agent_exit_code"] == 0
    assert aider["total_agent_runtime_ms"] == 150
    assert aider["agent_execution_failure"] is False

    old_setup_failure = analyzer.normalize_repair_metadata(
        {
            "setup_exit_code": 1,
            "public_validation_success": True,
            "overall_success": True,
        }
    )
    assert old_setup_failure["llm_invocations"] == 0
    assert old_setup_failure["loop_limit_reached"] is False
    assert old_setup_failure["infrastructure_failure"] is True
    assert old_setup_failure["infrastructure_failure_stage"] == "setup"
    assert old_setup_failure["infrastructure_failure_classification_inferred"] is True
    assert old_setup_failure["agent_execution_failure"] is False
    assert old_setup_failure["public_validation_success"] is False
    assert old_setup_failure["overall_success"] is False
    new_setup_failure = analyzer.normalize_repair_metadata(
        {
            "setup_exit_code": 1,
            "overall_success": False,
            "infrastructure_failure": True,
            "infrastructure_failure_stage": "setup",
            "infrastructure_failure_classification_inferred": False,
            "agent_execution_failure": False,
            "agent_execution_failure_stage": None,
            "agent_execution_failure_classification_inferred": False,
        }
    )
    assert new_setup_failure["infrastructure_failure"] is True
    assert new_setup_failure["agent_execution_failure"] is False
    assert new_setup_failure["llm_invocations"] == 0

    old_opencode_failure = analyzer.normalize_repair_metadata(
        {
            "opencode_exit_code": 42,
            "overall_success": False,
            "infrastructure_failure": True,
            "infrastructure_failure_stage": "opencode",
        }
    )
    assert old_opencode_failure["infrastructure_failure"] is False
    assert old_opencode_failure["infrastructure_failure_stage"] is None
    assert old_opencode_failure["agent_execution_failure"] is True
    assert old_opencode_failure["agent_execution_failure_stage"] == "opencode"
    assert old_opencode_failure["agent_execution_failure_classification_inferred"] is True
    old_timeout = analyzer.normalize_repair_metadata(
        {"opencode_exit_code": 124, "overall_success": False}
    )
    assert old_timeout["infrastructure_failure"] is False
    assert old_timeout["agent_execution_failure"] is True
    assert old_timeout["agent_execution_failure_stage"] == "timeout"
    old_permission_failure = analyzer.normalize_repair_metadata(
        {
            "opencode_exit_code": 0,
            "opencode_permission_rejected": True,
            "overall_success": False,
            "infrastructure_failure": True,
            "infrastructure_failure_stage": "permission",
        }
    )
    assert old_permission_failure["infrastructure_failure"] is False
    assert old_permission_failure["agent_execution_failure"] is True
    assert old_permission_failure["agent_execution_failure_stage"] == "permission"
    contradictory_timeout = analyzer.normalize_repair_metadata(
        {
            "opencode_exit_code": 124,
            "infrastructure_failure": True,
            "infrastructure_failure_stage": "opencode",
            "agent_execution_failure": False,
            "agent_execution_failure_stage": None,
            "public_validation_success": True,
            "overall_success": True,
        }
    )
    assert contradictory_timeout["infrastructure_failure"] is False
    assert contradictory_timeout["agent_execution_failure"] is True
    assert contradictory_timeout["agent_execution_failure_stage"] == "timeout"
    assert contradictory_timeout["public_validation_success"] is False
    assert contradictory_timeout["overall_success"] is False
    assert (
        contradictory_timeout["agent_execution_failure_classification_inferred"]
        is True
    )
    for candidate_failure in (
        {"opencode_exit_code": 0, "build_exit_code": 1},
        {"opencode_exit_code": 0, "base_test_exit_code": 1},
        {"opencode_exit_code": 0, "extra_test_exit_code": 1},
    ):
        normalized = analyzer.normalize_repair_metadata(candidate_failure)
        assert normalized["infrastructure_failure"] is False


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
    assert summary["repair_eligible_initial_failures"] == 2
    assert summary["recovered_repair_eligible_failures"] == 1
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


def test_repair_recovery_uses_only_repair_eligible_failures(analyzer):
    rows = [
        analyzer.normalize_repair_metadata(
            {
                "initial_success": True,
                "success_loop": 0,
                "public_validation_success": True,
                "overall_success": True,
                "opencode_exit_code": 0,
                "loops": [
                    {
                        "opencode_exit_code": 0,
                        "opencode_permission_rejected": False,
                        "validation_success": True,
                    }
                ],
            }
        ),
        analyzer.normalize_repair_metadata(
            {
                "initial_success": False,
                "repair_loops": 1,
                "success_loop": 1,
                "public_validation_success": True,
                "overall_success": True,
                "opencode_exit_code": 0,
                "loops": [
                    {
                        "opencode_exit_code": 0,
                        "opencode_permission_rejected": False,
                        "validation_success": False,
                    },
                    {
                        "opencode_exit_code": 0,
                        "opencode_permission_rejected": False,
                        "validation_success": True,
                    },
                ],
            }
        ),
        analyzer.normalize_repair_metadata(
            {
                "initial_success": False,
                "repair_loops": 1,
                "success_loop": None,
                "public_validation_success": False,
                "overall_success": False,
                "opencode_exit_code": 0,
                "loops": [
                    {
                        "opencode_exit_code": 0,
                        "opencode_permission_rejected": False,
                        "validation_success": False,
                    },
                    {
                        "opencode_exit_code": 0,
                        "opencode_permission_rejected": False,
                        "validation_success": False,
                    },
                ],
            }
        ),
        analyzer.normalize_repair_metadata(
            {
                "initial_success": False,
                "public_validation_success": False,
                "overall_success": False,
                "opencode_exit_code": 124,
                "loops": [
                    {
                        "opencode_exit_code": 124,
                        "opencode_permission_rejected": False,
                        "validation_success": False,
                    }
                ],
            }
        ),
    ]

    summary = analyzer.build_repair_summary(rows)
    reliability = analyzer.build_reliability_summary(rows)
    intervals = analyzer.build_reliability_wilson_intervals(reliability, summary)

    assert summary["initial_public_success_rate"] == pytest.approx(1 / 4)
    assert summary["final_public_success_rate"] == pytest.approx(2 / 4)
    assert summary["repair_eligible_initial_failures"] == 2
    assert summary["recovered_repair_eligible_failures"] == 1
    assert summary["repair_ineligible_initial_failures"] == 1
    assert summary["repair_ineligible_initial_failure_stages"] == {"timeout": 1}
    assert summary["repair_recovery_rate"] == pytest.approx(1 / 2)
    assert intervals["repair_recovery_rate"]["estimate"] == pytest.approx(1 / 2)
    assert intervals["repair_recovery_rate"]["n"] == 2
    assert analyzer.pass_at_k(4, 2, 1) == pytest.approx(1 / 2)


@pytest.mark.parametrize(
    "failure_metadata, expected_stage",
    [
        (
            {
                "opencode_exit_code": 0,
                "opencode_permission_rejected": True,
                "loops": [
                    {
                        "opencode_exit_code": 0,
                        "opencode_permission_rejected": True,
                    }
                ],
            },
            "permission_rejection",
        ),
        (
            {
                "opencode_exit_code": 42,
                "loops": [
                    {
                        "opencode_exit_code": 42,
                        "opencode_permission_rejected": False,
                    }
                ],
            },
            "opencode_error",
        ),
        (
            {
                "setup_exit_code": 1,
                "infrastructure_failure": True,
                "infrastructure_failure_stage": "setup",
            },
            "infrastructure_failure",
        ),
    ],
)
def test_agent_and_infrastructure_failures_are_not_repair_eligible(
    analyzer, failure_metadata: dict, expected_stage: str
):
    row = analyzer.normalize_repair_metadata(
        {
            "initial_success": False,
            "public_validation_success": False,
            "overall_success": False,
            **failure_metadata,
        }
    )
    summary = analyzer.build_repair_summary([row])

    assert analyzer.initial_agent_invocation_status(row) == expected_stage
    assert summary["repair_eligible_initial_failures"] == 0
    assert summary["recovered_repair_eligible_failures"] == 0
    assert summary["repair_recovery_rate"] is None


def test_completed_generation_with_public_failure_is_repair_eligible(analyzer):
    row = analyzer.normalize_repair_metadata(
        {
            "initial_success": False,
            "public_validation_success": False,
            "overall_success": False,
            "opencode_exit_code": 0,
            "build_exit_code": 1,
            "loops": [
                {
                    "opencode_exit_code": 0,
                    "opencode_permission_rejected": False,
                    "build_exit_code": 1,
                    "validation_success": False,
                }
            ],
        }
    )
    summary = analyzer.build_repair_summary([row])

    assert analyzer.initial_agent_invocation_status(row) == "completed"
    assert summary["repair_eligible_initial_failures"] == 1
    assert summary["recovered_repair_eligible_failures"] == 0
    assert summary["repair_recovery_rate"] == 0.0


def test_loop_zero_success_is_not_a_repair_recovery(analyzer):
    row = analyzer.normalize_repair_metadata(
        {
            "initial_success": False,
            "public_validation_success": True,
            "success_loop": 0,
            "opencode_exit_code": 0,
            "loops": [
                {
                    "opencode_exit_code": 0,
                    "opencode_permission_rejected": False,
                    "validation_success": False,
                }
            ],
        }
    )
    summary = analyzer.build_repair_summary([row])

    assert summary["repair_eligible_initial_failures"] == 1
    assert summary["recovered_repair_eligible_failures"] == 0
    assert summary["repair_recovery_rate"] == 0.0


def test_reliability_denominators_exclude_infrastructure_trials(analyzer):
    rows = [
        analyzer.normalize_repair_metadata(
            {
                "initial_success": True,
                "public_validation_success": True,
                "overall_success": True,
                "infrastructure_failure": False,
            }
        ),
        analyzer.normalize_repair_metadata(
            {
                "initial_success": False,
                "public_validation_success": False,
                "overall_success": False,
                "infrastructure_failure": False,
            }
        ),
        analyzer.normalize_repair_metadata(
            {
                "opencode_exit_code": 124,
                "initial_success": False,
                "public_validation_success": False,
                "overall_success": False,
            }
        ),
        analyzer.normalize_repair_metadata(
            {
                "setup_exit_code": 1,
                "overall_success": False,
                "infrastructure_failure": True,
                "infrastructure_failure_stage": "setup",
            }
        ),
    ]
    reliability = analyzer.build_reliability_summary(rows)
    repair = analyzer.build_repair_summary(rows)
    assert reliability["n_attempts"] == 4
    assert reliability["n_valid_agent_trials"] == 3
    assert reliability["n_infrastructure_failures"] == 1
    assert reliability["n_agent_execution_failures"] == 1
    assert reliability["agent_execution_failure_stages"] == {"timeout": 1}
    assert reliability["infrastructure_attrition_rate"] == pytest.approx(1 / 4)
    assert reliability["end_to_end_success_rate"] == pytest.approx(1 / 4)
    assert reliability["conditional_agent_success_rate"] == pytest.approx(1 / 3)
    assert analyzer.pass_at_k(
        reliability["n_valid_agent_trials"],
        reliability["successful_valid_agent_trials"],
        1,
    ) == pytest.approx(1 / 3)
    assert repair["initial_public_success_rate"] == pytest.approx(1 / 3)
    assert repair["final_public_success_rate"] == pytest.approx(1 / 3)
    assert repair["repair_recovery_rate"] is None

    population = dm.primary_population(
        [
            {"run_id": "success", "overall_success": True, "complete": True},
            {"run_id": "timeout", "overall_success": False, "complete": True},
        ],
        "complete",
    )
    assert population["run_ids"] == ["success"]


def test_analysis_configuration_precedence(analyzer):
    metadata = {
        "analysis_architecture_threshold": 0.25,
        "analysis_strategy_threshold": 0.35,
        "analysis_diversity_k_max": 5,
    }

    inherited = analyzer.resolve_analysis_configuration(
        cli_architecture_threshold=None,
        cli_strategy_threshold=None,
        cli_diversity_k_max=None,
        experiment_metadata=metadata,
        inherit_experiment_metadata=True,
    )
    assert inherited == {
        "architecture_threshold": 0.25,
        "architecture_threshold_source": "experiment_metadata",
        "strategy_threshold": 0.35,
        "strategy_threshold_source": "experiment_metadata",
        "diversity_k_max": 5,
        "diversity_k_max_source": "experiment_metadata",
    }

    cli = analyzer.resolve_analysis_configuration(
        cli_architecture_threshold=0.20,
        cli_strategy_threshold=0.40,
        cli_diversity_k_max=7,
        experiment_metadata=metadata,
        inherit_experiment_metadata=True,
    )
    assert cli["architecture_threshold"] == 0.20
    assert cli["architecture_threshold_source"] == "cli"
    assert cli["strategy_threshold"] == 0.40
    assert cli["strategy_threshold_source"] == "cli"
    assert cli["diversity_k_max"] == 7
    assert cli["diversity_k_max_source"] == "cli"

    defaults = analyzer.resolve_analysis_configuration(
        cli_architecture_threshold=None,
        cli_strategy_threshold=None,
        cli_diversity_k_max=None,
        experiment_metadata={},
        inherit_experiment_metadata=True,
    )
    assert defaults["architecture_threshold"] == 0.30
    assert defaults["architecture_threshold_source"] == "default"
    assert defaults["strategy_threshold"] == 0.30
    assert defaults["strategy_threshold_source"] == "architecture_threshold"
    assert defaults["diversity_k_max"] is None
    assert defaults["diversity_k_max_source"] == "default"

    architecture_fallback = analyzer.resolve_analysis_configuration(
        cli_architecture_threshold=0.27,
        cli_strategy_threshold=None,
        cli_diversity_k_max=None,
        experiment_metadata={},
        inherit_experiment_metadata=True,
    )
    assert architecture_fallback["strategy_threshold"] == 0.27
    assert (
        architecture_fallback["strategy_threshold_source"]
        == "architecture_threshold"
    )


def test_formal_analysis_requires_complete_versioned_configuration(
    analyzer, tmp_path: Path
):
    with pytest.raises(SystemExit, match="formal-analysis requires"):
        analyzer.load_frozen_analysis_configuration(None, {}, formal=True)

    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(SystemExit, match="incomplete"):
        analyzer.load_frozen_analysis_configuration(incomplete, {}, formal=True)

    complete = {
        "schema_version": 1,
        "architecture_threshold": 0.30,
        "strategy_threshold": 0.30,
        "threshold_sensitivity": {"rule": "deterministic_local_grid"},
        "bootstrap_repetitions": 1000,
        "bootstrap_seed": 20260723,
        "strategy_exclusion_regex": analyzer.DEFAULT_STRATEGY_EXCLUDE_REGEX,
        "strategy_include_functions": [],
        "include_main": True,
        "clang_extra_arguments": [],
        "fixed_diversity_k": None,
    }
    path = tmp_path / "formal.json"
    path.write_text(json.dumps(complete), encoding="utf-8")
    assert analyzer.load_frozen_analysis_configuration(
        path, {}, formal=True
    ) == complete
    changed = {**complete, "bootstrap_seed": 17}
    assert analyzer.analysis_configuration_fingerprint(complete) != (
        analyzer.analysis_configuration_fingerprint(changed)
    )


def test_formal_security_configuration_is_separate_required_and_fingerprinted(
    analyzer, tmp_path: Path
):
    with pytest.raises(SystemExit, match="formal RQ3 security analysis requires"):
        analyzer.load_security_configuration(
            None, {}, requested=True, formal=True
        )
    configuration = sd.default_security_configuration()
    path = tmp_path / "security.json"
    path.write_text(json.dumps(configuration), encoding="utf-8")
    assert analyzer.load_security_configuration(
        path, {}, requested=True, formal=True
    ) == configuration
    changed = {**configuration, "unsafe_calls": [*configuration["unsafe_calls"], "demo"]}
    assert sd.security_configuration_fingerprint(configuration) != (
        sd.security_configuration_fingerprint(changed)
    )


def test_lineage_population_paper_row_is_not_a_seven_of_seven_reliability_row(
    analyzer,
):
    population = {
        "run_count": 7,
        "effective_family_count": 3.0,
        "dominant_family_share": 0.4,
        "mean_pairwise_distance": 0.25,
    }
    configuration = {
        "configuration_version": 1,
        "configuration_fingerprint": "a" * 64,
        "architecture_threshold": 0.30,
        "strategy_threshold": 0.30,
        "diversity_k_max": None,
        "strategy_exclude_regex": analyzer.DEFAULT_STRATEGY_EXCLUDE_REGEX,
        "strategy_include_functions": [],
        "strategy_main_included": True,
        "clang_extra_args": [],
        "threshold_sensitivity": {"rule": "deterministic_local_grid"},
        "bootstrap_repetitions": 1000,
        "bootstrap_seed": 20260723,
    }
    summary = {
        "experiment_format": "lineage_population_view",
        "population_size": 7,
        "source_size": {
            "mean_source_line_count": 42.0,
            "median_source_line_count": 41.0,
            "sample_sd_source_line_count": 3.0,
            "source_line_count_cv": 3.0 / 42.0,
            "mean_source_bytes": 900.0,
        },
        "successful_runs": None,
        "analysis_configuration": configuration,
        "clustering": {
            "architecture": {"populations": {"passing_complete_runs": population}},
            "strategy": {"populations": {"passing_complete_runs": population}},
        },
        "pass_at_k": {"pass@1": 1.0, "pass@5": 1.0, "pass@10": 1.0},
        "repair": {
            "initial_public_success_rate": 1.0,
            "final_public_success_rate": 1.0,
            "repair_recovery_rate": 1.0,
        },
        "reliability": {
            "n_attempts": 7,
            "end_to_end_success_rate": 1.0,
            "conditional_agent_success_rate": 1.0,
        },
    }
    rows = [
        {
            "analysis_population_member": True,
            "lines_edited": 100,
            "gumtree_normalized_edit_distance": 1.0,
        }
        for _ in range(7)
    ]
    paper = analyzer.build_paper_metrics_row({}, summary, rows)
    assert paper["Population N"] == 7
    assert paper["N Attempts"] is None
    assert paper["Successful Runs"] is None
    for field in (
        "End-to-End Success Rate",
        "Conditional Agent Success Rate",
        "Initial Public Success Rate",
        "Final Public Success Rate",
        "Repair Recovery Rate",
        "Pass@1",
        "Pass@5",
        "Pass@10",
    ):
        assert paper[field] is None
    descriptive = analyzer.build_paper_descriptive_row({}, summary, rows)
    assert descriptive["Mean Source LOC"] == 42.0
    assert descriptive["Median Source LOC"] == 41.0
    assert descriptive["SD Source LOC"] == 3.0
    assert descriptive["Source LOC CV"] == pytest.approx(3.0 / 42.0)
    assert descriptive["Mean Source Bytes"] == 900.0
    assert descriptive["Mean Lines Edited"] is None
    assert descriptive["Mean Normalized GumTree Edit-Action Magnitude"] is None
    assert descriptive["Maintenance Change Scope"] == (
        "unsupported_for_lineage_population_empty_baseline"
    )


def test_analysis_signature_changes_with_primary_configuration(analyzer):
    base = {
        "architecture_threshold": 0.30,
        "strategy_threshold": 0.35,
        "diversity_k_max": 10,
        "strategy_exclude_regex": analyzer.DEFAULT_STRATEGY_EXCLUDE_REGEX,
        "strategy_include_functions": ["worker"],
        "strategy_main_included": True,
        "clang_extra_args": [],
    }
    signature = analyzer.build_analysis_signature(base)
    assert signature == analyzer.build_analysis_signature(dict(base))
    assert signature["architecture_threshold"] == 0.30
    assert signature["strategy_threshold"] == 0.35
    assert signature["diversity_k_max"] == 10
    assert signature["strategy_exclude_regex"] == analyzer.DEFAULT_STRATEGY_EXCLUDE_REGEX
    assert signature["strategy_include_functions"] == ["worker"]
    assert signature["strategy_main_included"] is True
    assert signature["clang_extra_args"] == []

    for key, value in (
        ("architecture_threshold", 0.25),
        ("strategy_threshold", 0.40),
        ("diversity_k_max", 20),
        ("strategy_exclude_regex", "^parse"),
    ):
        changed = {**base, key: value}
        assert analyzer.build_analysis_signature(changed) != signature

    clang_signature = analyzer.build_analysis_signature(
        {**base, "clang_extra_args": ["-DVALUE=1", "-Iinclude"]}
    )
    assert clang_signature["clang_extra_args"] == ["-DVALUE=1", "-Iinclude"]
    assert clang_signature == analyzer.build_analysis_signature(
        {**base, "clang_extra_args": ["-DVALUE=1", "-Iinclude"]}
    )
    assert clang_signature != analyzer.build_analysis_signature(
        {**base, "clang_extra_args": ["-Iinclude", "-DVALUE=1"]}
    )


@pytest.mark.parametrize(
    "setting, value",
    [
        ("architecture_threshold", 0.25),
        ("strategy_threshold", 0.25),
        ("diversity_k_max", 7),
        ("strategy_exclude_regex", "^parse"),
        ("strategy_include_functions", ["worker"]),
        ("strategy_main_included", False),
        ("clang_extra_args", ["-DVALUE=1"]),
    ],
)
def test_confirmatory_configuration_matches_recorded_primary_settings(
    analyzer, setting: str, value: object
):
    experiment = {
        "analysis_architecture_threshold": 0.30,
        "analysis_strategy_threshold": 0.30,
        "analysis_diversity_k_max": 10,
    }
    configuration = {
        "architecture_threshold": 0.30,
        "strategy_threshold": 0.30,
        "diversity_k_max": 10,
        "strategy_exclude_regex": analyzer.DEFAULT_STRATEGY_EXCLUDE_REGEX,
        "strategy_include_functions": [],
        "strategy_main_included": True,
        "clang_extra_args": [],
    }

    matches, mismatches = analyzer.confirmatory_configuration_status(
        experiment, configuration
    )
    assert matches is True
    assert mismatches == []

    matches, mismatches = analyzer.confirmatory_configuration_status(
        experiment, {**configuration, setting: value}
    )
    assert matches is False
    assert [mismatch["setting"] for mismatch in mismatches] == [setting]


def test_schema_v7_aggregate_skips_older_rows(analyzer, tmp_path: Path, capsys):
    root = tmp_path / "repository"
    exploratory_path = root / "runs" / "experiments" / "a-exploratory" / "analysis"
    base_path = root / "runs" / "experiments" / "b-base" / "analysis"
    match_path = root / "runs" / "experiments" / "c-match" / "analysis"
    threshold_path = root / "runs" / "experiments" / "d-threshold" / "analysis"
    k_path = root / "runs" / "experiments" / "e-k" / "analysis"
    old_path = root / "runs" / "experiments" / "z-old" / "analysis"
    old_analyzer_path = (
        root / "runs" / "experiments" / "y-old-analyzer" / "analysis"
    )
    malformed_path = root / "runs" / "experiments" / "malformed" / "analysis"
    exploratory_path.mkdir(parents=True)
    base_path.mkdir(parents=True)
    match_path.mkdir(parents=True)
    threshold_path.mkdir(parents=True)
    k_path.mkdir(parents=True)
    old_path.mkdir(parents=True)
    old_analyzer_path.mkdir(parents=True)
    malformed_path.mkdir(parents=True)
    common = {"Issue": "sort", "Checkpoint": "base", "Model": "m", "Temp": 0}
    (old_path / "paper_metrics_row.json").write_text(
        json.dumps({**common, "_schema_version": 4}), encoding="utf-8"
    )
    valid_row = {column: None for column in analyzer.PAPER_METRICS_COLUMNS}
    valid_row.update(common)
    signature = analyzer.build_analysis_signature(
        {
            "architecture_threshold": 0.30,
            "strategy_threshold": 0.35,
            "diversity_k_max": 10,
            "strategy_exclude_regex": analyzer.DEFAULT_STRATEGY_EXCLUDE_REGEX,
            "strategy_include_functions": [],
            "strategy_main_included": True,
            "clang_extra_args": [],
        }
    )

    def write_row(
        path: Path,
        checkpoint: str,
        row_signature: dict,
        *,
        confirmatory: bool = True,
    ) -> None:
        (path / "paper_metrics_row.json").write_text(
            json.dumps(
                {
                    **valid_row,
                    "Checkpoint": checkpoint,
                    "_schema_version": 7,
                    "_analyzer_version": "5.2.0",
                    "_analysis_signature": row_signature,
                    "_confirmatory_configuration_match": confirmatory,
                    "_confirmatory_configuration_mismatches": (
                        [] if confirmatory else [{"setting": "architecture_threshold"}]
                    ),
                }
            ),
            encoding="utf-8",
        )

    write_row(
        exploratory_path,
        "exploratory",
        {**signature, "architecture_threshold": 0.25},
        confirmatory=False,
    )
    write_row(base_path, "base", signature)
    write_row(match_path, "match", dict(signature))
    write_row(
        threshold_path,
        "threshold",
        {**signature, "architecture_threshold": 0.25},
    )
    write_row(k_path, "k", {**signature, "diversity_k_max": 20})
    (old_analyzer_path / "paper_metrics_row.json").write_text(
        json.dumps(
            {
                **valid_row,
                "Checkpoint": "old-analyzer",
                "_schema_version": 7,
                "_analyzer_version": "4.9.9",
                "_analysis_signature": signature,
                "_confirmatory_configuration_match": True,
            }
        ),
        encoding="utf-8",
    )
    (malformed_path / "paper_metrics_row.json").write_text(
        json.dumps(
            {
                **common,
                "_schema_version": 7,
                "_analyzer_version": "5.2.0",
            }
        ),
        encoding="utf-8",
    )
    aggregate_metadata = analyzer.rebuild_paper_metrics_aggregate(root)
    aggregate = json.loads(
        (root / "runs" / "experiments" / "paper_metrics.json").read_text()
    )
    assert len(aggregate) == 2
    assert {row["Checkpoint"] for row in aggregate} == {"base", "match"}
    assert aggregate_metadata == json.loads(
        (
            root
            / "runs"
            / "experiments"
            / "paper_metrics_metadata.json"
        ).read_text()
    )
    assert aggregate_metadata["included_rows"] == 2
    assert aggregate_metadata["skipped_old_rows"] == 3
    assert aggregate_metadata["skipped_nonconfirmatory_rows"] == 1
    assert aggregate_metadata["skipped_configuration_mismatch_rows"] == 2
    assert aggregate_metadata["analysis_signature"] == signature
    output = capsys.readouterr().out
    assert "skipped 3 older/incompatible rows" in output
    assert "skipped 1 exploratory/nonconfirmatory rows" in output
    assert "skipped 2 rows with incompatible confirmatory configuration" in output


def test_schema_v7_paper_columns(analyzer):
    assert analyzer.ANALYZER_VERSION == "5.2.0"
    assert analyzer.PAPER_SCHEMA_VERSION == 7
    assert "Exact Unique Rate" not in analyzer.PAPER_METRICS_COLUMNS
    assert "Exact Modal Share" not in analyzer.PAPER_METRICS_COLUMNS
    assert "Exact Unique Rate" in analyzer.PAPER_DESCRIPTIVE_COLUMNS
    assert "Exact Modal Share" in analyzer.PAPER_DESCRIPTIVE_COLUMNS
    assert (
        "Mean Normalized GumTree Edit-Action Magnitude"
        in analyzer.PAPER_DESCRIPTIVE_COLUMNS
    )
    assert "Architecture Family-Discovery AUC@K" not in analyzer.PAPER_METRICS_COLUMNS
    assert "Strategy Family-Discovery AUC@K" not in analyzer.PAPER_METRICS_COLUMNS
    assert "Mean Pairwise Architecture Distance" in analyzer.PAPER_METRICS_COLUMNS
    assert "Mean Pairwise Strategy Distance" in analyzer.PAPER_METRICS_COLUMNS
    assert "Architecture Family-Discovery AUC@K" in analyzer.PAPER_DESCRIPTIVE_COLUMNS
    for column in (
        "Mean Source LOC",
        "Median Source LOC",
        "SD Source LOC",
        "Source LOC CV",
        "Mean Source Bytes",
    ):
        assert column in analyzer.PAPER_DESCRIPTIVE_COLUMNS
    public_text = (
        ANALYZER.read_text(encoding="utf-8")
        + (REPO_ROOT / "scripts" / "analysis" / "diversity_metrics.py").read_text(
            encoding="utf-8"
        )
    )
    assert "Diversity Awareness" not in public_text


def test_source_line_count_and_descriptors_are_physical_and_baseline_independent(
    analyzer, tmp_path: Path
):
    source = tmp_path / "candidate.c"
    source.write_text("// comment\n\nint main(void) { return 0; }\n", encoding="utf-8")
    assert analyzer.source_physical_line_count(source) == 3

    summary = analyzer.build_source_size_summary(
        [
            {
                "overall_success": True,
                "source_line_count": 1,
                "source_bytes": 10,
                "lines_edited": 999,
            },
            {
                "overall_success": True,
                "source_line_count": 3,
                "source_bytes": 30,
                "lines_edited": 0,
            },
            {
                "overall_success": False,
                "source_line_count": 100,
                "source_bytes": 1000,
            },
        ],
        "overall_success",
    )
    assert summary["population_n"] == 2
    assert summary["mean_source_line_count"] == 2.0
    assert summary["median_source_line_count"] == 2.0
    assert summary["sample_sd_source_line_count"] == pytest.approx(2 ** 0.5)
    assert summary["source_line_count_cv"] == pytest.approx(2 ** 0.5 / 2)
    assert summary["mean_source_bytes"] == 20.0
    assert "blank and comment lines included" in summary[
        "source_line_count_definition"
    ]


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
                "analysis_architecture_threshold": 0.25,
                "analysis_strategy_threshold": 0.35,
                "analysis_diversity_k_max": 5,
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
    assert summary["schema_version"] == 7
    assert summary["analyzer_version"] == "5.2.0"
    assert summary["analysis_configuration"]["architecture_threshold"] == 0.25
    assert (
        summary["analysis_configuration"]["architecture_threshold_source"]
        == "experiment_metadata"
    )
    assert summary["analysis_configuration"]["strategy_threshold"] == 0.35
    assert (
        summary["analysis_configuration"]["strategy_threshold_source"]
        == "experiment_metadata"
    )
    assert summary["analysis_configuration"]["diversity_k_max"] == 5
    assert (
        summary["analysis_configuration"]["diversity_k_max_source"]
        == "experiment_metadata"
    )
    assert summary["analysis_configuration"]["clang_extra_args"] == []
    assert summary["pass_at_k"]["pass@1"] == pytest.approx(0.5)
    assert summary["repair"]["initial_public_success_rate"] == pytest.approx(0.5)
    assert summary["repair"]["final_public_success_rate"] == 1.0
    assert summary["repair"]["mean_llm_invocations"] == 2.0
    assert summary["successful_runs"] == 1
    assert summary["source_size"]["population_n"] == 1
    assert summary["source_size"]["mean_source_line_count"] == 1.0
    assert summary["source_size"]["median_source_line_count"] == 1.0
    assert summary["source_size"]["sample_sd_source_line_count"] is None
    assert summary["source_size"]["source_line_count_cv"] is None
    assert summary["source_size"]["mean_source_bytes"] == len(
        baseline_source.encode("utf-8")
    )
    assert summary["exact_generation_convergence"]["exact_unique_rate"] == 1.0
    assert summary["clustering"]["primary_population"] == {
        "architecture": "passing_complete_runs",
        "strategy": "passing_complete_runs",
    }
    for relative in (
        "runs.csv",
        "paper_metrics.csv",
        "paper_descriptive_metrics.csv",
        "diversity/architecture_family_discovery_curve.csv",
        "diversity/strategy_family_discovery_curve.csv",
        "diversity/exact_repetition.csv",
        "diagnostics/uncertainty.csv",
    ):
        assert (experiment / "analysis" / relative).exists()
    primary_header = (experiment / "analysis" / "paper_metrics.csv").read_text().splitlines()[0]
    assert "Mean LLM Total Tokens" not in primary_header
    assert "entropy" not in primary_header.lower()
    assert "singleton" not in primary_header.lower()
    assert "Exact Unique Rate" not in primary_header
    descriptive_header = (
        experiment / "analysis" / "paper_descriptive_metrics.csv"
    ).read_text().splitlines()[0]
    assert "Exact Unique Rate" in descriptive_header
    assert "Mean Source LOC" in descriptive_header
    assert "Mean Source Bytes" in descriptive_header
    assert "Mean Normalized GumTree Edit-Action Magnitude" in descriptive_header
    paper_row = json.loads(
        (experiment / "analysis" / "paper_metrics_row.json").read_text()
    )
    assert paper_row["_schema_version"] == 7
    assert paper_row["_analyzer_version"] == "5.2.0"
    assert paper_row["_confirmatory_configuration_match"] is False
    assert paper_row["_confirmatory_configuration_mismatches"][0]["setting"] == (
        "formal_analysis_configuration"
    )
    expected_signature_subset = {
        "architecture_threshold": 0.25,
        "strategy_threshold": 0.35,
        "diversity_k_max": 5,
        "strategy_exclude_regex": load_analyzer().DEFAULT_STRATEGY_EXCLUDE_REGEX,
        "strategy_include_functions": [],
        "strategy_main_included": True,
        "clang_extra_args": [],
    }
    for key, value in expected_signature_subset.items():
        assert paper_row["_analysis_signature"][key] == value
    assert len(paper_row["_analysis_signature"]["configuration_fingerprint"]) == 64
    assert not (experiment / "analysis" / "diagnostics" / "representation_ablation.csv").exists()

    diagnostic_result = subprocess.run(
        [
            sys.executable,
            str(ANALYZER),
            "--experiment",
            str(experiment),
            "--diagnostic-output",
            "--bootstrap-repetitions",
            "2",
            "--clang-extra-arg=-DVALUE=1",
            "--clang-extra-arg=-Irelative/include",
            "--clean-output",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
        check=False,
    )
    assert diagnostic_result.returncode == 0, diagnostic_result.stderr
    diagnostic_summary = json.loads(
        (experiment / "analysis" / "summary.json").read_text(encoding="utf-8")
    )
    assert diagnostic_summary["analysis_configuration"]["clang_extra_args"] == [
        "-DVALUE=1",
        "-Irelative/include",
    ]
    diagnostic_paper_row = json.loads(
        (experiment / "analysis" / "paper_metrics_row.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostic_paper_row["_analysis_signature"]["clang_extra_args"] == [
        "-DVALUE=1",
        "-Irelative/include",
    ]
    assert diagnostic_paper_row["_confirmatory_configuration_match"] is False
    with (
        experiment / "analysis" / "diagnostics" / "representation_ablation.csv"
    ).open(newline="", encoding="utf-8") as handle:
        ablations = list(csv.DictReader(handle))
    assert {
        row["representation"]
        for row in ablations
        if row["space"] == "architecture"
    } == {
        "clang_only",
        "tree_sitter_only",
        "gumtree_only",
        "clang_plus_tree_sitter",
        "clang_plus_tree_sitter_plus_gumtree",
    }
    assert {
        row["representation"] for row in ablations if row["space"] == "strategy"
    } == {
        "clang_only",
        "tree_sitter_only",
        "clang_plus_tree_sitter",
        "clang_plus_tree_sitter_without_main",
    }
    for space in ("architecture", "strategy"):
        space_rows = [row for row in ablations if row["space"] == space]
        assert len({row["population_n"] for row in space_rows}) == 1
        assert len({row["threshold_used"] for row in space_rows}) == 1
        primary_name = (
            "clang_plus_tree_sitter_plus_gumtree"
            if space == "architecture"
            else "clang_plus_tree_sitter"
        )
        primary = next(
            row for row in space_rows if row["representation"] == primary_name
        )
        assert primary["adjusted_rand_vs_primary"] == "1.0"


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
