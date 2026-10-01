"""Infrastructure regressions only: no Rust utility implementations."""
from __future__ import annotations

import base64
import gzip
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO))
import capture_candidate
import checkpoint_boundary_gate as gate
import lineage_plan
import stage_test_bundle
from reference_generators import heldout_contract, transfer_oracle
from reference_generators.transfer_cases import definitions, heldout, file, link


def manifest(utility):
    return json.loads((REPO / f"experiments/utilities/{utility}.json").read_text())


def corpus(utility, hidden=False):
    name = "heldout/heldout_cases.json.gz" if hidden else "suites/cases.json.gz"
    return json.loads(gzip.decompress((REPO / f"tests/{utility}-test-suite" / name).read_bytes()))["cases"]


class HiddenDualTests(unittest.TestCase):
    def test_long_options_preserved_in_duals(self):
        for utility in ("cp", "mv"):
            visible = definitions(utility)
            hidden = heldout(visible)
            self.assertEqual(hidden, heldout(visible))
            for original, dual in zip(visible, hidden):
                options = [arg for arg in original["args"]
                           if arg in ("--interactive", "--force", "--recursive")]
                for option in options:
                    self.assertEqual(dual["args"].count(option), original["args"].count(option))
                if options:
                    self.assertNotEqual(dual["fixture"], original["fixture"])
            self.assertTrue(any("--interactive" in case["args"] for case in hidden))

    def test_bare_dash_remains_a_literal_filename(self):
        for utility in ("cp", "mv"):
            visible = definitions(utility)
            original = next(c for c in visible if c["name"] == "bare-dash")
            dual = next(c for c in heldout(visible) if c["dual_of"] == "bare-dash")
            self.assertEqual(dual["args"][0], "-")
            source = next(f for f in dual["fixture"] if f["path"] == "-")
            self.assertNotEqual(source["contents_b64"], original["fixture"][0]["contents_b64"])
            self.assertNotEqual(dual["args"][1], original["args"][1])
            self.assertNotIn("--", dual["args"])

    def test_affirmative_duals_keep_distinct_response_shapes(self):
        for utility in ("cp", "mv"):
            duals = {c["dual_of"]: c for c in heldout(definitions(utility))}
            answers = {name: base64.b64decode(duals[name]["stdin_b64"])
                       for name in ("ask-yes", "ask-prefix", "ask-long")}
            self.assertEqual(answers["ask-yes"], b"YES\n")
            self.assertRegex(answers["ask-prefix"], rb"^yprivate-answer-[0-9]+\n$")
            self.assertEqual(answers["ask-long"], b"Y\n")
            self.assertEqual(len(set(answers.values())), 3)
            self.assertIn("--interactive", duals["ask-long"]["args"])

    def test_isolation_exempts_only_declared_option_tokens(self):
        option = "--interactive"
        def scan(**fields):
            return heldout_contract.scannable_values(
                {"name": "heldout-example", **fields}, public_options=frozenset({option}))
        self.assertNotIn(option, scan(args=[option, "src", "dst"]))
        self.assertIn(option, scan(args=["--", option]))
        self.assertIn("--unknown-private", scan(args=["--unknown-private"]))
        self.assertIn(option, scan(fixture=[{"path": option}]))
        self.assertIn(option, scan(stdout_b64=base64.b64encode(option.encode()).decode()))
        self.assertIn(option, heldout_contract.scannable_values(
            {"name": "heldout-example", "args": [option]}))


