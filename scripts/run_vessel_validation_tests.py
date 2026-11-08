#!/usr/bin/env python3
"""Run required validation suites; missing, empty, skipped or failed checks fail.

Runtime suites invoke the existing isolated Docker adapter. Integrity and
workflow suites are host-safe. This runner never builds images or approves runs.
"""
import argparse
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODULE = "scripts.validation."
SUITES = {
    "runtime": (MODULE + "test_runtime",),
    "c-runtime": (MODULE + "test_runtime.CompilerFailureClassification",
                  MODULE + "test_runtime.DockerIntegration"),
    "cross-runtime": (MODULE + "test_runtime.CrossLanguageDocker",),
    "jailed": (
        MODULE + "test_runtime.DockerIntegration.test_nonroot_chroot_and_no_controller_assets",
        MODULE + "test_runtime.CrossLanguageDocker.test_real_rust_and_python_runtime_isolation_and_io",
    ),
    "integrity": (MODULE + "test_integrity",),
    "workflow": (MODULE + "test_workflow",),
}


def run_suites(names, stream=None):
    if sys.flags.optimize or os.environ.get("PYTHONOPTIMIZE", "0") not in ("", "0"):
        raise ValueError("Python assertion checks must be enabled for validation")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in names:
        selected = loader.loadTestsFromNames(SUITES[name])
        if loader.errors or not selected.countTestCases():
            raise ValueError("missing or empty required validation suite: " + name)
        suite.addTests(selected)
    expected = suite.countTestCases()
    if not expected:
        raise ValueError("no validation tests selected")
    result = unittest.TextTestRunner(stream=stream, verbosity=2, failfast=True).run(suite)
    # unittest treats skipped/expected-failure tests as success. Neither can
    # supply affirmative evidence for a mandatory formal acceptance check.
    return 0 if (result.wasSuccessful() and result.testsRun == expected
                 and not result.skipped and not result.expectedFailures) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=tuple(SUITES), action="append", required=True)
    args = parser.parse_args(argv)
    try:
        return run_suites(args.suite)
    except (ImportError, ValueError, KeyError) as error:
        print("validation suite error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
