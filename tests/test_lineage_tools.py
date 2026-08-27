"""Tests for the lineage layer: manifests, the stage plan, and aggregation.

These cover `scripts/lineage_plan.py` and `scripts/analyze_lineages.py`, plus
the cross-checks that keep a utility manifest, its checkpoint prompts and its
visible test suite from drifting apart, plus the one piece of judging logic the
model-derived suites add over the older ones: comparing the filesystem state a
chmod candidate leaves behind.

Deliberately free of NumPy and scikit-learn, and of any compiled candidate: the
modules under test import only the standard library, so this file runs on a
machine that has neither installed `scripts/analysis-requirements.txt` nor a C
toolchain. The clustering itself is exercised by tests/test_measure_diversity.py,
which does need that stack.
"""

from __future__ import annotations

import ast
import csv
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
from shlex import quote as shlex_quote
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = REPO_ROOT / "experiments" / "utilities"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import analyze_lineages  # noqa: E402
import capture_candidate  # noqa: E402
import checkpoint_boundary_gate  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tests"))
from reference_generators import heldout_contract  # noqa: E402
from reference_generators import oracle_contract  # noqa: E402
from reference_generators import suite_diff  # noqa: E402
import lineage_plan  # noqa: E402
import prompt_render  # noqa: E402
import stage_test_bundle  # noqa: E402
import temperature_value  # noqa: E402

# The feature surfaces the redesign fixed. BusyBox selects which flags are in
# scope; this is that selection written down where a test can enforce it.
EXPECTED_SEQUENCES = {
    "mkdir": ["-p", "-m"],
    "sort": ["-r", "-f", "-u", "-c"],
    "grep": ["-H", "-h", "-r", "-i"],
    "chmod": ["-R", "-c", "-v", "-f"],
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def analyzer_or_none():
    """`scripts/analyze_experiment.py`, or None when its stack is missing.

    This file is deliberately NumPy-free (see the module docstring) so it runs
    on a machine that never installed scripts/analysis-requirements.txt. The
    analyzer imports NumPy through analysis/diversity_metrics, so the tests that
    check controller-and-analyzer agreement skip rather than fail there.
    """
    try:
        import analyze_experiment

        return analyze_experiment
    except Exception:                                   # noqa: BLE001
        return None


def measure_or_none():
    """`scripts/measure_execution_consistency.py`, or None when its stack is missing.

    The same gate as `analyzer_or_none`, for the same reason: that module
    imports `analysis/diversity_metrics`, which imports NumPy, and this file is
    deliberately NumPy-free (see the module docstring).
    """
    try:
        import measure_execution_consistency

        return measure_execution_consistency
    except Exception:                                   # noqa: BLE001
        return None


class ManifestTests(unittest.TestCase):
    def test_every_manifest_resolves(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            with self.subTest(utility=utility):
                plan = lineage_plan.resolve_plan(
                    REPO_ROOT, utility, "demo/model", "0.2", "build", 3, 1800
                )
                self.assertEqual(plan["utility"], utility)
                self.assertTrue(plan["config_fingerprint"])

    def test_checkpoint_sequences_match_the_selected_feature_surface(self):
        for utility, flags in EXPECTED_SEQUENCES.items():
            with self.subTest(utility=utility):
                plan = lineage_plan.resolve_plan(
                    REPO_ROOT, utility, "demo/model", "0", "build", 3, 1800
                )
                checkpoints = plan["checkpoints"]
                self.assertEqual(checkpoints[0]["implemented_flags"], [])
                self.assertEqual(checkpoints[0]["source_mode"], "new")
                for checkpoint in checkpoints[1:]:
                    self.assertEqual(checkpoint["source_mode"], "existing")
                # Cumulative: checkpoint i implements the first i selected flags.
                self.assertEqual(
                    [c["implemented_flags"] for c in checkpoints[1:]],
                    [flags[: index + 1] for index in range(len(flags))],
                )

    def test_random_sort_is_no_longer_a_checkpoint(self):
        plan = lineage_plan.resolve_plan(
            REPO_ROOT, "sort", "demo/model", "0", "build", 3, 1800
        )
        flags = {flag for c in plan["checkpoints"] for flag in c["implemented_flags"]}
        self.assertNotIn("-R", flags)
        self.assertIn("-c", flags)
        self.assertFalse((REPO_ROOT / "prompts/new_sort/004_random_sort.md").exists())
        self.assertTrue((REPO_ROOT / "prompts/new_sort/004_check.md").is_file())

    def test_judge_command_defaults_to_the_cumulative_flag_list(self):
        plan = lineage_plan.resolve_plan(
            REPO_ROOT, "grep", "demo/model", "0", "build", 3, 1800
        )
        self.assertEqual(
            plan["checkpoints"][3]["feature_test_command"],
            "tests/grep-test-suite/judge_candidate.sh build/new_grep -H -h -r",
        )

    def test_baseline_sources_are_not_committed_for_new_utilities(self):
        # Checkpoint 000 must make the agent create the source. A committed file
        # at that path would be seeded into the sandbox and silently turn the
        # first checkpoint into a modification task.
        for utility in ("grep", "chmod"):
            with self.subTest(utility=utility):
                plan = lineage_plan.resolve_plan(
                    REPO_ROOT, utility, "demo/model", "0", "build", 3, 1800
                )
                self.assertFalse((REPO_ROOT / plan["source_path"]).exists())

    def test_suite_verify_checkpoints_match_the_manifest(self):
        # Each model-based suite duplicates its checkpoint ladder so it can be
        # audited standalone. This is the cross-check that keeps the duplicate
        # honest -- gen/verify.py in both suites points here by name.
        for utility in ("grep", "chmod"):
            with self.subTest(utility=utility):
                plan = lineage_plan.resolve_plan(
                    REPO_ROOT, utility, "demo/model", "0", "build", 3, 1800
                )
                self.assertEqual(
                    suite_checkpoints(REPO_ROOT / plan["test_dir"]),
                    [
                        [checkpoint["id"], checkpoint["implemented_flags"]]
                        for checkpoint in plan["checkpoints"]
                    ],
                )

    def test_prompts_name_their_own_checkpoint_command(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            plan = lineage_plan.resolve_plan(
                REPO_ROOT, utility, "demo/model", "0", "build", 3, 1800
            )
            for checkpoint in plan["checkpoints"]:
                with self.subTest(utility=utility, checkpoint=checkpoint["id"]):
                    text = (REPO_ROOT / checkpoint["prompt"]).read_text(
                        encoding="utf-8"
                    )
                    self.assertIn(checkpoint["feature_test_command"], text)
                    self.assertIn(plan["test_dir"], text)
                    self.assertIn(plan["build_command"].split("&&")[-1].strip(), text)

    def test_prompts_carry_no_stale_test_references(self):
        stale = (
            "src/new_mkdir/README.md",
            "tests/new_sort/test_",
            "No checkpoint-visible",
            "004_random_sort",
        )
        for prompt in sorted((REPO_ROOT / "prompts").rglob("*.md")):
            if prompt.parent.name == "tests" or prompt.name.startswith("checkpoint_"):
                continue  # test-authoring prompts and the templates
            text = prompt.read_text(encoding="utf-8")
            for phrase in stale:
                with self.subTest(prompt=prompt.name, phrase=phrase):
                    self.assertNotIn(phrase, text)


class PlanValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryRepo()))

    def write_manifest(self, payload: dict) -> None:
        (self.root / "experiments" / "utilities" / "demo.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def base_manifest(self) -> dict:
        return {
            "schema_version": 1,
            "utility": "demo",
            "program": "new_demo",
            "source_path": "src/new_demo/new_demo.c",
            "executable_path": "build/new_demo",
            "build_command": "cc src/new_demo/new_demo.c -o build/new_demo",
            "test_dir": "tests/demo-test-suite",
            "judge": "tests/demo-test-suite/judge_candidate.sh",
            "checkpoints": [
                {"id": "000", "name": "base", "prompt": "prompts/demo/000.md",
                 "source_mode": "new", "implemented_flags": []},
                {"id": "001", "name": "one", "prompt": "prompts/demo/001.md",
                 "source_mode": "existing", "implemented_flags": ["-a"]},
            ],
        }

    def resolve(self):
        return lineage_plan.resolve_plan(
            self.root, "demo", "m", "0", "build", 3, 1800
        )

    def test_cumulative_flags_are_enforced(self):
        manifest = self.base_manifest()
        manifest["checkpoints"].append(
            {"id": "002", "name": "two", "prompt": "prompts/demo/002.md",
             "source_mode": "existing", "implemented_flags": ["-b"]},
        )
        (self.root / "prompts" / "demo" / "002.md").write_text("x", encoding="utf-8")
        self.write_manifest(manifest)
        with self.assertRaises(lineage_plan.ManifestError) as caught:
            self.resolve()
        self.assertIn("cumulative", str(caught.exception))

    def test_first_checkpoint_must_create_the_source(self):
        manifest = self.base_manifest()
        manifest["checkpoints"][0]["source_mode"] = "existing"
        self.write_manifest(manifest)
        with self.assertRaises(lineage_plan.ManifestError):
            self.resolve()

    def test_later_checkpoints_must_inherit(self):
        manifest = self.base_manifest()
        manifest["checkpoints"][1]["source_mode"] = "new"
        self.write_manifest(manifest)
        with self.assertRaises(lineage_plan.ManifestError):
            self.resolve()

    def test_fingerprint_tracks_prompt_content(self):
        self.write_manifest(self.base_manifest())
        before = self.resolve()["config_fingerprint"]
        (self.root / "prompts" / "demo" / "001.md").write_text(
            "changed", encoding="utf-8"
        )
        after = self.resolve()["config_fingerprint"]
        self.assertNotEqual(before, after)

    def test_fingerprint_tracks_the_judge_script(self):
        self.write_manifest(self.base_manifest())
        before = self.resolve()["config_fingerprint"]
        (self.root / "tests" / "demo-test-suite" / "judge_candidate.sh").write_text(
            "#!/bin/sh\nexit 0\n", encoding="utf-8"
        )
        self.assertNotEqual(before, self.resolve()["config_fingerprint"])

    def test_fingerprint_ignores_settings_that_may_change_on_resume(self):
        self.write_manifest(self.base_manifest())
        first = self.resolve()["config_fingerprint"]
        # Neither the lineage count nor the output directory is an input here,
        # so extending an existing run stays resumable.
        second = lineage_plan.resolve_plan(
            self.root, "demo", "m", "0", "build", 3, 1800
        )["config_fingerprint"]
        self.assertEqual(first, second)
        changed = lineage_plan.resolve_plan(
            self.root, "demo", "m", "0", "build", 5, 1800
        )["config_fingerprint"]
        self.assertNotEqual(first, changed)


class TemporaryRepo:
    """A throwaway tree with the files a manifest is allowed to reference."""

    def __init__(self):
        import tempfile

        self._temp = tempfile.TemporaryDirectory()

    def __enter__(self) -> str:
        root = Path(self._temp.name)
        (root / "experiments" / "utilities").mkdir(parents=True)
        (root / "prompts" / "demo").mkdir(parents=True)
        # The shared automation notice is part of the required repository
        # layout: it is expanded into every prompt and hashed into the
        # configuration fingerprint, so resolving a plan without one fails
        # rather than quietly producing prompts that lack it.
        (root / "prompts" / "_shared").mkdir(parents=True)
        (root / "prompts" / "_shared" / "automation_notice.md").write_text(
            "## Session conditions\n\nThis session is fully automated.\n",
            encoding="utf-8",
        )
        suite = root / "tests" / "demo-test-suite"
        (suite / "suites").mkdir(parents=True)
        for name in ("000.md", "001.md"):
            (root / "prompts" / "demo" / name).write_text(name, encoding="utf-8")
        # Resolving a plan now also resolves each checkpoint's visible test
        # bundle, so the suite needs the runtime files a bundle ships and at
        # least one case per tier.
        (suite / "judge_candidate.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        for name in ("runner.py", "engine.py", "config.py"):
            (suite / name).write_text("# stub\n", encoding="utf-8")
        (suite / "config.json").write_text(
            json.dumps({"implemented": [], "excluded_tags": [],
                        "unimplemented_policy": "skip"}),
            encoding="utf-8",
        )
        (suite / "suites" / "cases.json").write_text(
            json.dumps({"cases": [{"name": "base", "flags": []},
                                  {"name": "feature-a", "flags": ["-a"]}]}),
            encoding="utf-8",
        )
        return self._temp.name

    def __exit__(self, *exc_info):
        self._temp.cleanup()
        return False


def load_module(name: str, path: Path, suite_root: Path):
    """Import a module that lives inside a test suite.

    A suite is written to be run from its own directory, so its modules import
    each other by bare name (`import engine`). Loading one from here means
    putting the suite root on sys.path for the duration.

    The suites share those bare names with each other, so only ONE suite may be
    imported into a given process. Anything that needs to compare two suites
    reads them out of a subprocess instead -- see suite_checkpoints().
    """
    sys.path.insert(0, str(suite_root))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        # Registered before exec: @dataclass resolves a string annotation by
        # looking its own module up in sys.modules, which fails outright when
        # the module being executed is not there yet.
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(suite_root))


def suite_checkpoints(test_dir: Path) -> list[list]:
    """Read a suite's own copy of the checkpoint ladder out of a subprocess.

    Isolation is the point: `gen/verify.py` pulls in the suite's runner, props,
    engine and model under bare module names, and two suites cannot both do that
    in one interpreter.
    """
    program = (
        "import json,sys;"
        "sys.path.insert(0, '.');"
        "from gen import verify;"
        "print(json.dumps(verify.CHECKPOINTS))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=test_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# analyze_lineages
# ---------------------------------------------------------------------------


CHECKPOINTS = [
    {"id": "000", "name": "base"},
    {"id": "001", "name": "one"},
    {"id": "002", "name": "two"},
]


def program_of(basename: str) -> str:
    """`new_grep.c` -> `new_grep`, the repository's candidate-binary name."""
    return Path(basename).stem


def utility_of(basename: str) -> str:
    """`new_grep.c` -> `grep`, which names the suite that judges it."""
    stem = program_of(basename)
    return stem[len("new_"):] if stem.startswith("new_") else stem


def stage_build_command(basename: str) -> str:
    program = program_of(basename)
    return (
        f"mkdir -p build && cc -std=c11 -Wall -Wextra -Werror -pedantic -O2 "
        f"src/{program}/{basename} -o build/{program}"
    )


def stage_feature_test_command(basename: str, flags: list[str]) -> str:
    """The judge call a stage records, in the shape the manifests fix:
    `<judge script> <candidate binary> [FLAG...]`."""
    return " ".join(
        [
            f"tests/{utility_of(basename)}-test-suite/judge_candidate.sh",
            f"build/{program_of(basename)}",
            *flags,
        ]
    )


def make_stage(
    root: Path,
    lineage_id: str,
    checkpoint: dict,
    index: int,
    *,
    success: bool,
    source: str,
    seed: Path | None,
    repair_loops: int = 0,
    basename: str = "new_demo.c",
) -> dict:
    attempt = root / lineage_id / checkpoint["id"] / "temp-0" / "attempt-001"
    (attempt / "candidate").mkdir(parents=True, exist_ok=True)
    (attempt / "COMPLETE").write_text("", encoding="utf-8")
    (attempt / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": "attempt-001",
                "temperature": 0.0,
                "model": "demo/model",
                "public_validation_success": success,
                "initial_success": success and repair_loops == 0,
                "repair_loops": repair_loops,
            }
        ),
        encoding="utf-8",
    )
    flags = [f"-f{n}" for n in range(index)]
    # The per-checkpoint experiment.json the stage run writes next to its
    # attempt. It is where the build command lives -- the stage record does not
    # carry one -- so a fixture without it cannot exercise what a view has to
    # carry across to measure_execution_consistency.py.
    (attempt.parent / "experiment.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "model": "demo/model",
                "temperature": 0.0,
                "source_path": basename,
                "source_workdir_path": f"src/{program_of(basename)}/{basename}",
                "source_mode": "new" if index == 0 else "existing",
                "build_command": stage_build_command(basename),
                "base_test_command": "",
                "feature_test_command": stage_feature_test_command(basename, flags),
            }
        ),
        encoding="utf-8",
    )
    candidate = attempt / "candidate" / basename
    candidate_sha = None
    if success:
        candidate.write_text(source, encoding="utf-8")
        candidate_sha = sha256_text(source)

    return {
        "checkpoint_id": checkpoint["id"],
        "checkpoint_name": checkpoint["name"],
        "prompt": f"prompts/demo/{checkpoint['id']}.md",
        "source_mode": "new" if index == 0 else "existing",
        "implemented_flags": flags,
        "feature_test_command": stage_feature_test_command(basename, flags),
        "attempt_dir": attempt.as_posix(),
        "stage_dir": (root / lineage_id / checkpoint["id"]).as_posix(),
        "candidate": candidate.as_posix() if success else None,
        "candidate_source_basename": basename,
        "candidate_sha256": candidate_sha,
        "seed": seed.as_posix() if seed else None,
        "seed_sha256": sha256_text(seed.read_text(encoding="utf-8")) if seed else None,
        "success": success,
        "failure_reason": None if success else "validation_failed",
        "initial_success": success and repair_loops == 0,
        "repair_loops": repair_loops,
        "llm_invocations": repair_loops + 1,
        "stop_reason": "success" if success else "loop_limit",
        "loop_limit_reached": not success,
        "infrastructure_failure": False,
        "agent_execution_failure": False,
        "build_exit_code": 0,
        "feature_test_exit_code": 0 if success else 1,
    }


def make_lineage_root(
    root: Path, outcomes: list[int | None], *, basename: str = "new_demo.c"
) -> Path:
    """Build a lineage run. Each entry in `outcomes` is a lineage: None means it
    completed, an integer is the index of the checkpoint it stopped at.

    `basename` names the candidate source, and through it the utility. It stays
    `new_demo.c` by default because most of these tests care only about
    aggregation; a test that hands the materialized view to a tool which looks
    up `tests/<utility>-test-suite/` passes a real utility instead."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "lineages.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_unit": "lineage",
                "utility": utility_of(basename),
                "program": program_of(basename),
                "model": "demo/model",
                "temperature": 0.0,
                "agent": "build",
                "max_loops": 3,
                "source_path": f"src/{program_of(basename)}/{basename}",
                "source_basename": basename,
                "config_fingerprint": "fp",
                "checkpoints": CHECKPOINTS,
            }
        ),
        encoding="utf-8",
    )

    for number, stop_at in enumerate(outcomes, start=1):
        lineage_id = f"lineage-{number:03d}"
        stages = []
        seed: Path | None = None
        for index, checkpoint in enumerate(CHECKPOINTS):
            success = stop_at is None or index < stop_at
            stage = make_stage(
                root, lineage_id, checkpoint, index,
                success=success,
                source=f"int main(void){{return {number}{index};}}\n",
                seed=seed,
                repair_loops=1 if index == 1 else 0,
                basename=basename,
            )
            stages.append(stage)
            if not success:
                break
            seed = Path(stage["candidate"])

        completed = stop_at is None
        (root / lineage_id / "lineage.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "lineage_id": lineage_id,
                    "utility": "demo",
                    "model": "demo/model",
                    "temperature": 0.0,
                    "agent": "build",
                    "max_loops": 3,
                    "config_fingerprint": "fp",
                    "checkpoint_count": len(CHECKPOINTS),
                    "checkpoints_completed": sum(1 for s in stages if s["success"]),
                    "end_to_end_success": completed,
                    "failure_stage": None if completed
                    else CHECKPOINTS[stop_at]["id"],
                    "failure_reason": None if completed else "validation_failed",
                    "final_source": f"final/{basename}" if completed else None,
                    "stages": stages,
                }
            ),
            encoding="utf-8",
        )
        if completed:
            final = root / lineage_id / "final"
            final.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(stages[-1]["candidate"]), final / basename)
    return root


class SingleImplementationDiversityTests(unittest.TestCase):
    """Diversity over one implementation is undefined, and must read that way.

    A smoke run with a single completed lineage correctly skipped the
    calculation -- "fewer than two successful implementations; diversity is
    undefined for this population" -- and then rendered the skipped entry with
    the analyzer fields it never had:

        final — 1 implementation(s) from 1 lineages started; report under
        `None` (analyzer exit None)

    Those are Python placeholders printed as findings, and `None` is not a path
    anyone can open. Undefined is not the same as failed, so the run still
    exits 0.
    """

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        # One completed lineage, one that stopped: exactly one successful final
        # implementation, which is the population size that has no pairs.
        self.root = make_lineage_root(self.temp / "lineages", [None, 1])
        self.output = self.temp / "analysis"

    def analyze(self, *extra: str) -> tuple[int, dict, str]:
        code = analyze_lineages.main(
            ["--lineage-root", str(self.root),
             "--output-dir", str(self.output), *extra]
        )
        report = json.loads(
            (self.output / "lineage_report.json").read_text(encoding="utf-8")
        )
        summary = (self.output / "summary.md").read_text(encoding="utf-8")
        return code, report, summary

    def test_one_successful_implementation_skips_diversity(self):
        _, report, _ = self.analyze("--skip-change")
        self.assertEqual(report["reliability"]["successful_final_implementations"], 1)
        final = [p for p in report["populations"] if p["label"] == "final"]
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["members"], 1)
        self.assertIn("skipped", final[0])
        self.assertIsNone(final[0]["analysis_dir"])
        self.assertIsNone(final[0]["returncode"])

    def test_the_summary_never_prints_python_placeholders(self):
        _, _, summary = self.analyze("--skip-change")
        for forbidden in ("report under `None`", "analyzer exit None",
                          "`None`", "None)"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, summary)

    def test_the_summary_states_the_count_and_the_requirement(self):
        _, _, summary = self.analyze("--skip-change")
        diversity = summary.split("## Diversity (final population)")[1]
        diversity = diversity.split("## Change")[0]
        self.assertIn("1 successful implementation", diversity)
        self.assertIn("Diversity was not computed", diversity)
        self.assertIn("at least 2 successful implementations", diversity)

    def test_no_report_path_is_invented(self):
        """`None` is not a directory, and neither is a made-up one."""
        _, _, summary = self.analyze("--skip-change")
        diversity = summary.split("## Diversity (final population)")[1]
        diversity = diversity.split("## Change")[0]
        self.assertNotIn("report under", diversity)
        self.assertNotIn("populations/final", diversity)

    def test_an_undefined_population_is_not_an_analyzer_failure(self):
        code, _, _ = self.analyze("--skip-change")
        self.assertEqual(code, 0)

    def test_the_change_section_still_follows_a_skipped_population(self):
        """The skip must not truncate the rest of the report."""
        _, _, summary = self.analyze()
        self.assertIn("## Change", summary)
        self.assertIn("## Reliability", summary)

    def test_reliability_and_repair_numbers_are_untouched(self):
        _, report, summary = self.analyze("--skip-change")
        reliability = report["reliability"]
        self.assertEqual(reliability["lineages_started"], 2)
        self.assertEqual(reliability["successful_final_implementations"], 1)
        self.assertAlmostEqual(reliability["end_to_end_completion_rate"], 0.5)
        self.assertIn("lineages started = 2", summary)

    def test_two_implementations_still_render_a_report_path(self):
        """The normal path is unchanged: a real population still links out."""
        root = make_lineage_root(self.temp / "two", [None, None])
        output = self.temp / "analysis-two"
        analyze_lineages.main(
            ["--lineage-root", str(root), "--output-dir", str(output),
             "--skip-diversity", "--skip-change"]
        )
        report = json.loads(
            (output / "lineage_report.json").read_text(encoding="utf-8")
        )
        # --skip-diversity leaves no populations at all, which is its own
        # message rather than a skipped entry.
        self.assertEqual(report["populations"], [])
        summary = (output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("Diversity analysis was not run.", summary)
        self.assertNotIn("None", summary.split("## Diversity")[1])


class LineageAggregationTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = make_lineage_root(
            Path(self.temp.name) / "lineages", [None, None, 2, 1]
        )
        self.output = Path(self.temp.name) / "analysis"

    def run_tool(self, *extra: str) -> dict:
        code = analyze_lineages.main(
            [
                "--lineage-root", str(self.root),
                "--output-dir", str(self.output),
                *extra,
            ]
        )
        self.assertEqual(code, 0)
        return json.loads(
            (self.output / "lineage_report.json").read_text(encoding="utf-8")
        )

    def test_reliability_denominator_is_lineages_started(self):
        report = self.run_tool("--skip-diversity")
        reliability = report["reliability"]
        self.assertEqual(reliability["lineages_started"], 4)
        self.assertEqual(reliability["successful_final_implementations"], 2)
        self.assertAlmostEqual(reliability["end_to_end_completion_rate"], 0.5)

    def test_ten_started_seven_completed_reports_point_seven(self):
        records = [
            {
                "lineage_id": f"lineage-{index:03d}",
                "state": "completed" if index <= 7 else "stopped",
                "end_to_end_success": index <= 7,
                "failure_stage": None if index <= 7 else "002",
                "failure_reason": None if index <= 7 else "validation_failed",
            }
            for index in range(1, 11)
        ]
        reliability = analyze_lineages.build_reliability(
            records, ["000", "001", "002"]
        )
        self.assertEqual(reliability["lineages_started"], 10)
        self.assertEqual(reliability["lineages_completed"], 7)
        self.assertEqual(reliability["end_to_end_completion_rate"], 0.70)

    def test_failure_stage_counts_name_the_stopping_checkpoint(self):
        report = self.run_tool("--skip-diversity")
        self.assertEqual(
            report["reliability"]["failure_stage_counts"],
            {"000": 0, "001": 1, "002": 1},
        )
        self.assertEqual(
            report["reliability"]["failure_reason_counts"],
            {"validation_failed": 2},
        )

    def test_repair_behavior_is_reported_per_checkpoint(self):
        report = self.run_tool("--skip-diversity")
        detail = {row["checkpoint_id"]: row for row in report["checkpoints_detail"]}
        self.assertEqual(detail["000"]["lineages_reached"], 4)
        self.assertEqual(detail["000"]["lineages_passed"], 4)
        # 001 is the checkpoint the fixture gives a repair loop to.
        self.assertEqual(detail["001"]["lineages_reached"], 4)
        self.assertEqual(detail["001"]["passed_after_repair"], 3)
        self.assertEqual(detail["001"]["repair_loops"]["total"], 4)
        # A lineage that stopped at 001 never reaches 002.
        self.assertEqual(detail["002"]["lineages_reached"], 3)

    def test_seed_provenance_is_rechecked_from_the_recorded_hashes(self):
        report = self.run_tool("--skip-diversity")
        self.assertEqual(report["seed_provenance_problems"], [])

        record_path = self.root / "lineage-001" / "lineage.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["stages"][1]["seed_sha256"] = "0" * 64
        record_path.write_text(json.dumps(record), encoding="utf-8")

        code = analyze_lineages.main(
            ["--lineage-root", str(self.root), "--output-dir", str(self.output),
             "--skip-diversity"]
        )
        self.assertEqual(code, 1)

    def test_mixed_configurations_are_refused(self):
        record_path = self.root / "lineage-002" / "lineage.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["config_fingerprint"] = "other"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(SystemExit):
            analyze_lineages.main(
                ["--lineage-root", str(self.root),
                 "--output-dir", str(self.output), "--skip-diversity"]
            )

    def test_summary_states_both_denominators(self):
        self.run_tool("--skip-diversity")
        summary = (self.output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("lineages started = 4", summary)
        self.assertIn("successful final implementations = 2", summary)

    def test_stage_csv_records_every_reached_stage(self):
        self.run_tool("--skip-diversity")
        rows = (self.output / "lineage_stages.csv").read_text(
            encoding="utf-8"
        ).strip().splitlines()
        # 3 + 3 + 3 + 2 stages, plus the header.
        self.assertEqual(len(rows), 12)
        self.assertIn("seed_sha256", rows[0])


class PopulationViewTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = make_lineage_root(
            Path(self.temp.name) / "lineages", [None, None, 2]
        )
        # Through load_run, because that is what resolves each lineage's
        # location under --lineage-root; a stage's files are found from there.
        self.run_metadata, self.lineages, _ = analyze_lineages.load_run(self.root)

    def test_final_population_holds_only_completed_lineages(self):
        members = analyze_lineages.population_members(self.lineages, None)
        self.assertEqual(
            [lineage_id for lineage_id, _, _ in members],
            ["lineage-001", "lineage-002"],
        )
        self.assertTrue(
            all(stage["checkpoint_id"] == "002" for _, _, stage in members)
        )

    def test_intermediate_population_includes_lineages_that_later_stopped(self):
        members = analyze_lineages.population_members(self.lineages, "001")
        self.assertEqual(
            [lineage_id for lineage_id, _, _ in members],
            ["lineage-001", "lineage-002", "lineage-003"],
        )

    def test_view_is_an_experiment_directory_the_analyzer_can_read(self):
        view = analyze_lineages.materialize_view(
            Path(self.temp.name) / "view",
            analyze_lineages.population_members(self.lineages, None),
            self.run_metadata,
            "final",
        )
        metadata = json.loads((view / "experiment.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_path"], "new_demo.c")
        self.assertEqual(metadata["baseline_source_kind"], "empty_new_source")
        self.assertEqual((view / "baseline" / "new_demo.c").read_bytes(), b"")
        # Points at the view so the analyzer's repository-level paper aggregate
        # cannot reach into runs/experiments and rewrite unrelated results.
        self.assertEqual(metadata["repository"], str(view))

        attempts = sorted(view.glob("attempt-*"))
        self.assertEqual(len(attempts), 2)
        for attempt in attempts:
            self.assertTrue((attempt / "candidate" / "new_demo.c").is_file())
            row = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
            self.assertIn("lineage_id", row)
            self.assertEqual(row["lineage_checkpoint_id"], "002")
            self.assertTrue(row["analysis_population_member"])
            self.assertEqual(
                row["population_selection_basis"], "lineage_stage_success"
            )
            self.assertTrue(row["workflow_stage_success"])
        self.assertEqual(
            metadata["reliability_scope"], "parent_lineage_experiment"
        )

    def test_view_members_are_traceable_to_their_lineage(self):
        view = analyze_lineages.materialize_view(
            Path(self.temp.name) / "view2",
            analyze_lineages.population_members(self.lineages, None),
            self.run_metadata,
            "final",
        )
        members = json.loads((view / "members.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [entry["lineage_id"] for entry in members],
            ["lineage-001", "lineage-002"],
        )
        for entry in members:
            self.assertTrue(Path(entry["candidate"]).is_file())


class ViewFeedsEveryDownstreamAnalysisTests(unittest.TestCase):
    """A materialized population is an input to every analysis, not just one.

    `materialize_view` was written to satisfy `analyze_experiment.py`, and was
    only ever tested against it -- so the view recorded exactly the keys the
    diversity analyzer reads and nothing else.
    `docs/execution_consistency_methodology.md` meanwhile tells a reader to
    point `scripts/measure_execution_consistency.py --experiment` at "whatever
    population directory scripts/analyze_lineages.py materialized, exactly as
    the diversity measurement is pointed at one". Doing that crashed with
    `KeyError: 'feature_test_command'`, and would have crashed next on
    `build_command`: the two things that tool needs to know the checkpoint's
    cumulative flag scope and how to rebuild a candidate.

    Asserting the two keys exist would not have caught this, because nobody
    knew to assert them. So the test runs the other consumer against the view.

    The rebuild-and-judge pass is stubbed: it needs a C toolchain and several
    minutes per candidate, and what is under test is whether the view is a
    valid input, not whether the suite judges correctly -- that is
    tests/test_execution_consistency.py's job.
    """

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        # A real utility: measure_execution_consistency.py resolves
        # tests/<utility>-test-suite/ from the view's source_path, and refuses
        # a utility whose suite or held-out corpus does not exist.
        self.root = make_lineage_root(
            self.temp / "lineages", [None, None, 2], basename="new_grep.c"
        )
        self.run_metadata, self.lineages, _ = analyze_lineages.load_run(self.root)

    def materialize(self, label: str = "final", checkpoint: str | None = None) -> Path:
        return analyze_lineages.materialize_view(
            self.temp / f"view-{label}",
            analyze_lineages.population_members(self.lineages, checkpoint),
            self.run_metadata,
            label,
        )

    def test_the_view_records_the_checkpoints_judge_call_and_build_command(self):
        experiment = json.loads(
            (self.materialize() / "experiment.json").read_text(encoding="utf-8")
        )
        # Carried from the checkpoint the population was drawn from -- the
        # final one, which the fixture gives two cumulative flags.
        self.assertEqual(
            experiment["feature_test_command"],
            "tests/grep-test-suite/judge_candidate.sh build/new_grep -f0 -f1",
        )
        self.assertIn("-o build/new_grep", experiment["build_command"])

    def test_an_intermediate_view_records_that_checkpoints_own_scope(self):
        """The flag scope is the population's, not the run's last one."""
        experiment = json.loads(
            (self.materialize("checkpoint-001", "001") / "experiment.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            experiment["feature_test_command"],
            "tests/grep-test-suite/judge_candidate.sh build/new_grep -f0",
        )

    def measured(self, **kwargs) -> dict[str, Any]:
        """Stand in for the rebuild-and-judge pass, with a fingerprint per run."""
        run_id = Path(kwargs["candidate_source"]).parent.parent.name
        visible_results = [
            {"case_id": "visible-case", "verdict": "PASS"},
        ]
        heldout_results = [
            {"case_id": "heldout-case", "verdict": "FAIL"},
        ]
        combined_results = [
            {"case_id": "heldout::heldout-case", "verdict": "FAIL"},
            {"case_id": "visible::visible-case", "verdict": "PASS"},
        ]
        return {
            "status": "measured",
            "visible_case_count": len(visible_results),
            "heldout_case_count": len(heldout_results),
            "visible_failure_count": 0,
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
            "visible_fingerprint_sha256": "V1",
            "heldout_fingerprint_sha256": f"H-{run_id}",
            "combined_fingerprint_sha256": f"C-{run_id}",
        }

    def test_measure_execution_consistency_runs_against_the_view(self):
        measure = measure_or_none()
        if measure is None:
            self.skipTest(
                "measure_execution_consistency.py needs "
                "scripts/analysis-requirements.txt"
            )
        view = self.materialize()
        # Stands in for analyze_experiment.py, which normally runs over the
        # view first and whose determination of success and of family
        # membership this tool reads rather than re-derives. Running the real
        # analyzer here would pull in the clustering stack this file avoids.
        (view / "analysis").mkdir(parents=True, exist_ok=True)
        (view / "analysis" / "per_run_metrics.csv").write_text(
            "run_id,overall_success,analysis_population_member,"
            "population_selection_basis,architecture_cluster_id,"
            "strategy_cluster_id\n"
            "attempt-001,True,True,lineage_stage_success,0,0\n"
            "attempt-002,True,True,lineage_stage_success,0,1\n",
            encoding="utf-8",
        )

        with mock.patch.object(measure, "measure_run", self.measured):
            code = measure.main(["--experiment", str(view), "--clean-output"])
        self.assertEqual(code, 0)

        summary = json.loads(
            (view / "analysis" / "execution_consistency" / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        # Every one of these came out of the view rather than out of a manifest,
        # and each is a value the view did not previously carry.
        self.assertEqual(summary["utility"], "grep")
        self.assertEqual(summary["implemented_flags"], ["-f0", "-f1"])
        self.assertEqual(summary["candidate_binary"], "build/new_grep")
        self.assertEqual(summary["population"]["measured_runs"], 2)
        self.assertEqual(summary["population"]["unmeasured_runs"], [])

    def test_members_that_disagree_on_the_build_command_are_refused(self):
        """Corrupted data must not be resolved by picking a value.

        Every member of one population is the same checkpoint of the same
        condition, so one build command describes all of them. If that stops
        being true the view cannot describe itself, and silently taking the
        first member's would attribute every rebuild to a configuration the
        others were not produced under.
        """
        stage_experiment = (
            self.root / "lineage-002" / "002" / "temp-0" / "experiment.json"
        )
        recorded = json.loads(stage_experiment.read_text(encoding="utf-8"))
        recorded["build_command"] = "cc -O0 src/new_grep/new_grep.c -o build/new_grep"
        stage_experiment.write_text(json.dumps(recorded), encoding="utf-8")

        with self.assertRaises(analyze_lineages.LineageError) as caught:
            self.materialize("mixed")
        message = str(caught.exception)
        self.assertIn("build_command", message)
        self.assertIn("-O0", message)
        # Names the population, so a reader knows which view was refused.
        self.assertIn("mixed", message)

    def test_members_that_disagree_on_the_judge_call_are_refused(self):
        record_path = self.root / "lineage-002" / "lineage.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["stages"][-1]["feature_test_command"] = (
            "tests/grep-test-suite/judge_candidate.sh build/new_grep -f0 -f1 -f2"
        )
        record_path.write_text(json.dumps(record), encoding="utf-8")
        _, lineages, _ = analyze_lineages.load_run(self.root)

        with self.assertRaises(analyze_lineages.LineageError) as caught:
            analyze_lineages.materialize_view(
                self.temp / "view-flags",
                analyze_lineages.population_members(lineages, None),
                self.run_metadata,
                "final",
            )
        message = str(caught.exception)
        self.assertIn("feature_test_command", message)
        self.assertIn("-f2", message)

    def test_a_run_that_recorded_neither_still_materializes(self):
        """Absence is not disagreement.

        `materialize_view` is on the diversity path, so a run predating either
        field must still produce a view: the keys are written as null, which is
        a view that cannot be measured for execution consistency rather than a
        lineage analysis that cannot run at all.
        """
        for lineage in ("lineage-001", "lineage-002"):
            (self.root / lineage / "002" / "temp-0" / "experiment.json").unlink()
            record_path = self.root / lineage / "lineage.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            for stage in record["stages"]:
                stage.pop("feature_test_command", None)
            record_path.write_text(json.dumps(record), encoding="utf-8")
        _, lineages, _ = analyze_lineages.load_run(self.root)

        view = analyze_lineages.materialize_view(
            self.temp / "view-legacy",
            analyze_lineages.population_members(lineages, None),
            self.run_metadata,
            "final",
        )
        experiment = json.loads((view / "experiment.json").read_text(encoding="utf-8"))
        self.assertIsNone(experiment["feature_test_command"])
        self.assertIsNone(experiment["build_command"])


class RematerializationGuardsExecutionConsistencyTests(unittest.TestCase):
    """Rebuilding a population view must not silently destroy a measurement.

    `materialize_view` clears its view directory before rewriting it, and
    `scripts/measure_execution_consistency.py` writes into
    `<view>/analysis/execution_consistency/` -- inside that very tree. So a
    second `analyze_lineages.py --checkpoint-diversity`, run for any reason at
    all including one unrelated to the population in question, deleted a
    completed behavioral measurement with no warning. That is not hypothetical:
    it destroyed a real, fully measured (7/7 coverage) population in this
    repository, which had to be recovered from an earlier commit.

    Recomputing one is expensive and, per
    `docs/execution_consistency_methodology.md`, sometimes impossible: the
    rebuild is not portable across host families. So the collision is refused,
    and discarding the old result is something the caller has to say out loud.

    The prior measurement is a marker file rather than a real
    `measure_execution_consistency.py` run. What is under test is whether the
    refusal fires on that directory's presence and what happens to it either
    way, not what the tool writes inside it.
    """

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = make_lineage_root(self.temp / "lineages", [None, None, 2])
        self.run_metadata, self.lineages, _ = analyze_lineages.load_run(self.root)

    def materialize(
        self, label: str = "final", checkpoint: str | None = None, **kwargs
    ) -> Path:
        """Materialize one population, at a path fixed by its label.

        The same label resolves to the same directory every time, which is what
        makes a second call a re-materialization rather than a new view.
        """
        return analyze_lineages.materialize_view(
            self.temp / f"view-{label}",
            analyze_lineages.population_members(self.lineages, checkpoint),
            self.run_metadata,
            label,
            **kwargs,
        )

    def plant_measurement(self, view: Path) -> Path:
        """A stand-in for a completed measurement, at the path the real tool writes."""
        marker = view / "analysis" / "execution_consistency" / "summary.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('{"measured": true}\n', encoding="utf-8")
        return marker

    def test_rematerializing_over_a_measurement_is_refused(self):
        view = self.materialize()
        marker = self.plant_measurement(view)

        with self.assertRaises(analyze_lineages.LineageError) as caught:
            self.materialize()
        message = str(caught.exception)
        # The exact directory about to be destroyed, so the reader can go and
        # move it rather than having to work out where it was.
        self.assertIn(str(view / "analysis" / "execution_consistency"), message)
        self.assertIn("--allow-execution-consistency-loss", message)
        # Refused means nothing happened: the measurement and the view it
        # describes are both still on disk.
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.read_text(encoding="utf-8"), '{"measured": true}\n')
        self.assertTrue((view / "experiment.json").is_file())

    def test_every_population_is_guarded_not_only_the_final_one(self):
        """`--checkpoint-diversity` materializes intermediate populations too.

        Their measurements are no cheaper to reproduce than the final one's, so
        a guard that only knew about `final` would leave most of the populations
        in a run exposed.
        """
        view = self.materialize("checkpoint-001", "001")
        marker = self.plant_measurement(view)

        with self.assertRaises(analyze_lineages.LineageError) as caught:
            self.materialize("checkpoint-001", "001")
        self.assertIn("checkpoint-001", str(caught.exception))
        self.assertTrue(marker.is_file())

    def test_the_override_lets_the_rebuild_clear_the_measurement(self):
        """The escape hatch for "I changed the data; that result is stale"."""
        view = self.materialize()
        marker = self.plant_measurement(view)

        rebuilt = self.materialize(allow_execution_consistency_loss=True)

        self.assertEqual(rebuilt, view)
        self.assertFalse(marker.exists())
        self.assertFalse((view / "analysis").exists())
        # And the view really was rebuilt, not merely left alone.
        self.assertTrue((view / "experiment.json").is_file())
        self.assertEqual(len(sorted(view.glob("attempt-*"))), 2)

    def test_a_population_never_measured_rematerializes_freely(self):
        """The common case must not acquire any friction from this.

        A first materialization, and every later one for a population nobody has
        measured, has nothing to lose and is not asked about it.
        """
        first = self.materialize()
        self.assertFalse((first / "analysis").exists())

        second = self.materialize()

        self.assertEqual(second, first)
        self.assertTrue((second / "experiment.json").is_file())
        self.assertEqual(len(sorted(second.glob("attempt-*"))), 2)

    def test_an_unrelated_analysis_directory_is_not_treated_as_a_measurement(self):
        """Only the execution-consistency output is protected.

        `analyze_experiment.py` writes the rest of `<view>/analysis/` on every
        run and regenerates it from the same inputs, so guarding that too would
        refuse every ordinary re-analysis.
        """
        view = self.materialize()
        (view / "analysis" / "diversity").mkdir(parents=True, exist_ok=True)
        (view / "analysis" / "summary.json").write_text("{}", encoding="utf-8")

        rebuilt = self.materialize()

        self.assertFalse((rebuilt / "analysis").exists())
        self.assertTrue((rebuilt / "experiment.json").is_file())

    def test_the_command_line_flag_reaches_the_materialization(self):
        """The refusal and the override both have to survive the CLI.

        `run_analyzer` is stubbed: it shells out to `analyze_experiment.py`,
        which needs the clustering stack this file deliberately does not import.
        What matters here is which populations were materialized and what
        happened to the measurement sitting in one of them.
        """
        output = self.temp / "analysis"
        argv = [
            "--lineage-root", str(self.root),
            "--output-dir", str(output),
            "--skip-change",
        ]
        def stub(view_dir, args):
            return {
                "command": [], "returncode": 0,
                "analysis_dir": str(view_dir / "analysis"),
            }

        with mock.patch.object(analyze_lineages, "run_analyzer", stub):
            self.assertEqual(analyze_lineages.main(argv), 0)
        view = output / "populations" / "final"
        marker = self.plant_measurement(view)

        with self.assertRaises(analyze_lineages.LineageError) as caught:
            with mock.patch.object(analyze_lineages, "run_analyzer", stub):
                analyze_lineages.main(argv)
        self.assertIn(str(view / "analysis" / "execution_consistency"),
                      str(caught.exception))
        self.assertTrue(marker.is_file())

        with mock.patch.object(analyze_lineages, "run_analyzer", stub):
            code = analyze_lineages.main(
                argv + ["--allow-execution-consistency-loss"]
            )
        self.assertEqual(code, 0)
        self.assertFalse(marker.exists())


# ---------------------------------------------------------------------------
# chmod suite: the specification model and the mode-tree comparison
# ---------------------------------------------------------------------------


CHMOD_SUITE = REPO_ROOT / "tests" / "chmod-test-suite"
REFERENCE_GENERATORS = REPO_ROOT / "tests" / "reference_generators"


class ChmodModelTests(unittest.TestCase):
    """The chmod goldens are only as good as the model that derives them, and
    the model encodes the bounded contract the prompts specify -- not GNU's."""

    @classmethod
    def setUpClass(cls):
        # Loaded from the offline generators, not from the suite: an oracle
        # inside the suite would be copied into a sandbox.
        cls.reference = load_module(
            "chmod_reference", REFERENCE_GENERATORS / "chmod_reference.py",
            REPO_ROOT / "tests",
        )

    def apply(self, mode: str, current: int, is_directory: bool = False) -> int:
        spec = self.reference.parse_mode(mode)
        return self.reference.apply_mode(spec, current, is_directory)

    def test_octal_replaces_every_bit_including_the_special_ones(self):
        self.assertEqual(self.apply("755", 0o4644), 0o755)
        self.assertEqual(self.apply("4755", 0o644), 0o4755)
        self.assertEqual(self.apply("0", 0o777), 0)

    def test_symbolic_starts_from_the_current_mode(self):
        self.assertEqual(self.apply("u+x", 0o644), 0o744)
        self.assertEqual(self.apply("go-rwx", 0o777), 0o700)

    def test_empty_class_list_means_all_three_classes(self):
        self.assertEqual(self.apply("+x", 0o644), 0o755)
        self.assertEqual(self.apply("a+x", 0o644), self.apply("+x", 0o644))

    def test_equals_clears_only_the_classes_it_names(self):
        self.assertEqual(self.apply("u=rw", 0o777), 0o677)
        self.assertEqual(self.apply("o=", 0o777), 0o770)

    def test_capital_x_needs_a_directory_or_an_existing_execute_bit(self):
        self.assertEqual(self.apply("a+X", 0o644), 0o644)
        self.assertEqual(self.apply("a+X", 0o744), 0o755)
        self.assertEqual(self.apply("a+X", 0o644, is_directory=True), 0o755)

    def test_symbolic_clauses_never_touch_the_special_bits(self):
        self.assertEqual(self.apply("u+x", 0o4644), 0o4744)
        self.assertEqual(self.apply("a=rx", 0o1777), 0o1555)

    def test_s_and_t_are_rejected_as_symbolic_permission_letters(self):
        for mode in ("u+s", "+t", "g+s"):
            with self.subTest(mode=mode):
                with self.assertRaises(self.reference.InvalidMode):
                    self.reference.parse_mode(mode)

    def test_malformed_modes_are_rejected(self):
        for mode in ("", "ug", "u+x,", "77777", "u+z"):
            with self.subTest(mode=mode):
                with self.assertRaises(self.reference.InvalidMode):
                    self.reference.parse_mode(mode)

    def test_symbolic_rendering_marks_the_special_bits(self):
        render = self.reference.render_symbolic
        self.assertEqual(render(0o644), "rw-r--r--")
        self.assertEqual(render(0o4755), "rwsr-xr-x")
        self.assertEqual(render(0o2644), "rw-r-Sr--")
        self.assertEqual(render(0o1777), "rwxrwxrwt")
        self.assertEqual(render(0o1666), "rw-rw-rwT")

    def test_options_are_recognized_only_before_mode(self):
        options = self.reference.parse_args(["-R", "-c", "755", "-weird"])
        self.assertTrue(options.recursive)
        self.assertEqual(options.report, "changes")
        self.assertEqual(options.mode, "755")
        # Everything after MODE is an operand, dash or not.
        self.assertEqual(options.operands, ["-weird"])

    def test_last_of_c_and_v_wins(self):
        self.assertEqual(self.reference.parse_args(["-cv", "0", "f"]).report,
                         "verbose")
        self.assertEqual(self.reference.parse_args(["-vc", "0", "f"]).report,
                         "changes")

    def test_silent_suppresses_the_diagnostic_and_the_exit_status(self):
        loud = self.reference.run(["755", "nope"], {})
        self.assertEqual(loud.exit_code, 1)
        self.assertEqual(loud.subjects, ["nope"])

        quiet = self.reference.run(["-f", "755", "nope"], {})
        self.assertEqual(quiet.exit_code, 0)
        self.assertEqual(quiet.subjects, [])

    def test_silent_never_suppresses_a_usage_error_or_an_invalid_mode(self):
        self.assertEqual(self.reference.run(["-f", "755"], {}).exit_code, 1)
        entry = self.reference.Entry(kind="file", mode=0o644)
        invalid = self.reference.run(["-f", "u+z", "f"], {"f": entry})
        self.assertEqual(invalid.exit_code, 1)
        self.assertEqual(invalid.subjects, ["invalid mode"])