class PlanningTests(unittest.TestCase):
    def test_rust_plans(self):
        for utility, count in (("cp", 4), ("mv", 3)):
            with self.subTest(utility=utility):
                plan = lineage_plan.resolve_plan(REPO, utility, "", "0", None, 0, 0)
                self.assertEqual([c["id"] for c in plan["checkpoints"]], [f"{i:03d}" for i in range(count)])
                self.assertEqual(plan["source_path"], f"src/new_{utility}/new_{utility}.rs")
                self.assertFalse((REPO / plan["source_path"]).exists())
                self.assertEqual(plan["source_basename"], f"new_{utility}.rs")
                self.assertEqual(plan["build_command"], manifest(utility)["build_command"])
                self.assertIn("rustc --edition=2021 -C opt-level=2 -D warnings", plan["build_command"])
                self.assertEqual(plan["functional_oracle"]["project"], "GNU Coreutils")
                self.assertEqual(plan["historical_vulnerability_source"]["project"], "uutils/coreutils")
                previous = set()
                for index, c in enumerate(plan["checkpoints"]):
                    self.assertEqual(c["source_mode"], "existing" if index else "new")
                    self.assertLessEqual(previous, set(c["implemented_flags"]))
                    previous = set(c["implemented_flags"])
                    expected = f"tests/{utility}-test-suite/judge_candidate.sh build/new_{utility}"
                    if previous:
                        expected += " " + " ".join(c["implemented_flags"])
                    self.assertEqual(c["feature_test_command"], expected)

    def test_c_plans_and_all_bundles_unchanged(self):
        for utility in ("grep", "mkdir", "sort", "chmod"):
            with self.subTest(utility=utility):
                plan = lineage_plan.resolve_plan(REPO, utility, "", "0", None, 0, 0)
                self.assertTrue(plan["source_path"].endswith(".c"))
                self.assertEqual(plan["build_command"], manifest(utility)["build_command"])
                for checkpoint in plan["checkpoints"]:
                    payload = stage_test_bundle.build_payload(REPO, plan["test_dir"], checkpoint, utility)
                    self.assertGreater(payload["manifest"]["cases_included"], 0)

    def test_prompt_anchors_and_scope(self):
        for utility, anchor in (("cp", "copy_path"), ("mv", "move_path")):
            m = manifest(utility)
            for index, c in enumerate(m["checkpoints"]):
                with self.subTest(utility=utility, checkpoint=c["id"]):
                    text = (REPO / c["prompt"]).read_text()
                    self.assertIn(anchor, text)
                    self.assertIn("from `main` through", text)
                    self.assertIn("standard library only", text)
                    self.assertIn("never repair", text)
                    if index == 0:
                        self.assertIn("There is intentionally no starter implementation.", text)
                        self.assertIn("Create exactly:", text)
                        self.assertIn("Create the parent directory if necessary.", text)
                    else:
                        self.assertIn("Modify:", text)
                        self.assertIn("do not rename or remove it", text)
                    for flag in set(m["checkpoints"][-1]["implemented_flags"]) - set(c["implemented_flags"]):
                        for option in [flag, *m["flag_aliases"][flag]]:
                            self.assertIsNone(re.search(r"(?<![\w-])" + re.escape(option) + r"(?![\w-])", text))

    def test_no_alternative_starters(self):
        for utility in ("cp", "mv"):
            self.assertFalse((REPO / "src" / f"new_{utility}").exists())
            # Controller test data and historical GNU C sources are not generated
            # Rust candidates. No new Rust candidate file may exist anywhere tracked.
            tracked = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO).decode().splitlines()
            self.assertFalse(any(Path(p).name == f"new_{utility}.rs" for p in tracked))


class BundleTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix" and os.environ.get("CP_ORACLE_BIN") and os.environ.get("MV_ORACLE_BIN"), "verified oracle environment required")
    def test_staged_judges_and_controller_heldout_wrapper(self):
        for utility in ("cp", "mv"):
            binary, _ = transfer_oracle.oracle(utility)
            m = manifest(utility)
            with tempfile.TemporaryDirectory() as temp:
                work = Path(temp)
                for checkpoint in m["checkpoints"]:
                    suite = work / m["test_dir"]
                    payload = stage_test_bundle.build_payload(REPO, m["test_dir"], checkpoint, utility)
                    stage_test_bundle.write_bundle(payload, suite)
                    before = (suite / "config.json").read_bytes()
                    visible = subprocess.run([str(suite / "judge_candidate.sh"), binary, *checkpoint["implemented_flags"]], cwd=work, capture_output=True)
                    self.assertEqual(visible.returncode, 0, visible.stdout + visible.stderr)
                    self.assertEqual(before, (suite / "config.json").read_bytes())
                    hidden = subprocess.run([sys.executable, str(REPO / "scripts/heldout_judge.py"),
                                             "--utility", utility, "--test-dir", m["test_dir"],
                                             "--candidate", binary, "--workdir", str(work)], cwd=work, capture_output=True)
                    self.assertEqual(hidden.returncode, 0, hidden.stdout + hidden.stderr)
                    self.assertFalse((suite / "heldout").exists())
                    for path in suite.rglob("*"):
                        if path.is_file():
                            self.assertNotIn(binary.encode(), path.read_bytes())

    def test_every_checkpoint_hides_future_and_controller_data(self):
        for utility in ("cp", "mv"):
            m = manifest(utility)
            all_flags = set(m["checkpoints"][-1]["implemented_flags"])
            last = set()
            for c in m["checkpoints"]:
                with self.subTest(utility=utility, checkpoint=c["id"]):
                    payload = stage_test_bundle.build_payload(REPO, m["test_dir"], c, utility)
                    content = b"\n".join(payload["files"].values()) + json.dumps(payload["manifest"]).encode()
                    for flag in all_flags - set(c["implemented_flags"]):
                        for option in [flag, *m["flag_aliases"][flag]]:
                            self.assertIsNone(re.search(rb"(?<![\w-])" + re.escape(option.encode()) + rb"(?![\w-])", content))
                    for token in (b"heldout-", b"private-", b"ORACLE_BIN", b"uutils", b"oracle_bin"):
                        self.assertNotIn(token, content)
                    for name in payload["files"]:
                        self.assertFalse(name.startswith(("heldout/", "gen/")))
                    included = json.loads(payload["files"]["suites/cases.json.gz"])["cases"]
                    names = {case["name"] for case in included}
                    self.assertLessEqual(last, names)
                    last = names
                    self.assertEqual(len(included), sum(set(x["flags"]) <= set(c["implemented_flags"]) for x in corpus(utility)))

    def test_boundary_contracts_and_aliases(self):
        for utility in ("cp", "mv"):
            rows = gate.availability(manifest(utility))
            self.assertTrue(rows[0]["forbidden_options"])
            self.assertEqual(rows[-1]["forbidden_options"], [])
            with tempfile.TemporaryDirectory() as temp:
                plan = gate.PROBES[utility]["build"]("--force", "-f", Path(temp))
                self.assertEqual(plan["argv"], ["--force", "input", "output"])
                self.assertTrue((Path(temp) / "input").is_file())

    def test_corpus_schema_hashes_and_duals(self):
        for utility in ("cp", "mv"):
            transfer_oracle.audit(REPO / f"tests/{utility}-test-suite", utility)
            public = corpus(utility)
            private = corpus(utility, True)
            self.assertEqual(len(public), len(definitions(utility)))
            self.assertEqual(len(private), len(heldout(definitions(utility))))
            self.assertEqual({c["dual_of"] for c in private}, {c["name"] for c in public})

    def test_oracle_behavior_matches_pinned_contract(self):
        for utility in ("cp", "mv"):
            cases = {c["name"]: c for c in corpus(utility)}
            for name in ("empty", "text", "binary", "large", "overwrite"):
                self.assertEqual(cases[name]["exit_code"], 0, (utility, name))
            for name in ("ask-no", "ask-eof", "ask-space", "ask-blank"):
                self.assertEqual(cases[name]["exit_code"], 1, (utility, name))
            self.assertEqual(cases["partial"]["exit_code"], 1)
            self.assertEqual(cases["unknown"]["exit_code"], 1)
            self.assertEqual(cases["ask-new"]["stderr_class"], "empty")
            self.assertEqual(cases["order-fi"]["stderr_class"], "nonempty")
            self.assertEqual(cases["order-if"]["stderr_class"], "nonempty" if utility == "cp" else "empty")
            self.assertEqual(cases["ask-no"]["expected_tree"]["dst"]["sha256"], cases["ask-space"]["expected_tree"]["dst"]["sha256"])


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.engine = transfer_oracle.load_engine(REPO / "tests/cp-test-suite")

    def test_rejects_unsafe_paths_before_materialization(self):
        for name in ("/outside", "../outside", "a/../../outside", "C:/outside", "\\\\host\\share", "a\0b"):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                with self.assertRaises(self.engine.SandboxEscapeError):
                    self.engine.materialize_fixture([file("first"), file(name)], root)
                self.assertEqual(list(root.iterdir()), [])

    def test_dash_operands_are_not_exempt_from_path_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            for args in (["--", "/outside"], ["-dir/../../outside"], ["--", "../outside"]):
                with self.assertRaises(self.engine.SandboxEscapeError):
                    self.engine.validate_case({"args": args}, Path(temp).resolve())

    def test_rejects_link_escape_and_link_ancestors_in_either_order(self):
        fixtures = [[link("alias", "/outside")], [link("alias", "../outside")],
                    [link("a", "."), file("a/b")], [file("a/b"), link("a", ".")]]
        for fixture in fixtures:
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(self.engine.SandboxEscapeError):
                    self.engine.materialize_fixture(fixture, Path(temp).resolve())

    @unittest.skipUnless(os.name == "posix", "POSIX symlinks and modes")
    def test_resolved_escape_and_deterministic_semantic_snapshot(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp).resolve()
            (root / "escape").symlink_to(outside)
            with self.assertRaises(self.engine.SandboxEscapeError):
                self.engine.safe_path(root, "escape/file")
            (root / "escape").unlink()
            self.engine.materialize_fixture([file("z", b"\0\xff"), file("a", b""), link("cycle", ".")], root)
            first = self.engine.snapshot_tree(root)
            second = self.engine.snapshot_tree(root)
            self.assertEqual(first, second)
            self.assertEqual(list(first), sorted(first))
            self.assertEqual(first["cycle"], {"type": "symlink", "target": "."})
            self.assertNotIn("inode", json.dumps(first))

    def test_oracle_selection_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "CP_ORACLE_BIN"):
                transfer_oracle.oracle("cp")
        with tempfile.TemporaryDirectory() as temp:
            wrong = Path(temp) / "cp"
            wrong.write_text("not executable")
            with patch.dict(os.environ, {"CP_ORACLE_BIN": str(wrong)}):
                with self.assertRaises(ValueError):
                    transfer_oracle.oracle("cp")


