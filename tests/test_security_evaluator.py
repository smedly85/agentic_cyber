from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.analysis.security_results import (
    aggregate_security_results,
    load_security_result,
)
from security.common import evaluator


REPO = Path(__file__).resolve().parents[1]


def minimal_call_graph():
    main = {
        "function": "main", "function_id": "main", "source_file": "candidate.c",
        "start_line": 1, "end_line": 1, "lines_of_code": 1,
        "ast_node_count": None, "call_depth": 0, "reachable_from_entry": True,
        "diversification_eligible": False, "callers": [], "callees": [],
        "direct_callers": [], "direct_callees": [], "callback_callers": [],
        "callback_callees": [], "outgoing_call_edges": [],
        "analysis_method": "regex_fallback", "diversification_rank": None,
    }
    return {
        "analysis_method": "regex_fallback", "entry_points": ["main"],
        "resolved_entry_points": ["main"], "function_reachability": [main],
        "reachable_function_count": 1,
        "diversification_eligible_function_count": 0,
        "unreachable_function_count": 0, "max_reachable_call_depth": 0,
        "functions_by_call_depth": {"0": ["main"]},
        "call_depth_ranking": ["main"], "structural_exposure_ranking": [],
        "security_sensitive_calls": [], "unresolved_direct_calls": [],
        "unresolved_callback_targets": [],
    }


