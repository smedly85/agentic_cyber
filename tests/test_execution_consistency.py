"""Tests for the behavioral/execution-consistency measurement (dimension 2).

Mirrors the conventions of tests/test_measure_diversity.py: pure statistics are
exercised directly out of `scripts/analysis/`, the orchestration script is loaded
by path, and one test runs the real thing end to end through a real suite.

That last one is the point of the file. Everything else verifies that this code
parses a report shape correctly; only the subprocess test verifies that the
shape is what `runner.py --json-report` actually emits, and that a rebuild of
identical source really does reproduce a fingerprint.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SORT_SUITE = REPO_ROOT / "tests" / "sort-test-suite"
MEASURE = REPO_ROOT / "scripts" / "measure_execution_consistency.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from analysis import diversity_metrics as dm  # noqa: E402
from analysis import execution_metrics as em  # noqa: E402


def load_measure():
    spec = importlib.util.spec_from_file_location(
        "measure_execution_consistency", MEASURE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def measure():
    return load_measure()


# ---------------------------------------------------------------------------
# scripts/analysis/execution_metrics.py
# ---------------------------------------------------------------------------


class BehavioralFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_order_independent(self):
        forward = em.behavioral_fingerprint_hash(
            "corpus-a",
            [{"case_id": "case-a", "verdict": "PASS"},
             {"case_id": "case-b", "verdict": "CRASH"},
             {"case_id": "case-c", "verdict": "TIMEOUT"}],
        )
        shuffled = em.behavioral_fingerprint_hash(
            "corpus-a",
            [{"case_id": "case-c", "verdict": "TIMEOUT"},
             {"case_id": "case-a", "verdict": "PASS"},
             {"case_id": "case-b", "verdict": "CRASH"}],
        )
        self.assertEqual(forward, shuffled)
        # The runner reports failures from a thread pool, so order carries no
        # information about the candidate and must not enter the hash.
        self.assertEqual(len(forward), 64)

    def test_fingerprint_is_sensitive_to_verdict_and_membership(self):
        trace = lambda case, verdict: [{"case_id": case, "verdict": verdict}]
        baseline = em.behavioral_fingerprint_hash("corpus", trace("case-a", "FAIL"))
        other_verdict = em.behavioral_fingerprint_hash("corpus", trace("case-a", "CRASH"))
        other_case = em.behavioral_fingerprint_hash("corpus", trace("case-b", "FAIL"))
        extra_case = em.behavioral_fingerprint_hash(
            "corpus",
            [*trace("case-a", "FAIL"), *trace("case-b", "FAIL")],
        )
        self.assertNotEqual(baseline, other_verdict)
        self.assertNotEqual(baseline, other_case)
        self.assertNotEqual(baseline, extra_case)
        # An all-passing candidate has a well-defined fingerprint of its own.
        self.assertNotEqual(baseline, em.behavioral_fingerprint_hash("corpus", []))
        self.assertEqual(
            em.behavioral_fingerprint_hash("corpus", []),
            em.behavioral_fingerprint_hash("corpus", ()),
        )
        self.assertNotEqual(
            baseline,
            em.behavioral_fingerprint_hash("different-corpus", trace("case-a", "FAIL")),
        )

    def test_fingerprint_does_not_confuse_name_and_verdict_boundaries(self):
        # A flat concatenation would collide these; the pairs are hashed as
        # structured JSON precisely so they do not.
        self.assertNotEqual(
            em.behavioral_fingerprint_hash(
                "corpus", [{"case_id": "a", "verdict": "bc"}]
            ),
            em.behavioral_fingerprint_hash(
                "corpus", [{"case_id": "ab", "verdict": "c"}]
            ),
        )

    def test_pairwise_disagreement_uses_every_verdict(self):
        left = [
            {"case_id": "a", "verdict": "PASS"},
            {"case_id": "b", "verdict": "PASS"},
            {"case_id": "c", "verdict": "FAIL"},
        ]
        right = [
            {"case_id": "a", "verdict": "PASS"},
            {"case_id": "b", "verdict": "TIMEOUT"},
            {"case_id": "c", "verdict": "FAIL"},
        ]
        self.assertEqual(em.pairwise_verdict_disagreement(left, left), 0.0)
        self.assertEqual(em.pairwise_verdict_disagreement(left, right), 1 / 3)
        with self.assertRaises(ValueError):
            em.pairwise_verdict_disagreement(left, right[:-1])


class StructuralBehaviorAgreementTests(unittest.TestCase):
    def test_aligned_partitions_agree_exactly(self):
        run_ids = ["r1", "r2", "r3", "r4"]
        behavioral = {"r1": "A", "r2": "A", "r3": "B", "r4": "B"}
        structural = {"r1": "7", "r2": "7", "r3": "4", "r4": "4"}
        result = em.structural_behavior_agreement(run_ids, behavioral, structural)
        self.assertEqual(result["population_n"], 4)
        self.assertEqual(result["adjusted_rand_index"], 1.0)
        self.assertIsNone(result["unavailable_reason"])

    def test_crossed_partitions_disagree(self):
        run_ids = ["r1", "r2", "r3", "r4"]
        behavioral = {"r1": "A", "r2": "A", "r3": "B", "r4": "B"}
        structural = {"r1": "0", "r2": "1", "r3": "0", "r4": "1"}
        result = em.structural_behavior_agreement(run_ids, behavioral, structural)
        self.assertAlmostEqual(result["adjusted_rand_index"], -0.5)
        self.assertIsNone(result["unavailable_reason"])

    def test_only_shared_runs_contribute_to_nontrivial_partitions(self):
        run_ids = ["r1", "r2", "r3", "r4", "r5"]
        behavioral = {"r1": "A", "r2": "A", "r3": "B", "r4": "B", "r5": "C"}
        # r3 sits outside the architecture population, so it has no family label.
        structural = {"r1": "0", "r2": "0", "r4": "1", "r5": "1"}
        result = em.structural_behavior_agreement(run_ids, behavioral, structural)
        self.assertEqual(result["population_n"], 4)
        self.assertIsNotNone(result["adjusted_rand_index"])

    def test_one_behavioral_group_is_not_reported(self):
        result = em.structural_behavior_agreement(
            ["r1", "r2", "r3"],
            {"r1": "A", "r2": "A", "r3": "A"},
            {"r1": "0", "r2": "1", "r3": "1"},
        )
        self.assertIsNone(result["adjusted_rand_index"])
        self.assertEqual(
            result["unavailable_reason"], "trivial_behavioral_partition"
        )

    def test_one_structural_group_is_not_reported(self):
        result = em.structural_behavior_agreement(
            ["r1", "r2", "r3"],
            {"r1": "A", "r2": "B", "r3": "B"},
            {"r1": "0", "r2": "0", "r3": "0"},
        )
        self.assertIsNone(result["adjusted_rand_index"])
        self.assertEqual(
            result["unavailable_reason"], "trivial_structural_partition"
        )

    def test_both_trivial_partitions_are_not_reported(self):
        result = em.structural_behavior_agreement(
            ["r1", "r2"],
            {"r1": "A", "r2": "A"},
            {"r1": "0", "r2": "0"},
        )
        self.assertIsNone(result["adjusted_rand_index"])
        self.assertEqual(result["unavailable_reason"], "both_partitions_trivial")

    def test_ari_is_null_below_two_shared_runs(self):
        for behavioral, structural in (
            ({"r1": "A"}, {"r1": "0"}),
            ({"r1": "A", "r2": "A"}, {"r3": "0"}),
            ({}, {}),
        ):
            result = em.structural_behavior_agreement(
                ["r1", "r2", "r3"], behavioral, structural
            )
            self.assertIsNone(result["adjusted_rand_index"])
            self.assertEqual(
                result["unavailable_reason"], "insufficient_shared_runs"
            )
        self.assertEqual(
            em.structural_behavior_agreement([], {}, {}),
            {
                "population_n": 0,
                "adjusted_rand_index": None,
                "unavailable_reason": "insufficient_shared_runs",
            },
        )

    def test_agreement_is_order_deterministic(self):
        behavioral = {"r1": "A", "r2": "B", "r3": "A"}
        structural = {"r1": "0", "r2": "1", "r3": "0"}
        forward = em.structural_behavior_agreement(
            ["r1", "r2", "r3"], behavioral, structural
        )
        reversed_order = em.structural_behavior_agreement(
            ["r3", "r2", "r1"], behavioral, structural
        )
        self.assertEqual(forward, reversed_order)


# ---------------------------------------------------------------------------
# Pure helpers in scripts/measure_execution_consistency.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source_path, expected",
    [
        ("new_grep.c", "grep"),
        ("new_sort.c", "sort"),
        ("new_mkdir.c", "mkdir"),
        ("new_chmod.c", "chmod"),
        # Not every experiment has to use the new_ convention.
        ("chmod.c", "chmod"),
    ],
)
def test_utility_name_is_inferred_from_source_path(measure, source_path, expected):
    assert measure.utility_from_source_path(source_path) == expected


def test_utility_name_rejects_an_unusable_source_path(measure):
    with pytest.raises(ValueError):
        measure.utility_from_source_path("new_.c")


@pytest.mark.parametrize(
    "command, expected",
    [
        ("tests/grep-test-suite/judge_candidate.sh build/new_grep -H -h", ["-H", "-h"]),
        ("tests/sort-test-suite/judge_candidate.sh build/new_sort", []),
        (
            "tests/sort-test-suite/judge_candidate.sh build/new_sort -n -k -u -t -o "
            "-m --sort",
            ["-n", "-k", "-u", "-t", "-o", "-m", "--sort"],
        ),
    ],
)
def test_implemented_flags_come_from_the_recorded_judge_call(
    measure, command, expected
):
    assert measure.implemented_flags(command) == expected


def test_implemented_flags_rejects_a_command_with_no_binary(measure):
    with pytest.raises(ValueError):
        measure.implemented_flags("judge_candidate.sh")


@pytest.mark.parametrize(
    "command, expected",
    [
        (
            "mkdir -p build && cc -std=c11 -Wall -O2 src/new_grep/new_grep.c "
            "-o build/new_grep",
            "build/new_grep",
        ),
        ("cc -o out/a.out a.c", "out/a.out"),
        # A chained build: the executable is the output of the final step.
        ("cc -c -o build/a.o a.c && cc -o build/tool build/a.o", "build/tool"),
    ],
)
def test_binary_path_comes_from_the_build_command(measure, command, expected):
    assert measure.binary_from_build_command(command) == expected


def test_binary_path_rejects_a_build_command_without_output(measure):
    with pytest.raises(ValueError):
        measure.binary_from_build_command("make all")


def test_report_extraction_matches_the_json_report_contract(measure):
    payload = {
        "counts": {"PASS": 40, "FAIL": 2, "SKIP": 8, "CRASH": 1},
        "per_suite": {"curated.json.gz": {"PASS": 40}},
        "failures": [
            ["case-one", "FAIL", "expected 'a\\nb\\n', got 'b\\na\\n'"],
            ["case-two", "CRASH", "SIGSEGV"],
            ["case-three", "FAIL", "exit 1 vs 0"],
        ],
        "results": [
            {"case_id": "suite::case-one", "verdict": "FAIL"},
            {"case_id": "suite::case-pass", "verdict": "PASS"},
        ],
    }
    assert measure.report_failures(payload) == [
        ("case-one", "FAIL"),
        ("case-two", "CRASH"),
        ("case-three", "FAIL"),
    ]
    # SKIPs are cases too and remain in the complete verdict trace denominator.
    assert measure.report_case_count(payload) == 51


def test_complete_report_trace_contains_pass_and_failure_verdicts(measure):
    payload = {
        "counts": {"PASS": 1, "FAIL": 1},
        "failures": [["failed", "FAIL", "detail"]],
        "results": [
            {"case_id": "suite::passed", "verdict": "PASS"},
            {"case_id": "suite::failed", "verdict": "FAIL"},
        ],
    }
    assert measure.report_results(payload) == sorted(
        payload["results"], key=lambda entry: entry["case_id"]
    )
    assert "failures" in payload


def test_runner_case_ids_distinguish_variants_and_invocation_modes(monkeypatch):
    monkeypatch.syspath_prepend(str(SORT_SUITE))
    spec = importlib.util.spec_from_file_location(
        "sort_runner_case_identity", SORT_SUITE / "runner.py"
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    first_variant = {"_suite": "frozen.json.gz", "_case_ordinal": 12}
    second_variant = {"_suite": "frozen.json.gz", "_case_ordinal": 13}
    identifiers = [
        runner.case_result_id(first_variant, "logical-case"),
        runner.case_result_id(first_variant, "logical-case.p"),
        runner.case_result_id(first_variant, "logical-case.r"),
        runner.case_result_id(second_variant, "logical-case"),
    ]
    assert len(identifiers) == len(set(identifiers))
    assert identifiers == [
        runner.case_result_id(first_variant, "logical-case"),
        runner.case_result_id(first_variant, "logical-case.p"),
        runner.case_result_id(first_variant, "logical-case.r"),
        runner.case_result_id(second_variant, "logical-case"),
    ]
    assert identifiers[1].endswith(".p")
    assert identifiers[2].endswith(".r")


def test_report_extraction_handles_a_clean_pass(measure):
    payload = {"counts": {"PASS": 3}, "per_suite": {}, "failures": []}
    assert measure.report_failures(payload) == []
    assert measure.report_case_count(payload) == 3
    assert measure.report_failures({"counts": {}}) == []
    assert measure.report_case_count({}) == 0


def test_report_extraction_rejects_a_malformed_failure_entry(measure):
    with pytest.raises(ValueError):
        measure.report_failures({"failures": [["case-one"]]})


def test_combined_fingerprint_namespaces_the_two_corpora(measure):
    """A visible and a held-out case of the same name must not collide."""
    result = [{"case_id": "x", "verdict": "FAIL"}]
    assert measure.namespaced_results("visible", result) == [
        {"case_id": "visible::x", "verdict": "FAIL"}
    ]
    visible_only = em.behavioral_fingerprint_hash(
        "combined", measure.namespaced_results("visible", result)
    )
    heldout_only = em.behavioral_fingerprint_hash(
        "combined", measure.namespaced_results("heldout", result)
    )
    assert visible_only != heldout_only


def test_case_count_stability_detects_an_uneven_condition(measure):
    stable = measure.case_count_stability(
        [
            {"visible_case_count": 51, "heldout_case_count": 29},
            {"visible_case_count": 51, "heldout_case_count": 29},
        ]
    )
    assert stable["case_count_stable"] is True
    assert stable["distinct_visible_case_counts"] == [51]

    uneven = measure.case_count_stability(
        [
            {"visible_case_count": 51, "heldout_case_count": 29},
            {"visible_case_count": 48, "heldout_case_count": 29},
        ]
    )
    assert uneven["case_count_stable"] is False
    assert uneven["distinct_visible_case_counts"] == [48, 51]
    # An empty population is vacuously stable rather than an error.
    assert measure.case_count_stability([])["case_count_stable"] is True


def test_lineage_population_selection_uses_controller_membership(measure, tmp_path):
    metrics = tmp_path / "per_run_metrics.csv"
    with metrics.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "run_id", "overall_success", "analysis_population_member",
                "population_selection_basis",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "run_id": "heldout-failed-but-promoted",
                "overall_success": "False",
                "analysis_population_member": "True",
                "population_selection_basis": "lineage_stage_success",
            }
        )
    population = measure.successful_population(
        metrics,
        {
            "experiment_format": "lineage_population_view",
            "population_selection_basis": "lineage_stage_success",
        },
    )
    assert [row["run_id"] for row in population] == [
        "heldout-failed-but-promoted"
    ]


def test_lineage_population_selection_rejects_missing_explicit_membership(
    measure, tmp_path
):
    metrics = tmp_path / "per_run_metrics.csv"
    metrics.write_text(
        "run_id,overall_success\nattempt-001,True\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="malformed lineage_population_view"):
        measure.successful_population(
            metrics,
            {
                "experiment_format": "lineage_population_view",
                "population_selection_basis": "lineage_stage_success",
            },
        )


def test_convergence_summary_reuses_the_diversity_statistic(measure):
    hashes = ["A", "A", "B", "C"]
    run_ids = ["r1", "r2", "r3", "r4"]
    summary = measure.convergence_summary(hashes, run_ids)
    reference = dm.exact_repetition_summary(hashes, run_ids)
    assert summary["exact_behavioral_unique_rate"] == reference["exact_unique_rate"]
    assert summary["exact_behavioral_modal_share"] == reference["exact_modal_share"]
    assert summary["exact_behavioral_unique_rate"] == 0.75
    assert summary["exact_behavioral_modal_share"] == 0.5
    # Group membership is retained, exactly as source-hash groups are.
    group = next(g for g in summary["hash_groups"] if g["sha256"] == "A")
    assert group["members"] == ["r1", "r2"]


def test_visible_suite_files_exclude_the_manifest(measure):
    names = [path.name for path in measure.visible_suite_files(SORT_SUITE)]
    assert names, "the sort suite ships frozen suite files"
    assert "MANIFEST.json" not in names
    assert "curated.json.gz" in names


def test_judging_config_carries_the_suites_platform_gate(measure, tmp_path: Path):
    destination = tmp_path / "config.json"
    measure.judging_config(SORT_SUITE, tmp_path / "bin", ["-n"], destination)
    config = json.loads(destination.read_text())
    assert config["implemented"] == ["-n"]
    assert config["paths"]["candidate_bin"] == str(tmp_path / "bin")
    assert config["unimplemented_policy"] == "skip"
    # Judging Linux goldens on another host would fingerprint the host.
    assert config["required_platform"] == "Linux"
    # The committed suite config is never touched.
    assert json.loads((SORT_SUITE / "config.json").read_text())["paths"][
        "candidate_bin"
    ] == "/path/to/your/sort"


# ---------------------------------------------------------------------------
# Visible-pass scope: the corpus the checkpoint was really judged on
# ---------------------------------------------------------------------------

SUITE_ROOTS = {
    utility: REPO_ROOT / "tests" / f"{utility}-test-suite"
    for utility in ("sort", "mkdir", "grep", "chmod")
}


def visible_config(measure, suite_root: Path, destination: Path) -> dict:
    measure.judging_config(
        suite_root,
        destination.parent / "bin",
        [],
        destination,
        scope_overrides=measure.visible_scope_overrides(suite_root),
    )
    return json.loads(destination.read_text())


@pytest.mark.parametrize(
    "utility, excluded_tags, stdin_only",
    [
        # sort and mkdir commit real exclusions that the real judgement honours.
        ("sort", ["debug", "doc", "compress", "files0", "obsolete"], True),
        ("mkdir", ["selinux", "doc"], False),
        ("grep", [], False),
        ("chmod", [], False),
    ],
)
def test_visible_config_reproduces_the_real_judging_scope(
    measure, tmp_path: Path, utility, excluded_tags, stdin_only
):
    """The visible fingerprint must describe the corpus that drove the repair loop.

    Judging a broader corpus than `judge_candidate.sh` did would put a
    `visible_case_count` next to a `feature_test_exit_code` that came from a
    different set of cases.
    """
    config = visible_config(
        measure, SUITE_ROOTS[utility], tmp_path / f"{utility}.json"
    )
    assert config["excluded_tags"] == excluded_tags
    if stdin_only:
        assert config["scope"] == {"stdin_only": True}
    else:
        assert "scope" not in config
    # The scope fix must not disturb anything else about the pass.
    assert config["unimplemented_policy"] == "skip"
    assert config["implemented"] == []


@pytest.mark.parametrize("utility", ["sort", "mkdir", "grep", "chmod"])
def test_heldout_config_still_matches_heldout_judge(
    measure, tmp_path: Path, utility
):
    """The held-out pass must keep matching `scripts/heldout_judge.py` exactly.

    That script is what actually ran the held-out corpus during the experiment,
    and it applies no exclusions and no stdin-only scope. Leaking the
    visible-only fix into this pass would make the held-out fingerprint describe
    a pass the experiment never performed.
    """
    destination = tmp_path / f"{utility}-heldout.json"
    measure.judging_config(SUITE_ROOTS[utility], tmp_path / "bin", [], destination)
    config = json.loads(destination.read_text())
    assert config["excluded_tags"] == []
    assert "scope" not in config
    assert config["unimplemented_policy"] == "skip"
    # Nothing beyond the minimal shape plus the platform abort gate.
    assert set(config) <= {
        "paths",
        "implemented",
        "unimplemented_policy",
        "excluded_tags",
        "required_platform",
    }


def test_visible_and_heldout_configs_diverge_only_where_intended(
    measure, tmp_path: Path
):
    visible = visible_config(measure, SORT_SUITE, tmp_path / "visible.json")
    heldout_path = tmp_path / "heldout.json"
    measure.judging_config(SORT_SUITE, tmp_path / "bin", [], heldout_path)
    heldout = json.loads(heldout_path.read_text())
    differing = {
        key
        for key in set(visible) | set(heldout)
        if visible.get(key) != heldout.get(key)
    }
    assert differing == {"excluded_tags", "scope"}


def test_stdin_only_scope_is_detected_from_the_wrapper_not_hardcoded(
    measure, tmp_path: Path
):
    assert measure.judge_wrapper_pins_stdin_only(SORT_SUITE) is True
    for utility in ("mkdir", "grep", "chmod"):
        assert measure.judge_wrapper_pins_stdin_only(SUITE_ROOTS[utility]) is False

    # Prose alone must not trigger it -- sort's wrapper documents the pin in a
    # comment as well as performing it, and so may others.
    mentions_only = tmp_path / "mentions-only"
    mentions_only.mkdir()
    (mentions_only / "judge_candidate.sh").write_text(
        "# this wrapper does not pin scope.stdin_only\n", encoding="utf-8"
    )
    assert measure.judge_wrapper_pins_stdin_only(mentions_only) is False

    injects = tmp_path / "injects"
    injects.mkdir()
    (injects / "judge_candidate.sh").write_text(
        'config.setdefault("scope", {})["stdin_only"] = True\n', encoding="utf-8"
    )
    assert measure.judge_wrapper_pins_stdin_only(injects) is True
    # A suite with no wrapper at all is simply unrestricted.
    assert measure.judge_wrapper_pins_stdin_only(tmp_path / "absent") is False


def test_visible_scope_overrides_names_only_what_differs(measure):
    assert measure.visible_scope_overrides(SUITE_ROOTS["grep"]) == {
        "excluded_tags": []
    }
    assert measure.visible_scope_overrides(SUITE_ROOTS["mkdir"]) == {
        "excluded_tags": ["selinux", "doc"]
    }
    assert measure.visible_scope_overrides(SORT_SUITE) == {
        "excluded_tags": ["debug", "doc", "compress", "files0", "obsolete"],
        "scope": {"stdin_only": True},
    }


# ---------------------------------------------------------------------------
# Real rebuild + real runner.py, against a real frozen suite
# ---------------------------------------------------------------------------

SORT_REQUIRED_PLATFORM = json.loads(
    (SORT_SUITE / "config.json").read_text(encoding="utf-8")
).get("required_platform")

# A plain lexicographic line sorter. Not a complete `sort`, and it does not need
# to be: the measurement compares candidates to each other, not to a bar.
CORRECT_SORT_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int ascending(const void *left, const void *right) {
    return strcmp(*(const char *const *)left, *(const char *const *)right);
}

int main(void) {
    char **lines = NULL;
    size_t count = 0, capacity = 0;
    char *line = NULL;
    size_t length = 0;
    ssize_t got;

    while ((got = getline(&line, &length, stdin)) != -1) {
        if (got > 0 && line[got - 1] == '\n') {
            line[got - 1] = '\0';
        }
        if (count == capacity) {
            capacity = capacity ? capacity * 2 : 16;
            char **grown = realloc(lines, capacity * sizeof *grown);
            if (grown == NULL) {
                return 2;
            }
            lines = grown;
        }
        lines[count] = strdup(line);
        if (lines[count] == NULL) {
            return 2;
        }
        count++;
    }
    free(line);

    qsort(lines, count, sizeof *lines, ascending);
    for (size_t index = 0; index < count; index++) {
        if (puts(lines[index]) == EOF) {
            fprintf(stderr, "new_sort: write error\n");
            return 2;
        }
    }
    if (fflush(stdout) != 0) {
        fprintf(stderr, "new_sort: write error\n");
        return 2;
    }
    free(lines);
    return 0;
}
"""

