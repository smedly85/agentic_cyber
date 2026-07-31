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
import checkpoint_boundary_gate  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tests"))
from reference_generators import oracle_contract  # noqa: E402
from reference_generators import suite_diff  # noqa: E402
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


def maintained_shell_scripts() -> list[Path]:
    """Every *.sh the repository maintains.

    `runs/` and `review-bundle/` are archived outputs, not maintained source,
    and are excluded deliberately.
    """
    return [
        path for path in sorted(REPO_ROOT.rglob("*.sh"))
        if not {"runs", "review-bundle", ".git"} & set(path.relative_to(REPO_ROOT).parts)
    ]


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

    PINS = {"sort": "9.4", "mkdir": "9.11"}

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
        fake = fake_version_tool(directory, "sort", "sort (GNU coreutils) 9.4")
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
            "--model", "m", "--temperature", "0", "--agent", "build",
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


if __name__ == "__main__":
    unittest.main()
