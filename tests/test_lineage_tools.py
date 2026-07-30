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
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = REPO_ROOT / "experiments" / "utilities"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import analyze_lineages  # noqa: E402
import capture_candidate  # noqa: E402
import lineage_plan  # noqa: E402
import stage_test_bundle  # noqa: E402

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
    candidate = attempt / "candidate" / "new_demo.c"
    candidate_sha = None
    if success:
        candidate.write_text(source, encoding="utf-8")
        candidate_sha = sha256_text(source)

    return {
        "checkpoint_id": checkpoint["id"],
        "checkpoint_name": checkpoint["name"],
        "prompt": f"prompts/demo/{checkpoint['id']}.md",
        "source_mode": "new" if index == 0 else "existing",
        "implemented_flags": [f"-f{n}" for n in range(index)],
        "attempt_dir": attempt.as_posix(),
        "stage_dir": (root / lineage_id / checkpoint["id"]).as_posix(),
        "candidate": candidate.as_posix() if success else None,
        "candidate_source_basename": "new_demo.c",
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


def make_lineage_root(root: Path, outcomes: list[int | None]) -> Path:
    """Build a lineage run. Each entry in `outcomes` is a lineage: None means it
    completed, an integer is the index of the checkpoint it stopped at."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "lineages.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment_unit": "lineage",
                "utility": "demo",
                "program": "new_demo",
                "model": "demo/model",
                "temperature": 0.0,
                "agent": "build",
                "max_loops": 3,
                "source_path": "src/new_demo/new_demo.c",
                "source_basename": "new_demo.c",
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
                    "final_source": "final/new_demo.c" if completed else None,
                    "stages": stages,
                }
            ),
            encoding="utf-8",
        )
        if completed:
            final = root / lineage_id / "final"
            final.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(stages[-1]["candidate"]), final / "new_demo.c")
    return root


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
        self.run_metadata = json.loads(
            (self.root / "lineages.json").read_text(encoding="utf-8")
        )
        self.lineages = [
            json.loads((self.root / f"lineage-{n:03d}" / "lineage.json").read_text(
                encoding="utf-8"))
            for n in (1, 2, 3)
        ]

    def test_final_population_holds_only_completed_lineages(self):
        members = analyze_lineages.population_members(self.lineages, None)
        self.assertEqual(
            [lineage_id for lineage_id, _ in members],
            ["lineage-001", "lineage-002"],
        )
        self.assertTrue(all(stage["checkpoint_id"] == "002" for _, stage in members))

    def test_intermediate_population_includes_lineages_that_later_stopped(self):
        members = analyze_lineages.population_members(self.lineages, "001")
        self.assertEqual(
            [lineage_id for lineage_id, _ in members],
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
            ("temperature", {"temperature": "0.7"}),
            ("agent", {"agent": "plan"}),
            ("max_loops", {"max_loops": 5}),
        ):
            with self.subTest(setting=label):
                self.assertNotEqual(base, self.plan(**overrides)["config_fingerprint"])

    def test_plan_records_every_required_component(self):
        plan = self.plan()
        # Manifest-level components.
        for key in ("utility", "program", "source_path", "executable_path",
                    "build_command", "test_dir", "judge", "judge_sha256",
                    "model", "temperature", "agent", "max_loops"):
            self.assertIn(key, plan)
        # Per-checkpoint components.
        for checkpoint in plan["checkpoints"]:
            for key in ("id", "prompt", "prompt_sha256", "implemented_flags",
                        "feature_test_command", "test_bundle_fingerprint"):
                self.assertIn(key, checkpoint)

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
        view = analyze_lineages.materialize_view(
            Path(self.temp.name) / "view",
            analyze_lineages.population_members(
                [json.loads((self.root / f"lineage-{n:03d}" / "lineage.json")
                            .read_text(encoding="utf-8")) for n in (1, 2, 3)],
                None,
            ),
            json.loads((self.root / "lineages.json").read_text(encoding="utf-8")),
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
        members = analyze_lineages.population_members(
            [json.loads((self.root / f"lineage-{n:03d}" / "lineage.json")
                        .read_text(encoding="utf-8")) for n in (1, 2)],
            None,
        )
        attempt = Path(members[0][1]["attempt_dir"])
        (attempt / "diff-numstat.txt").write_text("9\t9\tnew_demo.c\n",
                                                  encoding="utf-8")
        view = analyze_lineages.materialize_view(
            Path(self.temp.name) / "view2", members,
            json.loads((self.root / "lineages.json").read_text(encoding="utf-8")),
            "final",
        )
        self.assertFalse((view / "attempt-001" / "diff-numstat.txt").exists())


class ChangeBaselineTests(unittest.TestCase):
    """Audit 5 C and D: each change measure uses its own correct baseline."""

    def setUp(self):
        import tempfile

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = make_lineage_root(
            Path(self.temp.name) / "lineages", [None, None, 2]
        )
        self.lineages = [
            json.loads((self.root / f"lineage-{n:03d}" / "lineage.json")
                       .read_text(encoding="utf-8"))
            for n in (1, 2, 3)
        ]
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
        """A case may only name a later flag when it exists to assert that the
        flag is still rejected."""
        for utility, checkpoint_id, implemented in ALL_UTILITY_CHECKPOINTS:
            flags = set(self.future_flags(utility, checkpoint_id))
            if not flags:
                continue
            bundle = shared_bundle(utility, checkpoint_id)
            with self.subTest(utility=utility, checkpoint=checkpoint_id):
                for case in StageBundleLeakageTests.bundled_cases(self, bundle):
                    named = flags & set(case.get("args", []))
                    permitted = set(case.get("absent_flags", []))
                    self.assertLessEqual(
                        named, permitted,
                        f"{case.get('name')} invokes {sorted(named - permitted)} "
                        "without declaring it absent",
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
    """Audit 4: the ladder is tested from above as well as from below."""

    def test_selectable_honors_absent_flags(self):
        case = {"flags": [], "absent_flags": ["-H"]}
        self.assertTrue(stage_test_bundle.selectable(case, set()))
        self.assertTrue(stage_test_bundle.selectable(case, {"-r"}))
        self.assertFalse(stage_test_bundle.selectable(case, {"-H"}))

    def test_absent_and_required_flags_compose(self):
        case = {"flags": ["-H"], "absent_flags": ["-i"]}
        self.assertFalse(stage_test_bundle.selectable(case, set()))
        self.assertTrue(stage_test_bundle.selectable(case, {"-H"}))
        self.assertFalse(stage_test_bundle.selectable(case, {"-H", "-i"}))

    def test_premature_cases_live_exactly_until_their_flag_arrives(self):
        for utility in ("grep", "chmod"):
            ladder = EXPECTED_SEQUENCES[utility]
            checkpoints = [(c, f) for u, c, f in ALL_UTILITY_CHECKPOINTS
                           if u == utility]
            for checkpoint_id, implemented in checkpoints:
                bundle = shared_bundle(utility, checkpoint_id)
                cases = StageBundleLeakageTests.bundled_cases(self, bundle)
                present = {
                    tuple(sorted(c["absent_flags"])): c["name"]
                    for c in cases if c.get("absent_flags")
                }
                for flag in ladder:
                    with self.subTest(utility=utility, checkpoint=checkpoint_id,
                                      flag=flag):
                        expected = flag not in set(implemented)
                        self.assertEqual(
                            (flag,) in present, expected,
                            f"rejection case for {flag} should "
                            f"{'exist' if expected else 'be gone'} at "
                            f"{checkpoint_id}",
                        )

    def test_model_backed_suites_reject_every_ladder_flag_at_000(self):
        """grep and chmod assert each of their flags is unknown at 000."""
        for utility in ("grep", "chmod"):
            bundle = shared_bundle(utility, "000")
            cases = StageBundleLeakageTests.bundled_cases(self, bundle)
            declared = {
                flag for case in cases for flag in case.get("absent_flags", [])
            }
            with self.subTest(utility=utility):
                self.assertEqual(declared, set(EXPECTED_SEQUENCES[utility]))
                for case in cases:
                    if case.get("absent_flags"):
                        self.assertNotEqual(
                            case["exit_code"], 0,
                            "a case asserting a flag is absent must reject",
                        )

    def test_oracle_backed_suites_have_no_rejection_cases_and_that_is_recorded(self):
        """sort and mkdir freeze goldens by running a real GNU binary, which
        supports -r and -p, so it cannot produce a "must be rejected" golden for
        a flag it implements. This is the documented Audit 4 gap: assert the
        state matches the documentation rather than letting it drift silently.
        """
        for utility in ("sort", "mkdir"):
            bundle = shared_bundle(utility, "000")
            cases = StageBundleLeakageTests.bundled_cases(self, bundle)
            with self.subTest(utility=utility):
                self.assertEqual(
                    [c["name"] for c in cases if c.get("absent_flags")], [],
                )
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Coverage and its limits", readme)


class LineageControllerInvocationTests(unittest.TestCase):
    """Audit 1, read off the controller's own resolved commands."""

    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash:
            raise unittest.SkipTest("bash is required to run the controller")

    def dry_run(self, utility: str, output_dir: Path) -> list[str]:
        result = subprocess.run(
            [self.bash, str(REPO_ROOT / "scripts" / "run_lineage_experiment.sh"),
             "--utility", utility, "--model", "demo/m", "--temperature", "0.2",
             "--lineages", "2", "--output-dir", str(output_dir), "--dry-run"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
            env={**os.environ, "PYTHON_BIN": sys.executable},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line for line in result.stdout.splitlines()
                if "run_experiment.sh" in line]

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


if __name__ == "__main__":
    unittest.main()