# Byte-identical apart from the comparator's argument order: same structure,
# deliberately different observable behavior.
REVERSED_SORT_C = CORRECT_SORT_C.replace(
    "return strcmp(*(const char *const *)left, *(const char *const *)right);",
    "return strcmp(*(const char *const *)right, *(const char *const *)left);",
)

SORT_BUILD_COMMAND = (
    "mkdir -p build && cc -std=c11 -O1 -D_POSIX_C_SOURCE=200809L "
    "src/new_sort/new_sort.c -o build/new_sort"
)


@pytest.mark.skipif(
    platform.system() != SORT_REQUIRED_PLATFORM,
    reason=(
        f"the sort suite's frozen goldens require {SORT_REQUIRED_PLATFORM}; "
        f"this host is {platform.system()}"
    ),
)
@pytest.mark.skipif(
    shutil.which("cc") is None, reason="no C compiler on PATH to rebuild candidates"
)
def test_rebuild_and_judge_round_trip_through_the_real_suite(
    measure, tmp_path: Path
):
    """The contract test: real build, real runner.py, real --json-report.

    Every other test in this file asserts that this code handles a report shape
    correctly. This one asserts that the shape is the one the suite emits, and
    that the pipeline is deterministic where it claims to be -- two independent
    rebuilds of identical source must agree, and a behaviorally different
    candidate must not.
    """
    corpora = measure.visible_suite_files(SORT_SUITE)
    heldout = measure.heldout_contract.corpus_path(SORT_SUITE)
    assert heldout.is_file()

    results = {}
    for label, source_text in (
        ("correct-first", CORRECT_SORT_C),
        ("correct-second", CORRECT_SORT_C),
        ("reversed", REVERSED_SORT_C),
    ):
        source = tmp_path / f"{label}.c"
        source.write_text(source_text, encoding="utf-8")
        results[label] = measure.measure_run(
            candidate_source=source,
            workdir=tmp_path / f"work-{label}",
            source_workdir_path="src/new_sort/new_sort.c",
            build_command=SORT_BUILD_COMMAND,
            binary_relative_path="build/new_sort",
            suite_root=SORT_SUITE,
            visible_corpora=corpora,
            heldout_corpus=heldout,
            flags=[],
        )

    for label, result in results.items():
        assert result["status"] == "measured", f"{label}: {result.get('detail')}"
        for scope in ("visible", "heldout", "combined"):
            case_ids = [entry["case_id"] for entry in result[f"{scope}_results"]]
            assert len(case_ids) == len(set(case_ids)), (
                f"{label}: {scope} trace contains duplicate case IDs"
            )

    first, second, reversed_variant = (
        results["correct-first"],
        results["correct-second"],
        results["reversed"],
    )

    # (a) Two independent rebuilds of byte-identical source agree exactly.
    assert (
        first["combined_fingerprint_sha256"] == second["combined_fingerprint_sha256"]
    )
    assert first["visible_fingerprint_sha256"] == second["visible_fingerprint_sha256"]
    assert first["heldout_fingerprint_sha256"] == second["heldout_fingerprint_sha256"]
    assert first["combined_results"] == second["combined_results"]

    assert em.pairwise_verdict_disagreement(
        first["combined_results"], second["combined_results"]
    ) == 0.0

    # (b) A behaviorally different candidate does not.
    assert (
        reversed_variant["combined_fingerprint_sha256"]
        != first["combined_fingerprint_sha256"]
    )
    assert em.pairwise_verdict_disagreement(
        first["combined_results"], reversed_variant["combined_results"]
    ) > 0.0

    # Counts remain a diagnostic; corpus identities and ordered case IDs are
    # the authoritative compatibility check.
    stability = measure.case_count_stability(list(results.values()))
    assert stability["case_count_stable"] is True
    assert stability["distinct_visible_case_counts"][0] > 0
    assert stability["distinct_heldout_case_counts"][0] > 0

    # Guard against a vacuous pass: if every candidate failed every case the
    # agreement above would be meaningless. The correct sorter must actually
    # pass cases the reversed one fails.
    assert first["visible_failure_count"] < reversed_variant["visible_failure_count"]
    assert first["heldout_failure_count"] < reversed_variant["heldout_failure_count"]