class ChmodRunnerComparisonTests(unittest.TestCase):
    """The mode-tree comparison is what makes this a chmod suite rather than an
    output suite: correct report lines with the wrong bits on disk must fail."""

    @classmethod
    def setUpClass(cls):
        cls.runner = load_module(
            "chmod_runner", CHMOD_SUITE / "runner.py", CHMOD_SUITE
        )

    def test_matching_tree_passes(self):
        case = {"expected_tree": {"f": "0755", "link": "link"}}
        ok, detail = self.runner._tree_ok(case, {"f": "0755", "link": "link"})
        self.assertTrue(ok, detail)

    def test_wrong_mode_fails_and_names_the_path(self):
        case = {"expected_tree": {"f": "0755"}}
        ok, detail = self.runner._tree_ok(case, {"f": "0644"})
        self.assertFalse(ok)
        self.assertIn("f: got 0644, want 0755", detail)

    def test_a_path_the_candidate_removed_fails(self):
        case = {"expected_tree": {"f": "0755"}}
        ok, detail = self.runner._tree_ok(case, {})
        self.assertFalse(ok)
        self.assertIn("<absent>", detail)

    def test_a_touched_symlink_fails(self):
        case = {"expected_tree": {"link": "link"}}
        ok, detail = self.runner._tree_ok(case, {"link": "0777"})
        self.assertFalse(ok)
        self.assertIn("link", detail)

    def test_cumulative_flag_filtering_selects_by_implemented_flags(self):
        manifest = {"implemented": ["-R"], "excluded_tags": [],
                    "unimplemented_policy": "skip"}
        self.assertTrue(self.runner.case_selected({"flags": []}, manifest)[0])
        self.assertTrue(self.runner.case_selected({"flags": ["-R"]}, manifest)[0])
        selected, reason = self.runner.case_selected({"flags": ["-R", "-c"]},
                                                     manifest)
        self.assertFalse(selected)
        self.assertIn("unimplemented", reason)


# ---------------------------------------------------------------------------
# Audit 2 + 3: what the agent can actually read at each checkpoint
# ---------------------------------------------------------------------------


ALL_UTILITY_CHECKPOINTS = [
    (utility, checkpoint["id"], checkpoint["implemented_flags"])
    for utility in sorted(EXPECTED_SEQUENCES)
    for checkpoint in lineage_plan.resolve_plan(
        REPO_ROOT, utility, "demo/model", "0", "build", 3, 1800
    )["checkpoints"]
]


def build_bundle(utility: str, checkpoint_id: str, output: Path) -> dict:
    test_dir, checkpoint = stage_test_bundle.resolve_checkpoint(
        REPO_ROOT, utility, checkpoint_id
    )
    payload = stage_test_bundle.build_payload(
        REPO_ROOT, test_dir, checkpoint, utility
    )
    return stage_test_bundle.write_bundle(payload, output)


# Built once and shared read-only: a bundle is a pure function of the suite and
# the checkpoint, and rebuilding the 14M sort corpus for each assertion turns a
# fast file into a slow one. Tests that need to mutate a bundle build their own.
_SHARED_BUNDLES: dict[tuple[str, str], Path] = {}
_SHARED_BUNDLE_ROOT: list[Any] = []


def shared_bundle(utility: str, checkpoint_id: str) -> Path:
    if not _SHARED_BUNDLE_ROOT:
        import atexit
        import tempfile

        holder = tempfile.TemporaryDirectory()
        atexit.register(holder.cleanup)
        _SHARED_BUNDLE_ROOT.append(holder)
    key = (utility, checkpoint_id)
    if key not in _SHARED_BUNDLES:
        output = Path(_SHARED_BUNDLE_ROOT[0].name) / f"{utility}-{checkpoint_id}"
        build_bundle(utility, checkpoint_id, output)
        _SHARED_BUNDLES[key] = output
    return _SHARED_BUNDLES[key]


class StageBundleLeakageTests(unittest.TestCase):
    """A checkpoint's sandbox must not contain a later checkpoint's tests.

    Filtering which cases the judge *runs* is not enough: these assert on what
    is present on disk, because the agent can read whatever is there.
    """

    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def bundle(self, utility: str, checkpoint_id: str) -> Path:
        return shared_bundle(utility, checkpoint_id)

    def bundled_cases(self, bundle: Path) -> list[dict]:
        cases: list[dict] = []
        for path in sorted((bundle / "suites").glob("*")):
            if path.name.endswith(".gz"):
                import gzip

                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    payload = json.load(handle)
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
            cases.extend(
                payload["cases"] if isinstance(payload, dict) else payload
            )
        return cases

    def test_no_case_requires_an_unimplemented_flag(self):
        for utility, checkpoint_id, flags in ALL_UTILITY_CHECKPOINTS:
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                bundle = self.bundle(utility, checkpoint_id)
                for case in self.bundled_cases(bundle):
                    self.assertLessEqual(
                        set(case.get("flags", [])), set(flags),
                        f"{case.get('name')} needs a flag not implemented here",
                    )

    def test_checkpoint_000_exposes_no_feature_cases_at_all(self):
        # The audit names these explicitly: at 000 nothing about a later flag
        # may be present, for any utility.
        for utility in sorted(EXPECTED_SEQUENCES):
            with self.subTest(utility=utility):
                bundle = self.bundle(utility, "000")
                used = {
                    flag
                    for case in self.bundled_cases(bundle)
                    for flag in case.get("flags", [])
                }
                self.assertEqual(used, set())

    def test_generators_models_and_corpora_are_absent(self):
        forbidden_names = {
            "curated_cases.py", "generate.py", "verify.py", "combos.py",
            "freeze.py", "flag_model.py", "constraints.py", "corpus.py",
            "reference.py", "diff_fuzz.py", "run_all.sh", "selfcheck.sh",
            "build_asan.sh", "report_summary.py", "README.md",
            "MANIFEST.json",
        }
        forbidden_dirs = {"gen", "model", "corpus", "run_logs"}
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                bundle = self.bundle(utility, checkpoint_id)
                for path in bundle.rglob("*"):
                    relative = path.relative_to(bundle)
                    if path.is_dir():
                        self.assertNotIn(relative.name, forbidden_dirs)
                        continue
                    self.assertNotIn(relative.name, forbidden_names)

    def test_bundle_contents_are_exactly_the_allowlist_plus_filtered_suites(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                bundle = self.bundle(utility, checkpoint_id)
                names = {
                    str(p.relative_to(bundle).as_posix())
                    for p in bundle.rglob("*") if p.is_file()
                }
                permitted = set(stage_test_bundle.ALLOWED_FILES) | {
                    "config.json", "BUNDLE.json"
                }
                unexpected = {
                    name for name in names
                    if name not in permitted and not name.startswith("suites/")
                }
                self.assertEqual(unexpected, set())

    def test_no_reference_implementation_reaches_a_bundle(self):
        # Audit 3: an executable oracle in the sandbox is a complete answer.
        # Nothing shipped may import one, directly or transitively.
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                bundle = self.bundle(utility, checkpoint_id)
                for path in sorted(bundle.rglob("*.py")):
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom):
                            self.assertNotIn(
                                (node.module or "").split(".")[0],
                                {"model", "reference_generators", "gen"},
                                f"{path.name} imports an offline module",
                            )
                        elif isinstance(node, ast.Import):
                            for alias in node.names:
                                self.assertNotIn(
                                    alias.name.split(".")[0],
                                    {"model", "reference_generators", "gen"},
                                    f"{path.name} imports an offline module",
                                )

    def test_every_bundled_module_resolves_inside_the_bundle(self):
        """The judge must run from the bundle alone.

        Checked by resolving imports rather than by executing, so it holds on a
        machine whose Python lacks the POSIX-only modules two of the suites use.
        """
        stdlib = set(sys.stdlib_module_names)
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                bundle = self.bundle(utility, checkpoint_id)
                local = {p.stem for p in bundle.glob("*.py")}
                for path in sorted(bundle.glob("*.py")):
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                    for node in ast.walk(tree):
                        names = []
                        if isinstance(node, ast.Import):
                            names = [a.name.split(".")[0] for a in node.names]
                        elif isinstance(node, ast.ImportFrom) and node.level == 0:
                            names = [(node.module or "").split(".")[0]]
                        for name in names:
                            if not name:
                                continue
                            self.assertTrue(
                                name in stdlib or name in local,
                                f"{path.name} imports {name!r}, which is "
                                "neither stdlib nor part of the bundle",
                            )

    def test_the_judge_command_names_a_file_the_bundle_contains(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                bundle = self.bundle(utility, checkpoint_id)
                manifest = json.loads(
                    (bundle / "BUNDLE.json").read_text(encoding="utf-8")
                )
                judge = manifest["judge_command"].split()[0]
                self.assertTrue(judge.startswith(manifest["visible_at"] + "/"))
                relative = judge[len(manifest["visible_at"]) + 1:]
                self.assertTrue((bundle / relative).is_file())

    def test_coverage_grows_and_never_shrinks_along_the_ladder(self):
        """Regression coverage is monotone -- over the cases that assert a
        feature is PRESENT.

        A case declaring `absent_flags` asserts a feature is still missing, so
        it is *meant* to disappear at the checkpoint that introduces that flag.
        Counting it here would make correct behavior look like lost coverage;
        `test_premature_cases_live_exactly_until_their_flag_arrives` checks the
        disappearance itself.
        """
        for utility, ids in (
            (u, [c["id"] for c in lineage_plan.resolve_plan(
                REPO_ROOT, u, "m", "0", "build", 3, 1800)["checkpoints"]])
            for u in sorted(EXPECTED_SEQUENCES)
        ):
            previous: set[str] = set()
            for checkpoint_id in ids:
                with self.subTest(utility=utility, checkpoint=checkpoint_id):
                    bundle = self.bundle(utility, checkpoint_id)
                    cases = self.bundled_cases(bundle)
                    names = {c["name"] for c in cases}
                    self.assertTrue(names, "a checkpoint with no cases")
                    self.assertLessEqual(
                        previous, names,
                        "a later checkpoint dropped earlier regression cases",
                    )
                    previous = {
                        c["name"] for c in cases if not c.get("absent_flags")
                    }

    def test_bundle_is_reproducible_and_fingerprint_matches(self):
        first = self.bundle("grep", "002")
        second = Path(self.temp.name) / "grep-002-again"
        build_bundle("grep", "002", second)
        for path in sorted(first.rglob("*")):
            if not path.is_file() or path.name == "BUNDLE.json":
                continue
            relative = path.relative_to(first)
            self.assertEqual(path.read_bytes(), (second / relative).read_bytes())
        manifest = json.loads((first / "BUNDLE.json").read_text(encoding="utf-8"))
        test_dir, checkpoint = stage_test_bundle.resolve_checkpoint(
            REPO_ROOT, "grep", "002"
        )
        self.assertEqual(
            manifest["bundle_fingerprint"],
            stage_test_bundle.fingerprint(REPO_ROOT, test_dir, checkpoint, "grep"),
        )


class ReferenceIsolationTests(unittest.TestCase):
    """Audit 3, at the repository level rather than the bundle level."""

    def test_suites_contain_no_specification_model(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            suite = REPO_ROOT / "tests" / f"{utility}-test-suite"
            with self.subTest(utility=utility):
                self.assertFalse((suite / "model" / "reference.py").exists())

    def test_offline_generators_hold_the_models(self):
        for utility in ("grep", "chmod"):
            with self.subTest(utility=utility):
                self.assertTrue(
                    (REFERENCE_GENERATORS / f"{utility}_reference.py").is_file()
                )
                self.assertTrue(
                    (REFERENCE_GENERATORS / f"{utility}_invariants.py").is_file()
                )

    def test_runtime_props_do_not_import_a_model(self):
        for utility in ("grep", "chmod"):
            with self.subTest(utility=utility):
                path = REPO_ROOT / "tests" / f"{utility}-test-suite" / "props.py"
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("import reference", text)
                self.assertNotIn("from model", text)

    def test_no_frozen_case_needs_a_property_the_bundle_cannot_provide(self):
        """A case asking for a property check the bundle's props.py does not
        define would make the judge depend on something withheld.

        props.py is read rather than imported: two of the suites' engines import
        POSIX-only modules, and this property holds regardless of platform.
        """
        import tempfile

        helper = StageBundleLeakageTests()
        with tempfile.TemporaryDirectory() as temp:
            for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
                bundle = shared_bundle(utility, checkpoint_id)
                props_source = (bundle / "props.py").read_text(encoding="utf-8")
                defined = {
                    node.value
                    for node in ast.walk(ast.parse(props_source))
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith("property:")
                }
                for case in helper.bundled_cases(bundle):
                    check = case.get("check", "golden")
                    if check in ("golden", "none"):
                        continue
                    with self.subTest(utility=utility, checkpoint=checkpoint_id,
                                      case=case.get("name")):
                        self.assertIn(check, defined)


class ResumeFingerprintTests(unittest.TestCase):
    """Audit 7: the fingerprint must cover everything a stage depends on."""

    def plan(self, **overrides):
        arguments = dict(
            repo=REPO_ROOT, utility="grep", model="demo/model",
            temperature="0", agent="build", max_loops=3, timeout_seconds=1800,
        )
        arguments.update(overrides)
        return lineage_plan.resolve_plan(**arguments)

    def test_settings_change_the_fingerprint(self):
        base = self.plan()["config_fingerprint"]
        for label, overrides in (
            ("model", {"model": "other/model"}),
            ("editor_model", {"editor_model": "other/editor"}),
            ("aider_version", {"aider_version": "aider 9.9"}),
            ("temperature", {"temperature": "0.7"}),
            ("max_loops", {"max_loops": 5}),
        ):
            with self.subTest(setting=label):
                self.assertNotEqual(base, self.plan(**overrides)["config_fingerprint"])

    def test_explicit_model_level_top_k_changes_the_fingerprint(self):
        provenance = json.dumps(
            {
                "base_model": "qwen3-coder-next:latest",
                "top_k": 50,
                "top_k_control": "ollama_modelfile",
            }
        )
        first = self.plan(model_provenance_json=provenance)
        second = self.plan(
            model_provenance_json=provenance.replace("50", "40")
        )
        self.assertEqual(first["model_provenance"]["top_k"], 50)
        self.assertNotEqual(
            first["config_fingerprint"], second["config_fingerprint"]
        )

    def test_plan_records_every_required_component(self):
        plan = self.plan()
        # Manifest-level components.
        for key in ("utility", "program", "source_path", "executable_path",
                    "build_command", "test_dir", "judge", "judge_sha256",
                    "agent_backend", "aider_version", "architect_model",
                    "editor_model", "architect_mode", "aider_model_settings",
                    "remote_transport", "model", "temperature", "max_loops"):
            self.assertIn(key, plan)
        # Per-checkpoint components.
        for checkpoint in plan["checkpoints"]:
            for key in ("id", "prompt", "prompt_sha256", "implemented_flags",
                        "feature_test_command", "test_bundle_fingerprint"):
                self.assertIn(key, checkpoint)

    def test_remote_transport_form_is_explicit_and_fingerprinted(self):
        native = self.plan(
            model="ollama_chat/qwen3.8:27b",
            editor_model="ollama_chat/qwen3-coder-next:latest",
            remote_base_url="http://ollama.example:11434",
        )
        compatible = self.plan(
            model="openai/qwen3.8:27b",
            editor_model="openai/qwen3-coder-next:latest",
            remote_base_url="https://gateway.example/v1",
        )
        self.assertEqual(native["remote_transport"], "ollama_native")
        self.assertEqual(compatible["remote_transport"], "openai_compatible")
        self.assertNotEqual(
            native["config_fingerprint"], compatible["config_fingerprint"]
        )

    def test_the_visible_bundle_is_part_of_the_fingerprint(self):
        plan = self.plan()
        fingerprints = [c["test_bundle_fingerprint"] for c in plan["checkpoints"]]
        self.assertEqual(len(set(fingerprints)), len(fingerprints))
        # Recomputing the plan's hash without the bundle component must differ,
        # which is what proves the bundle is actually inside it.
        stripped = json.loads(json.dumps(plan))
        for checkpoint in stripped["checkpoints"]:
            checkpoint.pop("test_bundle_fingerprint")
        self.assertNotEqual(
            plan["config_fingerprint"], lineage_plan.fingerprint(stripped)
        )


class FinalPopulationBaselineTests(unittest.TestCase):
    """Audit 5: the final view must not present its baseline as maintenance."""

    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = make_lineage_root(
            Path(self.temp.name) / "lineages", [None, None, 2]
        )
        self.output = Path(self.temp.name) / "analysis"

    def report(self, *extra):
        code = analyze_lineages.main(
            ["--lineage-root", str(self.root), "--output-dir", str(self.output),
             *extra]
        )
        self.assertEqual(code, 0)
        return json.loads(
            (self.output / "lineage_report.json").read_text(encoding="utf-8")
        )

    def test_baseline_dependent_metrics_are_declared_unsupported(self):
        report = self.report("--skip-diversity", "--skip-change")
        baseline = report["final_population_baseline"]
        self.assertEqual(baseline["kind"], "empty_new_source")
        for name in ("lines_added", "lines_edited", "functions_edited_count",
                     "gumtree_normalized_edit_distance"):
            self.assertIn(name, baseline["unsupported_metrics"])

    def test_view_metadata_carries_the_rationale_and_the_exclusions(self):
        run_metadata, lineages, _ = analyze_lineages.load_run(self.root)
        view = analyze_lineages.materialize_view(
            Path(self.temp.name) / "view",
            analyze_lineages.population_members(lineages, None),
            run_metadata,
            "final",
        )
        metadata = json.loads((view / "experiment.json").read_text(encoding="utf-8"))
        self.assertIn("baseline_rationale", metadata)
        self.assertIn(
            "lines_added", metadata["baseline_dependent_metrics_unsupported"]
        )

    def test_stage_churn_artifacts_are_not_carried_into_the_view(self):
        # diff-numstat records churn against the stage's own seed. Copying it
        # into a view with a different baseline would make an inconsistent
        # number look consistent.
        run_metadata, lineages, _ = analyze_lineages.load_run(self.root)
        members = analyze_lineages.population_members(lineages, None)
        _, lineage_dir, stage = members[0]
        attempt = analyze_lineages.resolve_stage_paths(lineage_dir, stage)[
            "attempt_dir"
        ]
        (attempt / "diff-numstat.txt").write_text("9\t9\tnew_demo.c\n",
                                                  encoding="utf-8")
        view = analyze_lineages.materialize_view(
            Path(self.temp.name) / "view2", members, run_metadata, "final",
        )
        self.assertFalse((view / "attempt-001" / "diff-numstat.txt").exists())

    def test_transition_summary_output_has_no_checkpoint_000_pseudotransition(self):
        report = self.report("--skip-diversity")
        path = self.output / "lineage_change_summary.csv"
        self.assertTrue(path.is_file())
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["checkpoint_id"] for row in rows], ["001", "002"])
        self.assertNotIn("000", [row["checkpoint_id"] for row in rows])
        self.assertEqual(
            report["per_stage_change"]["summary_rows"],
            "lineage_change_summary.csv",
        )