class DynamicSecurityEvaluatorTests(unittest.TestCase):
    def _evaluate_with_execution(
        self, root: Path, *, stderr: bytes = b"", return_code: int = 0,
        timed_out: bool = False, resource_reason: str | None = None,
    ):
        source = root / "candidate.c"
        source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        output = root / "security_results.json"
        artifacts = root / "artifacts"
        scenario = {
            "id": "regression", "args": [], "stdin_b64": "",
            "fixture": [], "allowed_mutation_prefixes": [],
        }
        with (
            mock.patch.object(evaluator, "analyze_source_file", return_value=minimal_call_graph()),
            mock.patch.object(evaluator.shutil, "which", return_value="/usr/bin/cc"),
            mock.patch.object(
                evaluator.subprocess,
                "run",
                return_value=SimpleNamespace(stdout="cc regression version\n"),
            ),
            mock.patch.object(
                evaluator, "compile_candidate", return_value={"ok": True, "error": None}
            ),
            mock.patch.object(evaluator, "base_scenarios", return_value=[scenario]),
            mock.patch.object(
                evaluator, "_run_bounded",
                return_value=(return_code, b"stdout", stderr, timed_out, resource_reason, 4096),
            ),
        ):
            result = evaluator.evaluate(
                utility="sort", source=source, output=output, artifacts=artifacts,
                seed=11, fuzz_seconds=1.0, max_inputs=1, timeout=0.1,
            )
        return result, output, artifacts

    def test_security_findings_cannot_change_overall_success(self):
        script = (REPO / "scripts" / "run_experiment.sh").read_text(encoding="utf-8")
        outcome = script.index("        overall_success=true")
        security = script.index("        # The functional outcome above is final.")
        capture = script.index("        # Flatten the sources", security)
        self.assertLess(outcome, security)
        self.assertNotIn("overall_success=", script[security:capture])
        self.assertIn('if [[ "$overall_success" == true && -n "$SECURITY_CMD" ]]', script)

    def test_security_cannot_trigger_repair_or_control_lineage_promotion(self):
        runner = (REPO / "scripts" / "run_experiment.sh").read_text(encoding="utf-8")
        loop_end = runner.index("        # ---- end loop")
        security = runner.index("        # The functional outcome above is final.")
        capture = runner.index("        # Flatten the sources", security)
        self.assertLess(loop_end, security)
        self.assertNotIn("REPAIR_TOOL", runner[security:capture])
        self.assertNotIn("current_prompt=", runner[security:capture])

        lineage = (REPO / "scripts" / "run_lineage_experiment.sh").read_text(encoding="utf-8")
        success_line = "success = attempt_complete and public_success and candidate_sha is not None"
        self.assertIn(success_line, lineage)
        self.assertIn('json.loads(sys.argv[1])["success"]', lineage)
        self.assertLess(lineage.index(success_line), lineage.index("security_evaluation_completed"))

    def test_infrastructure_failure_is_distinct_from_a_clean_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "candidate.c"
            source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
            with mock.patch.object(evaluator.shutil, "which", return_value=None):
                failed = evaluator.evaluate(
                    utility="sort", source=source,
                    output=root / "failed.json", artifacts=root / "failed-artifacts",
                    seed=1, fuzz_seconds=1.0, max_inputs=1, timeout=0.1,
                    compiler="definitely-not-a-compiler",
                )
            clean, _, _ = self._evaluate_with_execution(root)
        self.assertIs(failed["security_evaluation_completed"], False)
        self.assertIs(failed["security_clean"], False)
        self.assertIn("compiler_not_found", failed["infrastructure_error"])
        self.assertEqual(failed["security_evaluator_exit_code"], 2)
        self.assertIs(clean["security_evaluation_completed"], True)
        self.assertIs(clean["security_clean"], True)
        self.assertIsNone(clean["infrastructure_error"])

    def test_address_sanitizer_output_is_classified(self):
        kind, category, frame = evaluator._sanitizer_details(
            "==7==ERROR: AddressSanitizer: heap-use-after-free on address 0x1234\n"
            "#0 0x123 in vulnerable /tmp/candidate.c:17:3\n"
        )
        self.assertEqual((kind, category, frame), (
            "asan", "heap-use-after-free", "vulnerable@candidate.c"
        ))

    def test_undefined_behavior_sanitizer_output_is_classified(self):
        kind, category, frame = evaluator._sanitizer_details(
            "candidate.c:4:9: runtime error: signed integer overflow: "
            "2147483647 + 1 cannot be represented\n"
        )
        self.assertEqual(kind, "ubsan")
        self.assertIn("signed integer overflow", category)
        self.assertEqual(frame, "candidate.c:<line>")

    def test_finding_evidence_and_artifacts_are_persisted(self):
        diagnostic = (
            b"ERROR: AddressSanitizer: stack-buffer-overflow on address 0x1234\n"
            b"#0 0x123 in vulnerable /tmp/candidate.c:9:2\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            result, output, artifacts = self._evaluate_with_execution(
                Path(directory), stderr=diagnostic, return_code=1
            )
            finding = result["unique_security_findings"][0]
            artifact = artifacts / finding["artifact"]
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(finding["kind"], "asan")
            self.assertFalse(result["security_clean"])
            self.assertEqual(persisted["unique_security_findings"][0]["signature"], finding["signature"])
            self.assertTrue((artifact / "args.json").is_file())
            self.assertTrue((artifact / "stdin.bin").is_file())
            self.assertTrue((artifact / "fixture.json").is_file())
            self.assertIn("stack-buffer-overflow", (artifact / "stderr.txt").read_text())
            evidence = json.loads((artifact / "result.json").read_text())
            self.assertEqual(evidence["finding_signatures"], [finding["signature"]])

    def test_non_sanitizer_timeout_has_its_own_finding_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _, artifacts = self._evaluate_with_execution(
                Path(directory), return_code=-9, timed_out=True
            )
            finding = result["unique_security_findings"][0]
            self.assertEqual(finding["kind"], "timeout")
            self.assertEqual(finding["category"], "per-input-timeout")
            self.assertTrue((artifacts / finding["artifact"] / "result.json").is_file())

    def test_missing_security_result_is_unevaluated_not_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = load_security_result(Path(directory) / "missing.json")
        self.assertIs(loaded["security_results_available"], False)
        self.assertIs(loaded["security_evaluation_completed"], False)
        self.assertIsNone(loaded["security_clean"])
        self.assertEqual(loaded["security_finding_count"], 0)

    def test_aggregation_keeps_missing_results_out_of_clean_denominator(self):
        rows = [
            {
                "security_evaluation_completed": True,
                "security_clean": True,
                "security_finding_count": 0,
                "unique_security_findings": [],
                "unique_crash_signatures": [],
            },
            {
                "security_evaluation_completed": False,
                "security_clean": None,
                "security_finding_count": 0,
                "unique_security_findings": [],
                "unique_crash_signatures": [],
            },
        ]
        summary = aggregate_security_results(rows)
        self.assertEqual(summary["security_candidate_count"], 2)
        self.assertEqual(summary["security_evaluated_count"], 1)
        self.assertEqual(summary["security_unevaluated_count"], 1)
        self.assertEqual(summary["security_clean_count"], 1)
        self.assertIn("not_evaluated", summary["missing_results_semantics"])


if __name__ == "__main__":
    unittest.main()