@pytest.mark.skipif(
    shutil.which("cc") is None, reason="no C compiler on PATH to rebuild candidates"
)
def test_a_candidate_that_does_not_compile_is_recorded_not_dropped(
    measure, tmp_path: Path
):
    source = tmp_path / "broken.c"
    source.write_text("int main(void) { this is not C }\n", encoding="utf-8")
    result = measure.measure_run(
        candidate_source=source,
        workdir=tmp_path / "work",
        source_workdir_path="src/new_sort/new_sort.c",
        build_command=SORT_BUILD_COMMAND,
        binary_relative_path="build/new_sort",
        suite_root=SORT_SUITE,
        visible_corpora=measure.visible_suite_files(SORT_SUITE),
        heldout_corpus=measure.heldout_contract.corpus_path(SORT_SUITE),
        flags=[],
    )
    assert result["status"] == measure.UNMEASURED_REBUILD_FAILED
    assert result["detail"]


def sort_measure_run(measure, tmp_path: Path, source_text: str, **overrides):
    source = tmp_path / "candidate.c"
    source.write_text(source_text, encoding="utf-8")
    arguments = {
        "candidate_source": source,
        "workdir": tmp_path / "work",
        "source_workdir_path": "src/new_sort/new_sort.c",
        "build_command": SORT_BUILD_COMMAND,
        "binary_relative_path": "build/new_sort",
        "suite_root": SORT_SUITE,
        "visible_corpora": measure.visible_suite_files(SORT_SUITE),
        "heldout_corpus": measure.heldout_contract.corpus_path(SORT_SUITE),
        "flags": [],
    }
    return measure.measure_run(**{**arguments, **overrides})


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="the build command runs through /bin/sh, so `sleep` is POSIX-only",
)
def test_a_build_that_hangs_is_recorded_not_left_to_stall_the_batch(
    measure, tmp_path: Path, monkeypatch
):
    """A hang is one candidate's outcome, not a reason to abandon the condition.

    Uses a real sleeping build command so the `timeout=` argument itself is
    exercised, rather than only the handler that catches its expiry.
    """
    monkeypatch.setattr(measure, "BUILD_TIMEOUT_SECONDS", 0.5)
    result = sort_measure_run(
        measure,
        tmp_path,
        "int main(void) { return 0; }\n",
        build_command="sleep 30",
    )
    assert result["status"] == measure.UNMEASURED_REBUILD_FAILED
    assert "timed out" in result["detail"]
    assert "0.5s" in result["detail"]