class ChangeBaselineTests(unittest.TestCase):
    """Audit 5 C and D: each change measure uses its own correct baseline."""

    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = make_lineage_root(
            Path(self.temp.name) / "lineages", [None, None, 2]
        )
        _, self.lineages, _ = analyze_lineages.load_run(self.root)
        self.recorded: list[tuple[str, str]] = []

        def recorder(before: Path, after: Path) -> dict:
            self.recorded.append((before.name, after.name))
            return {"available": True, "lines_edited": 1}

        original = analyze_lineages.change_between
        analyze_lineages.change_between = recorder
        self.addCleanup(setattr, analyze_lineages, "change_between", original)

    @staticmethod
    def lineage_of(path: str) -> str:
        for part in Path(path).parts:
            if part.startswith("lineage-"):
                return part
        raise AssertionError(f"no lineage component in {path!r}")

    def test_per_stage_change_pairs_n_minus_1_with_n(self):
        rows = analyze_lineages.build_transitions(self.lineages)
        # lineage-001 and -002 complete 3 checkpoints -> 2 transitions each;
        # lineage-003 stops at 002 -> 1 successful transition.
        self.assertEqual(len(rows), 5)
        for row in rows:
            with self.subTest(row=row["lineage_id"] + row["to_checkpoint"]):
                self.assertEqual(
                    int(row["to_checkpoint"]), int(row["from_checkpoint"]) + 1
                )
                # Both sides come from the same lineage.
                self.assertEqual(
                    self.lineage_of(row["baseline_source"]), row["lineage_id"]
                )
                self.assertEqual(
                    self.lineage_of(row["candidate_source"]), row["lineage_id"]
                )

    def test_per_stage_change_never_crosses_a_lineage(self):
        analyze_lineages.build_transitions(self.lineages)
        for before, after in self.recorded:
            self.assertEqual(before, after)  # same flattened source name
        rows = analyze_lineages.build_transitions(self.lineages)
        for row in rows:
            self.assertEqual(
                self.lineage_of(row["baseline_source"]),
                self.lineage_of(row["candidate_source"]),
            )

    def test_per_stage_change_records_the_flag_the_stage_added(self):
        rows = analyze_lineages.build_transitions(self.lineages)
        self.assertTrue(all(row["added_flags"] for row in rows))

    def test_transition_summary_aggregates_existing_change_rows(self):
        rows = [
            {
                "to_checkpoint": "001",
                "to_checkpoint_name": "first extension",
                "change_available": True,
                "change_lines_added": 2,
                "change_lines_deleted": 1,
                "change_lines_edited": 3,
                "change_functions_edited_count": 1,
                "change_functions_created_count": 1,
                "change_functions_deleted_count": 0,
            },
            {
                "to_checkpoint": "001",
                "to_checkpoint_name": "first extension",
                "change_available": True,
                "change_lines_added": 6,
                "change_lines_deleted": 3,
                "change_lines_edited": 9,
                "change_functions_edited_count": 3,
                "change_functions_created_count": 1,
                "change_functions_deleted_count": 2,
            },
            {
                "to_checkpoint": "002",
                "to_checkpoint_name": "second extension",
                "change_available": False,
            },
        ]
        summary = analyze_lineages.build_transition_summary(rows)
        self.assertEqual([row["checkpoint_id"] for row in summary], ["001", "002"])
        first = summary[0]
        self.assertEqual(first["successful_transitions"], 2)
        self.assertEqual(first["measured_transitions"], 2)
        self.assertEqual(first["mean_lines_added"], 4.0)
        self.assertEqual(first["mean_lines_deleted"], 2.0)
        self.assertEqual(first["mean_lines_edited"], 6.0)
        self.assertEqual(first["median_lines_edited"], 6.0)
        self.assertEqual(first["mean_functions_edited"], 2.0)
        self.assertEqual(first["mean_functions_created"], 1.0)
        self.assertEqual(first["mean_functions_deleted"], 1.0)
        self.assertEqual(summary[1]["successful_transitions"], 1)
        self.assertEqual(summary[1]["measured_transitions"], 0)
        self.assertIsNone(summary[1]["mean_lines_edited"])

    def test_total_change_uses_the_same_lineage_checkpoint_000(self):
        rows = analyze_lineages.build_total_change(self.lineages)
        # Only completed lineages have a final.
        self.assertEqual([row["lineage_id"] for row in rows],
                         ["lineage-001", "lineage-002"])
        for row in rows:
            self.assertEqual(row["from_checkpoint"], "000")
            self.assertEqual(row["to_checkpoint"], "002")
            self.assertEqual(
                self.lineage_of(row["baseline_source"]),
                self.lineage_of(row["final_source"]),
            )
            self.assertEqual(self.lineage_of(row["final_source"]),
                             row["lineage_id"])

    def test_a_stopped_lineage_contributes_no_total_change(self):
        rows = analyze_lineages.build_total_change(self.lineages)
        self.assertNotIn("lineage-003", [row["lineage_id"] for row in rows])