class CaptureAndAnalysisTests(unittest.TestCase):
    def test_capture_keeps_rust_and_c_and_preserves_lineage_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for extension in ("rs", "c"):
                work = root / extension / "work"
                work.mkdir(parents=True)
                source = work / f"specimen.{extension}"
                source.write_text("// opaque capture marker\n")
                first = root / extension / "first"
                capture_candidate.capture(work, first, None, [f"*.{extension}"], [])
                inherited = first / "candidate" / source.name
                baseline = root / extension / "baseline"
                baseline.mkdir()
                shutil.copy2(inherited, baseline / source.name)
                source.write_text(inherited.read_text() + "// second checkpoint marker\n")
                second = root / extension / "second"
                capture_candidate.capture(work, second, baseline, [f"*.{extension}"], [])
                self.assertEqual((baseline / source.name).read_text(), "// opaque capture marker\n")
                self.assertIn("second checkpoint", (second / "candidate" / source.name).read_text())
                self.assertIn("1\t0", (second / "diff-numstat.txt").read_text())

    def test_c_callgraph_refuses_rust(self):
        from security.common.callgraph import analyze_sources
        with self.assertRaisesRegex(ValueError, "Rust"):
            analyze_sources([("specimen.rs", b"// opaque marker")])
        result = analyze_sources([("empty.c", b"/* empty C translation unit */")], force_fallback=True)
        self.assertEqual(result["function_reachability"], [])

    def test_structural_analyzer_refuses_rust(self):
        import analyze_experiment
        with self.assertRaisesRegex(ValueError, "Rust"):
            analyze_experiment.analyze_source(Path("absent.rs"), None, [])
        with self.assertRaisesRegex(ValueError, "Rust"):
            analyze_experiment.parse_tree_sitter(Path("absent.rs"))
        with self.assertRaisesRegex(ValueError, "Rust"):
            analyze_experiment.parse_clang_ast(Path("absent.rs"), None, [])
        with self.assertRaisesRegex(ValueError, "Rust"):
            analyze_experiment.run_gumtree(Path("baseline.c"), Path("absent.rs"), None, None, None)

    def test_rust_security_descriptors_refused(self):
        from analysis.security_diagnostics import measure_security_candidate
        with self.assertRaisesRegex(ValueError, "Rust"):
            measure_security_candidate(run_id="test", source=Path("absent.rs"),
                                       source_identifier="absent.rs", configuration={}, provenance={})

    def test_lineage_analyzer_refuses_rust(self):
        import analyze_lineages
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "lineages.json").write_text(json.dumps({"source_path": "specimen.rs"}))
            (root / "lineage-001").mkdir()
            with self.assertRaisesRegex(analyze_lineages.LineageError, "Rust"):
                analyze_lineages.main(["--lineage-root", str(root)])

    def test_security_reports_unsupported_without_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "specimen.rs"
            source.write_text("// opaque marker, not an implementation\n")
            output = root / "result.json"
            result = subprocess.run([sys.executable, str(REPO / "security/run_security_evaluator.py"),
                                     "--utility", "cp", "--source", str(source), "--output", str(output)], capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            data = json.loads(output.read_text())
            self.assertFalse(data["security_evaluation_completed"])
            self.assertIsNone(data["security_clean"])
            self.assertIn("Rust", data["unsupported_reason"])

    @unittest.skipUnless(os.name == "posix", "bash controller integration")
    def test_actual_stage_controller_absence_capture_and_inheritance(self):
        # Fake agent writes comments only. It tests controller transport, not a
        # utility implementation or model quality, and makes no model requests.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            agent = root / "fake-agent"
            agent.write_text('''#!/usr/bin/env python3
import pathlib, sys
if "--version" in sys.argv:
    print("controller-test-agent")
    raise SystemExit(0)
source = pathlib.Path(sys.argv[sys.argv.index("--file") + 1])
prompt = pathlib.Path(sys.argv[sys.argv.index("--message-file") + 1]).read_text()
if "INHERIT_MARKER" in prompt:
    assert source.read_text() == "// lineage A\\n"
    source.write_text("// lineage A\\n// stage two\\n")
else:
    assert not source.exists(), "controller created a placeholder"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("// lineage A\\n")
''')
            agent.chmod(0o755)
            prompt = root / "prompt.md"
            env = dict(os.environ, AIDER_BIN=str(agent), PYTHON_BIN=sys.executable)
            source = "src/specimen/specimen.rs"
            def stage(name, seed=None):
                prompt.write_text("INHERIT_MARKER" if seed else "CREATE_MARKER")
                command = ["bash", str(REPO / "scripts/run_experiment.sh"), "--model", "test-model",
                           "--temperature", "0", "--runs", "1", "--max-loops", "0", "--timeout", "30",
                           "--prompt", str(prompt), "--source", source,
                           "--source-mode", "existing" if seed else "new", "--build-cmd", "true",
                           "--feature-test-cmd", "true", "--output-dir", str(root / name), "--no-analysis"]
                if seed:
                    command += ["--seed-file", f"{seed}:{source}"]
                result = subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout[-2500:] + result.stderr[-2500:])
                captured = list((root / name).glob("temp-*/attempt-*/candidate/" + Path(source).name))
                self.assertEqual(len(captured), 1)
                metadata = json.loads((captured[0].parents[1] / "metadata.json").read_text())
                self.assertTrue(metadata["public_validation_success"])
                return captured[0]
            first = stage("lineage-a-stage-zero")
            second = stage("lineage-a-stage-one", first)
            independent = stage("lineage-b-stage-zero")
            self.assertEqual(first.read_text(), independent.read_text())
            self.assertNotEqual(second.read_text(), independent.read_text())
            source = "src/specimen/specimen.c"
            first_c = stage("c-stage-zero")
            second_c = stage("c-stage-one", first_c)
            self.assertNotEqual(first_c.read_text(), second_c.read_text())


if __name__ == "__main__":
    unittest.main()