@pytest.mark.skipif(
    shutil.which("cc") is None, reason="no C compiler on PATH to rebuild candidates"
)
def test_a_judging_pass_that_hangs_is_recorded_not_left_to_stall_the_batch(
    measure, tmp_path: Path, monkeypatch
):
    """Same for the judge pass, whose bound is the backstop for a whole corpus."""
    monkeypatch.setattr(measure, "JUDGE_TIMEOUT_SECONDS", 0.01)
    result = sort_measure_run(
        measure, tmp_path, "int main(void) { return 0; }\n"
    )
    assert result["status"] == measure.UNMEASURED_JUDGE_FAILED
    assert "timed out" in result["detail"]


def test_a_build_timeout_does_not_escape_measure_run(
    measure, tmp_path: Path, monkeypatch
):
    """The taxonomy folding holds even where no compiler is available."""

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="cc", timeout=300, output="partial\n")

    monkeypatch.setattr(measure, "rebuild_candidate", hang)
    result = sort_measure_run(measure, tmp_path, "int main(void) { return 0; }\n")
    assert result["status"] == measure.UNMEASURED_REBUILD_FAILED
    assert "timed out after 300s" in result["detail"]
    assert "partial" in result["detail"]


def test_output_tail_handles_a_killed_process_with_nothing_captured(measure):
    # `TimeoutExpired.output` is None when the process was killed before it
    # wrote anything, which must not turn into an AttributeError.
    assert measure.output_tail(None) == ""
    assert measure.output_tail(b"bytes output\n") == "bytes output"
    assert measure.output_tail("x" * 900, limit=10) == "x" * 10


