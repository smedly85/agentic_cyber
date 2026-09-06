from __future__ import annotations

import importlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / "tests" / "sort-test-suite"
UNIQUE_PROMPT = REPO / "prompts" / "new_sort" / "003_unique.md"


class SortDarwinContractTests(unittest.TestCase):
    def test_target_contract_is_darwin_coreutils_9_11(self) -> None:
        config = json.loads((SUITE / "config.json").read_text(encoding="utf-8"))

        self.assertEqual(config["required_platform"], "Darwin")
        self.assertEqual(config["oracle_version_required"], "9.11")
        self.assertEqual(config["paths"]["oracle_bin"], "")

    def test_darwin_generator_omits_only_devfull_fault(self) -> None:
        sys.path.insert(0, str(SUITE))
        try:
            curated_cases = importlib.import_module("gen.curated_cases")
        finally:
            sys.path.pop(0)

        self.assertEqual(
            curated_cases.platform_exclusions("Darwin"),
            {"fault-devfull": "Linux-only /dev/full ENOSPC device"},
        )
        self.assertEqual(curated_cases.platform_exclusions("Linux"), {})

        corpus = {"generic": b"pear\napple\n"}
        darwin_names = {
            case["name"] for case in curated_cases.build_faults(corpus, "Darwin")
        }
        linux_names = {
            case["name"] for case in curated_cases.build_faults(corpus, "Linux")
        }
        self.assertNotIn("fault-devfull", darwin_names)
        self.assertEqual(linux_names - darwin_names, {"fault-devfull"})

    @unittest.skipIf(platform.system() in {"Darwin", "Windows"},
                     "exercises the Linux platform-mismatch contract")
    def test_linux_candidate_judging_is_platform_incompatible(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "runner.py",
                "suites/singles.json.gz",
                "--config",
                "config.json",
                "--all-flags",
                "--",
                sys.executable,
            ],
            cwd=SUITE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 3)
        self.assertIn("PLATFORM INCOMPATIBLE", completed.stderr)
        self.assertIn("requires Darwin", completed.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_oracle_contract_refuses_bsd_and_wrong_gnu_version(self) -> None:
        tool = REPO / "tests" / "reference_generators" / "oracle_contract.py"
        with tempfile.TemporaryDirectory() as directory:
            for name, version_line in (
                ("bsd-sort", "sort (BSD sort) 1.0"),
                ("wrong-gnu-sort", "sort (GNU coreutils) 9.10"),
            ):
                binary = Path(directory) / name
                binary.write_text(
                    f"#!/bin/sh\nprintf '%s\\n' '{version_line}'\n",
                    encoding="utf-8",
                )
                binary.chmod(0o755)
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(tool),
                        "verify",
                        "--suite",
                        "sort",
                        "--config",
                        str(SUITE / "config.json"),
                        "--suite-root",
                        str(SUITE),
                        "--oracle-bin",
                        str(binary),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 2, completed.stderr)


class SortUniquePromptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt = UNIQUE_PROMPT.read_text(encoding="utf-8")

    def test_secondary_order_does_not_select_unique_representative(self) -> None:
        self.assertNotIn(
            "choose one representative using the normal deterministic secondary order",
            self.prompt,
        )
        self.assertIn("Without `-u`, ordinary `-f` ordering", self.prompt)
        self.assertIn("With both `-f` and `-u`", self.prompt)
        self.assertIn(
            "The original-byte secondary comparison\n"
            "must not distinguish members of that group or choose the retained member.",
            self.prompt,
        )

    def test_case_insensitive_unique_keeps_first_input_record(self) -> None:
        self.assertIn(
            "For input order `abc` then `ABC`, retain `abc`.", self.prompt
        )
        self.assertIn(
            "For input order `ABC` then `abc`, retain `ABC`.", self.prompt
        )

    def test_reverse_does_not_change_unique_representative(self) -> None:
        self.assertIn(
            "Reverse affects the ordering of the surviving groups, not\n"
            "which representative survives. Thus `-r` does not change the retained\n"
            "representative.",
            self.prompt,
        )


if __name__ == "__main__":
    unittest.main()