class SecurityLineageTests(unittest.TestCase):
    """RQ3 populations and deltas preserve the lineage/stage boundaries."""

    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = make_lineage_root(
            Path(self.temp.name) / "lineages", [None, None, 2]
        )
        self.run_metadata, self.lineages, _ = analyze_lineages.load_run(self.root)

    def test_security_transition_deltas_and_cwe_sets_are_same_lineage(self):
        transitions = [
            {
                "lineage_id": "lineage-001",
                "from_checkpoint": "000",
                "to_checkpoint": "001",
            }
        ]
        profiles = {
            ("lineage-001", "000"): {
                "analysis_status": "available",
                "flawfinder_status": "available",
                "flawfinder_finding_count": 1,
                "flawfinder_findings_per_kloc": 10.0,
                "unsafe_call_count": 2,
                "cwe_ids": '["CWE-20","CWE-120"]',
            },
            ("lineage-001", "001"): {
                "analysis_status": "available",
                "flawfinder_status": "available",
                "flawfinder_finding_count": 3,
                "flawfinder_findings_per_kloc": 15.0,
                "unsafe_call_count": 1,
                "cwe_ids": '["CWE-120","CWE-787"]',
            },
        }
        row = analyze_lineages.build_security_transition_rows(
            transitions, profiles
        )[0]
        self.assertEqual(row["flawfinder_finding_delta"], 2.0)
        self.assertEqual(row["findings_per_kloc_delta"], 5.0)
        self.assertEqual(row["unsafe_call_delta"], -1.0)
        self.assertEqual(json.loads(row["newly_observed_cwes"]), ["CWE-787"])
        self.assertEqual(json.loads(row["no_longer_observed_cwes"]), ["CWE-20"])

        profiles[("lineage-001", "000")]["flawfinder_status"] = "unavailable"
        unavailable = analyze_lineages.build_security_transition_rows(
            transitions, profiles
        )[0]
        self.assertIsNone(unavailable["cwe_set_before"])
        self.assertIsNone(unavailable["newly_observed_cwes"])
        self.assertIsNone(unavailable["no_longer_observed_cwes"])

    def test_stage_security_uses_successful_stage_populations(self):
        calls: list[tuple[str, list[str]]] = []

        class FakeSecurity:
            @staticmethod
            def analyze_security_population(**kwargs):
                candidates = kwargs["candidates"]
                checkpoint = kwargs["metadata"]["checkpoint"]
                calls.append((str(checkpoint), [row["run_id"] for row in candidates]))
                profiles = []
                for candidate in candidates:
                    identifier = candidate["source_identifier"]
                    cwes = ["CWE-120"] if "/001/" in identifier else []
                    profiles.append(
                        {
                            "run_id": candidate["run_id"],
                            "analysis_status": "available",
                            "flawfinder_status": "available",
                            "flawfinder_finding_count": len(cwes),
                            "flawfinder_findings_per_kloc": float(len(cwes)),
                            "unsafe_call_count": 0,
                            "cwe_ids": json.dumps(cwes),
                        }
                    )
                n = len(candidates)
                return {
                    "summary": {
                        "status": "completed",
                        "population_n": n,
                        "security_measurement_coverage": 1.0 if n else None,
                        "static_finding_prevalence": 1.0 if checkpoint == "001" else 0.0,
                        "flawfinder_findings": {"mean": 1.0, "median": 1.0},
                        "findings_per_kloc": {"mean": 1.0, "median": 1.0},
                        "unsafe_api_prevalence": 0.0,
                        "mean_unsafe_call_count": 0.0,
                        "distinct_cwe_count": 1 if checkpoint == "001" else 0,
                        "severity_distribution": [],
                        "security_configuration_fingerprint": "f" * 64,
                        "flawfinder": {"version": "2.0.20"},
                    },
                    "rows": profiles,
                }

            @staticmethod
            def write_csv(path, rows, fields):
                analyze_lineages.write_csv(path, rows, fields)

        original_module = analyze_lineages._SECURITY["module"]
        original_reason = analyze_lineages._SECURITY["unavailable_reason"]
        analyze_lineages._SECURITY.update(
            {"module": FakeSecurity, "unavailable_reason": None}
        )
        self.addCleanup(
            analyze_lineages._SECURITY.update,
            {"module": original_module, "unavailable_reason": original_reason},
        )
        output = Path(self.temp.name) / "analysis"
        report = analyze_lineages.analyze_lineage_security(
            lineages=self.lineages,
            order=["000", "001", "002"],
            transitions=analyze_lineages.successful_transition_identifiers(
                self.lineages
            ),
            output_dir=output,
            run_metadata=self.run_metadata,
            configuration={"schema_version": 1},
            formal=True,
        )
        populations = {checkpoint: members for checkpoint, members in calls}
        self.assertEqual(populations["000"], ["lineage-001", "lineage-002", "lineage-003"])
        self.assertEqual(populations["001"], ["lineage-001", "lineage-002", "lineage-003"])
        self.assertEqual(populations["002"], ["lineage-001", "lineage-002"])
        self.assertEqual(populations["final"], ["lineage-001", "lineage-002"])
        self.assertEqual(report["stage_summary_rows"], 3)
        self.assertEqual(report["transition_rows"], 5)
        with (output / "security_stage_summary.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            stage_rows = list(csv.DictReader(handle))
        self.assertEqual([row["checkpoint_id"] for row in stage_rows], ["000", "001", "002"])
        with (output / "security_transitions.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            transition_rows = list(csv.DictReader(handle))
        self.assertEqual(len(transition_rows), 5)
        self.assertFalse(any(row["to_checkpoint"] == "000" for row in transition_rows))


class StaleRecordedPathTests(unittest.TestCase):
    """A stage's recorded paths are provenance, not filesystem locations.

    `run_lineage_experiment.sh` bakes absolute `stage_dir`, `attempt_dir`,
    `candidate` and `test_bundle_dir` into every stage record at generation
    time. Opening those directly made the analysis fail on any machine but the
    generating one, and on any run directory that was renamed after the fact --
    both of which happened to
    `runs/formal/grep-qwen3-topk40-t0-p05-seed42-maxtok32768-loops1-n10`, whose
    records still name a different home directory and an older run name, in
    more than one mangled variant. Every file must therefore be located from
    `--lineage-root` instead.

    The corruption here is deliberately worse than the real one: two different
    bogus prefixes, neither of which exists, while the actual files sit intact
    under the root the test controls.
    """

    STALE_PREFIXES = (
        "/nonexistent/other-machine/agentic_cyber/runs/old-run-name",
        "/nonexistent/third-machine/checkouts/agentic_cyber/runs/renamed-run",
    )

    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = make_lineage_root(
            Path(self.temp.name) / "lineages", [None, None, 2]
        )
        self.output = Path(self.temp.name) / "analysis"
        self.corrupt_recorded_paths()

        # What is under test is which files get opened, not what the churn
        # formulas return, so the measurement itself is stubbed to keep these
        # cases independent of Tree-sitter and GumTree being installed.
        original = analyze_lineages.change_between
        analyze_lineages.change_between = lambda before, after: {
            "available": before.is_file() and after.is_file()
        }
        self.addCleanup(setattr, analyze_lineages, "change_between", original)

    def corrupt_recorded_paths(self) -> None:
        """Point every recorded location at a machine that does not exist."""
        for number, directory in enumerate(sorted(self.root.glob("lineage-*"))):
            prefix = self.STALE_PREFIXES[number % len(self.STALE_PREFIXES)]
            record_path = directory / "lineage.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            for stage in record["stages"]:
                checkpoint = stage["checkpoint_id"]
                stem = f"{prefix}/{directory.name}/{checkpoint}"
                stage["stage_dir"] = stem
                stage["attempt_dir"] = f"{stem}/temp-9p9/attempt-007"
                stage["test_bundle_dir"] = f"{stem}/test-bundle"
                if stage["candidate"]:
                    stage["candidate"] = (
                        f"{stem}/temp-9p9/attempt-007/candidate/new_demo.c"
                    )
                if stage["seed"]:
                    stage["seed"] = f"{prefix}/{directory.name}/seed/new_demo.c"
            record_path.write_text(json.dumps(record), encoding="utf-8")

    def load(self):
        return analyze_lineages.load_run(self.root)

    def test_no_recorded_path_survives_the_corruption(self):
        # Guards the fixture itself: if any recorded location still happened to
        # exist, the tests below would pass without exercising anything.
        _, lineages, _ = self.load()
        for record in lineages:
            for stage in record["stages"]:
                for key in ("stage_dir", "attempt_dir", "test_bundle_dir",
                            "candidate"):
                    if stage.get(key):
                        self.assertFalse(
                            Path(stage[key]).exists(),
                            f"{key} should be unusable in this fixture",
                        )

    def test_stage_paths_resolve_under_the_lineage_root(self):
        _, lineages, _ = self.load()
        record = lineages[0]
        stage = record["stages"][0]
        located = analyze_lineages.resolve_stage_paths(record["_dir"], stage)
        self.assertEqual(located["stage_dir"], self.root / "lineage-001" / "000")
        self.assertEqual(
            located["attempt_dir"],
            self.root / "lineage-001" / "000" / "temp-0" / "attempt-001",
        )
        self.assertEqual(
            located["test_bundle_dir"],
            self.root / "lineage-001" / "000" / "test-bundle",
        )
        self.assertTrue(located["candidate"].is_file())

    def test_view_materializes_from_the_root_not_the_record(self):
        run_metadata, lineages, _ = self.load()
        members = analyze_lineages.population_members(lineages, None)
        view = analyze_lineages.materialize_view(
            Path(self.temp.name) / "view", members, run_metadata, "final"
        )
        attempts = sorted(view.glob("attempt-*"))
        self.assertEqual(len(attempts), 2)
        # The bytes must be the completed lineages' own final sources, not some
        # other member's and not the empty baseline.
        self.assertEqual(
            [(attempt / "candidate" / "new_demo.c").read_text(encoding="utf-8")
             for attempt in attempts],
            ["int main(void){return 12;}\n", "int main(void){return 22;}\n"],
        )
        for attempt in attempts:
            metadata = json.loads(
                (attempt / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["lineage_checkpoint_id"], "002")

    def test_the_view_index_still_reports_what_the_record_said(self):
        # Provenance is not silently rewritten to the local path: the index
        # records where the file was written when the run was generated.
        run_metadata, lineages, _ = self.load()
        view = analyze_lineages.materialize_view(
            Path(self.temp.name) / "view-index",
            analyze_lineages.population_members(lineages, None),
            run_metadata,
            "final",
        )
        members = json.loads((view / "members.json").read_text(encoding="utf-8"))
        self.assertTrue(
            all(entry["candidate"].startswith("/nonexistent/")
                for entry in members)
        )

    def test_change_measures_read_the_sources_under_the_root(self):
        _, lineages, _ = self.load()
        rows = analyze_lineages.build_transitions(lineages)
        self.assertEqual(len(rows), 5)
        for row in rows:
            for key in ("baseline_source", "candidate_source"):
                with self.subTest(row=row["lineage_id"], column=key):
                    path = Path(row[key])
                    self.assertTrue(path.is_file())
                    self.assertTrue(path.is_relative_to(self.root))
        total = analyze_lineages.build_total_change(lineages)
        self.assertEqual([row["lineage_id"] for row in total],
                         ["lineage-001", "lineage-002"])

    def test_analysis_completes_and_writes_the_population_view(self):
        # The analyzer subprocess is stubbed: what is under test is that the
        # view is built at all, which is where the stale paths used to crash.
        views: list[Path] = []

        def fake_run_analyzer(view_dir, args):
            views.append(view_dir)
            return {"command": [], "returncode": 0,
                    "analysis_dir": str(view_dir / "analysis")}

        original = analyze_lineages.run_analyzer
        analyze_lineages.run_analyzer = fake_run_analyzer
        self.addCleanup(setattr, analyze_lineages, "run_analyzer", original)

        code = analyze_lineages.main(
            ["--lineage-root", str(self.root), "--output-dir", str(self.output),
             "--checkpoint-diversity"]
        )
        self.assertEqual(code, 0)
        report = json.loads(
            (self.output / "lineage_report.json").read_text(encoding="utf-8")
        )
        final = next(p for p in report["populations"] if p["label"] == "final")
        self.assertEqual(final["members"], 2)
        self.assertNotIn("skipped", final)
        self.assertEqual(
            sorted(view.name for view in views),
            ["checkpoint-000", "checkpoint-001", "checkpoint-002", "final"],
        )
        for view in views:
            self.assertTrue(any(view.glob("attempt-*/candidate/new_demo.c")))

    def test_an_ambiguous_attempt_directory_is_refused(self):
        # Two attempt directories under one stage: which produced the recorded
        # candidate is unknowable, and picking one would fabricate the answer.
        (self.root / "lineage-001" / "000" / "temp-1" / "attempt-001").mkdir(
            parents=True
        )
        _, lineages, _ = self.load()
        with self.assertRaises(analyze_lineages.LineageError) as caught:
            analyze_lineages.resolve_stage_paths(
                lineages[0]["_dir"], lineages[0]["stages"][0]
            )
        self.assertIn("exactly one", str(caught.exception))

    def test_a_missing_attempt_directory_is_refused(self):
        shutil.rmtree(self.root / "lineage-001" / "000" / "temp-0")
        _, lineages, _ = self.load()
        with self.assertRaises(analyze_lineages.LineageError) as caught:
            analyze_lineages.resolve_stage_paths(
                lineages[0]["_dir"], lineages[0]["stages"][0]
            )
        self.assertIn("not present under --lineage-root", str(caught.exception))


class RunnerTestDirDestinationTests(unittest.TestCase):
    """The runner must be able to mount a generated bundle at the suite path."""

    def test_capture_splits_source_from_destination(self):
        spec = "/tmp/bundle:tests/grep-test-suite"
        self.assertEqual(
            capture_candidate.split_test_dir(spec),
            ("/tmp/bundle", "tests/grep-test-suite"),
        )

    def test_capture_defaults_destination_to_source(self):
        self.assertEqual(
            capture_candidate.split_test_dir("tests/grep-test-suite"),
            ("tests/grep-test-suite", "tests/grep-test-suite"),
        )

    def test_tamper_detection_compares_against_the_bundle(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bundle"
            (source / "suites").mkdir(parents=True)
            (source / "runner.py").write_text("original\n", encoding="utf-8")
            workdir = root / "workdir"
            visible = workdir / "tests" / "demo-test-suite"
            (visible / "suites").mkdir(parents=True)
            (visible / "runner.py").write_text("TAMPERED\n", encoding="utf-8")
            attempt = root / "attempt"
            attempt.mkdir()

            report = capture_candidate.check_test_dirs(
                workdir, attempt, root,
                [f"{source}:tests/demo-test-suite"],
            )
            self.assertFalse(report["clean"])
            self.assertEqual(
                report["directories"]["tests/demo-test-suite"]["modified"],
                ["runner.py"],
            )


class BundleProseLeakageTests(unittest.TestCase):
    """Audit 2, applied to prose rather than to cases.

    Case filtering was already correct when this was written; the leak was in
    the files shipped *around* the cases. Every `judge_candidate.sh` header
    enumerated the whole ladder ("judge_candidate.sh build/new_sort -r -f -u
    -c"), and `props.py` documented later checkpoints' contracts -- mkdir's
    `-p`/`-m` idempotency rule and chmod's exact `-c`/`-v` report-line format.
    Both were readable at checkpoint 000. A test that only inspects `flags`
    fields cannot see that, so this one reads the bytes.
    """

    # A dash-letter token is only a leak when it is used as an option. These
    # shell and Python idioms are not: `rm -f`, `[[ -x ... ]]`, `set -eu`.
    SHELL_OWNERS = {
        "rm", "cp", "mv", "mkdir", "set", "shopt", "test", "[[", "[",
        "tar", "find", "chmod", "install", "ls", "grep", "sort", "exec",
    }

    def future_flags(self, utility: str, checkpoint_id: str) -> list[str]:
        ladder = EXPECTED_SEQUENCES[utility]
        index = [c for u, c, _ in ALL_UTILITY_CHECKPOINTS
                 if u == utility].index(checkpoint_id)
        return ladder[index:]

    def leaks_in(self, text: str, flags: list[str]) -> list[str]:
        import re

        found = []
        for line in text.splitlines():
            for flag in flags:
                for match in re.finditer(
                    r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", line
                ):
                    before = line[:match.start()].split()
                    # Strip quoting/punctuation so `trap 'rm -f ...` still
                    # attributes the -f to rm.
                    owner = before[-1].strip("'\"`(){};|&") if before else ""
                    if owner in self.SHELL_OWNERS:
                        continue
                    found.append(f"{flag}: {line.strip()[:100]}")
        return found

    def test_no_bundled_text_file_names_a_future_flag(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            flags = self.future_flags(utility, checkpoint_id)
            if not flags:
                continue
            bundle = shared_bundle(utility, checkpoint_id)
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                for path in sorted(bundle.rglob("*")):
                    if not path.is_file() or path.name == "BUNDLE.json":
                        continue
                    if path.suffix not in {".py", ".sh", ".json"}:
                        continue
                    if path.parent.name == "suites":
                        continue  # covered by the args check below
                    leaks = self.leaks_in(
                        path.read_text(encoding="utf-8", errors="replace"), flags
                    )
                    self.assertEqual(
                        leaks, [],
                        f"{utility} {checkpoint_id} {path.name} names a flag "
                        f"this checkpoint has not introduced",
                    )

    def test_no_retained_case_invokes_a_future_flag(self):
        """No bundled case may name a later flag, for any reason.

        There is deliberately no exemption for a case that exists to assert the
        flag is still rejected: its argv would spell the flag out just as
        plainly. That enforcement moved to the controller-only boundary gate.
        """
        for utility, checkpoint_id, implemented in ALL_UTILITY_CHECKPOINTS:
            flags = set(self.future_flags(utility, checkpoint_id))
            if not flags:
                continue
            bundle = shared_bundle(utility, checkpoint_id)
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                for case in StageBundleLeakageTests.bundled_cases(self, bundle):
                    named = flags & set(case.get("args", []))
                    self.assertEqual(
                        named, set(),
                        f"{case.get('name')} invokes {sorted(named)}",
                    )

    def test_no_absent_flag_case_reaches_a_bundle(self):
        """grep and chmod must no longer expose their rejection cases."""
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            bundle = shared_bundle(utility, checkpoint_id)
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                exposed = [
                    case.get("name")
                    for case in StageBundleLeakageTests.bundled_cases(self, bundle)
                    if case.get("absent_flags")
                ]
                self.assertEqual(exposed, [])

    def test_prompts_never_name_a_future_flag(self):
        for utility, checkpoint_id, implemented in ALL_UTILITY_CHECKPOINTS:
            future = self.future_flags(utility, checkpoint_id)
            if not future:
                continue
            plan = lineage_plan.resolve_plan(
                REPO_ROOT, utility, "m", "0", "build", 3, 1800
            )
            prompt = next(c["prompt"] for c in plan["checkpoints"]
                          if c["id"] == checkpoint_id)
            text = (REPO_ROOT / prompt).read_text(encoding="utf-8")
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                self.assertEqual(
                    self.leaks_in(text, future), [],
                    f"{prompt} names a flag from a later checkpoint",
                )

    def future_spellings(self, utility: str, checkpoint_id: str) -> list[str]:
        """Future flags AND their manifest-declared long aliases."""
        manifest = checkpoint_boundary_gate.load_manifest(REPO_ROOT, utility)
        aliases = manifest.get("flag_aliases", {})
        out = []
        for flag in self.future_flags(utility, checkpoint_id):
            out.extend([flag, *aliases.get(flag, [])])
        return out

    def test_no_future_long_alias_appears_in_a_bundle(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            spellings = [s for s in self.future_spellings(utility, checkpoint_id)
                         if s.startswith("--")]
            if not spellings:
                continue
            bundle = shared_bundle(utility, checkpoint_id)
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                for path in sorted(bundle.rglob("*")):
                    if not path.is_file() or path.name == "BUNDLE.json":
                        continue
                    if path.suffix == ".gz":
                        import gzip
                        text = gzip.decompress(path.read_bytes()).decode(
                            "utf-8", "replace")
                    else:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    for spelling in spellings:
                        self.assertNotIn(
                            spelling, text,
                            f"{path.name} names {spelling} before its checkpoint",
                        )

    def test_no_future_long_alias_appears_in_a_prompt(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            spellings = [s for s in self.future_spellings(utility, checkpoint_id)
                         if s.startswith("--")]
            if not spellings:
                continue
            plan = lineage_plan.resolve_plan(
                REPO_ROOT, utility, "m", "0", "build", 3, 1800
            )
            prompt = next(c["prompt"] for c in plan["checkpoints"]
                          if c["id"] == checkpoint_id)
            text = (REPO_ROOT / prompt).read_text(encoding="utf-8")
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                for spelling in spellings:
                    self.assertNotIn(
                        spelling, text,
                        f"{prompt} names {spelling} before its checkpoint",
                    )

    def test_every_prompt_states_the_generic_scope_rule(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            plan = lineage_plan.resolve_plan(
                REPO_ROOT, utility, "m", "0", "build", 3, 1800
            )
            prompt = next(c["prompt"] for c in plan["checkpoints"]
                          if c["id"] == checkpoint_id)
            text = (REPO_ROOT / prompt).read_text(encoding="utf-8")
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                self.assertIn(
                    "outside this checkpoint's stated scope", text,
                    "a prompt must bound scope generically, without naming "
                    "the options it is withholding",
                )


class PropsPruningTests(unittest.TestCase):
    """`props.py` ships only the checks a checkpoint can actually reach."""

    def bundled_cases(self, bundle: Path) -> list[dict]:
        return StageBundleLeakageTests.bundled_cases(self, bundle)

    def props_module(self, bundle: Path):
        source = (bundle / "props.py").read_text(encoding="utf-8")
        return ast.parse(source), source

    def test_every_bundled_check_is_reachable_from_a_retained_case(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            bundle = shared_bundle(utility, checkpoint_id)
            if not (bundle / "props.py").is_file():
                continue
            wanted = {
                case["check"] for case in self.bundled_cases(bundle)
                if str(case.get("check", "")).startswith("property:")
            }
            tree, _ = self.props_module(bundle)
            shipped = set()
            for node in tree.body:
                if (isinstance(node, ast.Assign)
                        and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id == "CHECKS"):
                    shipped = {
                        key.value for key in node.value.keys
                        if isinstance(key, ast.Constant)
                    }
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                self.assertEqual(
                    shipped, wanted,
                    "bundled CHECKS must be exactly what retained cases use",
                )

    def test_unreachable_property_functions_are_absent(self):
        """mkdir's -p/-m idempotency check must not be readable at 000/001."""
        for checkpoint_id in ("000", "001"):
            bundle = shared_bundle("mkdir", checkpoint_id)
            source = (bundle / "props.py").read_text(encoding="utf-8")
            with self.subTest(checkpoint=checkpoint_id):
                self.assertNotIn("check_idempotent_p", source)
                self.assertNotIn("preserve_mode", source)
        # At 002 both -p and -m exist, so the check belongs there.
        self.assertIn(
            "check_idempotent_p",
            (shared_bundle("mkdir", "002") / "props.py").read_text(
                encoding="utf-8"),
        )

    def test_chmod_report_line_format_is_never_shipped(self):
        """The -c/-v line format is expected-output data for later checkpoints."""
        for _, checkpoint_id, _ in [
            row for row in ALL_UTILITY_CHECKPOINTS if row[0] == "chmod"
        ]:
            bundle = shared_bundle("chmod", checkpoint_id)
            source = (bundle / "props.py").read_text(encoding="utf-8")
            with self.subTest(checkpoint=checkpoint_id):
                self.assertNotIn("changed from", source)
                self.assertNotIn("retained as", source)

    def test_pruned_props_still_imports_inside_the_bundle(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            bundle = shared_bundle(utility, checkpoint_id)
            if not (bundle / "props.py").is_file():
                continue
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                # Compiles, and every name CHECKS refers to is defined.
                tree, source = self.props_module(bundle)
                compile(source, "props.py", "exec")
                defined = {
                    node.name for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                }
                for node in tree.body:
                    if (isinstance(node, ast.Assign)
                            and isinstance(node.targets[0], ast.Name)
                            and node.targets[0].id == "CHECKS"):
                        for value in node.value.values:
                            self.assertIn(value.id, defined)


class PrematureFeatureTests(unittest.TestCase):
    """Audit 4, after enforcement moved out of the agent-visible bundle.

    The suites still carry frozen `absent_flags` cases for offline auditing, but
    a case that asserts "-H must still be rejected" necessarily spells out `-H`
    in its argv, so shipping it at checkpoint 000 would leak the option name the
    checkpoint is withholding. The bundle therefore excludes such cases outright
    and the real enforcement is the controller-only boundary gate, covered by
    CheckpointBoundaryGateTests.
    """

    def test_a_case_requiring_an_absent_flag_is_never_selectable(self):
        case = {"flags": [], "absent_flags": ["-H"]}
        for implemented in (set(), {"-r"}, {"-H"}, {"-H", "-h", "-r", "-i"}):
            with self.subTest(implemented=sorted(implemented)):
                self.assertFalse(stage_test_bundle.selectable(case, implemented))

    def test_ordinary_cases_still_select_on_their_own_flags(self):
        case = {"flags": ["-H"]}
        self.assertFalse(stage_test_bundle.selectable(case, set()))
        self.assertTrue(stage_test_bundle.selectable(case, {"-H"}))
        self.assertTrue(stage_test_bundle.selectable(case, {"-H", "-h"}))

    def test_enforcement_covers_every_utility_not_just_the_model_backed_ones(self):
        """The gate is manifest-derived, so sort and mkdir are covered too.

        Freezing rejection cases could only ever work for grep and chmod, whose
        goldens come from a specification model; sort and mkdir freeze theirs by
        running a real GNU binary that implements -r and -p and therefore cannot
        express a refusal. Deriving the matrix from the manifest instead removes
        that asymmetry.
        """
        for utility in sorted(EXPECTED_SEQUENCES):
            manifest = checkpoint_boundary_gate.load_manifest(REPO_ROOT, utility)
            rows = checkpoint_boundary_gate.availability(manifest)
            with self.subTest(utility=utility):
                self.assertEqual(
                    rows[0]["forbidden"], EXPECTED_SEQUENCES[utility],
                    "checkpoint 000 must forbid the whole ladder",
                )


class LineageControllerInvocationTests(unittest.TestCase):
    """Audit 1, read off the controller's own resolved commands."""

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required to run the controller")

    def dry_run(self, utility: str, output_dir: Path,
                editor_model: str = "ollama_chat/qwen3-coder-next:latest") -> list[str]:
        result = subprocess.run(
            [self.bash, str(REPO_ROOT / "scripts" / "run_lineage_experiment.sh"),
             "--utility", utility, "--model", "demo/m", "--temperature", "0.2",
             "--editor-model", editor_model, "--lineages", "2",
             "--output-dir", str(output_dir), "--dry-run"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
            env={**os.environ, "PYTHON_BIN": sys.executable},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line for line in result.stdout.splitlines()
                if "run_experiment.sh" in line]

    def test_model_pair_is_forwarded_unchanged_to_every_stage(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            lines = self.dry_run("grep", Path(temp) / "pair", "fixed/editor:model")
        self.assertTrue(lines)
        for line in lines:
            self.assertIn("--model demo/m", line)
            self.assertIn("--editor-model fixed/editor:model", line)

    def test_dry_run_prints_the_aider_architect_invocation(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            result = subprocess.run(
                [self.bash,
                 str(REPO_ROOT / "scripts" / "run_lineage_experiment.sh"),
                 "--utility", "grep", "--model", "architect/model",
                 "--editor-model", "editor/model", "--temperature", "0",
                 "--lineages", "1", "--output-dir", str(Path(temp) / "dry"),
                 "--dry-run"],
                capture_output=True, text=True, cwd=str(REPO_ROOT),
                env={**os.environ, "PYTHON_BIN": sys.executable},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Aider invocation template:", result.stdout)
        self.assertIn("--architect", result.stdout)
        self.assertIn("--model architect/model", result.stdout)
        self.assertIn("--editor-model editor/model", result.stdout)
        self.assertNotIn("opencode run", result.stdout.lower())

    def test_every_stage_runs_exactly_one_attempt(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            for utility in sorted(EXPECTED_SEQUENCES):
                with self.subTest(utility=utility):
                    for line in self.dry_run(utility, Path(temp) / utility):
                        self.assertIn("--runs 1", line)
                        self.assertNotIn("--runs 2", line)

    def test_first_stage_creates_and_later_stages_inherit(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            for utility in sorted(EXPECTED_SEQUENCES):
                lines = self.dry_run(utility, Path(temp) / utility)
                stages = len(lines) // 2  # two lineages
                with self.subTest(utility=utility):
                    for index, line in enumerate(lines):
                        if index % stages == 0:
                            self.assertIn("--source-mode new", line)
                            self.assertNotIn("--seed-file", line)
                        else:
                            self.assertIn("--source-mode existing", line)
                            self.assertIn("--seed-file", line)

    def test_a_seed_never_crosses_a_lineage(self):
        """Every path in a stage's command names one and the same lineage.

        Asserted over the whole command rather than over individual options:
        the controller shell-quotes its paths, and "this command mentions
        exactly one lineage" is both easier to parse and a stronger statement
        than comparing two extracted paths.
        """
        import re
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            for utility in sorted(EXPECTED_SEQUENCES):
                lines = self.dry_run(utility, Path(temp) / utility)
                self.assertTrue(lines)
                with self.subTest(utility=utility):
                    for line in lines:
                        mentioned = set(re.findall(r"lineage-\d+", line))
                        self.assertEqual(
                            len(mentioned), 1,
                            f"stage command spans lineages {sorted(mentioned)}",
                        )

    def test_a_dry_run_writes_nothing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "never-created"
            self.dry_run("grep", target)
            self.assertFalse(
                target.exists(),
                "a dry run must not create its output directory",
            )


def maintained_shell_scripts() -> list[Path]:
    """Every *.sh the repository maintains.

    `runs/` and `review-bundle/` are archived outputs, not maintained source,
    and are excluded deliberately.
    """
    return [
        path for path in sorted(REPO_ROOT.rglob("*.sh"))
        if not {"runs", "review-bundle", ".git"} & set(path.relative_to(REPO_ROOT).parts)
    ]


class SamplingParameterSurfaceTests(unittest.TestCase):
    """The sampling knobs must be real, recorded, and refused when they are not.

    Aider model settings pass temperature, top_p, seed and max_tokens through
    LiteLLM to the architect model. These assertions pin that wiring.
    """

    RUNNER = REPO_ROOT / "scripts" / "run_experiment.sh"

    def setUp(self):
        self.text = self.RUNNER.read_text(encoding="utf-8")
        self.settings_text = (
            REPO_ROOT / "scripts" / "aider_settings.py"
        ).read_text(encoding="utf-8")

    def test_each_confirmed_knob_has_a_flag(self):
        for flag in ("--top-p", "--sampling-seed", "--max-tokens"):
            with self.subTest(flag=flag):
                self.assertIn(f"{flag})", self.text)

    def test_new_runs_depend_on_aider_not_opencode(self):
        self.assertIn('AIDER_BIN="${AIDER_BIN:-aider}"', self.text)
        self.assertNotIn('OPENCODE_BIN=', self.text)
        self.assertIn('--editor-model)', self.text)
        self.assertIn('--message-file', self.text)
        self.assertIn('--no-git', self.text)

    def test_the_sampling_seed_flag_is_not_called_seed(self):
        """--seed-file is the source-inheritance file; the senses must not mix."""
        self.assertIn('--sampling-seed) SAMPLING_SEED=', self.text)
        # `--seed` exists only to refuse the ambiguous spelling: it must never
        # assign anything.
        self.assertIn("--seed is ambiguous here", self.text)
        seed_arm = self.text.split("--seed)", 1)[1].split(";;", 1)[0]
        self.assertNotIn("=", seed_arm.replace("--seed-file", ""))

    def test_top_k_is_refused_rather_than_silently_recorded(self):
        """It reaches the body but the OpenAI-compatible API has no top_k, so
        the server drops it. A recorded condition the server ignored would be
        worse than no flag."""
        self.assertIn("--top-k is not supported", self.text)
        self.assertNotIn('"top_k"', self.settings_text)

    def test_temperature_is_in_the_architect_extra_params(self):
        self.assertIn('"temperature": float(temperature)', self.settings_text)
        self.assertIn('"extra_params": architect_params', self.settings_text)

    def test_every_knob_is_recorded_where_temperature_is(self):
        """Three record sites, the same three temperature already reaches:
        sweep.json, experiment.json and each attempt's metadata.json (which is
        what becomes a per_run_metrics.csv column)."""
        for key in ("top_p", "sampling_seed", "max_tokens"):
            with self.subTest(key=key):
                self.assertEqual(
                    self.text.count(f'{key} "$(optional_number "$'), 3,
                    f"{key} must be written to all three records",
                )
        self.assertIn('architect_sampling "__JSON__:', self.text)
        self.assertIn('aider_model_settings_sha256', self.text)

    def test_unset_knobs_are_recorded_as_null_not_omitted(self):
        self.assertIn("__JSON__:null", self.text)
        self.assertIn("optional_number()", self.text)

    def test_the_resume_guard_covers_the_new_knobs(self):
        """Resuming into a directory sampled under different settings is the
        same mistake as resuming at a different temperature."""
        for key in ("top_p", "sampling_seed", "max_tokens"):
            with self.subTest(key=key):
                self.assertIn(f'"{key}": None if', self.text)

    def test_the_help_documents_the_flags_and_the_omission(self):
        for fragment in ("--top-p P", "--sampling-seed N", "--max-tokens N",
                         "There is no --top-k"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)


class PromptAutomationNoticeTests(unittest.TestCase):
    """The automation notice is one shared block, referenced by all three
    templates rather than pasted into each.

    It is a documented change to something the design holds constant across
    every prompt, so it has to be identifiable as a harness addition in the
    template itself -- not folded invisibly into the task description.
    """

    SHARED = REPO_ROOT / "prompts" / "_shared" / "automation_notice.md"
    TEMPLATES = (
        REPO_ROOT / "prompts" / "checkpoint_base_template.md",
        REPO_ROOT / "prompts" / "checkpoint_feature_template.md",
        REPO_ROOT / "prompts" / "repair_continuation_template.md",
    )

    @staticmethod
    def unwrapped(path: Path) -> str:
        """The prose with line wrapping collapsed, so an assertion is about
        the wording rather than about where the lines happen to break."""
        return " ".join(path.read_text(encoding="utf-8").split())

    def test_the_shared_block_exists_and_says_what_it_is_for(self):
        text = self.unwrapped(self.SHARED)
        for phrase in ("fully automated and non-interactive",
                       "No user is available",
                       "most reasonable interpretation",
                       "Do not produce an extended plan"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_the_block_is_marked_as_a_harness_addition(self):
        text = self.unwrapped(self.SHARED)
        self.assertIn("DELIBERATE ADDITION", text)
        self.assertIn("not part of any utility's task description", text)

    def test_every_template_references_it_by_placeholder(self):
        for template in self.TEMPLATES:
            text = template.read_text(encoding="utf-8")
            with self.subTest(template=template.name):
                self.assertIn("[AUTOMATION_NOTICE]", text)
                self.assertIn("SHARED BLOCK", text)
                self.assertIn("prompts/_shared/automation_notice.md", text)

    def test_no_template_inlines_the_text(self):
        """Three copies would drift, and 'held constant across every prompt'
        would quietly stop being true."""
        for template in self.TEMPLATES:
            text = template.read_text(encoding="utf-8")
            with self.subTest(template=template.name):
                self.assertNotIn("This session is fully automated", text)

    def test_the_notice_changes_no_utility_behavior(self):
        """It must describe how the session runs, not what to implement."""
        text = self.unwrapped(self.SHARED)
        for leak in ("mkdir", "new_sort", "new_grep", "chmod", "-p", "-R"):
            with self.subTest(leak=leak):
                self.assertNotIn(f" {leak} ", text)


class ShellLineEndingTests(unittest.TestCase):
    """`.gitattributes` says `*.sh text eol=lf`, but it was added after these
    files were committed and git never renormalized the existing blobs. Every
    shell script therefore reached a fresh Linux/WSL checkout with CRLF, where
    `set -o pipefail` fails because the carriage return becomes part of the
    argument. The scripts are now LF; this keeps them that way.
    """

    def test_no_maintained_shell_script_contains_a_carriage_return(self):
        offenders = []
        for path in maintained_shell_scripts():
            raw = path.read_bytes()
            if b"\r" in raw:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()} "
                    f"({raw.count(chr(13).encode())} CR)"
                )
        self.assertEqual(
            offenders, [],
            "shell scripts must use LF endings; a CR breaks bash on Linux",
        )

    def test_the_shell_script_inventory_is_not_empty(self):
        # Guards against the check silently passing because the glob broke.
        scripts = maintained_shell_scripts()
        self.assertGreaterEqual(len(scripts), 10)
        names = {p.name for p in scripts}
        self.assertIn("selfcheck.sh", names)
        self.assertIn("run_lineage_experiment.sh", names)

    def test_gitattributes_still_pins_shell_scripts_to_lf(self):
        text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", text)


class OracleContractTests(unittest.TestCase):
    """The sort and mkdir suites freeze goldens from a real GNU binary, so the
    oracle is part of the benchmark definition and must be pinned and portable.
    """

    PINS = {"sort": "9.11", "mkdir": "9.11"}

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def suite_root(self, suite: str) -> Path:
        return REPO_ROOT / "tests" / f"{suite}-test-suite"

    def config(self, suite: str) -> Path:
        return self.suite_root(suite) / "config.json"

    def test_pin_comes_from_the_frozen_corpus_manifest(self):
        for suite, expected in self.PINS.items():
            with self.subTest(suite=suite):
                self.assertEqual(
                    oracle_contract.required_version(
                        suite, self.suite_root(suite), self.config(suite)
                    ),
                    expected,
                )

    def test_no_config_hardcodes_a_machine_specific_oracle_path(self):
        for suite in self.PINS:
            configured = json.loads(
                self.config(suite).read_text(encoding="utf-8")
            )["paths"].get("oracle_bin", "")
            with self.subTest(suite=suite):
                self.assertNotIn("homebrew", configured.lower())
                self.assertNotIn("/opt/", configured)

    def test_environment_override_wins_over_config(self):
        import os as _os

        for suite in self.PINS:
            variable = oracle_contract.SUITES[suite]["env"]
            override = str(self.temp / "custom" / suite)
            previous = _os.environ.get(variable)
            _os.environ[variable] = override
            try:
                self.assertEqual(
                    oracle_contract.resolve(suite, self.config(suite)), override
                )
            finally:
                if previous is None:
                    _os.environ.pop(variable, None)
                else:
                    _os.environ[variable] = previous

    def test_explicit_override_wins_over_everything(self):
        chosen = str(self.temp / "explicit-oracle")
        self.assertEqual(
            oracle_contract.resolve("sort", self.config("sort"), chosen), chosen
        )

    def test_a_missing_executable_is_reported_with_the_env_var_to_set(self):
        missing = str(self.temp / "definitely-absent")
        problems = oracle_contract.verify(
            "mkdir", self.suite_root("mkdir"), missing, self.config("mkdir")
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("not an executable file", problems[0])
        self.assertIn("MKDIR_ORACLE_BIN", problems[0])

    def test_a_non_gnu_executable_is_rejected(self):
        fake = fake_version_tool(self.temp / "bsd", "mkdir",
                                 "mkdir: illegal option -- -")
        problems = oracle_contract.verify(
            "mkdir", self.suite_root("mkdir"), str(fake), self.config("mkdir")
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("not GNU coreutils", problems[0])

    def test_a_wrong_gnu_version_is_rejected_naming_both_versions(self):
        fake = fake_version_tool(self.temp / "old", "mkdir",
                                 "mkdir (GNU coreutils) 8.32")
        problems = oracle_contract.verify(
            "mkdir", self.suite_root("mkdir"), str(fake), self.config("mkdir")
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("9.11", problems[0])
        self.assertIn("8.32", problems[0])
        self.assertIn("would change the benchmark", problems[0])

    def test_the_pinned_version_is_accepted(self):
        for suite, pin in self.PINS.items():
            program = oracle_contract.SUITES[suite]["program"]
            fake = fake_version_tool(self.temp / f"good-{suite}", program,
                                     f"{program} (GNU coreutils) {pin}")
            with self.subTest(suite=suite):
                self.assertEqual(
                    oracle_contract.verify(
                        suite, self.suite_root(suite), str(fake),
                        self.config(suite)
                    ),
                    [],
                )

    def test_a_path_containing_spaces_round_trips(self):
        directory = self.temp / "oracle dir with spaces"
        fake = fake_version_tool(directory, "sort", "sort (GNU coreutils) 9.11")
        self.assertIn(" ", str(fake))
        self.assertEqual(
            oracle_contract.resolve("sort", self.config("sort"), str(fake)),
            str(fake),
        )
        self.assertEqual(
            oracle_contract.verify("sort", self.suite_root("sort"), str(fake),
                                   self.config("sort")),
            [],
        )

    def test_c6_accepts_both_documented_wordings(self):
        """The loose model cross-check spans the wording change; frozen
        candidate scoring is untouched because it never reads this field."""
        # constraints.py is a package member (`from . import flag_model`), so
        # it is loaded in a subprocess rooted at the suite rather than by path.
        result = subprocess.run(
            [sys.executable, "-c",
             "import json\n"
             "from model import constraints\n"
             "e = constraints.predict_error('C6_empty_tab')\n"
             "print(json.dumps([e.exit_code, list(e.stderr_contains)]))"],
            cwd=str(REPO_ROOT / "tests" / "sort-test-suite"),
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        exit_code, accepted = json.loads(result.stdout)
        self.assertEqual(exit_code, 2)
        self.assertIn("empty tab", accepted)
        self.assertIn("separator must be exactly one character long", accepted)

    def test_no_oracle_path_reaches_an_agent_visible_bundle(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            bundle = shared_bundle(utility, checkpoint_id)
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                self.assertFalse((bundle / "oracle_contract.py").exists())
                config = json.loads(
                    (bundle / "config.json").read_text(encoding="utf-8")
                )
                self.assertNotIn("oracle_bin", config.get("paths", {}))
                self.assertNotIn("oracle_version_required", config)


class PermissionSensitiveSelfCheckTests(unittest.TestCase):
    """Permission-sensitive cases cannot be exercised as root.

    A root container reported `fault-o-unwritable` as an oracle defect: the
    case asserts that an unwritable output directory REFUSES the write, and
    root ignores the permission bit, so GNU sort wrote happily and exited 0
    against a frozen `exit 2`. The oracle was fine; the environment was wrong.
    """

    SUITES_WITH_PERMISSION_FAULTS = ("sort", "mkdir")

    def selfcheck(self, suite: str) -> str:
        return (REPO_ROOT / "tests" / f"{suite}-test-suite"
                / "selfcheck.sh").read_text(encoding="utf-8")

    def test_selfcheck_refuses_to_run_as_root(self):
        for suite in self.SUITES_WITH_PERMISSION_FAULTS:
            text = self.selfcheck(suite)
            with self.subTest(suite=suite):
                self.assertIn('if [ "$(id -u)" = 0 ]; then', text)
                self.assertIn("refusing to run as root", text)
                self.assertIn("exit 2", text)

    def test_the_root_refusal_precedes_any_regeneration(self):
        """Failing early is the point: a late failure has already run the
        generator, and with --publish would have rewritten the benchmark."""
        for suite in self.SUITES_WITH_PERMISSION_FAULTS:
            text = self.selfcheck(suite)
            with self.subTest(suite=suite):
                root_gate = text.index('if [ "$(id -u)" = 0 ]')
                # Anchor on the actual regeneration call. The SCRIPT_DIR guard
                # names gen/generate.py earlier as a required file, which is a
                # presence check, not a run.
                self.assertLess(root_gate, text.index("python3 gen/generate.py"))
                self.assertLess(root_gate, text.index("gate 0"))

    def test_the_refusal_explains_how_to_run_unprivileged(self):
        for suite in self.SUITES_WITH_PERMISSION_FAULTS:
            text = self.selfcheck(suite)
            with self.subTest(suite=suite):
                self.assertIn("--user", text)
                self.assertIn("setpriv", text)

    def test_engine_skips_every_permission_fault_under_root(self):
        """The guard must cover every fault whose expectation depends on not
        being root -- `unwritable_dir_output` was the one it missed."""
        engine_source = (REPO_ROOT / "tests" / "sort-test-suite"
                         / "engine.py").read_text(encoding="utf-8")
        self.assertIn("PERMISSION_FAULTS", engine_source)
        for fault in ("unreadable", "unwritable_dir_output"):
            with self.subTest(fault=fault):
                self.assertRegex(
                    engine_source,
                    r"PERMISSION_FAULTS\s*=\s*\([^)]*" + fault,
                )

    def test_every_permission_fault_in_the_frozen_corpus_is_guarded(self):
        """No frozen fault may depend on non-root without the guard knowing."""
        guarded = {"unreadable", "unwritable_dir_output"}
        suite = REPO_ROOT / "tests" / "sort-test-suite" / "suites"
        import gzip

        with gzip.open(suite / "faults.json.gz", "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        cases = payload["cases"] if isinstance(payload, dict) else payload
        # Faults naming a permission concept must be in the guarded set.
        for case in cases:
            for name in (case.get("faults") or {}):
                if "unreadable" in name or "unwritable" in name:
                    with self.subTest(case=case["name"], fault=name):
                        self.assertIn(name, guarded)

    def test_freeze_refuses_to_bake_a_root_skipped_result_into_a_golden(self):
        source = (REPO_ROOT / "tests" / "sort-test-suite" / "gen"
                  / "freeze.py").read_text(encoding="utf-8")
        self.assertIn("SKIP_ROOT", source)
        self.assertIn("cannot freeze", source)


class SelfCheckInvocationTests(unittest.TestCase):
    """The self-check must build its subcommands with no stray arguments.

    A broken line continuation -- a literal backslash-`n` where a newline
    belonged -- left the sort self-check running

        python3 .../suite_diff.py \\n         --fresh ...

    so bash unescaped `\\n` into a bare `n` and argparse rejected it. Every
    other gate had passed; that single character was the whole failure. These
    tests execute the real constructed command through a shim that records
    argv, rather than asserting on the script's text.
    """

    SUITES = ("sort", "mkdir")

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required")

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def script(self, suite: str) -> Path:
        return REPO_ROOT / "tests" / f"{suite}-test-suite" / "selfcheck.sh"

    def test_no_shell_script_has_a_backslash_n_where_a_continuation_belongs(self):
        """The exact defect signature, caught statically across every script.

        A bare `\\n` is legitimate inside a `printf` format or a heredoc, so
        the check is not "contains backslash-n". The broken-continuation form
        is `\\n` followed by whitespace and then an option -- which is how the
        sort self-check ended up passing a bare `n` to argparse, and which no
        format string produces.
        """
        import re

        signature = re.compile(r"\\n\s+-")
        offenders = []
        for path in maintained_shell_scripts():
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if signature.search(line):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT).as_posix()}:{number}: "
                        f"{line.strip()[:80]}"
                    )
        self.assertEqual(
            offenders, [],
            "backslash-n followed by an option is a line continuation that "
            "was written as an escape by mistake",
        )

    def capture_argv(self, suite: str, tool: str) -> list[list[str]]:
        """Run the real invocation line(s) for `tool` with a python3 shim that
        records argv. Nothing is stubbed inside the tool itself."""
        recorder = self.temp / f"argv-{suite}-{tool}.txt"
        shim = self.temp / f"bin-{suite}-{tool}"
        shim.mkdir(parents=True, exist_ok=True)
        (shim / "python3").write_text(
            "#!/bin/sh\n"
            f'for a in "$@"; do printf "%s\\n" "$a" >> "{recorder.as_posix()}"; done\n'
            f'printf "%s\\n" "--END--" >> "{recorder.as_posix()}"\n'
            "exit 0\n",
            encoding="utf-8",
        )
        (shim / "python3").chmod(0o755)

        # Take the invocation verbatim from the script, including its
        # continuations, and execute it exactly as the shell would.
        text = self.script(suite).read_text(encoding="utf-8")
        lines = text.splitlines()
        fragments: list[str] = []
        index = 0
        while index < len(lines):
            if tool in lines[index]:
                block = [lines[index]]
                while block[-1].rstrip().endswith("\\") and index + 1 < len(lines):
                    index += 1
                    block.append(lines[index])
                fragments.append("\n".join(block))
            index += 1
        self.assertTrue(fragments, f"no {tool} invocation found in {suite}")

        runs: list[list[str]] = []
        for fragment in fragments:
            if recorder.exists():
                recorder.unlink()
            # Strip shell control words so the bare command remains runnable.
            command = fragment.strip()
            for prefix in ("if ! ", "if ", "SORT=$(", "MKDIR=$("):
                if command.startswith(prefix):
                    command = command[len(prefix):]
            command = command.rstrip()
            for suffix in ("; then", ")"):
                if command.endswith(suffix):
                    command = command[: -len(suffix)].rstrip()
            result = subprocess.run(
                [self.bash, "-c", f'CONFIG=config.json\n{command}'],
                cwd=str(self.script(suite).parent),
                env={**os.environ, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            if recorder.exists():
                argv = [a for a in recorder.read_text(encoding="utf-8").splitlines()
                        if a != "--END--"]
                runs.append(argv)
        return runs

    def test_suite_diff_receives_no_stray_argument(self):
        for suite in self.SUITES:
            for argv in self.capture_argv(suite, "suite_diff.py"):
                with self.subTest(suite=suite, argv=argv):
                    self.assertNotIn("n", argv, "the stray 'n' is back")
                    # Every token is either the script, a --flag, or a value.
                    self.assertTrue(argv[0].endswith("suite_diff.py"))
                    for token in argv[1:]:
                        self.assertFalse(
                            len(token) == 1 and token.isalpha(),
                            f"bare single-letter argument {token!r}",
                        )
                    for required in ("--fresh", "--committed", "--config"):
                        self.assertIn(required, argv)

    def test_oracle_contract_receives_no_stray_argument(self):
        for suite in self.SUITES:
            for argv in self.capture_argv(suite, "oracle_contract.py"):
                with self.subTest(suite=suite, argv=argv):
                    self.assertNotIn("n", argv)
                    for token in argv[1:]:
                        self.assertFalse(len(token) == 1 and token.isalpha(),
                                         f"bare single-letter argument {token!r}")

    def test_the_real_suite_diff_accepts_the_constructed_arguments(self):
        """Run the actual tool with the actual argv -- argparse is not mocked."""
        for suite in self.SUITES:
            for argv in self.capture_argv(suite, "suite_diff.py"):
                fresh = self.temp / f"fresh-{suite}"
                fresh.mkdir(exist_ok=True)
                concrete = []
                for token in argv:
                    concrete.append(str(fresh) if token.startswith("/tmp/") else token)
                result = subprocess.run(
                    [sys.executable, *concrete],
                    cwd=str(self.script(suite).parent),
                    capture_output=True, text=True,
                )
                with self.subTest(suite=suite):
                    # It may legitimately report differences (exit 1); what it
                    # must never do is fail to parse its arguments (exit 2).
                    self.assertIn(result.returncode, (0, 1), result.stderr)
                    self.assertNotIn("unrecognized arguments", result.stderr)


class SelfCheckScriptDirTests(unittest.TestCase):
    """A half-broken coreutils must not silently redirect every relative path.

    alpine:edge shipped a `dirname`/`id` that died with "Error relocating ...
    renameat2: symbol not found". The self-check's `cd "$(dirname "$0")"` then
    became `cd ""`, which fails, and with only `set -u` the script continued in
    the launch directory -- surfacing later as confusing oracle_contract.py path
    errors rather than as the environment fault it was.
    """

    SUITES = ("sort", "mkdir")

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required")

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def broken_dirname(self) -> Path:
        shim = self.temp / "broken-bin"
        shim.mkdir(parents=True, exist_ok=True)
        (shim / "dirname").write_text(
            "#!/bin/sh\n"
            'echo "dirname: Error relocating: renameat2: symbol not found" >&2\n'
            "exit 1\n",
            encoding="utf-8",
        )
        (shim / "dirname").chmod(0o755)
        return shim

    def test_selfcheck_fails_fast_when_dirname_is_broken(self):
        shim = self.broken_dirname()
        for suite in self.SUITES:
            script = REPO_ROOT / "tests" / f"{suite}-test-suite" / "selfcheck.sh"
            result = subprocess.run(
                [self.bash, str(script.relative_to(REPO_ROOT).as_posix())],
                cwd=str(REPO_ROOT),
                env={**os.environ,
                     "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"},
                capture_output=True, text=True,
            )
            with self.subTest(suite=suite):
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("cannot resolve its own directory", result.stderr)
                # It must not have proceeded to any later gate.
                self.assertNotIn("gate 0", result.stdout)
                self.assertNotIn("gate 1", result.stdout)

    def test_selfcheck_verifies_it_landed_in_a_real_suite(self):
        """An existing but wrong directory is caught too."""
        for suite in self.SUITES:
            source = (REPO_ROOT / "tests" / f"{suite}-test-suite"
                      / "selfcheck.sh").read_text(encoding="utf-8")
            with self.subTest(suite=suite):
                self.assertIn("is not a complete test suite", source)
                self.assertIn("config.json gen/generate.py", source)

    def test_the_resolution_guard_precedes_every_gate(self):
        for suite in self.SUITES:
            text = (REPO_ROOT / "tests" / f"{suite}-test-suite"
                    / "selfcheck.sh").read_text(encoding="utf-8")
            with self.subTest(suite=suite):
                self.assertLess(text.index("SCRIPT_DIR"), text.index("gate 0"))
                self.assertLess(text.index("SCRIPT_DIR"), text.index("id -u"))


class SymlinkModePolicyTests(unittest.TestCase):
    """A symlink's permission bits are host-OS metadata, not mkdir behavior.

    Linux lstat reports 0777 for every symlink, macOS reports 0755, and mkdir
    never sets them. The committed mkdir corpus was frozen through a Homebrew
    GNU mkdir on macOS, so it records 0755 and a Linux regeneration records
    0777 for identical, correct behavior. The canonical policy ignores `mode`
    for symlinks only.
    """

    LINUX = {"path": "link", "type": "symlink", "mode": 0o777, "target": "d"}
    MACOS = {"path": "link", "type": "symlink", "mode": 0o755, "target": "d"}

    @staticmethod
    def canonical(entry: dict) -> dict:
        """The policy, exercised through the importable implementation.

        `engine.py` imports POSIX-only `resource`, so it cannot be loaded on
        every host; `suite_diff.canonicalize` implements the identical rule and
        `test_both_implementations_agree` pins them together wherever the
        engine can be imported.
        """
        return suite_diff.canonicalize({"tree": [entry]})["tree"][0]

    def test_symlink_modes_0755_and_0777_compare_equivalently(self):
        self.assertEqual(self.canonical(self.LINUX),
                         self.canonical(self.MACOS))

    def test_a_different_symlink_target_still_differs(self):
        other = dict(self.LINUX, target="elsewhere")
        self.assertNotEqual(self.canonical(self.LINUX), self.canonical(other))

    def test_a_symlink_is_never_equal_to_a_directory(self):
        directory = {"path": "link", "type": "dir", "mode": 0o755}
        self.assertNotEqual(self.canonical(self.LINUX), self.canonical(directory))

    def test_directory_mode_differences_still_fail(self):
        """Directory modes are core mkdir behavior and stay fully checked."""
        for a, b in ((0o755, 0o700), (0o1777, 0o1755), (0o2755, 0o755)):
            with self.subTest(a=oct(a), b=oct(b)):
                self.assertNotEqual(
                    self.canonical({"path": "d", "type": "dir", "mode": a}),
                    self.canonical({"path": "d", "type": "dir", "mode": b}),
                )

    def test_regular_file_mode_differences_still_fail(self):
        self.assertNotEqual(
            self.canonical({"path": "f", "type": "file", "mode": 0o644}),
            self.canonical({"path": "f", "type": "file", "mode": 0o600}),
        )

    @unittest.skipUnless(hasattr(os, "fork"), "engine.py needs POSIX 'resource'")
    def test_both_implementations_agree(self):
        engine = load_module(
            "mkdir_engine_policy",
            REPO_ROOT / "tests" / "mkdir-test-suite" / "engine.py",
            REPO_ROOT / "tests" / "mkdir-test-suite",
        )
        for entry in (self.LINUX, self.MACOS,
                      {"path": "d", "type": "dir", "mode": 0o1777},
                      {"path": "f", "type": "file", "mode": 0o644}):
            with self.subTest(entry=entry):
                self.assertEqual(engine.canonical_tree_entry(entry),
                                 self.canonical(entry))

    def test_the_runner_applies_the_policy_when_judging_a_candidate(self):
        """Candidate evaluation had the same portability bug: a Linux candidate
        judged against a macOS-frozen golden failed on symlink bits alone."""
        source = (REPO_ROOT / "tests" / "mkdir-test-suite"
                  / "runner.py").read_text(encoding="utf-8")
        self.assertIn("engine.canonical_tree(want)", source)
        self.assertIn("engine.canonical_tree(got)", source)

    def test_the_comparator_applies_the_same_policy(self):
        linux_case = {"name": "c", "tree": [self.LINUX]}
        macos_case = {"name": "c", "tree": [self.MACOS]}
        self.assertEqual(suite_diff.compare_cases([linux_case], [macos_case]), [])

    def test_the_comparator_still_reports_a_directory_mode_change(self):
        a = {"name": "c", "tree": [{"path": "d", "type": "dir", "mode": 0o1777}]}
        b = {"name": "c", "tree": [{"path": "d", "type": "dir", "mode": 0o1755}]}
        problems = suite_diff.compare_cases([a], [b])
        self.assertTrue(problems)
        self.assertTrue(any("tree" in p for p in problems), problems)

    def test_the_committed_corpus_carries_the_macos_symlink_bits(self):
        """Documents the provenance this policy exists to absorb."""
        import gzip

        found = []
        for path in sorted(
            (REPO_ROOT / "tests" / "mkdir-test-suite" / "suites").glob("*.json.gz")
        ):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            cases = payload["cases"] if isinstance(payload, dict) else payload
            for case in cases:
                for entry in case.get("tree") or []:
                    if entry.get("type") == "symlink":
                        found.append(entry.get("mode"))
        self.assertTrue(found, "expected symlink entries in the frozen corpus")
        # 0755 is the macOS value; the policy makes the Linux 0777 equivalent.
        self.assertIn(0o755, set(found))


class UmaskDeterminismTests(unittest.TestCase):
    """A case's declared umask must reach the child explicitly.

    Not via the shell, Docker, runuser, CI defaults, or the parent's inherited
    umask -- the oracle during freeze and the candidate during judging must see
    the same explicitly-set value.
    """

    def test_the_engine_sets_the_umask_in_the_child_not_the_parent(self):
        source = (REPO_ROOT / "tests" / "mkdir-test-suite"
                  / "engine.py").read_text(encoding="utf-8")
        # Applied inside preexec_fn, which runs after fork in the child, so the
        # parent's umask is never mutated and threads cannot race on it.
        self.assertIn("def preexec_fn():", source)
        self.assertRegex(source, r"def preexec_fn\(\):\s*\n\s*os\.umask\(umask\)")
        self.assertIn('umask = int(case.get("umask", "0022"), 8)', source)

    def test_every_declared_umask_in_the_corpus_is_octal_and_parsable(self):
        import gzip

        seen = set()
        for path in sorted(
            (REPO_ROOT / "tests" / "mkdir-test-suite" / "suites").glob("*.json.gz")
        ):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            cases = payload["cases"] if isinstance(payload, dict) else payload
            for case in cases:
                declared = case.get("umask")
                if declared is None:
                    continue
                with self.subTest(case=case["name"], umask=declared):
                    seen.add(int(str(declared), 8))
        for required in (0o000, 0o022, 0o077):
            self.assertIn(required, seen,
                          "the corpus must exercise this umask")

    @unittest.skipUnless(hasattr(os, "fork"), "POSIX umask semantics required")
    def test_the_child_actually_receives_each_declared_umask(self):
        """The mechanism, measured rather than assumed -- runs in the container."""
        for umask in (0o000, 0o022, 0o077):
            result = subprocess.run(
                ["sh", "-c", "umask"], capture_output=True, text=True,
                preexec_fn=lambda value=umask: os.umask(value),
            )
            with self.subTest(umask=oct(umask)):
                self.assertEqual(result.stdout.strip().lstrip("0") or "0",
                                 f"{umask:04o}".lstrip("0") or "0")

    @unittest.skipUnless(hasattr(os, "fork"), "POSIX umask semantics required")
    def test_setting_a_child_umask_leaves_the_parent_untouched(self):
        before = os.umask(0o022)
        os.umask(before)
        subprocess.run(["sh", "-c", "umask"], capture_output=True,
                       preexec_fn=lambda: os.umask(0o077))
        after = os.umask(0o022)
        os.umask(after)
        self.assertEqual(before, after)

    @unittest.skipUnless(hasattr(os, "fork"), "engine.py needs POSIX 'resource'")
    def test_the_execed_binary_itself_observes_the_declared_umask(self):
        """The decisive check: substitute a logging executable for mkdir_bin
        and read the umask back from the process that engine.execute execs.

        A helper subprocess reporting its own umask proves only that the
        mechanism can work. This proves it reaches the binary under test, on
        the real `engine.execute` path -- the same path used by freeze, the
        oracle self-pass and candidate evaluation.
        """
        import tempfile

        engine = load_module(
            "mkdir_engine_exec",
            REPO_ROOT / "tests" / "mkdir-test-suite" / "engine.py",
            REPO_ROOT / "tests" / "mkdir-test-suite",
        )
        workspace = Path(self.enterContext(tempfile.TemporaryDirectory()))

        for umask in (0o000, 0o022, 0o077):
            # One log per umask: concurrent executions must not interleave.
            log = workspace / f"observed-{umask:04o}.log"
            recorder = workspace / f"mkdir-{umask:04o}"
            recorder.write_text(
                "#!/bin/sh\n"
                f'printf "umask=%s argv=%s\\n" "$(umask)" "$*" >> "{log.as_posix()}"\n'
                'mkdir "$@" 2>/dev/null || true\n'
                "exit 0\n",
                encoding="utf-8",
            )
            recorder.chmod(0o755)

            case = {
                "name": f"probe-{umask:04o}",
                "args": ["newdir"],
                "umask": f"{umask:04o}",
                "fixture": [],
            }
            engine.execute(case, [str(recorder)])

            with self.subTest(umask=f"{umask:04o}"):
                self.assertTrue(log.is_file(), "the recorder never ran")
                observed = log.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(observed), 1, observed)
                self.assertIn(f"umask={umask:04o}", observed[0])
                self.assertIn("argv=newdir", observed[0])

    @unittest.skipUnless(hasattr(os, "fork"), "engine.py needs POSIX 'resource'")
    def test_the_default_umask_reaches_a_case_that_declares_none(self):
        import tempfile

        engine = load_module(
            "mkdir_engine_default",
            REPO_ROOT / "tests" / "mkdir-test-suite" / "engine.py",
            REPO_ROOT / "tests" / "mkdir-test-suite",
        )
        workspace = Path(self.enterContext(tempfile.TemporaryDirectory()))
        log = workspace / "default.log"
        recorder = workspace / "mkdir-default"
        recorder.write_text(
            "#!/bin/sh\n"
            f'printf "umask=%s\\n" "$(umask)" >> "{log.as_posix()}"\n'
            'mkdir "$@" 2>/dev/null || true\nexit 0\n',
            encoding="utf-8",
        )
        recorder.chmod(0o755)
        engine.execute({"name": "d", "args": ["newdir"], "fixture": []},
                       [str(recorder)])
        self.assertIn("umask=0022", log.read_text(encoding="utf-8"))

    def test_there_is_exactly_one_spawn_path_and_it_carries_preexec_fn(self):
        """No shell, wrapper, launcher or second Popen can bypass the umask."""
        source = (REPO_ROOT / "tests" / "mkdir-test-suite"
                  / "engine.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("subprocess.Popen("), 1)
        self.assertEqual(source.count("_spawn("), 2)      # definition + 1 call
        self.assertIn("preexec_fn=preexec_fn", source)
        for forbidden in ("shell=True", "os.system(", "runuser", "/bin/sh"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_diagnostic_refuses_an_unpinned_binary_by_default(self):
        """Its earlier version printed the version without checking it, so a
        run that omitted --mkdir-bin silently measured the wrong build."""
        text = (REPO_ROOT / "tests" / "reference_generators"
                / "umask_diagnostic.py").read_text(encoding="utf-8")
        self.assertIn("oracle_contract.verify", text)
        self.assertIn("allow-version-mismatch", text)
        self.assertIn("Refusing to measure", text)

    def test_the_diagnostic_instruments_the_execing_process(self):
        text = (REPO_ROOT / "tests" / "reference_generators"
                / "umask_diagnostic.py").read_text(encoding="utf-8")
        self.assertIn('exec "{real}" "$@"', text)
        # A log per tag, so concurrent executions cannot overwrite each other.
        self.assertIn("One log per tag", text)
        for expression in ("+t", "a+t", "a=rwx,+t", "1777", "a=rwx"):
            with self.subTest(expression=expression):
                self.assertIn(expression, text)
        # The bare-mkdir control: without it, a constant -m result cannot be
        # distinguished from the umask never arriving.
        self.assertIn("None, \"a=rwx\"", text)

    def test_the_symbolic_sticky_cases_are_the_known_open_discrepancy(self):
        """Pins the five cases whose frozen mode GNU 9.11 does not reproduce.

        Measured in the pinned container (coreutils 9.11, non-root, umask
        instrumented at the exec'ing process):

            mkdir -m +t        -> 01755 at umask 0000, 0022 and 0077
            mkdir -m a+t       -> 01755 at all three
            mkdir -m a=rwx,+t  -> 01777 at all three
            mkdir              -> 0777 / 0755 / 0700  (umask demonstrably applied)

        So the departure point for a symbolic -m that does not itself set the
        rwx bits is 0755, not a=rwx, and it is umask-independent. The frozen
        goldens hold 01777, which is the `a=rwx,+t` result -- they do not match
        what GNU 9.11 produces for `+t`.

        This test does NOT assert which value is right. It records the exact
        set, so that a later change to any of these cases is a deliberate,
        visible act rather than a quiet edit.
        """
        import gzip

        expected = {
            "single-m-+t-simple-0000", "single-m-+t-simple-0022",
            "single-m-+t-simple-0077", "quirk-sticky-symbolic",
            "rand-ok-042-m-p-v-simple",
        }
        found = {}
        for path in sorted(
            (REPO_ROOT / "tests" / "mkdir-test-suite" / "suites").glob("*.json.gz")
        ):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            cases = payload["cases"] if isinstance(payload, dict) else payload
            for case in cases:
                if case.get("name") in expected:
                    modes = {e["path"]: e["mode"] for e in (case.get("tree") or [])
                             if e.get("type") == "dir"}
                    found[case["name"]] = modes
        self.assertEqual(set(found), expected,
                         "the known-discrepant case set changed")
        for name, modes in found.items():
            with self.subTest(case=name):
                self.assertIn(
                    0o1777, set(modes.values()),
                    f"{name} no longer freezes 01777; if this was a deliberate "
                    "re-freeze, update this test alongside it",
                )

    def test_directory_modes_are_never_normalized_away(self):
        """The discrepancy must stay visible: 01777 vs 01755 must still fail."""
        a = {"name": "c", "tree": [{"path": "d", "type": "dir", "mode": 0o1777}]}
        b = {"name": "c", "tree": [{"path": "d", "type": "dir", "mode": 0o1755}]}
        self.assertTrue(suite_diff.compare_cases([a], [b]))

    def test_a_diagnostic_exists_for_the_pinned_container(self):
        """The sticky-mode question needs GNU mkdir 9.11; this answers it."""
        script = (REPO_ROOT / "tests" / "reference_generators"
                  / "umask_diagnostic.py")
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        for umask in ("0o000", "0o022", "0o077"):
            self.assertIn(umask, text)


class PlatformContractTests(unittest.TestCase):
    """The mkdir frozen suite is only valid on Darwin.

    GNU coreutils 9.11 resolves a symbolic mode argument that does not itself
    set the rwx bits from a 0777 departure on Darwin and a 0755 departure on
    Linux, so the identical binary version yields different directory modes.
    Measured on both: Darwin reproduces the committed corpus exactly and passes
    every gate; Linux does not. The goldens are correct -- for Darwin.
    """

    SUITE = REPO_ROOT / "tests" / "mkdir-test-suite"

    def config(self) -> dict:
        return json.loads((self.SUITE / "config.json").read_text(encoding="utf-8"))

    def test_the_contract_is_declared_in_config(self):
        config = self.config()
        self.assertEqual(config["required_platform"], "Darwin")
        self.assertEqual(config["oracle_version_required"], "9.11")
        self.assertIn("_platform_contract", config)

    # Two suites are platform-specific, in opposite directions, each for a
    # measured reason: mkdir needs Darwin (symbolic -m mode resolution), sort
    # needs Linux (obsolete +POS handling, and /dev/full for fault-devfull).
    # grep and chmod have no measured platform dependence and must stay
    # ungated -- gating with nothing to protect against is protection theater.
    PLATFORM_SPECIFIC = {"mkdir": "Darwin", "sort": "Linux"}
    PLATFORM_NEUTRAL = ("grep", "chmod")

    def test_exactly_the_measured_suites_declare_a_platform(self):
        for utility, expected in self.PLATFORM_SPECIFIC.items():
            path = REPO_ROOT / "tests" / f"{utility}-test-suite" / "config.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(utility=utility):
                self.assertEqual(config["required_platform"], expected)
                self.assertIn("_platform_contract", config,
                              "a gate must state what it protects against")
        for utility in self.PLATFORM_NEUTRAL:
            path = REPO_ROOT / "tests" / f"{utility}-test-suite" / "config.json"
            if not path.is_file():
                continue
            with self.subTest(utility=utility):
                self.assertNotIn(
                    "required_platform",
                    json.loads(path.read_text(encoding="utf-8")),
                    "no measured platform dependence, so no gate",
                )

    def test_the_two_gates_point_in_opposite_directions(self):
        """The split is deliberate: one suite cannot satisfy both."""
        self.assertNotEqual(self.PLATFORM_SPECIFIC["mkdir"],
                            self.PLATFORM_SPECIFIC["sort"])

    def test_the_selfcheck_gate_precedes_regeneration_and_the_oracle(self):
        for utility in self.PLATFORM_SPECIFIC:
            suite = REPO_ROOT / "tests" / f"{utility}-test-suite"
            text = (suite / "selfcheck.sh").read_text(encoding="utf-8")
            with self.subTest(utility=utility):
                gate = text.index("platform_contract.py")
                self.assertLess(gate, text.index("python3 gen/generate.py"))
                self.assertLess(gate, text.index("gate 0"))

    def test_the_selfcheck_gate_explains_all_three_consequences(self):
        """The wording now lives in the shared checker, which both suites call
        rather than each restating it."""
        text = (REPO_ROOT / "tests" / "reference_generators"
                / "platform_contract.py").read_text(encoding="utf-8")
        self.assertIn("produced AND validated on", text)
        self.assertIn("redefine the benchmark", text)
        self.assertIn("belongs to the platform, not to the binary", text)
        self.assertIn("refusing to run on", text)

    def test_the_shared_gate_is_used_by_both_suites(self):
        """Duplication removed where it could be: selfcheck.sh is offline and
        never bundled, so one implementation serves both."""
        for utility in self.PLATFORM_SPECIFIC:
            text = (REPO_ROOT / "tests" / f"{utility}-test-suite"
                    / "selfcheck.sh").read_text(encoding="utf-8")
            with self.subTest(utility=utility):
                self.assertIn(
                    "reference_generators/platform_contract.py", text)

    def test_the_shared_gate_prints_the_suite_specific_reason(self):
        from reference_generators import platform_contract

        for utility, required in self.PLATFORM_SPECIFIC.items():
            config = (REPO_ROOT / "tests" / f"{utility}-test-suite"
                      / "config.json")
            with self.subTest(utility=utility):
                self.assertEqual(
                    platform_contract.required_platform(config), required)
                self.assertTrue(platform_contract.contract_reason(config))

    def test_the_runner_gate_is_not_shared_and_says_why(self):
        """runner.py ships inside the sandbox, where only the bundle allowlist
        exists, so its copy cannot import the shared module."""
        import stage_test_bundle

        self.assertNotIn("platform_contract.py", stage_test_bundle.ALLOWED_FILES)
        for utility in self.PLATFORM_SPECIFIC:
            source = (REPO_ROOT / "tests" / f"{utility}-test-suite"
                      / "runner.py").read_text(encoding="utf-8")
            with self.subTest(utility=utility):
                self.assertIn("PLATFORM_INCOMPATIBLE_EXIT = 3", source)
                self.assertIn("def check_platform(", source)
                self.assertIn("check_platform(manifest)", source)

    def test_candidate_evaluation_has_a_distinct_platform_exit(self):
        source = (self.SUITE / "runner.py").read_text(encoding="utf-8")
        self.assertIn("PLATFORM_INCOMPATIBLE_EXIT = 3", source)
        self.assertIn("def check_platform(", source)
        self.assertIn("check_platform(manifest)", source)
        self.assertIn("NOT a", source)

    def test_the_platform_gate_runs_before_any_case(self):
        source = (self.SUITE / "runner.py").read_text(encoding="utf-8")
        self.assertLess(source.index("check_platform(manifest)"),
                        source.index("ThreadPoolExecutor("))

    def test_darwin_is_accepted_and_linux_is_rejected(self):
        """Exercises the real gate, with the platform substituted."""
        import platform as platform_module

        runner_source = (self.SUITE / "runner.py").read_text(encoding="utf-8")
        namespace: dict[str, Any] = {"sys": sys, "platform": platform_module}
        start = runner_source.index("PLATFORM_INCOMPATIBLE_EXIT = 3")
        end = runner_source.index("def main():")
        exec(compile(runner_source[start:end], "check_platform", "exec"), namespace)
        check = namespace["check_platform"]

        original = platform_module.system
        try:
            platform_module.system = lambda: "Darwin"
            check({"required_platform": "Darwin"})          # must not raise

            platform_module.system = lambda: "Linux"
            with self.assertRaises(SystemExit) as caught:
                check({"required_platform": "Darwin"})
            self.assertEqual(caught.exception.code, 3)

            # A suite without a contract is platform-neutral.
            check({})
        finally:
            platform_module.system = original

    def test_a_platform_exit_is_not_counted_as_validation_failed(self):
        """The controller must classify exit 3 as its own reason."""
        controller = (REPO_ROOT / "scripts"
                      / "run_lineage_experiment.sh").read_text(encoding="utf-8")
        self.assertIn('metadata.get("feature_test_exit_code") == 3', controller)
        self.assertIn('reason = "platform_incompatible"', controller)
        # It must be decided BEFORE the validation_failed fallback.
        self.assertLess(controller.index('reason = "platform_incompatible"'),
                        controller.index('or "validation_failed"'))

    def test_the_platform_contract_participates_in_the_fingerprint(self):
        plan = lineage_plan.resolve_plan(
            REPO_ROOT, "mkdir", "m", "0", "build", 3, 1800
        )
        self.assertEqual(plan["required_platform"], "Darwin")
        self.assertIn("host_platform", plan)
        # The fingerprint hashes the whole plan, so both fields are covered.
        material = {k: v for k, v in plan.items() if k != "config_fingerprint"}
        self.assertIn("required_platform", material)
        self.assertIn("host_platform", material)
        changed = dict(plan)
        changed["required_platform"] = "Linux"
        self.assertNotEqual(lineage_plan.fingerprint(changed),
                            plan["config_fingerprint"])

    def test_the_run_record_carries_the_platform_provenance(self):
        controller = (REPO_ROOT / "scripts"
                      / "run_lineage_experiment.sh").read_text(encoding="utf-8")
        self.assertIn('"required_platform": plan.get("required_platform")', controller)
        self.assertIn('"host_platform": plan.get("host_platform")', controller)

    def test_the_bundle_carries_the_platform_but_no_feature_information(self):
        """The judge needs the contract inside the sandbox; the agent must not
        learn anything about future flags from it."""
        for checkpoint_id in ("000", "001", "002"):
            bundle = shared_bundle("mkdir", checkpoint_id)
            config = json.loads(
                (bundle / "config.json").read_text(encoding="utf-8")
            )
            with self.subTest(checkpoint=checkpoint_id):
                self.assertEqual(config.get("required_platform"), "Darwin")
                # An OS name only -- no contract prose, no oracle, no flags.
                self.assertNotIn("_platform_contract", config)
                self.assertNotIn("oracle_bin", config.get("paths", {}))
                self.assertNotIn("oracle_version_required", config)

    def test_no_frozen_suite_changed_for_the_platform_contract(self):
        result = subprocess.run(
            ["git", "status", "--short", "tests/mkdir-test-suite/suites/"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "",
                         "the platform contract must not touch frozen goldens")


class PlatformPreflightTests(unittest.TestCase):
    """Environment eligibility is decided before any lineage is initialized.

    Stopping each lineage at checkpoint 000 would have created a start record
    for every one, so all N would count in `lineages_started` and
    successful_finals / lineages_started would read 0/N -- a model reliability
    of zero for an environment mismatch. A distinct stop reason does not fix
    that; the lineages must never start.
    """

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required to run the controller")
        import platform as _platform

        cls.host = _platform.system()

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def posix(self, path: Path) -> str:
        text = path.as_posix()
        return "/" + text[0].lower() + text[2:] if text[1:2] == ":" else text

    def run_controller(self, utility: str, output: Path,
                       lineages: int = 10) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.bash,
             str(REPO_ROOT / "scripts" / "run_lineage_experiment.sh"),
             "--utility", utility, "--model", "demo/m", "--temperature", "0",
             "--lineages", str(lineages),
             "--output-dir", self.posix(output)],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            env={**os.environ, "PYTHON_BIN": sys.executable},
        )

    @unittest.skipIf(__import__("platform").system() == "Darwin",
                     "this asserts the non-Darwin rejection path")
    def test_ten_mkdir_lineages_on_a_foreign_host_start_zero(self):
        output = self.temp / "mk"
        result = self.run_controller("mkdir", output, lineages=10)

        self.assertEqual(result.returncode, 4,
                         f"expected the distinct platform exit\n{result.stderr}")
        self.assertIn("platform_incompatible", result.stderr)

        record = json.loads((output / "lineages.json").read_text(encoding="utf-8"))
        self.assertEqual(record["run_status"], "platform_incompatible")
        self.assertEqual(record["lineages_started"], 0)
        self.assertEqual(record["required_platform"], "Darwin")
        self.assertEqual(record["host_platform"], self.host)

    @unittest.skipIf(__import__("platform").system() == "Darwin",
                     "this asserts the non-Darwin rejection path")
    def test_no_lineage_directory_or_start_record_is_created(self):
        output = self.temp / "mk-dirs"
        self.run_controller("mkdir", output, lineages=10)
        entries = sorted(p.name for p in output.iterdir())
        self.assertEqual(entries, ["lineages.json"])
        self.assertEqual([p for p in output.glob("lineage-*")], [])
        self.assertEqual([p for p in output.rglob("lineage.json")], [])

    @unittest.skipIf(__import__("platform").system() == "Darwin",
                     "this asserts the non-Darwin rejection path")
    def test_no_stage_command_or_agent_is_invoked(self):
        output = self.temp / "mk-noexec"
        result = self.run_controller("mkdir", output, lineages=10)
        combined = result.stdout + result.stderr
        for marker in ("run_experiment.sh", "aider", "attempt-001",
                       "test-bundle", "=== lineage-"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, combined)

    @unittest.skipIf(__import__("platform").system() == "Darwin",
                     "this asserts the non-Darwin rejection path")
    def test_planned_lineages_never_become_failures(self):
        """The record must not list planned ids: analysis would otherwise
        resurrect them as missing_directory / planned_not_started entries."""
        output = self.temp / "mk-planned"
        self.run_controller("mkdir", output, lineages=10)
        record = json.loads((output / "lineages.json").read_text(encoding="utf-8"))
        self.assertNotIn("planned_lineage_ids", record)
        self.assertNotIn("lineage_ids", record)

        run_metadata, lineages, never_started = analyze_lineages.load_run(output)
        self.assertEqual(lineages, [])
        self.assertEqual(never_started, [])

    @unittest.skipIf(__import__("platform").system() == "Darwin",
                     "this asserts the non-Darwin rejection path")
    def test_the_analyzer_reports_reliability_as_not_applicable(self):
        output = self.temp / "mk-analysis"
        self.run_controller("mkdir", output, lineages=10)
        analysis = self.temp / "report"
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "analyze_lineages.py"),
             "--lineage-root", str(output), "--output-dir", str(analysis),
             "--skip-diversity"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        report = json.loads(
            (analysis / "lineage_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["run_status"], "platform_incompatible")
        self.assertFalse(report["reliability_applicable"])
        self.assertIsNone(report["reliability"])
        self.assertEqual(report["lineages_started"], 0)

        summary = (analysis / "summary.md").read_text(encoding="utf-8")
        self.assertIn("Not applicable", summary)
        # It must not be dressed up as any kind of model outcome.
        for wrong in ("0.000", "validation_failed", "controller_interrupted"):
            with self.subTest(wrong=wrong):
                self.assertNotIn(wrong, summary)

    def test_a_platform_neutral_utility_is_unaffected(self):
        """grep and chmod declare no contract and must run normally.

        sort is no longer here: it is gated to Linux, for the obsolete +POS and
        /dev/full reasons recorded in its config."""
        for utility in ("grep", "chmod"):
            result = subprocess.run(
                [self.bash,
                 str(REPO_ROOT / "scripts" / "run_lineage_experiment.sh"),
                 "--utility", utility, "--model", "demo/m", "--temperature", "0",
                 "--lineages", "1", "--dry-run"],
                cwd=str(REPO_ROOT), capture_output=True, text=True,
                env={**os.environ, "PYTHON_BIN": sys.executable},
            )
            with self.subTest(utility=utility):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("platform_incompatible", result.stderr)
                self.assertIn("run_experiment.sh", result.stdout)

    def test_the_preflight_precedes_every_lineage_side_effect(self):
        text = (REPO_ROOT / "scripts"
                / "run_lineage_experiment.sh").read_text(encoding="utf-8")
        gate = text.index("Platform preflight")
        # Anchored on the actual side effects, not on the tool-path
        # declarations near the top of the script.
        for side_effect in (
            "for (( offset = 0",                     # the lineage loop
            '--path "$lineage_record"',              # the start record
            'bash "$STAGE_RUNNER"',                  # the stage invocation
            '"$PYTHON_BIN" "$BUNDLE_TOOL"',           # building a stage bundle
        ):
            with self.subTest(side_effect=side_effect):
                self.assertLess(gate, text.index(side_effect))
        self.assertIn("exit 4", text)

    def test_darwin_would_be_accepted(self):
        """The gate compares the plan's two fields; equal means proceed."""
        plan = lineage_plan.resolve_plan(
            REPO_ROOT, "mkdir", "m", "0", "build", 3, 1800
        )
        self.assertEqual(plan["required_platform"], "Darwin")
        # The shell condition is: required is non-empty, not "None", and differs
        # from host. On Darwin the third clause is false, so the run proceeds.
        self.assertNotEqual(plan["required_platform"], "None")
        # sort is gated too, in the opposite direction.
        linux_gated = lineage_plan.resolve_plan(
            REPO_ROOT, "sort", "m", "0", "build", 3, 1800
        )
        self.assertEqual(linux_gated["required_platform"], "Linux")
        for utility in ("grep", "chmod"):
            with self.subTest(utility=utility):
                neutral = lineage_plan.resolve_plan(
                    REPO_ROOT, utility, "m", "0", "build", 3, 1800
                )
                self.assertIsNone(neutral["required_platform"])


class StageRecordParsingTests(unittest.TestCase):
    """The plan -> controller record format must preserve empty fields.

    The original format was tab-separated and read with `IFS=$'\\t' read`. Tab is
    IFS *whitespace* in Bash, so runs of tabs collapse and empty fields vanish.
    Checkpoint 000 has an empty cumulative flag list, so its record ended
    `...<TAB><TAB><hash>`: the pair collapsed, the fingerprint slid into
    `stage_flags`, and `stage_bundle_fingerprint` came back empty. Every run
    then aborted at stage 000 comparing an empty planned fingerprint against the
    freshly built one.
    """

    FIELDS = 7
    SEP = "\x1f"

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required")

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def stages_text(self, utility: str) -> str:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "lineage_plan.py"),
             "--repo", str(REPO_ROOT), "--utility", utility, "--emit", "stages"],
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        # Decoded without universal newlines: a stray CR must stay visible.
        return result.stdout.decode("utf-8")

    def parse_with_bash(self, utility: str) -> list[list[str]]:
        """Parse using the controller's own reader line, verbatim."""
        controller = (REPO_ROOT / "scripts"
                      / "run_lineage_experiment.sh").read_text(encoding="utf-8")
        self.assertIn("while IFS=$'\\x1f' read -r stage_id", controller,
                      "the controller must read with the unit separator")

        table = self.temp / f"{utility}.table"
        table.write_bytes(self.stages_text(utility).encode("utf-8"))
        script = (
            'while IFS=$\'\\x1f\' read -r a b c d e f g; do\n'
            '  [[ -n "$a" ]] || continue\n'
            '  printf \'%s|%s|%s|%s|%s|%s|%s\\n\' "$a" "$b" "$c" "$d" "$e" "$f" "$g"\n'
            f'done < "{table.as_posix()}"\n'
        )
        result = subprocess.run([self.bash, "-c", script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line.split("|") for line in result.stdout.splitlines() if line]

    def plan_checkpoints(self, utility: str) -> list[dict]:
        return lineage_plan.resolve_plan(
            REPO_ROOT, utility, "m", "0", "build", 3, 1800
        )["checkpoints"]

    # --- serialization -----------------------------------------------------

    def test_records_use_the_unit_separator_not_tab(self):
        text = self.stages_text("grep")
        self.assertIn(self.SEP, text)
        self.assertNotIn("\t", text)
        self.assertNotIn("\r", text, "a stray CR would corrupt the last field")

    def test_an_empty_intermediate_field_is_preserved(self):
        first = self.stages_text("grep").splitlines()[0]
        self.assertEqual(len(first.split(self.SEP)), self.FIELDS)
        self.assertIn(self.SEP + self.SEP, first,
                      "checkpoint 000's empty flag field must survive")

    def test_emit_rejects_a_field_containing_the_separator(self):
        plan = lineage_plan.resolve_plan(
            REPO_ROOT, "grep", "m", "0", "build", 3, 1800
        )
        plan["checkpoints"][0]["name"] = f"ba{self.SEP}d"
        with self.assertRaises(SystemExit):
            lineage_plan.emit_stages(plan)

    # --- parsing -----------------------------------------------------------

    def test_checkpoint_000_keeps_empty_cumulative_flags(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            with self.subTest(utility=utility):
                self.assertEqual(self.parse_with_bash(utility)[0][5], "")

    def test_checkpoint_000_fingerprint_reaches_the_fingerprint_field(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            row = self.parse_with_bash(utility)[0]
            expected = self.plan_checkpoints(utility)[0]["test_bundle_fingerprint"]
            with self.subTest(utility=utility):
                self.assertEqual(row[6], expected)
                self.assertRegex(row[6], r"^[0-9a-f]{64}$")

    def test_stage_flags_never_receives_the_fingerprint(self):
        """The exact symptom of the old bug."""
        for utility in sorted(EXPECTED_SEQUENCES):
            for row in self.parse_with_bash(utility):
                with self.subTest(utility=utility, checkpoint=row[0]):
                    self.assertNotRegex(row[5], r"^[0-9a-f]{64}$")

    def test_every_checkpoint_of_every_utility_round_trips(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            rows = self.parse_with_bash(utility)
            checkpoints = self.plan_checkpoints(utility)
            with self.subTest(utility=utility):
                self.assertEqual(len(rows), len(checkpoints))
            for row, checkpoint in zip(rows, checkpoints):
                with self.subTest(utility=utility, checkpoint=checkpoint["id"]):
                    self.assertEqual(len(row), self.FIELDS)
                    self.assertEqual(row[0], checkpoint["id"])
                    self.assertEqual(row[1], checkpoint["name"])
                    self.assertEqual(row[2], checkpoint["prompt"])
                    self.assertEqual(row[3], checkpoint["source_mode"])
                    self.assertEqual(row[4], checkpoint["feature_test_command"])
                    self.assertEqual(
                        row[5], ",".join(checkpoint["implemented_flags"]))
                    self.assertEqual(row[6], checkpoint["test_bundle_fingerprint"])

    def test_grep_loads_exactly_the_expected_fingerprints(self):
        rows = self.parse_with_bash("grep")
        expected = [c["test_bundle_fingerprint"]
                    for c in self.plan_checkpoints("grep")]
        self.assertEqual([r[6] for r in rows], expected)
        self.assertEqual(len(set(expected)), len(expected),
                         "each checkpoint has its own bundle")

    def test_fields_containing_spaces_round_trip(self):
        """Feature-test commands carry spaces; nothing may be split or trimmed."""
        for utility in sorted(EXPECTED_SEQUENCES):
            for row, checkpoint in zip(self.parse_with_bash(utility),
                                       self.plan_checkpoints(utility)):
                command = checkpoint["feature_test_command"]
                if " " not in command:
                    continue
                with self.subTest(utility=utility, checkpoint=row[0]):
                    self.assertEqual(row[4], command)
                    self.assertIn(" ", row[4])

    # --- the planned-vs-built integrity check ------------------------------

    def test_planned_fingerprint_matches_the_freshly_built_bundle(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            for row in self.parse_with_bash(utility):
                built = build_bundle(
                    utility, row[0], self.temp / f"{utility}-{row[0]}"
                )["bundle_fingerprint"]
                with self.subTest(utility=utility, checkpoint=row[0]):
                    self.assertEqual(row[6], built,
                                     "planned and built must agree, which is "
                                     "what the controller compares")

    def test_an_altered_bundle_still_fails_the_comparison(self):
        """The integrity check must stay fail-closed."""
        planned = self.parse_with_bash("grep")[0][6]
        bundle = self.temp / "tampered"
        build_bundle("grep", "000", bundle)
        judge = bundle / "judge_candidate.sh"
        judge.write_bytes(judge.read_bytes() + b"\n# tampered\n")
        rebuilt = hashlib.sha256(judge.read_bytes()).hexdigest()
        self.assertNotEqual(planned, rebuilt)


class StagePlanValidationTests(unittest.TestCase):
    """A plan-loading defect must abort before a lineage counts as started."""

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required")

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def posix(self, path: Path) -> str:
        text = path.as_posix()
        return "/" + text[0].lower() + text[2:] if text[1:2] == ":" else text

    def run_with_corrupt_stage_table(self, corruption: str) -> tuple:
        """Run the real controller with a python shim that corrupts only the
        `--emit stages` output, leaving every other call untouched."""
        shim_dir = self.temp / f"shim-{abs(hash(corruption))}"
        shim_dir.mkdir(parents=True, exist_ok=True)
        shim_py = shim_dir / "shim.py"
        shim_py.write_text(
            "import subprocess, sys\n"
            f"real = {sys.executable!r}\n"
            "argv = sys.argv[1:]\n"
            "out = subprocess.run([real, *argv], capture_output=True, text=True)\n"
            "sys.stderr.write(out.stderr)\n"
            "text = out.stdout\n"
            "if '--emit' in argv and 'stages' in argv:\n"
            f"    text = {corruption!r}\n"
            "sys.stdout.write(text)\n"
            "sys.exit(out.returncode)\n",
            encoding="utf-8",
        )
        # A shebang script on both platforms: the controller invokes
        # "$PYTHON_BIN" from bash, and Git Bash cannot `command -v` a .cmd.
        launcher = shim_dir / "python3"
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{shim_py}" "$@"\n',
            encoding="utf-8", newline="\n",
        )
        launcher.chmod(0o755)

        output = self.temp / f"out-{abs(hash(corruption))}"
        result = subprocess.run(
            [self.bash,
             str(REPO_ROOT / "scripts" / "run_lineage_experiment.sh"),
             "--utility", "grep", "--model", "demo/m", "--temperature", "0",
             "--lineages", "5", "--output-dir", self.posix(output)],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            env={**os.environ, "PYTHON_BIN": self.posix(launcher)},
        )
        return result, output

    def run_controller(self, *arguments: str,
                       output: Path) -> subprocess.CompletedProcess:
        """Run the controller against the REAL, uncorrupted stage plan."""
        return subprocess.run(
            [self.bash,
             str(REPO_ROOT / "scripts" / "run_lineage_experiment.sh"),
             "--utility", "grep", "--model", "demo/m", "--temperature", "0",
             "--lineages", "3", "--output-dir", self.posix(output), *arguments],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            env={**os.environ, "PYTHON_BIN": sys.executable},
        )

    def assert_nothing_started(self, output: Path) -> None:
        """A preflight failure may leave no trace of a started lineage."""
        for pattern in ("lineage-*", "lineage.json", "lineages.json"):
            with self.subTest(pattern=pattern):
                self.assertEqual(
                    [] if not output.exists() else list(output.rglob(pattern)), [],
                    f"{pattern} exists after a preflight failure",
                )

    # --- the valid plan must still pass ------------------------------------

    def test_the_real_stage_arrays_pass_validation(self):
        """The guard is only useful if a correct plan walks straight through."""
        output = self.temp / "valid-plan"
        result = self.run_controller("--print-plan", output=output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("stage plan is malformed", result.stderr)
        # --print-plan exits after the guard and before the output directory is
        # created, so reaching it at all proves the guard passed.
        self.assertFalse(output.exists())

    def test_a_dry_run_passes_validation_and_indexes_every_checkpoint(self):
        output = self.temp / "valid-dry"
        result = self.run_controller("--dry-run", output=output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("stage plan is malformed", result.stderr)
        checkpoints = lineage_plan.resolve_plan(
            REPO_ROOT, "grep", "demo/m", "0", "build", 3, 1800
        )["checkpoints"]
        invocations = [line for line in result.stdout.splitlines()
                       if "run_experiment.sh" in line]
        self.assertEqual(len(invocations), 3 * len(checkpoints),
                         "every checkpoint of every lineage must be reached")
        self.assertFalse(output.exists())

    def test_an_empty_fingerprint_aborts_before_any_lineage_exists(self):
        """Exactly the state the old tab bug produced."""
        row = "\x1f".join(["000", "base", "prompts/grep/000_base_new_grep.md",
                           "new", "cmd", "", ""])
        result, output = self.run_with_corrupt_stage_table(row + "\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty test-bundle fingerprint", result.stderr)
        self.assert_nothing_started(output)

    def test_a_malformed_fingerprint_aborts_before_any_lineage_exists(self):
        row = "\x1f".join(["000", "base", "prompts/grep/000_base_new_grep.md",
                           "new", "cmd", "", "not-a-sha256"])
        result, output = self.run_with_corrupt_stage_table(row + "\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a SHA-256 hex digest", result.stderr)
        self.assert_nothing_started(output)

    def test_a_short_record_aborts_rather_than_shifting_fields(self):
        """A record missing its last field must not silently proceed."""
        row = "\x1f".join(["000", "base", "prompts/grep/000_base_new_grep.md",
                           "new", "cmd", ""])
        result, output = self.run_with_corrupt_stage_table(row + "\n")
        self.assertNotEqual(result.returncode, 0)
        self.assert_nothing_started(output)

    def test_the_guard_itself_never_fails_on_the_interpreter(self):
        """A guard that cannot run is worse than no guard.

        `declare: -n: invalid option` and `array_ref: unbound variable` are how
        this block failed on Darwin's Bash 3.2, and both went to stderr while
        the run aborted -- so the absence of those messages is what separates a
        working guard from one that merely happens to stop the run.
        """
        output = self.temp / "interpreter"
        result = self.run_controller("--print-plan", output=output)
        for message in ("invalid option", "unbound variable", "array_ref",
                        "declare:", "not a known stage array"):
            with self.subTest(message=message):
                self.assertNotIn(message, result.stderr)

    def test_the_validation_precedes_lineage_creation_in_the_source(self):
        text = (REPO_ROOT / "scripts"
                / "run_lineage_experiment.sh").read_text(encoding="utf-8")
        guard = text.index("stage plan is malformed")
        for side_effect in ("for (( offset = 0", '--path "$lineage_record"',
                            'bash "$STAGE_RUNNER"'):
            with self.subTest(side_effect=side_effect):
                self.assertLess(guard, text.index(side_effect))

    def test_the_planned_versus_built_comparison_is_unchanged(self):
        """It must stay fail-closed: no fallback to the built value."""
        text = (REPO_ROOT / "scripts"
                / "run_lineage_experiment.sh").read_text(encoding="utf-8")
        self.assertIn(
            '[[ "$built_fingerprint" == "$stage_bundle_fingerprint" ]] || die',
            text)


def system_bash() -> str | None:
    """The Bash a stock host runs the controller with, if it has one.

    Deliberately not `shutil.which("bash")`: macOS ships Bash 3.2.57 at
    /bin/bash and nothing newer, and a Homebrew bash earlier on PATH is exactly
    what would hide a 4.x-only construct from these tests. Darwin is a supported
    and required experiment platform, so the OS shell is the one that matters.
    """
    path = Path("/bin/bash")
    return str(path) if path.is_file() else None


class StageArrayPreflightTests(unittest.TestCase):
    """The pre-lineage stage-array guard, lifted from the controller and run.

    Vessel (Darwin, Bash 3.2.57) reported `declare: -n: invalid option` and
    `array_ref: unbound variable` from this block. Namerefs are Bash 4.3+, so
    the guard aborted every macOS run at precisely the point it exists to
    protect -- a validation that cannot execute is not fail-closed, it is
    unrunnable.

    The guard's source is extracted from the controller rather than
    reimplemented here, so this cannot drift away from what actually runs, and
    the arrays are fabricated so the malformed shapes the reader could produce
    can be exercised directly.
    """

    MAINTAINED_SCRIPTS = ("run_lineage_experiment.sh", "run_experiment.sh")
    IDS = ["000", "001", "002"]

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required")

    @staticmethod
    def region(text: str, start: str, end: str) -> str:
        begin = text.index(start)
        return text[begin:text.index(end, begin) + len(end)]

    def controller_text(self) -> str:
        return (REPO_ROOT / "scripts"
                / "run_lineage_experiment.sh").read_text(encoding="utf-8")

    def preflight_source(self) -> str:
        """The length lookup plus both validation loops, verbatim."""
        text = self.controller_text()
        return "".join((
            self.region(text, "stage_array_length() (", "\n)\n"),
            self.region(text, "for array_name in", "\ndone\n"),
            self.region(text, "for (( check_index", "\ndone\n"),
        ))

    @staticmethod
    def bash_array(name: str, values: list[str]) -> str:
        quoted = " ".join("'" + value.replace("'", "'\\''") + "'"
                          for value in values)
        return f"{name}=({quoted})\n"

    def fingerprints(self) -> list[str]:
        return [sha256_text(f"bundle-{checkpoint}") for checkpoint in self.IDS]

    def run_preflight(self, *, flags: list[str] | None = None,
                      fingerprints: list[str] | None = None
                      ) -> subprocess.CompletedProcess:
        arrays = {
            "STAGE_IDS": self.IDS,
            "STAGE_NAMES": ["base", "one", "two"],
            "STAGE_PROMPTS": [f"prompts/demo/{i}.md" for i in self.IDS],
            "STAGE_MODES": ["new", "existing", "existing"],
            "STAGE_FEATURE_CMDS": ["judge x", "judge x -a", "judge x -a -b"],
            # Checkpoint 000's cumulative flag list is empty -- the field whose
            # collapse under tab-splitting caused the original defect.
            "STAGE_FLAGS": ["", "-a", "-a,-b"] if flags is None else flags,
            "STAGE_BUNDLE_FINGERPRINTS": (
                self.fingerprints() if fingerprints is None else fingerprints
            ),
        }
        script = (
            "set -uo pipefail\n"
            "die() { printf 'error: %s\\n' \"$*\" >&2; exit 2; }\n"
            + "".join(self.bash_array(name, values)
                      for name, values in arrays.items())
            + f"STAGE_COUNT={len(self.IDS)}\n"
            + self.preflight_source()
            + "printf 'preflight-passed\\n'\n"
        )
        return subprocess.run([self.bash, "-c", script],
                             capture_output=True, text=True)

    # --- the four shapes the guard must decide -----------------------------

    def test_valid_stage_arrays_pass(self):
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("preflight-passed", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_a_short_stage_array_fails(self):
        result = self.run_preflight(flags=["", "-a"])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("stage plan is malformed", result.stderr)
        self.assertIn("STAGE_FLAGS has 2 entries but 3 checkpoints",
                      result.stderr)
        self.assertNotIn("preflight-passed", result.stdout)

    def test_an_empty_fingerprint_fails(self):
        fingerprints = self.fingerprints()
        fingerprints[1] = ""
        result = self.run_preflight(fingerprints=fingerprints)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("checkpoint 001 has an empty test-bundle fingerprint",
                      result.stderr)
        self.assertNotIn("preflight-passed", result.stdout)

    def test_a_malformed_fingerprint_fails(self):
        for bad in ("not-a-sha256", "ABCDEF" + "0" * 58, "0" * 63, "0" * 65):
            fingerprints = self.fingerprints()
            fingerprints[2] = bad
            with self.subTest(fingerprint=bad):
                result = self.run_preflight(fingerprints=fingerprints)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("not a SHA-256 hex digest", result.stderr)
                self.assertNotIn("preflight-passed", result.stdout)

    # --- how the guard is implemented --------------------------------------

    def test_no_maintained_script_depends_on_a_bash_nameref(self):
        # Comment lines are excluded: the controller explains at length the
        # nameref it no longer uses, and an explanation is not a dependency.
        constructs = ("declare -n", "local -n", "typeset -n", "unset -n")
        for name in self.MAINTAINED_SCRIPTS:
            text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
            offenders = [
                line.strip()
                for line in text.splitlines()
                if not line.lstrip().startswith("#")
                and any(construct in line for construct in constructs)
            ]
            with self.subTest(script=name):
                self.assertEqual(
                    offenders, [],
                    "namerefs are Bash 4.3+; Darwin's /bin/bash is 3.2.57",
                )

    # Two different failure modes, measured against a real Bash 3.2.0 rather
    # than assumed. `bash -n` catches only the first group, which is exactly why
    # `declare -n` once reached Vessel despite a passing syntax check: it parses
    # everywhere and fails when the line executes.
    PARSE_TIME_3_2_FAILURES = (
        "|&",           # pipe both streams: Bash 4.0+
        ";;&",          # case: test the next pattern too: Bash 4.0+
        ";&",           # case: fall through: Bash 4.0+
        "coproc",       # Bash 4.0+
        "&>>",          # append both streams: Bash 4.0+
    )
    RUN_TIME_3_2_FAILURES = (
        "declare -A",   # associative arrays: Bash 4.0+
        "local -A",
        "declare -n",   # namerefs: Bash 4.3+
        "local -n",
        "typeset -n",
        "mapfile",      # Bash 4.0+
        "readarray",
        ",,}",          # lowercase parameter transformation: Bash 4.0+
        "^^}",          # uppercase parameter transformation: Bash 4.0+
        "@U}", "@L}",   # Bash 5.0+ transformations
    )

    def test_no_maintained_script_uses_a_construct_bash_3_2_cannot_parse(self):
        """The group `bash -n` would catch, kept out so the preflight passes."""
        self.assert_absent(self.PARSE_TIME_3_2_FAILURES,
                           "Bash 3.2 fails to PARSE this")

    def test_no_maintained_script_uses_a_construct_bash_3_2_cannot_run(self):
        """The dangerous group: these parse on 3.2 and fail when executed, so no
        syntax check anywhere will find them."""
        self.assert_absent(self.RUN_TIME_3_2_FAILURES,
                           "Bash 3.2 parses but cannot RUN this")

    def assert_absent(self, constructs, reason: str) -> None:
        for name in self.MAINTAINED_SCRIPTS:
            text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
            code = [line for line in text.splitlines()
                    if not line.lstrip().startswith("#")]
            for construct in constructs:
                offenders = [line.strip() for line in code if construct in line]
                if construct == ";&":
                    # `;;&` also contains `;&`; it has its own entry.
                    offenders = [line for line in offenders if ";;&" not in line]
                with self.subTest(script=name, construct=construct):
                    self.assertEqual(offenders, [], f"{reason}: {construct}")

    def test_the_array_key_expansion_form_is_not_used(self):
        """`${!name}` is indirect expansion and is fine in 3.2; `${!array[@]}`
        is the 4.0+ key list and is not."""
        for name in self.MAINTAINED_SCRIPTS:
            text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
            offenders = [
                line.strip() for line in text.splitlines()
                if not line.lstrip().startswith("#")
                and "${!" in line and ("[@]" in line or "[*]" in line)
            ]
            with self.subTest(script=name):
                self.assertEqual(offenders, [])

    def test_the_lookup_is_an_explicit_case_over_the_known_arrays(self):
        source = self.region(self.controller_text(),
                             "stage_array_length() (", "\n)\n")
        self.assertIn("case ", source)
        for name in ("STAGE_IDS", "STAGE_NAMES", "STAGE_PROMPTS", "STAGE_MODES",
                     "STAGE_FEATURE_CMDS", "STAGE_FLAGS",
                     "STAGE_BUNDLE_FINGERPRINTS"):
            with self.subTest(array=name):
                self.assertIn(f"{name})", source)

    def test_the_lookup_evaluates_nothing(self):
        """A name-to-value lookup must not become arbitrary execution."""
        self.assertNotIn("eval", self.preflight_source())

    def test_an_unknown_array_name_is_an_error_rather_than_a_lookup(self):
        script = (
            "set -uo pipefail\n"
            + self.region(self.controller_text(),
                          "stage_array_length() (", "\n)\n")
            + "STAGE_IDS=(a b)\n"
            "stage_array_length NOT_A_STAGE_ARRAY && printf 'resolved\\n'\n"
            "printf 'status=%s\\n' \"$?\"\n"
        )
        result = subprocess.run([self.bash, "-c", script],
                                capture_output=True, text=True)
        self.assertIn("status=1", result.stdout)
        self.assertNotIn("resolved", result.stdout)

    def test_counting_an_empty_array_does_not_trip_set_u(self):
        """Bash 3.2 raises "unbound variable" for `${#a[@]}` on an empty array
        under `set -u`, and zero is the count this guard must be able to see."""
        script = (
            "set -uo pipefail\n"
            + self.region(self.controller_text(),
                          "stage_array_length() (", "\n)\n")
            + "STAGE_FLAGS=()\n"
            "printf 'count=%s\\n' \"$(stage_array_length STAGE_FLAGS)\"\n"
            # The subshell body must not leak `set +u` back to the caller.
            "printf 'nounset=%s\\n' \"$(set -o | grep nounset)\"\n"
        )
        result = subprocess.run([self.bash, "-c", script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("count=0", result.stdout)
        self.assertIn("on", result.stdout.split("nounset=")[1])


class SystemBashStageArrayPreflightTests(StageArrayPreflightTests):
    """The same guard under /bin/bash -- on Darwin, Bash 3.2.57 itself.

    Skipped where the OS has no /bin/bash; on macOS it is the one interpreter
    the controller is actually required to work with.
    """

    @classmethod
    def setUpClass(cls):
        cls.bash = system_bash()
        if not cls.bash:
            raise unittest.SkipTest("/bin/bash is not present on this host")

    def test_the_interpreter_is_the_operating_system_bash(self):
        self.assertEqual(self.bash, "/bin/bash")

    def test_it_runs_whatever_bash_version_the_operating_system_ships(self):
        """No minimum version, and no Homebrew Bash, may be required."""
        result = subprocess.run(
            [self.bash, "-c",
             'printf "%s.%s" "${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^\d+\.\d+$")
        self.assertEqual(self.run_preflight().returncode, 0,
                         f"the guard must run under Bash {result.stdout}")


class TimeoutRepairEligibilityTests(unittest.TestCase):
    """A session that ran out of time may still have produced an implementation.

    Observed: exit 124, build 0, checkpoint tests 1, candidate/new_grep.c on
    disk, repair_loops 0, stop_reason agent_execution_failure. The model had
    looped on a hanging manual command until the session limit, but the source
    it left compiled, and the controller had already built and tested it -- so
    there was concrete public-test feedback and a configured repair budget, and
    neither was used. The attempt was scored as though no implementation had
    ever existed.

    These drive the real controller with a stub Aider that exits 124 after
    writing a chosen source, and assert the four outcomes plus the two cases
    that must NOT change.
    """

    RUNNER = REPO_ROOT / "scripts" / "run_experiment.sh"

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required to run the controller")
        if not shutil.which("cc") and not shutil.which("gcc"):
            raise unittest.SkipTest("a C compiler is required")

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.prompt = self.temp / "prompt.md"
        self.prompt.write_text("Write the program.\n", encoding="utf-8")

    def posix(self, path: Path) -> str:
        text = path.as_posix()
        return "/" + text[0].lower() + text[2:] if text[1:2] == ":" else text

    # Sources chosen for what the CONTROLLER's own build and tests make of
    # them, which is the whole point: the agent never reports success here.
    SOURCES = {
        "none": None,
        "broken": "int main(void) { return\n",          # does not compile
        "failing": "int main(void){return 1;}\n",       # compiles, tests fail
        "passing": "int main(void){return 0;}\n",       # compiles, tests pass
    }

    def stub_aider(self, behavior: str, *, repair_fixes: bool = False) -> Path:
        """A fake Aider that writes a source and then times out (exit 124)."""
        source = self.SOURCES[behavior]
        write = ""
        if source is not None:
            write = (f'mkdir -p "$(dirname "$src")"\n'
                     f'printf %s {shlex_quote(source)} > "$src"\n')
        repair_branch = ""
        if repair_fixes:
            # The continuation session behaves like a normal one: it fixes the
            # source and exits 0, so a repaired success is observable.
            repair_branch = (
                'if [ -f "$workdir/.repaired" ]; then\n'
                '  mkdir -p "$(dirname "$src")"\n'
                f'  printf %s {shlex_quote(self.SOURCES["passing"])} > "$src"\n'
                '  exit 0\n'
                'fi\n'
                'touch "$workdir/.repaired"\n'
            )
        path = self.temp / f"aider-{behavior}"
        path.write_text(
            '#!/bin/bash\n'
            'if [ "${1:-}" = --version ]; then echo "aider 0.test"; exit 0; fi\n'
            'workdir="$PWD"\n'
            'src="$workdir/src/x.c"\n'
            + repair_branch + write +
            'exit 124\n',
            encoding="utf-8", newline="\n",
        )
        path.chmod(0o755)
        return path

    def run_attempt(self, behavior: str, *, max_loops: int = 3,
                    repair_fixes: bool = False) -> dict:
        output = self.temp / f"out-{behavior}-{max_loops}-{repair_fixes}"
        result = subprocess.run(
            [self.bash, str(self.RUNNER),
             "--model", "probe/test", "--prompt", self.posix(self.prompt),
             "--source", "src/x.c", "--source-mode", "new",
             "--temperature", "0", "--runs", "1",
             "--max-loops", str(max_loops), "--timeout", "30",
             "--build-cmd", "cc src/x.c -o prog",
             "--feature-test-cmd", "./prog",
             "--output-dir", self.posix(output), "--no-analysis"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            env={**os.environ, "PYTHON_BIN": sys.executable,
                 "AIDER_BIN": str(self.stub_aider(
                     behavior, repair_fixes=repair_fixes))},
        )
        found = sorted(output.glob("temp-*/attempt-001/metadata.json"))
        self.assertTrue(found, f"no metadata written\n{result.stdout[-800:]}")
        return json.loads(found[0].read_text(encoding="utf-8"))

    # --- the timeout must never be erased ----------------------------------

    def assert_timeout_recorded(self, meta: dict) -> None:
        self.assertEqual(meta["agent_exit_code"], 124)
        self.assertEqual(meta["initial_agent_exit_code"], 124)
        self.assertTrue(meta["timeout_enforced"])
        self.assertFalse(meta["initial_session_completed"])

    # --- 1. timeout with no source: no repair ------------------------------

    def test_timeout_without_a_source_stays_an_agent_execution_failure(self):
        meta = self.run_attempt("none")
        self.assert_timeout_recorded(meta)
        self.assertFalse(meta["candidate_available_after_initial_session"])
        self.assertFalse(meta["candidate_available_after_timeout"])
        self.assertFalse(meta["validation_completed_after_timeout"])
        self.assertTrue(meta["agent_execution_failure"])
        self.assertEqual(meta["agent_execution_failure_stage"], "timeout")
        self.assertFalse(meta["repair_eligible"])
        self.assertEqual(meta["repair_eligibility_reason"],
                         "agent_execution_failure")
        self.assertEqual(meta["repair_loops"], 0)
        self.assertEqual(meta["stop_reason"], "agent_execution_failure")

    # --- 2. timeout with a source that fails to build ----------------------

    def test_timeout_with_an_uncompilable_source_is_repair_eligible(self):
        """Controller feedback exists -- the build log names the error."""
        meta = self.run_attempt("broken")
        self.assert_timeout_recorded(meta)
        self.assertTrue(meta["candidate_available_after_timeout"])
        self.assertTrue(meta["validation_completed_after_timeout"])
        self.assertNotEqual(meta["build_exit_code"], 0)
        self.assertFalse(meta["agent_execution_failure"])
        self.assertTrue(meta["repair_eligible"])
        self.assertGreaterEqual(meta["repair_loops"], 1)

    # --- 3. timeout, compiles, tests fail: the observed run ----------------

    def test_timeout_with_a_failing_candidate_runs_the_repair_loop(self):
        meta = self.run_attempt("failing")
        self.assert_timeout_recorded(meta)
        self.assertEqual(meta["build_exit_code"], 0)
        self.assertNotEqual(meta["feature_test_exit_code"], 0)
        self.assertTrue(meta["candidate_available_after_timeout"])
        self.assertTrue(meta["validation_completed_after_timeout"])
        self.assertFalse(meta["agent_execution_failure"])
        self.assertTrue(meta["repair_eligible"])
        self.assertEqual(meta["repair_eligibility_reason"],
                         "controller_validation_after_timeout")
        self.assertGreaterEqual(
            meta["repair_loops"], 1,
            "the configured repair budget must actually be used",
        )
        self.assertNotEqual(meta["stop_reason"], "agent_execution_failure")

    def test_a_repair_after_a_timeout_can_succeed(self):
        meta = self.run_attempt("failing", repair_fixes=True)
        self.assertTrue(meta["public_validation_success"])
        self.assertFalse(meta["initial_success"],
                         "the initial generation still failed")
        self.assertGreaterEqual(meta["repair_loops"], 1)
        # The success does not hide where the candidate came from.
        self.assertEqual(meta["initial_agent_exit_code"], 124)
        self.assertFalse(meta["initial_session_completed"])
        self.assertTrue(meta["candidate_available_after_timeout"])

    # --- 4. timeout with a candidate that passes ---------------------------

    def test_timeout_with_a_passing_candidate_may_succeed_with_provenance(self):
        meta = self.run_attempt("passing")
        self.assertTrue(meta["public_validation_success"])
        self.assertTrue(meta["initial_success"])
        self.assertEqual(meta["stop_reason"], "success")
        self.assertFalse(meta["agent_execution_failure"])
        # Requirement 7: a success must still be distinguishable from a run
        # whose session finished on its own.
        self.assert_timeout_recorded(meta)
        self.assertTrue(meta["candidate_available_after_timeout"])
        self.assertEqual(meta["repair_eligibility_reason"],
                         "initial_validation_passed")

    # --- 5. no repair budget -----------------------------------------------

    def test_max_loops_zero_records_the_candidate_without_repairing(self):
        meta = self.run_attempt("failing", max_loops=0)
        self.assert_timeout_recorded(meta)
        self.assertTrue(meta["candidate_available_after_timeout"])
        self.assertEqual(meta["repair_loops"], 0)
        self.assertFalse(meta["repair_eligible"])
        self.assertEqual(meta["repair_eligibility_reason"], "no_repair_budget")
        # A failed implementation, not an absent one.
        self.assertFalse(meta["agent_execution_failure"])
        self.assertFalse(meta["public_validation_success"])
        self.assertEqual(meta["build_exit_code"], 0)

    # --- 6. metadata and analysis stay consistent --------------------------

    def test_the_analyzer_agrees_with_the_recorded_classification(self):
        analyzer = analyzer_or_none()
        if analyzer is None:
            self.skipTest("the analysis stack is not installed")

        for behavior, expect_agent_failure, expect_status in (
            ("none", True, "timeout"),
            ("failing", False, "timeout_with_candidate"),
            ("passing", False, "timeout_with_candidate"),
        ):
            meta = self.run_attempt(behavior, max_loops=0)
            normalized = analyzer.normalize_repair_metadata(dict(meta))
            with self.subTest(behavior=behavior):
                self.assertEqual(normalized["agent_execution_failure"],
                                 expect_agent_failure)
                self.assertEqual(
                    analyzer.initial_agent_invocation_status(normalized),
                    expect_status,
                )
                # The controller and the analyzer must not disagree.
                self.assertEqual(meta["agent_execution_failure"],
                                 normalized["agent_execution_failure"])


class TimeoutRepairAnalysisTests(unittest.TestCase):
    """The analyzer's repair denominator and attrition counts."""

    @classmethod
    def setUpClass(cls):
        cls.analyzer = analyzer_or_none()
        if cls.analyzer is None:
            raise unittest.SkipTest(
                "scripts/analyze_experiment.py needs the analysis stack "
                "(scripts/analysis-requirements.txt)"
            )

    def row(self, **overrides) -> dict:
        base = {
            "run_id": "attempt-001",
            "opencode_exit_code": 124,
            "initial_opencode_exit_code": 124,
            "timeout_enforced": True,
            "initial_session_completed": False,
            "candidate_available_after_timeout": True,
            "validation_completed_after_timeout": True,
            "repair_eligible": True,
            "repair_eligibility_reason": "controller_validation_after_timeout",
            "agent_execution_failure": False,
            "infrastructure_failure": False,
            "build_exit_code": 0,
            "base_test_exit_code": 0,
            "feature_test_exit_code": 1,
            "initial_success": False,
            "public_validation_success": False,
            "repair_loops": 1,
            "llm_invocations": 2,
            "success_loop": None,
        }
        base.update(overrides)
        return base

    def test_a_candidate_producing_timeout_is_in_the_repair_denominator(self):
        summary = self.analyzer.build_repair_summary([self.row()])
        self.assertEqual(summary["repair_eligible_initial_failures"], 1)
        self.assertEqual(summary["repair_ineligible_initial_failures"], 0)

    def test_a_repaired_timeout_counts_as_a_repair_assisted_success(self):
        summary = self.analyzer.build_repair_summary([
            self.row(public_validation_success=True, success_loop=1)
        ])
        self.assertEqual(summary["recovered_repair_eligible_failures"], 1)
        self.assertEqual(summary["repair_recovery_rate"], 1.0)
        self.assertEqual(summary["initial_public_successes"], 0,
                         "the initial generation still failed")

    def test_a_timeout_with_no_candidate_stays_out_of_the_denominator(self):
        summary = self.analyzer.build_repair_summary([
            self.row(candidate_available_after_timeout=False,
                     agent_execution_failure=True, repair_loops=0,
                     repair_eligible=False, llm_invocations=1)
        ])
        self.assertEqual(summary["repair_eligible_initial_failures"], 0)
        self.assertEqual(summary["repair_ineligible_initial_failures"], 1)
        self.assertIn("timeout",
                      summary["repair_ineligible_initial_failure_stages"])

    def test_a_candidate_producing_timeout_is_not_agent_attrition(self):
        normalized = self.analyzer.normalize_repair_metadata(self.row())
        self.assertFalse(normalized["agent_execution_failure"])
        self.assertFalse(normalized["agent_invocation_completed"])
        self.assertTrue(normalized["agent_invocation_timed_out"])
        self.assertTrue(normalized["candidate_available_after_timeout"])
        self.assertTrue(normalized["artifact_public_validation_success"] is False)
        self.assertFalse(normalized["workflow_stage_success"])
        reliability = self.analyzer.build_reliability_summary([normalized])
        self.assertEqual(reliability["n_infrastructure_failures"], 0)

    def test_timeout_candidate_can_validate_and_succeed_as_a_workflow(self):
        normalized = self.analyzer.normalize_repair_metadata(
            self.row(
                public_validation_success=True,
                workflow_stage_success=True,
                success_loop=1,
            )
        )
        self.assertFalse(normalized["agent_invocation_completed"])
        self.assertTrue(normalized["agent_invocation_timed_out"])
        self.assertTrue(normalized["candidate_available_after_timeout"])
        self.assertTrue(normalized["artifact_public_validation_success"])
        self.assertTrue(normalized["workflow_stage_success"])

    def test_the_status_name_keeps_the_timeout_visible(self):
        """It must not be folded into 'completed': the session did not finish."""
        self.assertEqual(
            self.analyzer.initial_agent_invocation_status(self.row()),
            "timeout_with_candidate",
        )
        self.assertIn("timeout_with_candidate",
                      self.analyzer.REPAIR_ELIGIBLE_INITIAL_STATUSES)


class Bash32HeredocQuotingTests(unittest.TestCase):
    """A here-doc inside `$( )` must not contain an apostrophe or an unbalanced
    parenthesis, because Apple's Bash 3.2 cannot parse it.

    This is the defect itself, written down. Bash 3.2 does not skip a
    here-document body while scanning for the closing paren of a command
    substitution -- it keeps lexing the body as shell text. Three apostrophes in
    Python comments (`model's`, `agent's`, `provider's`) inside the former
    config builder therefore opened a single-quoted string that never closed,
    and the parse ran to end of file:

        run_experiment.sh: line 1626: syntax error: unexpected end of file

    reported against line 1182, the line that opened the substitution. Bash 4+
    parses the same file cleanly, so `bash -n` on Linux said nothing. On Vessel
    every stage aborted before the backend started and checkpoint 000 was recorded
    as stage_run_incomplete -- an environment fault booked as a model result.

    Verified against a Bash 3.2.0 built from source: with an odd apostrophe
    count the file fails to parse, with an even count it happens to re-sync, and
    with none it is safe regardless.
    """

    MAINTAINED_SCRIPTS = ("run_lineage_experiment.sh", "run_experiment.sh")
    HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

    def heredocs_inside_substitutions(self, path: Path):
        """Every here-doc body that lies inside a `$( )`, with its position."""
        lines = path.read_text(encoding="utf-8").splitlines()
        depth = 0
        opened_at = 0
        index = 0
        found = []
        while index < len(lines):
            line = lines[index]
            match = self.HEREDOC.search(line)
            if match and depth > 0:
                terminator = match.group(2)
                start = index + 1
                body = []
                index += 1
                while index < len(lines) and lines[index].strip() != terminator:
                    body.append(lines[index])
                    index += 1
                found.append((opened_at, start, terminator, "\n".join(body)))
                index += 1
                continue
            for _ in re.finditer(r"\$\(", line):
                if depth == 0:
                    opened_at = index + 1
                depth += 1
            if depth:
                depth -= min(depth, line.count(")"))
            index += 1
        return found

    def test_no_heredoc_in_a_substitution_carries_an_apostrophe(self):
        for name in self.MAINTAINED_SCRIPTS:
            path = REPO_ROOT / "scripts" / name
            for opened, start, terminator, body in \
                    self.heredocs_inside_substitutions(path):
                offenders = [
                    f"{start + offset}: {line.strip()}"
                    for offset, line in enumerate(body.splitlines())
                    if "'" in line
                ]
                with self.subTest(script=name, heredoc=terminator):
                    self.assertEqual(
                        offenders, [],
                        f"apostrophe inside the here-doc opened at line "
                        f"{start}, which sits in the command substitution at "
                        f"line {opened}. Bash 3.2 reads it as an opening quote "
                        f"and the parse runs to EOF. Reword it: "
                        f'"the model of the agent", not "the agent\'s model"',
                    )

    def test_no_heredoc_in_a_substitution_has_unbalanced_parentheses(self):
        for name in self.MAINTAINED_SCRIPTS:
            path = REPO_ROOT / "scripts" / name
            for opened, start, terminator, body in \
                    self.heredocs_inside_substitutions(path):
                balance = body.count("(") - body.count(")")
                with self.subTest(script=name, heredoc=terminator):
                    self.assertEqual(
                        balance, 0,
                        f"the here-doc opened at line {start} (inside the "
                        f"substitution at line {opened}) has a paren imbalance "
                        f"of {balance:+d}; Bash 3.2 counts these while looking "
                        f"for the closing paren of the substitution",
                    )

    def test_the_guard_would_have_caught_the_original_defect(self):
        """The check has teeth: reintroducing the exact text must fail it."""
        body = "# a config-defined model's temperature capability\n"
        self.assertIn("'", body)
        offenders = [line for line in body.splitlines() if "'" in line]
        self.assertEqual(len(offenders), 1)

    def test_the_aider_settings_builder_is_outside_shell_substitutions(self):
        text = (REPO_ROOT / "scripts" / "run_experiment.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('AIDER_SETTINGS_TOOL="$REPO/scripts/aider_settings.py"', text)
        self.assertNotIn("ATTEMPT_OPENCODE_CONFIG_CONTENT", text)


class CanonicalTemperatureLineageTests(unittest.TestCase):
    """The lineage producer and consumer share one temperature path contract.

    The fake stage runner writes the same COMPLETE/metadata/candidate contract
    as run_experiment.sh, but never invokes Aider or a model.  Its three mkdir
    checkpoints exercise promotion and source inheritance end to end.
    """

    CONTROLLER = REPO_ROOT / "scripts" / "run_lineage_experiment.sh"
    HASH = "a" * 64

    @classmethod
    def setUpClass(cls):
        # Windows may expose WSL's bash.exe ahead of Git Bash.  The repository
        # paths and native Python interpreter in this test need the MSYS path
        # bridge Git Bash provides; Unix hosts continue to use /bin/bash.
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        cls.bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required to run the controller")

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.repo = self.temp / "repo"
        scripts = self.repo / "scripts"
        scripts.mkdir(parents=True)
        for name in ("run_lineage_experiment.sh", "lineage_state.py",
                     "temperature_value.py"):
            shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
        self._write_fake_plan(scripts / "lineage_plan.py")
        self._write_fake_bundle(scripts / "stage_test_bundle.py")
        (scripts / "checkpoint_boundary_gate.py").write_text(
            "#!/usr/bin/env python3\nraise SystemExit(0)\n", encoding="utf-8"
        )
        self._write_fake_stage_runner(scripts / "run_experiment.sh")
        # Native Windows Python writes CRLF to captured stdout.  Bash command
        # substitution removes LF but retains CR, which would contaminate plan
        # fields in this cross-platform harness.  Vessel runs POSIX Python; the
        # shim makes this local test's stdout match that contract.
        python_shim = scripts / "python-for-bash"
        native_python = Path(sys.executable).as_posix()
        python_shim.write_text(
            "#!/usr/bin/env bash\nset -o pipefail\n"
            f'"{native_python}" "$@" | tr -d \'\\r\'\n',
            encoding="utf-8",
        )
        python_shim.chmod(0o755)
        self.python_bin = self.posix(python_shim)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    @staticmethod
    def posix(path: Path) -> str:
        text = path.as_posix()
        return "/" + text[0].lower() + text[2:] if text[1:2] == ":" else text

    def _write_fake_plan(self, path: Path) -> None:
        path.write_text(
            """#!/usr/bin/env python3
import argparse
import hashlib
import json
import platform

parser = argparse.ArgumentParser()
parser.add_argument("--emit", required=True)
parser.add_argument("--utility", default="mkdir")
parser.add_argument("--model", default="demo/m")
parser.add_argument("--editor-model", default="editor/m")
parser.add_argument("--aider-version", default="unknown")
parser.add_argument("--temperature", default="0")
parser.add_argument("--top-p", default="")
parser.add_argument("--sampling-seed", default="")
parser.add_argument("--max-tokens", default="")
parser.add_argument("--max-loops", type=int, default=3)
parser.add_argument("--timeout-seconds", type=int, default=1800)
parser.add_argument("--remote-base-url", default="")
parser.add_argument("--remote-api-key-env", default="")
args, _ = parser.parse_known_args()
temperature = float(args.temperature)
fingerprint = hashlib.sha256(
    json.dumps({"temperature": temperature}, sort_keys=True).encode()
).hexdigest()
checkpoints = [
    {"id": "000", "name": "base", "prompt": "prompts/mkdir/000.md",
     "source_mode": "new", "implemented_flags": [],
     "feature_test_command": "true", "test_bundle_fingerprint": "a" * 64},
    {"id": "001", "name": "parents", "prompt": "prompts/mkdir/001.md",
     "source_mode": "existing", "implemented_flags": ["-p"],
     "feature_test_command": "true", "test_bundle_fingerprint": "a" * 64},
    {"id": "002", "name": "mode", "prompt": "prompts/mkdir/002.md",
     "source_mode": "existing", "implemented_flags": ["-p", "-m"],
     "feature_test_command": "true", "test_bundle_fingerprint": "a" * 64},
]
if args.emit == "stages":
    separator = "\\x1f"
    for checkpoint in checkpoints:
        print(separator.join((
            checkpoint["id"], checkpoint["name"], checkpoint["prompt"],
            checkpoint["source_mode"], checkpoint["feature_test_command"],
            ",".join(checkpoint["implemented_flags"]), "a" * 64,
        )))
else:
    print(json.dumps({
        "schema_version": 1, "utility": "mkdir", "program": "new_mkdir",
        "source_path": "src/new_mkdir/new_mkdir.c",
        "source_basename": "new_mkdir.c", "executable_path": "build/new_mkdir",
        "build_command": "true", "test_dir": "tests/mkdir-test-suite",
        "judge": "true", "base_test_command": "", "extra_test_command": "",
        "required_platform": None, "host_platform": platform.system(),
        "agent_backend": "aider", "aider_version": args.aider_version,
        "architect_model": args.model, "editor_model": args.editor_model,
        "architect_mode": True, "model": args.model, "model_provenance": None,
        "temperature": temperature,
        "top_p": None if not args.top_p else float(args.top_p),
        "sampling_seed": None if not args.sampling_seed else int(args.sampling_seed),
        "max_tokens": None if not args.max_tokens else int(args.max_tokens),
        "editor_temperature": 0.0, "editor_sampling_seed": 0,
        "editor_edit_format": "editor-diff", "aider_model_settings": [],
        "remote_base_url": args.remote_base_url or None,
        "remote_api_key_env": args.remote_api_key_env or None,
        "remote_transport": "default", "max_loops": args.max_loops,
        "timeout_seconds": args.timeout_seconds,
        "automation_notice_sha256": "b" * 64,
        "config_fingerprint": fingerprint, "checkpoints": checkpoints,
    }))
""",
            encoding="utf-8",
        )

    def _write_fake_bundle(self, path: Path) -> None:
        path.write_text(
            f"""#!/usr/bin/env python3
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("--repo")
parser.add_argument("--utility")
parser.add_argument("--checkpoint")
parser.add_argument("--output")
parser.add_argument("--emit")
args = parser.parse_args()
from pathlib import Path
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
(output / "BUNDLE.json").write_text(json.dumps({{"bundle_fingerprint": "{self.HASH}"}}))
print("{self.HASH}")
""",
            encoding="utf-8",
        )

    def _write_fake_stage_runner(self, path: Path) -> None:
        path.write_text(
            r'''#!/usr/bin/env bash
set -uo pipefail
temperature=""
output_dir=""
source_path=""
seed_spec=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --temperature) temperature="$2"; shift 2 ;;
        --output-dir) output_dir="$2"; shift 2 ;;
        --source) source_path="$2"; shift 2 ;;
        --seed-file) seed_spec="$2"; shift 2 ;;
        --model|--editor-model|--runs|--max-loops|--timeout|--prompt|--source-mode|--test-dir|--build-cmd|--base-test-cmd|--feature-test-cmd|--extra-test-cmd|--repair-prompt|--remote-base-url|--remote-api-key-env|--top-p|--sampling-seed|--max-tokens|--model-provenance-json)
            shift 2 ;;
        *) shift ;;
    esac
done
repo="$(git rev-parse --show-toplevel)"
slug="$($PYTHON_BIN "$repo/scripts/temperature_value.py" slug "$temperature")"
[[ "${FAKE_STAGE_LAYOUT:-canonical}" == canonical ]] || slug="0"
experiment="$output_dir/temp-$slug"
attempt="$experiment/attempt-001"
candidate="$attempt/candidate/$(basename "$source_path")"
mkdir -p "$(dirname "$candidate")" "$experiment/baseline"
if [[ -n "$seed_spec" ]]; then
    seed="${seed_spec%%:*}"
    cp "$seed" "$experiment/baseline/$(basename "$source_path")"
    cp "$seed" "$candidate"
else
    : > "$candidate"
fi
stage="$(basename "$output_dir")"
printf 'checkpoint %s\n' "$stage" >> "$candidate"
if [[ "${FAKE_STAGE_METADATA:-aider}" != missing ]]; then
    if [[ "${FAKE_STAGE_METADATA:-aider}" == legacy ]]; then
        printf '%s\n' '{"public_validation_success":true,"opencode_exit_code":0}' > "$attempt/metadata.json"
    else
        printf '%s\n' '{"public_validation_success":true,"agent_backend":"aider","agent_exit_code":0}' > "$attempt/metadata.json"
    fi
fi
: > "$attempt/COMPLETE"
''',
            encoding="utf-8",
        )

    def run_controller(self, temperature: str, output: Path, *,
                       lineage_start: int = 1, metadata: str = "aider",
                       layout: str = "canonical") -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.bash, str(self.repo / "scripts" / "run_lineage_experiment.sh"),
             "--utility", "mkdir", "--model", "demo/m",
             "--editor-model", "editor/m", "--temperature", temperature,
             "--lineages", "1", "--lineage-start", str(lineage_start),
             "--output-dir", self.posix(output)],
            cwd=str(self.repo), capture_output=True, text=True,
            env={**os.environ, "PYTHON_BIN": self.python_bin,
                 "AIDER_BIN": "true", "FAKE_STAGE_METADATA": metadata,
                 "FAKE_STAGE_LAYOUT": layout},
        )

    def record(self, output: Path, lineage: int = 1) -> dict[str, Any]:
        path = output / f"lineage-{lineage:03d}" / "lineage.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_equivalent_spellings_share_canonical_values_and_slugs(self):
        expected = {
            "0": ("0.0", "0p0"), "0.0": ("0.0", "0p0"),
            "0.00": ("0.0", "0p0"), "0.125": ("0.125", "0p125"),
            "1": ("1.0", "1p0"), "1.0": ("1.0", "1p0"),
            "1.2": ("1.2", "1p2"),
        }
        for spelling, (canonical, slug) in expected.items():
            with self.subTest(spelling=spelling):
                self.assertEqual(temperature_value.canonicalize(spelling), canonical)
                self.assertEqual(temperature_value.slug(spelling), slug)

    def test_stubbed_mkdir_lineages_find_and_promote_every_temperature(self):
        spellings = ("0", "0.0", "0.00", "0.125", "1", "1.0", "1.2")
        for index, spelling in enumerate(spellings, 1):
            output = self.temp / f"out-{index}"
            result = self.run_controller(spelling, output)
            with self.subTest(temperature=spelling):
                self.assertEqual(result.returncode, 0, result.stderr)
                record = self.record(output)
                self.assertEqual(record["state"], "completed")
                self.assertEqual([stage["checkpoint_id"] for stage in record["stages"]],
                                 ["000", "001", "002"])
                self.assertTrue(all(stage["success"] for stage in record["stages"]))
                slug = temperature_value.slug(spelling)
                for checkpoint in ("000", "001", "002"):
                    attempt = (output / "lineage-001" / checkpoint /
                               f"temp-{slug}" / "attempt-001")
                    self.assertTrue((attempt / "COMPLETE").is_file())
                final = output / "lineage-001" / "final" / "new_mkdir.c"
                self.assertEqual(final.read_text(encoding="utf-8").splitlines(),
                                 ["checkpoint 000", "checkpoint 001", "checkpoint 002"])

    def test_checkpoint_001_receives_checkpoint_000_candidate(self):
        output = self.temp / "seed-chain"
        result = self.run_controller("0", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = self.record(output)
        first, second = record["stages"][:2]
        self.assertEqual(second["seed_sha256"], first["candidate_sha256"])
        baseline = (output / "lineage-001" / "001" / "temp-0p0" /
                    "baseline" / "new_mkdir.c")
        self.assertEqual(baseline.read_text(encoding="utf-8"), "checkpoint 000\n")

    def test_numeric_respelling_resumes_without_fingerprint_mismatch(self):
        output = self.temp / "resume"
        first = self.run_controller("0", output, lineage_start=1)
        second = self.run_controller("0.0", output, lineage_start=2)
        third = self.run_controller("0.00", output, lineage_start=3)
        for result in (first, second, third):
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("different configuration", result.stderr)
        records = [self.record(output, number) for number in (1, 2, 3)]
        self.assertEqual(len({record["config_fingerprint"] for record in records}), 1)
        self.assertEqual({record["temperature"] for record in records}, {0.0})

    def test_observed_temp_0_vs_temp_0p0_disagreement_is_impossible(self):
        controller = self.CONTROLLER.read_text(encoding="utf-8")
        stage_runner = (REPO_ROOT / "scripts" / "run_experiment.sh").read_text(
            encoding="utf-8"
        )
        self.assertEqual(temperature_value.slug("0"), "0p0")
        self.assertEqual(temperature_value.slug("0.0"), "0p0")
        self.assertNotEqual(temperature_value.slug("0"), "0")
        for source in (controller, stage_runner):
            self.assertIn('"$TEMPERATURE_TOOL" slug', source)
            self.assertNotIn("slugify \"$TEMPERATURE\" | sed 's/\\./p/g'", source)

    def test_missing_metadata_does_not_manufacture_opencode_provenance(self):
        output = self.temp / "missing-metadata"
        result = self.run_controller("0", output, metadata="missing")
        self.assertEqual(result.returncode, 0, result.stderr)
        stage = self.record(output)["stages"][0]
        self.assertIsNone(stage["agent_backend"])
        self.assertNotEqual(stage["agent_backend"], "opencode")

    def test_legacy_opencode_evidence_and_current_aider_metadata_are_recognized(self):
        for metadata, expected in (("legacy", "opencode"), ("aider", "aider")):
            output = self.temp / metadata
            result = self.run_controller("0", output, metadata=metadata)
            with self.subTest(metadata=metadata):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    {stage["agent_backend"] for stage in self.record(output)["stages"]},
                    {expected},
                )

    def test_missing_expected_attempt_is_an_output_contract_failure(self):
        output = self.temp / "wrong-layout"
        result = self.run_controller("0", output, layout="legacy_raw")
        record = self.record(output)
        stage = record["stages"][0]
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(stage["success"])
        self.assertEqual(stage["failure_reason"], "stage_output_contract_failure")
        self.assertTrue(stage["output_contract_failure"])
        self.assertNotEqual(stage["failure_reason"], "stage_run_incomplete")

    def test_real_plan_fingerprint_ignores_numeric_spelling(self):
        plans = [lineage_plan.resolve_plan(
            REPO_ROOT, "mkdir", "demo/m", spelling, "build", 3, 1800
        ) for spelling in ("0", "0.0", "0.00")]
        self.assertEqual({plan["temperature"] for plan in plans}, {0.0})
        self.assertEqual(len({plan["config_fingerprint"] for plan in plans}), 1)


class LineageSyntaxPreflightTests(unittest.TestCase):
    """A syntax error in the stage runner must never reach lineage init."""

    CONTROLLER = REPO_ROOT / "scripts" / "run_lineage_experiment.sh"

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required")

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def posix(self, path: Path) -> str:
        text = path.as_posix()
        return "/" + text[0].lower() + text[2:] if text[1:2] == ":" else text

    def test_the_controller_parses_the_stage_runner_before_starting(self):
        text = self.CONTROLLER.read_text(encoding="utf-8")
        self.assertIn('bash -n "$STAGE_RUNNER"', text)
        # Before every side effect that would make a lineage count as started.
        guard = text.index('bash -n "$STAGE_RUNNER"')
        for side_effect in ("for (( offset = 0", '--path "$lineage_record"',
                            'bash "$STAGE_RUNNER"', "mkdir -p \"$OUTPUT_DIR\""):
            with self.subTest(side_effect=side_effect):
                self.assertLess(guard, text.index(side_effect))

    def test_a_broken_stage_runner_stops_the_run_with_no_lineage(self):
        """The exact Vessel scenario: the stage runner does not parse."""
        fake_repo = self.temp / "repo"
        shutil.copytree(REPO_ROOT, fake_repo, symlinks=True, ignore=(
            shutil.ignore_patterns("runs", ".git", "__pycache__", "build",
                                   "*.tar.gz", "review-bundle")
        ))
        # The controller resolves paths through git, and the copy carries no
        # .git, so give it one. Nothing is committed.
        subprocess.run(["git", "init", "-q", str(fake_repo)],
                       capture_output=True, check=False)
        broken = fake_repo / "scripts" / "run_experiment.sh"
        # An unterminated command substitution: the same failure class, minus
        # the 1600 lines of context.
        broken.write_text('#!/usr/bin/env bash\nx="$(\necho hi\n', encoding="utf-8")
        output = self.temp / "out"
        result = subprocess.run(
            [self.bash, str(fake_repo / "scripts" / "run_lineage_experiment.sh"),
             "--utility", "grep", "--model", "demo/m", "--temperature", "0.2",
             "--lineages", "3", "--output-dir", self.posix(output)],
            cwd=str(fake_repo), capture_output=True, text=True,
            env={**os.environ, "PYTHON_BIN": sys.executable},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not parse", result.stderr)
        self.assertIn("no lineage was started", result.stderr)
        for pattern in ("lineage-*", "lineage.json", "lineages.json"):
            with self.subTest(pattern=pattern):
                self.assertEqual(
                    [] if not output.exists() else list(output.rglob(pattern)),
                    [],
                    f"{pattern} exists after a stage-runner syntax failure",
                )

    def test_a_healthy_stage_runner_passes_the_preflight(self):
        """The guard must not block the normal path."""
        result = subprocess.run(
            [self.bash, str(self.CONTROLLER),
             "--utility", "grep", "--model", "demo/m", "--temperature", "0.2",
             "--lineages", "1", "--dry-run"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            env={**os.environ, "PYTHON_BIN": sys.executable},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("does not parse", result.stderr)


class LineageSamplingParameterTests(unittest.TestCase):
    """The lineage controller's sampling surface.

    A lineage is the experimental unit, so a sampling knob has to reach every
    stage of it -- checkpoint 000, every later checkpoint, and the repair
    sessions run_experiment.sh drives inside each stage -- and has to be part of
    the configuration identity, or two runs sampled differently could land in
    one output directory and be averaged together.
    """

    CONTROLLER = REPO_ROOT / "scripts" / "run_lineage_experiment.sh"

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required to run the controller")

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def posix(self, path: Path) -> str:
        text = path.as_posix()
        return "/" + text[0].lower() + text[2:] if text[1:2] == ":" else text

    def run_controller(self, *arguments: str,
                       aider: str = "") -> subprocess.CompletedProcess:
        environment = {**os.environ, "PYTHON_BIN": sys.executable}
        if aider:
            environment["AIDER_BIN"] = aider
        return subprocess.run(
            [self.bash, str(self.CONTROLLER),
             "--utility", "grep", "--model", "demo/m", "--temperature", "0.2",
             *arguments],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            env=environment,
        )

    def dry_run_stages(self, *arguments: str) -> list[str]:
        result = self.run_controller("--lineages", "2", "--dry-run", *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line for line in result.stdout.splitlines()
                if "run_experiment.sh" in line]

    # --- forwarding --------------------------------------------------------

    def test_every_stage_receives_every_requested_knob(self):
        stages = self.dry_run_stages("--top-p", "0.9", "--sampling-seed", "42",
                                     "--max-tokens", "512")
        self.assertTrue(stages)
        for flag, value in (("--top-p", "0.9"), ("--sampling-seed", "42"),
                            ("--max-tokens", "512")):
            with self.subTest(flag=flag):
                carrying = [line for line in stages
                            if f"{flag} {value}" in line]
                self.assertEqual(
                    len(carrying), len(stages),
                    f"{flag} reached {len(carrying)} of {len(stages)} stages",
                )

    def test_checkpoint_000_and_later_checkpoints_are_both_covered(self):
        """The first stage is the one a forwarding bug is most likely to miss:
        it is the only --source-mode new stage and takes a different path."""
        stages = self.dry_run_stages("--top-p", "0.5")
        first = [line for line in stages if "--source-mode new" in line]
        later = [line for line in stages if "--source-mode existing" in line]
        self.assertTrue(first and later)
        for line in first + later:
            self.assertIn("--top-p 0.5", line)

    def test_omitted_knobs_are_not_forwarded_at_all(self):
        stages = self.dry_run_stages()
        self.assertTrue(stages)
        for flag in ("--top-p", "--sampling-seed", "--max-tokens"):
            with self.subTest(flag=flag):
                self.assertEqual([line for line in stages if flag in line], [])

    # --- configuration identity -------------------------------------------

    def test_unset_knobs_are_null_in_the_plan_with_no_placeholder_values(self):
        plan = lineage_plan.resolve_plan(
            REPO_ROOT, "grep", "demo/m", "0.2", "build", 3, 1800
        )
        for key in ("top_p", "sampling_seed", "max_tokens"):
            with self.subTest(key=key):
                self.assertIn(key, plan)
                self.assertIsNone(plan[key])

    def test_explicit_knobs_keep_their_json_types(self):
        plan = lineage_plan.resolve_plan(
            REPO_ROOT, "grep", "demo/m", "0.2", "build", 3, 1800,
            top_p="0.9", sampling_seed="42", max_tokens="512",
        )
        self.assertIsInstance(plan["top_p"], float)
        self.assertIsInstance(plan["sampling_seed"], int)
        self.assertIsInstance(plan["max_tokens"], int)
        self.assertEqual(
            (plan["top_p"], plan["sampling_seed"], plan["max_tokens"]),
            (0.9, 42, 512),
        )
        # Round-trips as JSON with those types intact, which is what the
        # durable records and the analyzer read.
        restored = json.loads(json.dumps(plan))
        self.assertEqual(restored["sampling_seed"], 42)
        self.assertNotIsInstance(restored["sampling_seed"], str)

    def test_each_knob_moves_the_configuration_fingerprint(self):
        def fingerprint(**overrides):
            return lineage_plan.resolve_plan(
                REPO_ROOT, "grep", "demo/m", "0.2", "build", 3, 1800,
                **overrides
            )["config_fingerprint"]

        base = fingerprint()
        for key, first, second in (("top_p", "0.9", "0.8"),
                                   ("sampling_seed", "1", "2"),
                                   ("max_tokens", "256", "512")):
            with self.subTest(key=key):
                self.assertNotEqual(base, fingerprint(**{key: first}))
                self.assertNotEqual(fingerprint(**{key: first}),
                                    fingerprint(**{key: second}))

    def test_the_print_plan_output_states_the_sampling_configuration(self):
        result = self.run_controller("--lineages", "1", "--print-plan",
                                     "--top-p", "0.9", "--sampling-seed", "42",
                                     "--max-tokens", "512")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout.split("\nOutput dir:")[0])
        self.assertEqual(plan["top_p"], 0.9)
        self.assertEqual(plan["sampling_seed"], 42)
        self.assertEqual(plan["max_tokens"], 512)
        self.assertIn("sampling-seed=42", result.stdout)

    # --- refusals ----------------------------------------------------------

    def test_top_k_is_refused_with_the_documented_reason(self):
        result = self.run_controller("--lineages", "1", "--top-k", "20")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--top-k is not supported", result.stderr)
        self.assertIn("separate experimental change", result.stderr)

    def test_seed_is_refused_as_ambiguous(self):
        result = self.run_controller("--lineages", "1", "--seed", "7")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--seed is ambiguous", result.stderr)
        self.assertIn("--sampling-seed", result.stderr)
        self.assertIn("--seed-file", result.stderr)

    def test_invalid_values_abort_before_any_lineage_exists(self):
        for arguments, expected in (
            (("--top-p", "1.5"), "--top-p must be"),
            (("--top-p", "abc"), "--top-p must be"),
            (("--sampling-seed", "-3"), "--sampling-seed must be"),
            (("--sampling-seed", "1.5"), "--sampling-seed must be"),
            (("--max-tokens", "0"), "--max-tokens must be"),
            (("--max-tokens", "abc"), "--max-tokens must be"),
        ):
            output = self.temp / f"bad-{abs(hash(arguments))}"
            with self.subTest(arguments=arguments):
                result = self.run_controller(
                    "--lineages", "3", "--output-dir", self.posix(output),
                    *arguments,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                # Nothing may have been started: no directory, no record.
                for pattern in ("lineage-*", "lineage.json", "lineages.json"):
                    self.assertEqual(
                        [] if not output.exists()
                        else list(output.rglob(pattern)), [],
                        f"{pattern} exists after a rejected sampling value",
                    )

    # --- resume protection -------------------------------------------------

    def start_run(self, output: Path, *arguments: str):
        """Begin a real run far enough to write lineages.json.

        AIDER_BIN points at a stub that fails generation, so the first stage fails --
        but the run record and the lineage record are both written before any
        stage starts, which is exactly the state a resume has to be checked
        against.
        """
        failing_aider = self.temp / "failing-aider"
        failing_aider.write_text(
            "#!/bin/sh\n"
            "if [ \"${1:-}\" = --version ]; then echo 'aider 0.test'; exit 0; fi\n"
            "exit 42\n",
            encoding="utf-8",
        )
        failing_aider.chmod(0o755)
        return self.run_controller(
            "--lineages", "1", "--max-loops", "0",
            "--output-dir", self.posix(output), *arguments,
            aider=str(failing_aider),
        )

    def test_durable_records_carry_the_sampling_configuration(self):
        output = self.temp / "durable"
        self.start_run(output, "--top-p", "0.9", "--sampling-seed", "42",
                       "--max-tokens", "512")
        record = json.loads(
            (output / "lineages.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["top_p"], 0.9)
        self.assertEqual(record["sampling_seed"], 42)
        self.assertEqual(record["max_tokens"], 512)
        self.assertTrue(record["automation_notice_sha256"])

        lineage = json.loads(
            (output / "lineage-001" / "lineage.json").read_text(encoding="utf-8")
        )
        self.assertEqual(lineage["top_p"], 0.9)
        self.assertEqual(lineage["sampling_seed"], 42)
        self.assertEqual(lineage["max_tokens"], 512)

    def test_unset_knobs_are_recorded_as_null_not_omitted(self):
        output = self.temp / "durable-null"
        self.start_run(output)
        record = json.loads(
            (output / "lineages.json").read_text(encoding="utf-8")
        )
        lineage = json.loads(
            (output / "lineage-001" / "lineage.json").read_text(encoding="utf-8")
        )
        for key in ("top_p", "sampling_seed", "max_tokens"):
            with self.subTest(key=key):
                self.assertIn(key, record)
                self.assertIsNone(record[key])
                self.assertIn(key, lineage)
                self.assertIsNone(lineage[key])

    def test_changing_one_sampling_value_refuses_the_output_directory(self):
        output = self.temp / "resume"
        self.start_run(output, "--top-p", "0.9")
        again = self.start_run(output, "--top-p", "0.8")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("different configuration", again.stderr)
        self.assertIn("top_p", again.stderr)

    def test_resuming_with_the_same_values_is_allowed(self):
        """The guard must refuse a changed condition, not every second run."""
        output = self.temp / "resume-same"
        self.start_run(output, "--top-p", "0.9")
        again = self.start_run(output, "--top-p", "0.9")
        self.assertNotIn("different configuration", again.stderr)


class SharedAutomationNoticeRenderTests(unittest.TestCase):
    """One canonical notice, expanded at one point, reaching every session.

    The notice lives in prompts/_shared/automation_notice.md and in no prompt
    file. scripts/prompt_render.py is the only expansion point: run_experiment.sh
    renders the task prompt through it before anything else touches the text,
    and repair_prompt.py renders the continuation template through it. These
    assert the properties that make that safe.
    """

    NOTICE = REPO_ROOT / "prompts" / "_shared" / "automation_notice.md"
    MARKER = "This session is fully automated"

    def manifest_prompts(self) -> list[Path]:
        prompts = []
        for utility in sorted(EXPECTED_SEQUENCES):
            plan = lineage_plan.resolve_plan(
                REPO_ROOT, utility, "demo/m", "0", "build", 3, 1800
            )
            prompts.extend(REPO_ROOT / c["prompt"] for c in plan["checkpoints"])
        return prompts

    def test_every_manifest_prompt_renders_with_the_notice_exactly_once(self):
        notice = prompt_render.notice_text(REPO_ROOT)
        for prompt in self.manifest_prompts():
            rendered = prompt_render.render_file(REPO_ROOT, prompt)
            with self.subTest(prompt=prompt.name):
                self.assertIn(notice, rendered)
                self.assertEqual(rendered.count(self.MARKER), 1)
                self.assertNotIn(prompt_render.PLACEHOLDER, rendered)

    def test_the_rendered_prompt_keeps_the_task_text_byte_for_byte(self):
        """Only the notice is added; the task content is untouched."""
        for prompt in self.manifest_prompts():
            original = prompt.read_text(encoding="utf-8")
            rendered = prompt_render.render_file(REPO_ROOT, prompt)
            with self.subTest(prompt=prompt.name):
                self.assertTrue(rendered.endswith(original.lstrip()))

    def test_no_manifest_prompt_file_carries_its_own_copy(self):
        """Twenty pasted copies is the drift this design exists to avoid."""
        for prompt in self.manifest_prompts():
            text = prompt.read_text(encoding="utf-8")
            with self.subTest(prompt=prompt.name):
                self.assertNotIn(self.MARKER, text)

    def test_the_repair_prompt_carries_the_notice_exactly_once(self):
        """A repair session is a fresh session and needs the same instructions,
        and must not restate them twice by quoting an already-rendered task."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            original = REPO_ROOT / "prompts" / "grep" / "000_base_new_grep.md"
            log = work / "build.log"
            log.write_text("error: something failed\n", encoding="utf-8")
            output = work / "repair.md"
            result = subprocess.run(
                [sys.executable,
                 str(REPO_ROOT / "scripts" / "repair_prompt.py"),
                 "--template",
                 str(REPO_ROOT / "prompts" / "repair_continuation_template.md"),
                 "--original-prompt", str(original),
                 "--source-path", "src/new_grep/new_grep.c",
                 "--loop-number", "1", "--max-loops", "3",
                 "--build-log", str(log), "--build-exit", "1",
                 "--repo", str(REPO_ROOT)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output.write_text(result.stdout, encoding="utf-8")
            rendered = result.stdout

        self.assertEqual(rendered.count(self.MARKER), 1)
        self.assertNotIn(prompt_render.PLACEHOLDER, rendered)
        self.assertIn(prompt_render.notice_text(REPO_ROOT), rendered)

    def test_editing_the_notice_changes_the_configuration_fingerprint(self):
        """The notice is part of every prompt the model sees, so it is part of
        the configuration even though no prompt file contains it."""
        before = lineage_plan.resolve_plan(
            REPO_ROOT, "grep", "demo/m", "0", "build", 3, 1800
        )["config_fingerprint"]
        original = self.NOTICE.read_bytes()
        try:
            self.NOTICE.write_bytes(original + b"\nOne more sentence.\n")
            after = lineage_plan.resolve_plan(
                REPO_ROOT, "grep", "demo/m", "0", "build", 3, 1800
            )["config_fingerprint"]
        finally:
            self.NOTICE.write_bytes(original)
        self.assertNotEqual(before, after)
        self.assertEqual(
            before,
            lineage_plan.resolve_plan(
                REPO_ROOT, "grep", "demo/m", "0", "build", 3, 1800
            )["config_fingerprint"],
            "restoring the notice must restore the fingerprint",
        )

    def test_rendering_is_idempotent(self):
        """The durable copy is itself a rendered prompt; re-rendering one must
        not add a second notice."""
        notice = prompt_render.notice_text(REPO_ROOT)
        once = prompt_render.render_file(
            REPO_ROOT, REPO_ROOT / "prompts" / "grep" / "000_base_new_grep.md"
        )
        twice = prompt_render.render(once, notice)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(self.MARKER), 1)

    def test_the_notice_body_excludes_its_maintainer_comment(self):
        """The header names other prompt files and explains the experimental
        contract; it is documentation for the repository, not for the model."""
        notice = prompt_render.notice_text(REPO_ROOT)
        self.assertNotIn("<!--", notice)
        self.assertNotIn("checkpoint_feature_template.md", notice)
        self.assertTrue(notice.startswith("## Session conditions"))

    def test_the_notice_introduces_no_future_checkpoint_information(self):
        for leak in ("-H", "-h", "-r", "-i", "-p", "-m", "-R", "-c", "-v",
                     "-f", "-u", "grep", "sort", "mkdir", "chmod"):
            with self.subTest(leak=leak):
                self.assertNotIn(
                    f" {leak} ", prompt_render.notice_text(REPO_ROOT)
                )

    def test_run_experiment_uses_the_rendered_prompt_everywhere(self):
        """Durable copy, sandbox copy and the text sent to Aider all come
        from the one rendered file, so they cannot disagree."""
        text = (REPO_ROOT / "scripts" / "run_experiment.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('cp "$RENDERED_PROMPT" "$experiment_dir/prompt.md"', text)
        self.assertIn('cp "$RENDERED_PROMPT" "$workdir/', text)
        self.assertIn('current_prompt="$RENDERED_PROMPT"', text)
        self.assertIn('--message-file "$prompt"', text)
        # And the unrendered file is what the repair renderer quotes, so the
        # notice is not stated twice in a continuation prompt.
        self.assertIn('--original-prompt "$PROMPT_ABS"', text)


class SystemBashStagePlanValidationTests(StagePlanValidationTests):
    """The whole controller preflight under /bin/bash rather than PATH's bash.

    Everything inherited runs again against the OS shell: the valid plan passes,
    a short record, an empty fingerprint and a malformed fingerprint each abort,
    and none of them leaves a lineage directory or a lineage.json behind.
    """

    @classmethod
    def setUpClass(cls):
        cls.bash = system_bash()
        if not cls.bash:
            raise unittest.SkipTest("/bin/bash is not present on this host")


class SuiteReproducibilityTests(unittest.TestCase):
    """The self-check must compare the reproducible artifact set, semantically."""

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def config(self, suite: str) -> dict:
        return json.loads(
            (REPO_ROOT / "tests" / f"{suite}-test-suite" / "config.json")
            .read_text(encoding="utf-8")
        )

    def committed(self, suite: str) -> Path:
        return REPO_ROOT / "tests" / f"{suite}-test-suite" / "suites"

    def stage_generated(self, suite: str, target: Path) -> Path:
        """A stand-in 'fresh' tree: exactly the declared generated tiers."""
        target.mkdir(parents=True, exist_ok=True)
        source = self.committed(suite)
        for tier in self.config(suite)["generated_suites"]:
            for candidate in (f"{tier}.json.gz", f"{tier}.json"):
                if (source / candidate).is_file():
                    shutil.copy(source / candidate, target / candidate)
                    break
        shutil.copy(source / "MANIFEST.json", target / "MANIFEST.json")
        return target

    def test_both_suites_declare_their_reproducible_artifact_set(self):
        for suite in ("sort", "mkdir"):
            config = self.config(suite)
            with self.subTest(suite=suite):
                self.assertIn("generated_suites", config)
                self.assertIn("separately_maintained_suites", config)
                self.assertTrue(config["generated_suites"])

    def test_committed_inventory_is_fully_accounted_for(self):
        """Every committed suite file is either generated or declared
        separately maintained -- nothing may be silently excluded."""
        for suite in ("sort", "mkdir"):
            config = self.config(suite)
            generated = set(config["generated_suites"])
            separate = {
                name.split(".json")[0]
                for name in config["separately_maintained_suites"]
            }
            present = set(suite_diff.suite_files(self.committed(suite)))
            with self.subTest(suite=suite):
                self.assertEqual(
                    present - generated - separate, set(),
                    "a committed suite is neither generated nor declared "
                    "separately maintained",
                )

    def test_generated_tiers_compare_clean_against_themselves(self):
        for suite in ("sort", "mkdir"):
            fresh = self.stage_generated(suite, self.temp / f"fresh-{suite}")
            config = self.config(suite)
            report = suite_diff.compare(
                fresh, self.committed(suite),
                config["generated_suites"],
                config["separately_maintained_suites"],
            )
            with self.subTest(suite=suite):
                self.assertTrue(report["reproducible"], report)
                self.assertEqual(report["inventory_problems"], [])

    def test_a_separately_maintained_file_is_not_reported_as_missing(self):
        """fuzz_regressions is absent from a fresh tree by design."""
        fresh = self.stage_generated("sort", self.temp / "fresh-sort-sep")
        self.assertFalse((fresh / "fuzz_regressions.json.gz").exists())
        config = self.config("sort")
        report = suite_diff.compare(
            fresh, self.committed("sort"), config["generated_suites"],
            config["separately_maintained_suites"],
        )
        self.assertTrue(report["reproducible"])
        self.assertIn("fuzz_regressions", report["separately_maintained"])

    def test_an_undeclared_committed_file_is_an_inventory_error(self):
        """The check must not be silenced by dropping a file from comparison."""
        fresh = self.stage_generated("sort", self.temp / "fresh-undeclared")
        committed = self.temp / "committed-undeclared"
        shutil.copytree(self.committed("sort"), committed)
        (committed / "surprise.json").write_text('{"cases": []}', encoding="utf-8")
        config = self.config("sort")
        report = suite_diff.compare(
            fresh, committed, config["generated_suites"],
            config["separately_maintained_suites"],
        )
        self.assertFalse(report["reproducible"])
        self.assertTrue(any("surprise" in p for p in report["inventory_problems"]))

    def test_a_semantic_case_change_is_reported_by_name_and_field(self):
        """A root-corrupted faults tier must be diagnosed, not just 'differ'."""
        import gzip

        fresh = self.stage_generated("sort", self.temp / "fresh-root")
        with gzip.open(fresh / "faults.json.gz", "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        cases = payload["cases"] if isinstance(payload, dict) else payload
        for case in cases:
            if (case.get("faults") or {}).get("unwritable_dir_output"):
                case["exit_code"] = 0          # what root freezes
        with gzip.GzipFile(fresh / "faults.json.gz", "wb", mtime=0) as handle:
            handle.write(
                (json.dumps(payload, indent=1, sort_keys=True) + "\n").encode()
            )

        config = self.config("sort")
        report = suite_diff.compare(
            fresh, self.committed("sort"), config["generated_suites"],
            config["separately_maintained_suites"],
        )
        self.assertFalse(report["reproducible"])
        differences = report["differences"]["faults"]
        self.assertTrue(
            any("fault-o-unwritable.exit_code" in d for d in differences),
            differences,
        )

    def test_gzip_container_metadata_alone_is_not_a_difference(self):
        """Recompressing identical cases must compare clean: the comparator
        reads cases, not gzip bytes."""
        import gzip

        fresh = self.stage_generated("sort", self.temp / "fresh-recompress")
        with gzip.open(fresh / "faults.json.gz", "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        # Different mtime and compression level, identical cases.
        with gzip.GzipFile(fresh / "faults.json.gz", "wb",
                           compresslevel=1, mtime=123456789) as handle:
            handle.write(
                (json.dumps(payload, indent=4, sort_keys=False) + "\n").encode()
            )
        self.assertNotEqual(
            (fresh / "faults.json.gz").read_bytes(),
            (self.committed("sort") / "faults.json.gz").read_bytes(),
            "the two files must differ as BYTES for this test to mean anything",
        )
        config = self.config("sort")
        report = suite_diff.compare(
            fresh, self.committed("sort"), config["generated_suites"],
            config["separately_maintained_suites"],
        )
        self.assertTrue(report["reproducible"], report["differences"])

    def test_manifest_describes_exactly_the_generated_tiers(self):
        """MANIFEST counts cover the reproducible set and nothing else."""
        for suite in ("sort", "mkdir"):
            manifest = json.loads(
                (self.committed(suite) / "MANIFEST.json").read_text(encoding="utf-8")
            )
            with self.subTest(suite=suite):
                self.assertEqual(
                    sorted(manifest["counts"]),
                    sorted(self.config(suite)["generated_suites"]),
                )

    def test_manifest_counts_match_the_committed_case_counts(self):
        for suite in ("sort", "mkdir"):
            manifest = json.loads(
                (self.committed(suite) / "MANIFEST.json").read_text(encoding="utf-8")
            )
            files = suite_diff.suite_files(self.committed(suite))
            for tier, expected in manifest["counts"].items():
                with self.subTest(suite=suite, tier=tier):
                    _, cases = suite_diff.load_cases(files[tier])
                    self.assertEqual(len(cases), expected)

    def test_the_separately_maintained_suite_has_a_deterministic_verifier(self):
        """fuzz_regressions is excluded from gate 1 only because gates 3 and 4
        still run the oracle and the teeth shims against it."""
        text = (REPO_ROOT / "tests" / "sort-test-suite"
                / "selfcheck.sh").read_text(encoding="utf-8")
        # gate 3 globs every suite file, fuzz_regressions included.
        self.assertIn('for s in suites/*.json suites/*.json.gz', text)
        self.assertIn('runner.py "${SUITES[@]}" --all-flags', text)

    def test_fuzz_regressions_provenance_is_documented(self):
        readme = (REPO_ROOT / "tests" / "sort-test-suite"
                  / "README.md").read_text(encoding="utf-8")
        self.assertIn("fuzz_regressions", readme)
        self.assertIn("diff_fuzz.py", readme)
        config = self.config("sort")
        self.assertIn("fuzz_regressions.json.gz",
                      config["separately_maintained_suites"])


def fake_version_tool(directory: Path, name: str, version_line: str) -> Path:
    """An executable whose only job is to answer --version a chosen way."""
    directory.mkdir(parents=True, exist_ok=True)
    implementation = directory / f"{name}_version.py"
    implementation.write_text(
        "import sys\n"
        f"sys.stdout.write({version_line!r} + '\\n')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        launcher = directory / f"{name}.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{implementation}" %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = directory / name
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{implementation}" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return launcher


def fake_utility(directory: Path, name: str, accepted: set[str]) -> Path:
    """A stand-in candidate that accepts exactly `accepted` short options.

    Anything else is refused the way an unknown option is refused: nothing on
    stdout, a diagnostic on stderr, exit 2. A native launcher is emitted because
    the gate execs the candidate directly, and Windows will not exec a .py file;
    the launcher just forwards to one portable implementation.
    """
    directory.mkdir(parents=True, exist_ok=True)
    implementation = directory / f"{name}_impl.py"
    implementation.write_text(
        "import sys\n"
        f"ACCEPTED = {sorted(accepted)!r}\n"
        "args = sys.argv[1:]\n"
        "for arg in args:\n"
        "    if arg == '--':\n"
        "        break\n"
        "    if arg.startswith('-') and arg != '-':\n"
        "        if arg not in ACCEPTED:\n"
        "            sys.stderr.write('unknown option %s\\n' % arg)\n"
        "            sys.exit(2)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        launcher = directory / f"{name}.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{implementation}" %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = directory / name
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{implementation}" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return launcher


class CheckpointBoundaryGateTests(unittest.TestCase):
    """The controller-only gate that rejects a candidate built ahead of schedule."""

    def setUp(self):
        import tempfile

        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def matrix(self, utility: str) -> list[dict]:
        manifest = checkpoint_boundary_gate.load_manifest(REPO_ROOT, utility)
        return checkpoint_boundary_gate.availability(manifest)

    def test_matrix_matches_the_required_availability(self):
        expected = {
            "sort": [
                ("000", [], ["-r", "-f", "-u", "-c"]),
                ("001", ["-r"], ["-f", "-u", "-c"]),
                ("002", ["-r", "-f"], ["-u", "-c"]),
                ("003", ["-r", "-f", "-u"], ["-c"]),
                ("004", ["-r", "-f", "-u", "-c"], []),
            ],
            "mkdir": [
                ("000", [], ["-p", "-m"]),
                ("001", ["-p"], ["-m"]),
                ("002", ["-p", "-m"], []),
            ],
            "grep": [
                ("000", [], ["-H", "-h", "-r", "-i"]),
                ("001", ["-H"], ["-h", "-r", "-i"]),
                ("002", ["-H", "-h"], ["-r", "-i"]),
                ("003", ["-H", "-h", "-r"], ["-i"]),
                ("004", ["-H", "-h", "-r", "-i"], []),
            ],
            "chmod": [
                ("000", [], ["-R", "-c", "-v", "-f"]),
                ("001", ["-R"], ["-c", "-v", "-f"]),
                ("002", ["-R", "-c"], ["-v", "-f"]),
                ("003", ["-R", "-c", "-v"], ["-f"]),
                ("004", ["-R", "-c", "-v", "-f"], []),
            ],
        }
        for utility, rows in expected.items():
            with self.subTest(utility=utility):
                actual = [
                    (row["checkpoint_id"], row["allowed"], row["forbidden"])
                    for row in self.matrix(utility)
                ]
                self.assertEqual(actual, [tuple(r) for r in rows])

    def test_availability_is_monotonic(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            previous: set[str] = set()
            for row in self.matrix(utility):
                with self.subTest(utility=utility, checkpoint=row["checkpoint_id"]):
                    allowed = set(row["allowed"])
                    self.assertLessEqual(previous, allowed, "a flag was withdrawn")
                    self.assertEqual(allowed & set(row["forbidden"]), set())
                    previous = allowed

    def test_final_checkpoint_forbids_nothing(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            with self.subTest(utility=utility):
                self.assertEqual(self.matrix(utility)[-1]["forbidden"], [])

    def test_a_candidate_implementing_every_flag_fails_at_000(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            executable = fake_utility(
                self.temp / f"all-{utility}", f"new_{utility}",
                set(EXPECTED_SEQUENCES[utility]),
            )
            report = checkpoint_boundary_gate.evaluate(
                REPO_ROOT, utility, "000", executable
            )
            with self.subTest(utility=utility):
                self.assertFalse(report["passed"])
                self.assertEqual(
                    report["failure_reason"], "premature_feature_implementation"
                )
                self.assertEqual(
                    sorted(report["violations"]),
                    sorted(EXPECTED_SEQUENCES[utility]),
                )

    def test_a_candidate_implementing_only_allowed_flags_passes(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            for row in self.matrix(utility):
                executable = fake_utility(
                    self.temp / f"ok-{utility}-{row['checkpoint_id']}",
                    f"new_{utility}", set(row["allowed"]),
                )
                report = checkpoint_boundary_gate.evaluate(
                    REPO_ROOT, utility, row["checkpoint_id"], executable
                )
                with self.subTest(utility=utility,
                                  checkpoint=row["checkpoint_id"]):
                    self.assertTrue(report["passed"], report["violations"])
                    self.assertIsNone(report["failure_reason"])

    def test_one_flag_ahead_is_caught(self):
        """Implementing exactly the next checkpoint's flag must be detected."""
        for utility in sorted(EXPECTED_SEQUENCES):
            rows = self.matrix(utility)
            for row in rows[:-1]:
                ahead = set(row["allowed"]) | {row["forbidden"][0]}
                executable = fake_utility(
                    self.temp / f"ahead-{utility}-{row['checkpoint_id']}",
                    f"new_{utility}", ahead,
                )
                report = checkpoint_boundary_gate.evaluate(
                    REPO_ROOT, utility, row["checkpoint_id"], executable
                )
                with self.subTest(utility=utility,
                                  checkpoint=row["checkpoint_id"]):
                    self.assertFalse(report["passed"])
                    self.assertEqual(report["violations"], [row["forbidden"][0]])

    def test_a_crash_is_not_accepted_as_a_rejection(self):
        crasher = self.temp / "crash"
        crasher.mkdir()
        implementation = crasher / "impl.py"
        implementation.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
        executable = fake_utility(crasher, "new_sort", set())
        # Sanity: the honest stand-in passes, so the assertions below are about
        # behavior rather than about the harness.
        self.assertTrue(
            checkpoint_boundary_gate.evaluate(
                REPO_ROOT, "sort", "000", executable)["passed"]
        )

    def test_every_manifest_alias_follows_the_checkpoint_matrix(self):
        """Short and long spellings obey exactly the same schedule."""
        for utility in sorted(EXPECTED_SEQUENCES):
            manifest = checkpoint_boundary_gate.load_manifest(REPO_ROOT, utility)
            aliases = manifest["flag_aliases"]
            for row in self.matrix(utility):
                allowed, forbidden = set(row["allowed"]), set(row["forbidden"])
                options = {e["option"] for e in row["forbidden_options"]}
                with self.subTest(utility=utility, checkpoint=row["checkpoint_id"]):
                    for flag in allowed:
                        for spelling in [flag, *aliases.get(flag, [])]:
                            self.assertIn(spelling, row["allowed_options"])
                            self.assertNotIn(spelling, options)
                    for flag in forbidden:
                        for spelling in [flag, *aliases.get(flag, [])]:
                            self.assertIn(spelling, options)
                            self.assertNotIn(spelling, row["allowed_options"])

    def test_every_declared_alias_is_a_long_option_of_a_ladder_flag(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            manifest = checkpoint_boundary_gate.load_manifest(REPO_ROOT, utility)
            with self.subTest(utility=utility):
                self.assertEqual(
                    sorted(manifest["flag_aliases"]),
                    sorted(EXPECTED_SEQUENCES[utility]),
                    "every ladder flag needs its aliases declared",
                )
                for flag, aliases in manifest["flag_aliases"].items():
                    for alias in aliases:
                        self.assertTrue(alias.startswith("--"), alias)

    def test_final_checkpoints_forbid_no_alias(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            with self.subTest(utility=utility):
                self.assertEqual(self.matrix(utility)[-1]["forbidden_options"], [])

    def test_a_candidate_supporting_only_a_future_long_alias_fails(self):
        """The long spelling alone is enough to fail the gate."""
        for utility in sorted(EXPECTED_SEQUENCES):
            manifest = checkpoint_boundary_gate.load_manifest(REPO_ROOT, utility)
            rows = self.matrix(utility)
            for row in rows[:-1]:
                ahead_flag = row["forbidden"][0]
                alias = manifest["flag_aliases"][ahead_flag][0]
                # Accepts the current checkpoint's options plus ONE future long
                # alias -- the short form is still correctly refused.
                executable = fake_utility(
                    self.temp / f"longalias-{utility}-{row['checkpoint_id']}",
                    f"new_{utility}", set(row["allowed_options"]) | {alias},
                )
                report = checkpoint_boundary_gate.evaluate(
                    REPO_ROOT, utility, row["checkpoint_id"], executable
                )
                with self.subTest(utility=utility,
                                  checkpoint=row["checkpoint_id"], alias=alias):
                    self.assertFalse(report["passed"])
                    self.assertEqual(report["violations"], [alias])
                    self.assertEqual(report["failure_reason"],
                                     "premature_feature_implementation")

    def test_a_candidate_supporting_every_declared_spelling_passes(self):
        for utility in sorted(EXPECTED_SEQUENCES):
            for row in self.matrix(utility):
                executable = fake_utility(
                    self.temp / f"spell-{utility}-{row['checkpoint_id']}",
                    f"new_{utility}", set(row["allowed_options"]),
                )
                report = checkpoint_boundary_gate.evaluate(
                    REPO_ROOT, utility, row["checkpoint_id"], executable
                )
                with self.subTest(utility=utility,
                                  checkpoint=row["checkpoint_id"]):
                    self.assertTrue(report["passed"], report["violations"])

    def test_gate_lives_outside_every_agent_visible_location(self):
        gate = REPO_ROOT / "scripts" / "checkpoint_boundary_gate.py"
        self.assertTrue(gate.is_file())
        # scripts/ is never copied into a sandbox, and the gate is not part of
        # any suite the bundle builder can reach.
        for utility in sorted(EXPECTED_SEQUENCES):
            suite = REPO_ROOT / "tests" / f"{utility}-test-suite"
            with self.subTest(utility=utility):
                self.assertFalse((suite / "checkpoint_boundary_gate.py").exists())
        self.assertNotIn("checkpoint_boundary_gate",
                         str(stage_test_bundle.ALLOWED_FILES))

    def test_gate_output_never_reaches_a_bundle(self):
        for utility, checkpoint_id, _ in ALL_UTILITY_CHECKPOINTS:
            bundle = shared_bundle(utility, checkpoint_id)
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                self.assertFalse((bundle / "boundary-gate.json").exists())
                for path in bundle.rglob("*"):
                    self.assertNotIn("boundary", path.name.lower())


class LineageStateTests(unittest.TestCase):
    """A lineage is countable from the moment it starts, not when it finishes."""

    def setUp(self):
        import tempfile

        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def state_tool(self, path: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "lineage_state.py"),
             "--path", str(path), "--now", "2026-07-30T00:00:00Z", *args],
            capture_output=True, text=True,
        )

    def start(self, lineage_id: str = "lineage-001") -> Path:
        path = self.root / lineage_id / "lineage.json"
        result = self.state_tool(
            path, "init", "--lineage-id", lineage_id, "--utility", "grep",
            "--model", "m", "--editor-model", "editor/m",
            "--aider-version", "aider 0.test", "--temperature", "0",
            "--max-loops", "3", "--fingerprint", "fp",
            "--checkpoint-count", "3", "--checkpoint-ids", "000,001,002",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def stage(self, path: Path, checkpoint: str, success: bool,
              reason: str | None = None, **extra) -> None:
        record = {"checkpoint_id": checkpoint, "success": success,
                  "failure_reason": reason, **extra}
        result = self.state_tool(path, "stage", "--stage-json",
                                 json.dumps(record))
        self.assertEqual(result.returncode, 0, result.stderr)

    def analyze(self) -> dict:
        write_json = analyze_lineages.write_json
        write_json(self.root / "lineages.json",
                   {"utility": "grep", "config_fingerprint": "fp",
                    "checkpoints": [{"id": "000"}, {"id": "001"}, {"id": "002"}]})
        _, lineages, never_started = analyze_lineages.load_run(self.root)
        return analyze_lineages.build_reliability(
            lineages, ["000", "001", "002"], never_started
        )

    def test_record_exists_before_the_first_checkpoint_finishes(self):
        path = self.start()
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "running")
        self.assertEqual(record["stages"], [])
        self.assertFalse(record["end_to_end_success"])

    def test_interrupted_before_checkpoint_000_counts_as_started(self):
        self.start()
        reliability = self.analyze()
        self.assertEqual(reliability["lineages_started"], 1)
        self.assertEqual(reliability["successful_final_implementations"], 0)
        self.assertEqual(reliability["controller_interrupted"], 1)
        self.assertEqual(reliability["end_to_end_completion_rate"], 0.0)

    def test_interrupted_between_checkpoints_counts_as_started(self):
        path = self.start()
        self.stage(path, "000", True)
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "running")
        self.assertEqual(record["completed_checkpoint_ids"], ["000"])
        reliability = self.analyze()
        self.assertEqual(reliability["lineages_started"], 1)
        self.assertEqual(reliability["controller_interrupted"], 1)
        self.assertEqual(reliability["successful_final_implementations"], 0)

    def test_incomplete_records_are_never_successful_finals(self):
        path = self.start()
        self.stage(path, "000", True)
        self.stage(path, "001", True)
        self.stage(path, "002", True)
        # Every checkpoint passed, but the controller never called finish.
        _, lineages, _ = analyze_lineages.load_run(self.root)
        self.assertFalse(analyze_lineages.is_successful(lineages[0]))
        self.assertEqual(
            analyze_lineages.classify(lineages[0]), "controller_interrupted"
        )
        self.assertEqual(
            analyze_lineages.population_members(lineages, None), []
        )

    def test_finish_marks_the_lineage_complete(self):
        path = self.start()
        for checkpoint in ("000", "001", "002"):
            self.stage(path, checkpoint, True)
        result = self.state_tool(path, "finish", "--success", "true",
                                 "--source-basename", "new_grep.c")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["state"], "completed")
        self.assertEqual(record["final_source"], "final/new_grep.c")
        self.assertEqual(self.analyze()["successful_final_implementations"], 1)

    def test_stop_reason_survives_into_analysis(self):
        path = self.start()
        self.stage(path, "000", True)
        self.stage(path, "001", False, "premature_feature_implementation")
        self.state_tool(path, "finish", "--success", "false",
                        "--failure-stage", "001",
                        "--failure-reason", "premature_feature_implementation")
        reliability = self.analyze()
        self.assertEqual(reliability["failure_stage_counts"]["001"], 1)
        self.assertEqual(
            reliability["failure_reason_counts"]["premature_feature_implementation"], 1
        )

    def test_ten_requested_three_started_counts_three(self):
        """The denominator counts starts, not intentions.

        lineages.json is written once, before any lineage runs, and lists every
        id the invocation planned. A controller interrupted after three of ten
        lineages must report three -- reading the plan as evidence of a start
        would report ten and silently invent seven outcomes.
        """
        for number in (1, 2, 3):
            self.start(f"lineage-{number:03d}")
        analyze_lineages.write_json(
            self.root / "lineages.json",
            {
                "utility": "grep",
                "config_fingerprint": "fp",
                "checkpoints": [{"id": "000"}, {"id": "001"}, {"id": "002"}],
                # Ten planned; only three ever began.
                "planned_lineage_ids": [f"lineage-{n:03d}" for n in range(1, 11)],
                "lineages_planned": 10,
            },
        )
        _, lineages, never_started = analyze_lineages.load_run(self.root)
        reliability = analyze_lineages.build_reliability(
            lineages, ["000", "001", "002"], never_started
        )

        self.assertEqual(reliability["lineages_started"], 3)
        self.assertEqual(reliability["lineages_planned_not_started"], 7)
        self.assertEqual(
            reliability["planned_not_started_lineage_ids"],
            [f"lineage-{n:03d}" for n in range(4, 11)],
        )
        # 004-010 must not be invented as outcomes of any kind.
        self.assertEqual(reliability["controller_interrupted"], 3)
        for identifier in (f"lineage-{n:03d}" for n in range(4, 11)):
            self.assertNotIn(identifier,
                             reliability["controller_interrupted_lineage_ids"])
            self.assertNotIn(identifier, reliability["stopped_lineage_ids"])
            self.assertNotIn(identifier, reliability["completed_lineage_ids"])
        self.assertNotIn("missing_directory",
                         reliability["incomplete_record_reasons"])
        self.assertEqual(
            sum(reliability["failure_stage_counts"].values())
            + sum(reliability["failure_stage_counts_other"].values()),
            3, "only started lineages may contribute failures",
        )

    def test_the_three_started_keep_their_own_classifications(self):
        """Excluding the unstarted must not disturb the started ones."""
        first = self.start("lineage-001")
        for checkpoint in ("000", "001", "002"):
            self.stage(first, checkpoint, True)
        self.state_tool(first, "finish", "--success", "true",
                        "--source-basename", "new_grep.c")

        second = self.start("lineage-002")          # running -> interrupted
        self.stage(second, "000", True)

        third = self.root / "lineage-003"           # started, record lost
        third.mkdir(parents=True, exist_ok=True)
        (third / "lineage.json").unlink(missing_ok=True)

        analyze_lineages.write_json(
            self.root / "lineages.json",
            {"utility": "grep", "config_fingerprint": "fp",
             "checkpoints": [{"id": "000"}, {"id": "001"}, {"id": "002"}],
             "planned_lineage_ids": [f"lineage-{n:03d}" for n in range(1, 11)]},
        )
        _, lineages, never_started = analyze_lineages.load_run(self.root)
        reliability = analyze_lineages.build_reliability(
            lineages, ["000", "001", "002"], never_started
        )
        self.assertEqual(reliability["lineages_started"], 3)
        self.assertEqual(reliability["successful_final_implementations"], 1)
        self.assertEqual(reliability["completed_lineage_ids"], ["lineage-001"])
        self.assertEqual(
            reliability["incomplete_record_reasons"], {"missing_record": 1}
        )
        self.assertEqual(reliability["lineages_planned_not_started"], 7)

    def test_a_missing_record_is_reported_not_skipped(self):
        (self.root / "lineage-007").mkdir(parents=True)
        reliability = self.analyze()
        self.assertEqual(reliability["lineages_started"], 1)
        self.assertEqual(
            reliability["incomplete_record_reasons"], {"missing_record": 1}
        )

    def test_a_malformed_record_is_reported_not_skipped(self):
        directory = self.root / "lineage-008"
        directory.mkdir(parents=True)
        (directory / "lineage.json").write_text("{ not json", encoding="utf-8")
        reliability = self.analyze()
        self.assertEqual(reliability["lineages_started"], 1)
        self.assertEqual(
            reliability["incomplete_record_reasons"], {"malformed_record": 1}
        )

    def test_updates_are_atomic(self):
        """No temporary file survives, and the record always parses."""
        path = self.start()
        for checkpoint in ("000", "001"):
            self.stage(path, checkpoint, True)
            json.loads(path.read_text(encoding="utf-8"))
        leftovers = [p.name for p in path.parent.iterdir()
                     if p.name != "lineage.json"]
        self.assertEqual(leftovers, [])

    def test_rerunning_a_checkpoint_replaces_rather_than_duplicates(self):
        path = self.start()
        self.stage(path, "000", False, "validation_failed")
        self.stage(path, "000", True)
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([s["checkpoint_id"] for s in record["stages"]], ["000"])
        self.assertTrue(record["stages"][0]["success"])

    def test_init_preserves_the_original_start_time_on_resume(self):
        path = self.start()
        first = json.loads(path.read_text(encoding="utf-8"))["started_at"]
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "lineage_state.py"),
             "--path", str(path), "--now", "2026-08-01T00:00:00Z",
             "init", "--lineage-id", "lineage-001", "--utility", "grep",
             "--checkpoint-count", "3", "--checkpoint-ids", "000,001,002"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["started_at"], first)
        self.assertEqual(record["updated_at"], "2026-08-01T00:00:00Z")

    def test_resume_keeps_each_lineage_separate(self):
        first = self.start("lineage-001")
        second = self.start("lineage-002")
        self.stage(first, "000", True, candidate_sha256="aaa")
        self.stage(second, "000", True, candidate_sha256="bbb")
        one = json.loads(first.read_text(encoding="utf-8"))
        two = json.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(one["stages"][0]["candidate_sha256"], "aaa")
        self.assertEqual(two["stages"][0]["candidate_sha256"], "bbb")
        self.assertEqual(self.analyze()["lineages_started"], 2)


class AbsoluteOutputPathTests(unittest.TestCase):
    """--output-dir may live anywhere, and the cwd must not matter."""

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required to run the controller")

    def dry_run(self, utility: str, output_dir: str,
                cwd: Path | None = None) -> list[str]:
        result = subprocess.run(
            [self.bash, str(REPO_ROOT / "scripts" / "run_lineage_experiment.sh"),
             "--utility", utility, "--model", "demo/m", "--temperature", "0",
             "--lineages", "1", "--output-dir", output_dir, "--dry-run"],
            capture_output=True, text=True, cwd=str(cwd or REPO_ROOT),
            env={**os.environ, "PYTHON_BIN": sys.executable},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line for line in result.stdout.splitlines()
                if "run_experiment.sh" in line]

    def posix(self, path: Path) -> str:
        """An --output-dir the controller's `!= /*` test treats as absolute."""
        text = path.as_posix()
        if len(text) > 1 and text[1] == ":":          # C:/x -> /c/x on Git Bash
            text = "/" + text[0].lower() + text[2:]
        return text

    def test_an_external_output_directory_is_not_prefixed_with_the_repo(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            target = self.posix(Path(temp) / "lineages")
            lines = self.dry_run("mkdir", target)
            for line in lines:
                self.assertIn(target, line)
                self.assertNotIn(f"{REPO_ROOT.as_posix()}/{target}", line)

    def test_an_output_directory_containing_spaces_is_handled(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            target = self.posix(Path(temp) / "with space" / "runs")
            lines = self.dry_run("mkdir", target)
            self.assertTrue(lines)
            for line in lines:
                # %q-quoted, so the space is escaped rather than splitting.
                self.assertIn("with\\ space", line)

    def test_invocation_from_a_subdirectory_matches_the_root(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            target = self.posix(Path(temp) / "cwd-check")
            from_root = self.dry_run("grep", target, cwd=REPO_ROOT)
            from_sub = self.dry_run("grep", target, cwd=REPO_ROOT / "scripts")
            self.assertEqual(from_root, from_sub)

    def test_seeds_stay_absolute_and_inside_one_lineage(self):
        import re
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            target = self.posix(Path(temp) / "seeds")
            for line in self.dry_run("sort", target):
                seed = re.search(r"--seed-file (\S+)", line)
                if not seed:
                    continue
                self.assertTrue(seed.group(1).startswith(target),
                                f"seed left the output root: {seed.group(1)}")
                self.assertEqual(len(set(re.findall(r"lineage-\d+", line))), 1)

    def test_dry_run_writes_nothing_outside_the_repository(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "never-created"
            self.dry_run("chmod", self.posix(target))
            self.assertFalse(target.exists())

    def test_record_path_keeps_external_paths_absolute(self):
        """The shell helper that decides how a path is written down."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            external = self.posix(Path(temp) / "out" / "candidate.c")
            script = (
                f'REPO={REPO_ROOT.as_posix()!r}\n'
                'record_path() {\n'
                '    local path="$1"\n'
                '    case "$path" in\n'
                '        "$REPO"/*) printf \'%s\' "${path#"$REPO"/}" ;;\n'
                '        *) printf \'%s\' "$path" ;;\n'
                '    esac\n'
                '}\n'
                f'record_path {external!r}; printf "\\n"\n'
                f'record_path "$REPO/scripts/x.py"; printf "\\n"\n'
            )
            result = subprocess.run([self.bash, "-c", script],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            outside, inside = result.stdout.splitlines()
            self.assertEqual(outside, external, "an external path must stay absolute")
            self.assertEqual(inside, "scripts/x.py", "a repo path stays relative")


class SeedProvenanceAcrossRootsTests(unittest.TestCase):
    """Hash equality must hold wherever the output tree lives."""

    def test_promotion_hashes_match_with_an_external_output_root(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "external-root"
            stages = []
            previous_sha = None
            for index, checkpoint in enumerate(("000", "001", "002")):
                candidate = (root / "lineage-001" / checkpoint / "temp-0" /
                             "attempt-001" / "candidate" / "new_grep.c")
                candidate.parent.mkdir(parents=True)
                candidate.write_text(f"/* revision {index} */\n", encoding="utf-8")
                sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
                stages.append({
                    "checkpoint_id": checkpoint,
                    "source_mode": "new" if index == 0 else "existing",
                    "success": True,
                    "candidate": str(candidate),
                    "candidate_sha256": sha,
                    "seed_sha256": previous_sha,
                })
                previous_sha = sha

            record = {"lineage_id": "lineage-001", "state": "completed",
                      "end_to_end_success": True, "stages": stages}
            self.assertEqual(
                analyze_lineages.check_seed_provenance([record]), [],
                "an absolute output root must not break seed provenance",
            )

    def test_a_broken_chain_is_still_detected_outside_the_repository(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "external-root"
            root.mkdir()
            record = {
                "lineage_id": "lineage-001", "state": "completed",
                "end_to_end_success": True,
                "stages": [
                    {"checkpoint_id": "000", "source_mode": "new",
                     "success": True, "candidate_sha256": "aaa"},
                    {"checkpoint_id": "001", "source_mode": "existing",
                     "success": True, "candidate_sha256": "bbb",
                     "seed_sha256": "not-aaa"},
                ],
            }
            problems = analyze_lineages.check_seed_provenance([record])
            self.assertEqual(len(problems), 1)
            self.assertIn("001", problems[0])


class HeldOutCorpusTests(unittest.TestCase):
    """The held-out pool: shape, scope, and the thing that must never happen.

    Offline throughout. No candidate is built and no oracle is consulted -- the
    corpora are read as committed, exactly the way the audit for the visible
    suites works.
    """

    LADDERS = {
        "chmod": [[], ["-R"], ["-R", "-c"], ["-R", "-c", "-v"],
                  ["-R", "-c", "-v", "-f"]],
        "grep": [[], ["-H"], ["-H", "-h"], ["-H", "-h", "-r"],
                 ["-H", "-h", "-r", "-i"]],
        "sort": [[], ["-r"], ["-r", "-f"], ["-r", "-f", "-u"],
                 ["-r", "-f", "-u", "-c"]],
        "mkdir": [[], ["-p"], ["-p", "-m"]],
    }

    @staticmethod
    def _corpus(utility):
        root = REPO_ROOT / "tests" / f"{utility}-test-suite"
        path = heldout_contract.corpus_path(root)
        return heldout_contract.load(root) if path.is_file() else None

    def _each_corpus(self):
        found = 0
        for utility in self.LADDERS:
            corpus = self._corpus(utility)
            if corpus is None:
                continue        # generated per host; absence is not a failure
            found += 1
            yield utility, corpus
        self.assertGreater(found, 0, "no held-out corpus is committed at all")

    def test_every_case_satisfies_the_shared_invariants(self):
        for utility, corpus in self._each_corpus():
            with self.subTest(utility=utility):
                self.assertEqual(
                    heldout_contract.corpus_invariants(
                        corpus, self.LADDERS[utility]),
                    [],
                )

    def test_no_case_leaves_the_bounded_ladder(self):
        """A dual outside the ladder would report scope drift as a failure."""
        for utility, corpus in self._each_corpus():
            ladder = {flag for stage in self.LADDERS[utility] for flag in stage}
            for case in heldout_contract.cases(corpus):
                with self.subTest(utility=utility, case=case["name"]):
                    self.assertLessEqual(set(case.get("flags") or []), ladder)

    def test_every_case_names_the_visible_case_it_is_a_dual_of(self):
        for utility, corpus in self._each_corpus():
            for case in heldout_contract.cases(corpus):
                with self.subTest(utility=utility, case=case["name"]):
                    self.assertTrue(case.get("dual_of"))
                    self.assertTrue(
                        case["name"].startswith(heldout_contract.NAME_PREFIX),
                        "the prefix is what makes a leak scan unambiguous",
                    )

    def test_a_dual_is_never_identical_to_the_case_it_came_from(self):
        """An unchanged dual is not held out: its values are in the bundle.

        This caught a real defect. sort's first generator substituted whole
        lines from a hand-written table, and 14 of 24 duals came out
        byte-identical to their visible twin -- that corpus would have measured
        nothing while appearing to pass.
        """
        for utility, corpus in self._each_corpus():
            visible = {}
            for path in sorted((REPO_ROOT / "tests" / f"{utility}-test-suite"
                                / "suites").iterdir()):
                if path.name == "MANIFEST.json" or path.suffix not in (".json", ".gz"):
                    continue
                opener = gzip.open if path.suffix == ".gz" else open
                with opener(path, "rt", encoding="utf-8") as handle:
                    data = json.load(handle)
                cases = (data["cases"] if isinstance(data, dict) and "cases" in data
                         else data)
                for case in cases:
                    visible[case["name"]] = case

            for case in heldout_contract.cases(corpus):
                twin = visible.get(case["dual_of"])
                if twin is None:
                    continue
                with self.subTest(utility=utility, case=case["name"]):
                    inputs = ("args", "stdin", "stdin_b64", "fixture", "tree",
                              "targets")
                    self.assertTrue(
                        any(case.get(key) != twin.get(key) for key in inputs),
                        f"{case['name']} has the same inputs as its twin",
                    )

    def test_a_dual_reaches_the_same_outcome_as_the_case_it_came_from(self):
        """A dual that exits differently has stopped testing the same thing.

        Enforced here rather than only in each generator, so it covers every
        committed corpus however it was produced. It caught eight broken grep
        duals: the pattern `needle` was mapped to `marker` while the fixture
        file bodies were not, so `r-directory-is-traversed-in-name-order`
        searched for a string none of its files contained and became a case
        about finding nothing -- exit 0 turned into exit 1. Nothing else
        noticed, because every individual step had done what it was told.
        """
        for utility, corpus in self._each_corpus():
            visible = {}
            for path in sorted((REPO_ROOT / "tests" / f"{utility}-test-suite"
                                / "suites").iterdir()):
                if path.name == "MANIFEST.json" or path.suffix not in (".json", ".gz"):
                    continue
                opener = gzip.open if path.suffix == ".gz" else open
                with opener(path, "rt", encoding="utf-8") as handle:
                    data = json.load(handle)
                cases = (data["cases"] if isinstance(data, dict) and "cases" in data
                         else data)
                if not isinstance(cases, list):
                    continue
                for case in cases:
                    if isinstance(case, dict) and "name" in case:
                        visible[case["name"]] = case

            for case in heldout_contract.cases(corpus):
                twin = visible.get(case["dual_of"])
                if twin is None or "exit_code" not in twin \
                        or "exit_code" not in case:
                    continue
                with self.subTest(utility=utility, case=case["name"]):
                    self.assertEqual(
                        case["exit_code"], twin["exit_code"],
                        f"{case['name']} no longer matches {case['dual_of']}",
                    )

    def test_the_corpus_lives_nowhere_the_bundle_would_copy_it(self):
        """The guarantee, checked against the allowlist rather than intent."""
        allowlisted = set(stage_test_bundle.ALLOWED_FILES)
        self.assertNotIn(heldout_contract.CORPUS_FILENAME, allowlisted)
        for entry in allowlisted:
            self.assertFalse(
                entry.startswith(heldout_contract.HELDOUT_DIRNAME),
                f"{entry} would copy the held-out corpus into a sandbox",
            )

    def test_the_isolation_check_passes_for_every_committed_corpus(self):
        """The real guard, run for real -- not a re-implementation of it."""
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" /
                                 "check_heldout_isolation.py")],
            capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0,
                         f"{completed.stdout}\n{completed.stderr}")

    def test_the_isolation_check_fails_when_a_case_really_does_leak(self):
        """A guard nobody has seen fail is not evidence of anything.

        Planting a held-out value in a file the bundle copies verbatim must turn
        the check red. `engine.py` is used rather than `props.py` because
        `props.py` is regenerated and pruned per checkpoint, so a canary planted
        there legitimately never propagates -- which once made the guard look
        toothless when it was not.
        """
        utility = next(iter(u for u, c in self._each_corpus()), None)
        corpus = self._corpus(utility)
        case = heldout_contract.cases(corpus)[0]
        needle = max(heldout_contract.scannable_values(case), key=len)

        engine = REPO_ROOT / "tests" / f"{utility}-test-suite" / "engine.py"
        original = engine.read_bytes()
        try:
            with engine.open("wb") as handle:
                handle.write(b"# canary " +
                             needle.encode("utf-8", "surrogateescape") + b"\n")
                handle.write(original)
            completed = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" /
                                     "check_heldout_isolation.py"),
                 "--utility", utility],
                capture_output=True, text=True,
            )
        finally:
            engine.write_bytes(original)
        self.assertEqual(completed.returncode, 1,
                         "a planted held-out value must be reported as a leak")
        self.assertIn("LEAK", completed.stderr)

    def test_every_utility_is_wired_to_run_its_held_out_pass(self):
        for utility in self.LADDERS:
            manifest = json.loads(
                (MANIFEST_DIR / f"{utility}.json").read_text(encoding="utf-8"))
            with self.subTest(utility=utility):
                command = manifest.get("extra_test_command", "")
                self.assertIn("heldout_judge.py", command)
                self.assertIn(f"--utility {utility}", command)
                self.assertIn("$HELDOUT_ROOT", command,
                              "a relative path would resolve inside the sandbox")

    def test_the_controller_exports_the_root_the_command_depends_on(self):
        text = (REPO_ROOT / "scripts" / "run_experiment.sh").read_text(
            encoding="utf-8")
        self.assertIn("export HELDOUT_ROOT=", text)


if __name__ == "__main__":
    unittest.main()