def test_a_missing_candidate_source_is_recorded_not_dropped(measure, tmp_path: Path):
    result = measure.measure_run(
        candidate_source=tmp_path / "absent.c",
        workdir=tmp_path / "work",
        source_workdir_path="src/new_sort/new_sort.c",
        build_command=SORT_BUILD_COMMAND,
        binary_relative_path="build/new_sort",
        suite_root=SORT_SUITE,
        visible_corpora=[],
        heldout_corpus=tmp_path / "nothing.json",
        flags=[],
    )
    assert result["status"] == measure.UNMEASURED_SOURCE_MISSING


# ---------------------------------------------------------------------------
# main(): output wiring over a fabricated condition
# ---------------------------------------------------------------------------

FABRICATED_EXPERIMENT = {
    "schema_version": 2,
    "model": "fake/model",
    "temperature": 0.0,
    "source_path": "new_sort.c",
    "source_workdir_path": "src/new_sort/new_sort.c",
    "build_command": SORT_BUILD_COMMAND,
    "feature_test_command": "tests/sort-test-suite/judge_candidate.sh build/new_sort -n",
    "extra_test_command": "true",
}

# attempt-001/002 behaved one way, attempt-003/004 another. Architecture
# families follow that split exactly (ARI 1.0); strategy families cross it
# (ARI -0.5). attempt-005 succeeded but cannot be rebuilt; attempt-006 failed
# and is not part of the population at all.
FABRICATED_FINGERPRINTS = {
    "attempt-001": ("V1", "H1", "C1"),
    "attempt-002": ("V1", "H2", "C1"),
    "attempt-003": ("V1", "H3", "C2"),
    "attempt-004": ("V2", "H4", "C2"),
}

FABRICATED_RUNS = [
    {
        "run_id": "attempt-001",
        "overall_success": "True",
        "architecture_cluster_id": "0",
        "strategy_cluster_id": "0",
    },
    {
        "run_id": "attempt-002",
        "overall_success": "True",
        "architecture_cluster_id": "0",
        "strategy_cluster_id": "1",
    },
    {
        "run_id": "attempt-003",
        "overall_success": "True",
        "architecture_cluster_id": "1",
        "strategy_cluster_id": "0",
    },
    {
        "run_id": "attempt-004",
        "overall_success": "True",
        "architecture_cluster_id": "1",
        "strategy_cluster_id": "1",
    },
    {
        # Successful, but outside both primary structural populations and
        # unable to rebuild.
        "run_id": "attempt-005",
        "overall_success": "True",
        "architecture_cluster_id": "",
        "strategy_cluster_id": "",
    },
    {
        "run_id": "attempt-006",
        "overall_success": "False",
        "architecture_cluster_id": "0",
        "strategy_cluster_id": "0",
    },
]


def fabricate_experiment(root: Path) -> Path:
    experiment = root / "temp-0p0"
    (experiment / "analysis").mkdir(parents=True)
    (experiment / "experiment.json").write_text(
        json.dumps(FABRICATED_EXPERIMENT, indent=2), encoding="utf-8"
    )
    with (experiment / "analysis" / "per_run_metrics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FABRICATED_RUNS[0]))
        writer.writeheader()
        writer.writerows(FABRICATED_RUNS)
    return experiment


def stub_measure_run(**kwargs):
    """Stand in for the real rebuild/judge with known fingerprints."""
    run_id = Path(kwargs["candidate_source"]).parent.parent.name
    if run_id not in FABRICATED_FINGERPRINTS:
        return {"status": "rebuild_failed", "detail": f"fabricated failure: {run_id}"}
    visible, heldout, combined = FABRICATED_FINGERPRINTS[run_id]
    visible_results = [
        {"case_id": f"visible::{index:03d}", "verdict": "PASS"}
        for index in range(51)
    ]
    heldout_results = [
        {"case_id": f"heldout::{index:03d}", "verdict": "PASS"}
        for index in range(29)
    ]
    combined_results = sorted(
        [{"case_id": f"visible::{entry['case_id']}", "verdict": entry["verdict"]}
         for entry in visible_results]
        + [{"case_id": f"heldout::{entry['case_id']}", "verdict": entry["verdict"]}
           for entry in heldout_results],
        key=lambda entry: entry["case_id"],
    )
    return {
        "status": "measured",
        "visible_case_count": 51,
        "heldout_case_count": 29,
        "visible_failure_count": 2,
        "heldout_failure_count": 1,
        "visible_results": visible_results,
        "heldout_results": heldout_results,
        "combined_results": combined_results,
        "visible_corpus": {"corpus_identity_sha256": "visible-corpus"},
        "heldout_corpus": {"corpus_identity_sha256": "heldout-corpus"},
        "combined_corpus": {"corpus_identity_sha256": "combined-corpus"},
        "visible_corpus_identity_sha256": "visible-corpus",
        "heldout_corpus_identity_sha256": "heldout-corpus",
        "combined_corpus_identity_sha256": "combined-corpus",
        "visible_fingerprint_sha256": visible,
        "heldout_fingerprint_sha256": heldout,
        "combined_fingerprint_sha256": combined,
    }


def test_main_wires_population_fingerprints_and_agreement(
    measure, tmp_path: Path, monkeypatch, capsys
):
    experiment = fabricate_experiment(tmp_path)
    monkeypatch.setattr(measure, "measure_run", stub_measure_run)

    assert measure.main(["--experiment", str(experiment), "--clean-output"]) == 0

    output = experiment / "analysis" / "execution_consistency"
    summary = json.loads((output / "summary.json").read_text())

    assert summary["schema_version"] == 3
    assert summary["utility"] == "sort"
    assert summary["implemented_flags"] == ["-n"]
    assert summary["candidate_binary"] == "build/new_sort"
    assert summary["case_count_stable"] is True

    population = summary["population"]
    assert population["successful_runs"] == 5
    assert population["measured_runs"] == 4
    assert population["measurement_coverage"] == 0.8
    # The run that could not be rebuilt is named, with its reason.
    assert [entry["run_id"] for entry in population["unmeasured_runs"]] == [
        "attempt-005"
    ]
    assert population["unmeasured_runs"][0]["status"] == "rebuild_failed"

    convergence = summary["exact_behavioral_convergence"]
    # visible: V1, V1, V1, V2
    assert convergence["visible"]["exact_behavioral_unique_rate"] == 0.5
    assert convergence["visible"]["exact_behavioral_modal_share"] == 0.75
    # held-out: four distinct fingerprints -- agreement on cases the agent could
    # read did not carry over to cases it could not.
    assert convergence["heldout"]["exact_behavioral_unique_rate"] == 1.0
    assert convergence["heldout"]["exact_behavioral_modal_share"] == 0.25
    # combined: C1, C1, C2, C2
    assert convergence["combined"]["exact_behavioral_unique_rate"] == 0.5
    assert convergence["combined"]["exact_behavioral_modal_share"] == 0.5
    assert convergence["combined"]["population_n"] == 4

    agreement = summary["structural_behavior_agreement"]
    assert agreement["architecture"]["population_n"] == 4
    assert agreement["architecture"]["adjusted_rand_index"] == 1.0
    assert agreement["strategy"]["population_n"] == 4
    assert agreement["strategy"]["adjusted_rand_index"] == pytest.approx(-0.5)

    with (output / "behavioral_fingerprints.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert [row["run_id"] for row in rows] == [
        "attempt-001",
        "attempt-002",
        "attempt-003",
        "attempt-004",
    ]
    assert rows[0]["combined_fingerprint_sha256"] == "C1"
    assert rows[0]["architecture_cluster_id"] == "0"
    assert rows[3]["strategy_cluster_id"] == "1"
    assert rows[0]["visible_case_count"] == "51"
    assert rows[0]["heldout_failure_count"] == "1"

    captured = capsys.readouterr()
    assert "Supporting combined behavioral unique rate" in captured.out
    assert "Architecture-behavior ARI: 1.000" in captured.out


def test_main_refuses_to_run_without_the_canonical_analysis(
    measure, tmp_path: Path, monkeypatch
):
    experiment = fabricate_experiment(tmp_path)
    (experiment / "analysis" / "per_run_metrics.csv").unlink()
    monkeypatch.setattr(measure, "measure_run", stub_measure_run)

    with pytest.raises(SystemExit) as error:
        measure.main(["--experiment", str(experiment)])
    assert "analyze_experiment.py" in str(error.value)


def test_main_reports_an_unstable_case_count(
    measure, tmp_path: Path, monkeypatch, capsys
):
    experiment = fabricate_experiment(tmp_path)

    def uneven(**kwargs):
        result = stub_measure_run(**kwargs)
        if result["status"] == "measured" and result["visible_fingerprint_sha256"] == "V2":
            result["visible_case_count"] = 48
            result["visible_corpus_identity_sha256"] = "different-visible-corpus"
            result["combined_corpus_identity_sha256"] = "different-combined-corpus"
        return result

    monkeypatch.setattr(measure, "measure_run", uneven)
    assert measure.main(["--experiment", str(experiment)]) == 0

    summary = json.loads(
        (
            experiment / "analysis" / "execution_consistency" / "summary.json"
        ).read_text()
    )
    assert summary["case_count_stable"] is False
    assert summary["distinct_visible_case_counts"] == [48, 51]
    visible_corpus = summary["behavioral_corpus"]["visible"]
    assert visible_corpus["compatible_population"] is False
    assert visible_corpus["distinct_corpus_identities"] == [
        "different-visible-corpus", "visible-corpus"
    ]
    visible_disagreement = summary["pairwise_behavioral_disagreement"]["visible"]
    assert visible_disagreement["incomparable_pairs"] > 0
    assert visible_disagreement["mean_pairwise_disagreement"] is None
    assert "incompatible case corpora" in visible_disagreement["unavailable_reason"]
    warning = capsys.readouterr().err
    assert "corpus identities differed" in warning
    assert "incomparable, not computed" in warning


def test_the_measurement_never_writes_into_the_experiment_attempts(
    measure, tmp_path: Path, monkeypatch
):
    """Strictly post-hoc: nothing outside analysis/execution_consistency moves."""
    experiment = fabricate_experiment(tmp_path)
    before = {
        path.relative_to(experiment): path.read_bytes()
        for path in experiment.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(measure, "measure_run", stub_measure_run)
    measure.main(["--experiment", str(experiment)])

    for relative, content in before.items():
        assert (experiment / relative).read_bytes() == content
    written = {
        path.relative_to(experiment)
        for path in experiment.rglob("*")
        if path.is_file()
    } - set(before)
    assert written == {
        Path("analysis") / "execution_consistency" / "summary.json",
        Path("analysis") / "execution_consistency" / "behavioral_fingerprints.csv",
        Path("analysis") / "execution_consistency" / "behavioral_verdict_traces.json",
        Path("analysis") / "execution_consistency" / "pairwise_behavioral_distances.csv",
    }


def test_the_measurement_script_does_not_reimplement_the_taxonomy():
    """Population and family labels are read, never re-derived."""
    text = MEASURE.read_text(encoding="utf-8")
    for forbidden in ("AgglomerativeClustering", "cosine_distance_matrix"):
        assert forbidden not in text
    assert "per_run_metrics.csv" in text
    # Exact convergence has one definition in the repository, not two.
    assert "diversity_metrics.exact_repetition_summary" in text
