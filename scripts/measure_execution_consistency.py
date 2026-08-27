#!/usr/bin/env python3
"""Measure whether repeated candidates in one condition behave the same way.

This is an optional post-hoc diagnostic subsystem, not a primary paper-facing
research question. Correctness and completion are measured by
`scripts/analyze_experiment.py` and `scripts/analyze_lineages.py`;
implementation diversity among functionally valid outputs is measured by
`scripts/analyze_experiment.py` plus `scripts/analysis/diversity_metrics.py`,
documented in `docs/diversity_methodology.md`.

The gap
-------
Architecture and strategy diversity describe candidate *source structure*
relative to a baseline. Exact convergence describes source-byte identity: a
SHA-256 over the file. Both are static. A condition can produce ten
structurally distinct candidates that are indistinguishable when run, and it
can produce two near-identical ones that diverge on the first input neither was
shown. Nothing in the repository could tell those cases apart, because nothing
compared candidates by what they *did*.

So this rebuilds each successful candidate and re-judges it, twice: once
against the checkpoint's visible corpus, and once against the held-out corpus
the agent never had access to. The observed verdicts become a behavioral
fingerprint, and the fingerprints are summarized with the same exact-convergence
statistics `diversity_metrics` already applies to source hashes -- literally the
same function, since it is generic over hash strings. Held-out behavior is
measured separately from visible behavior precisely because agreement on cases
the agent could read is the weaker claim.

The adjusted Rand index between the behavioral partition and the
architecture/strategy family partitions is an optional diagnostic association
measure. It asks whether structural family membership predicts behavioral
identity, without entering the paper-facing diversity metrics.

What it deliberately does not do
--------------------------------
  * It does not re-judge anything into existence. Like `heldout_judge.py`, it
    hands corpora to the suite's own `runner.py` and inherits its comparison
    semantics exactly. A second comparator could disagree with the recorded
    verdict and nobody would know which was right.

  * It does not re-derive the population or the family labels. Ordinary success
    and explicit lineage population membership are read from
    `analysis/per_run_metrics.csv`; so are architecture and strategy cluster
    ids. Reimplementing selection here would let definitions drift silently.

  * It does not change any outcome. It is strictly post-hoc and read-only with
    respect to the experiment: it never re-runs the coding backend, never enters the
    repair loop, never rewrites an attempt, and never turns a pass into a fail.
    Its rebuilds happen in a temporary directory that is discarded.

A run that cannot be measured -- missing retained source, a rebuild that does
not compile, a judging pass that produced no report -- is recorded with its
reason in `summary.json` and excluded from the fingerprint population. It is
never silently dropped, because a condition whose candidates mostly fail to
rebuild has a very different meaning from one whose candidates all behave
identically, and an unqualified convergence rate cannot distinguish them.

Usage
-----
`analyze_experiment.py` must have been run on the target experiment first.

```bash
python3 scripts/measure_execution_consistency.py \
    --experiment runs/experiments/<model>/<checkpoint>/temp-<temperature> \
    --clean-output
```
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

from analysis import diversity_metrics  # noqa: E402
from analysis import execution_metrics  # noqa: E402
from reference_generators import heldout_contract  # noqa: E402

SCHEMA_VERSION = 3

# `runner.py` exits 1 whenever any case fails, which is an ordinary outcome
# here rather than an error -- a candidate that fails cases still has a
# perfectly good behavioral fingerprint. Success is therefore judged by whether
# a parseable report was produced, not by exit status.
UNMEASURED_SOURCE_MISSING = "candidate_source_missing"
UNMEASURED_REBUILD_FAILED = "rebuild_failed"
UNMEASURED_JUDGE_FAILED = "judge_failed"

# Namespaces for the combined fingerprint. Visible and held-out case names are
# drawn from different corpora and could in principle collide; prefixing keeps
# "failed visible case X" and "failed held-out case X" distinct inputs.
VISIBLE_NAMESPACE = "visible"
HELDOUT_NAMESPACE = "heldout"

# This runs unattended over a whole population, so neither subprocess may be
# unbounded: a candidate that sends the compiler into a preprocessor blowup
# would otherwise stall the entire batch with nothing to recover it. Bounding
# unattended work is the repository's existing convention -- see
# `run_experiment.sh --timeout` and `scripts/timeout.py`.
#
# The judge bound is far more generous than the build bound because one judge
# call runs an entire corpus through `runner.py`'s thread pool, where every case
# already carries its own per-case timeout. This is only the backstop for the
# pass as a whole.
BUILD_TIMEOUT_SECONDS = 300
JUDGE_TIMEOUT_SECONDS = 900

# Matches the assignment `judge_candidate.sh` uses to pin stdin-only scope, and
# deliberately not prose: sort's wrapper also *documents* `scope.stdin_only` in
# a comment, and a bare substring search would fire on any suite that merely
# mentions it.
STDIN_ONLY_INJECTION = re.compile(r"""\[['"]stdin_only['"]\]\s*=\s*True""")

FINGERPRINT_CSV_FIELDS = (
    "run_id",
    "visible_case_count",
    "visible_failure_count",
    "heldout_case_count",
    "heldout_failure_count",
    "visible_corpus_identity_sha256",
    "heldout_corpus_identity_sha256",
    "combined_corpus_identity_sha256",
    "visible_fingerprint_sha256",
    "heldout_fingerprint_sha256",
    "combined_fingerprint_sha256",
    "architecture_cluster_id",
    "strategy_cluster_id",
)


# ---------------------------------------------------------------------------
# Pure helpers -- everything derivable from recorded metadata, no IO
# ---------------------------------------------------------------------------


def utility_from_source_path(source_path: str) -> str:
    """`new_grep.c` -> `grep`, which names the suite directory and the corpus.

    `source_path` is captured flattened, so it is a bare filename. The `new_`
    prefix is the repository's convention for a candidate implementation of a
    standard utility; stripping it and the extension yields the utility whose
    `tests/<utility>-test-suite/` judges it.
    """
    stem = Path(source_path).stem
    utility = stem[len("new_"):] if stem.startswith("new_") else stem
    if not utility:
        raise ValueError(f"cannot infer a utility name from source_path {source_path!r}")
    return utility


def implemented_flags(feature_test_command: str) -> list[str]:
    """The checkpoint's cumulative flag list, out of its recorded judge call.

    The command's shape is fixed by `experiments/utilities/<utility>.json`:
    `<judge script> <candidate binary> [FLAG...]`. Everything after the binary
    token is a flag, so the checkpoint's scope is recoverable without consulting
    the manifest -- which matters, because the manifest describes the ladder
    while `experiment.json` describes the rung this experiment actually ran.
    """
    tokens = shlex.split(feature_test_command)
    if len(tokens) < 2:
        raise ValueError(
            f"feature_test_command {feature_test_command!r} names no candidate "
            "binary; expected '<script> <binary> [-flag ...]'"
        )
    return tokens[2:]


def binary_from_build_command(build_command: str) -> str:
    """The path the build writes, i.e. the argument of the compiler's `-o`.

    Taken from the recorded command rather than guessed from the utility name,
    because the command is the only thing that actually determined where the
    binary landed. The last `-o` wins: a command may chain several steps, and
    the executable is the output of the final one.
    """
    tokens = shlex.split(build_command)
    for index in range(len(tokens) - 1, 0, -1):
        if tokens[index - 1] == "-o":
            return tokens[index]
    raise ValueError(
        f"build_command {build_command!r} has no '-o <path>'; cannot tell which "
        "file it produces"
    )


def report_failures(payload: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The `(case name, verdict)` pairs from a `--json-report` payload.

    The report's `failures` entries are `[name, verdict, detail]`. `detail` is
    deliberately discarded: it carries diagnostic prose that can embed absolute
    paths, byte offsets and timings, none of which are behavior.
    """
    failures = payload.get("failures") or []
    pairs: list[tuple[str, str]] = []
    for entry in failures:
        if len(entry) < 2:
            raise ValueError(f"malformed failure entry in report: {entry!r}")
        pairs.append((str(entry[0]), str(entry[1])))
    return pairs


def report_case_count(payload: Mapping[str, Any]) -> int:
    """Total cases the runner accounted for, over every verdict including skips.

    Summing `counts` rather than counting `failures` gives the denominator the
    fingerprint's sufficiency argument rests on: if two candidates were judged
    on different numbers of cases, their failure lists are not comparable and
    the condition was not held constant.
    """
    counts = payload.get("counts") or {}
    return sum(int(value) for value in counts.values())


def report_results(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    """Complete deterministic verdict trace from the schema-v2 runner report."""
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise ValueError(
            "runner report lacks complete 'results'; failure-only reports are "
            "diagnostically readable but cannot support behavioral comparison"
        )
    results: list[dict[str, str]] = []
    for entry in raw_results:
        if not isinstance(entry, Mapping) or not entry.get("case_id") or not entry.get("verdict"):
            raise ValueError(f"malformed complete result entry: {entry!r}")
        results.append(
            {"case_id": str(entry["case_id"]), "verdict": str(entry["verdict"])}
        )
    results.sort(key=lambda entry: entry["case_id"])
    case_ids = [entry["case_id"] for entry in results]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("runner report contains duplicate case IDs")
    if len(results) != report_case_count(payload):
        raise ValueError("runner report counts do not match complete result count")
    return results


def namespaced_results(
    namespace: str, results: Sequence[Mapping[str, str]]
) -> list[dict[str, str]]:
    return [
        {"case_id": f"{namespace}::{result['case_id']}",
         "verdict": str(result["verdict"])}
        for result in results
    ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def corpus_descriptor(
    *,
    scope: str,
    corpora: Sequence[Path],
    case_results: Sequence[Mapping[str, str]],
    implemented: Sequence[str],
    scope_configuration: Mapping[str, Any],
) -> dict[str, Any]:
    descriptor = {
        "schema_version": 1,
        "scope": scope,
        "corpus_files": [
            {"name": path.name, "sha256": sha256_file(path)}
            for path in sorted(corpora, key=lambda item: item.name)
        ],
        "ordered_case_ids": [str(result["case_id"]) for result in case_results],
        "number_of_cases": len(case_results),
        "implemented_checkpoint_flags": list(implemented),
        "scope_configuration": dict(scope_configuration),
    }
    material = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    descriptor["corpus_identity_sha256"] = hashlib.sha256(
        ("agentic-cyber.behavioral-corpus.v1\n" + material).encode("utf-8")
    ).hexdigest()
    return descriptor


def output_tail(output: str | bytes | None, limit: int = 800) -> str:
    """The last of a subprocess's captured output, for a failure `detail`.

    A timed-out process reports whatever it had written before the kill, which
    may be nothing, so `None` is an ordinary case rather than an error.
    """
    if output is None:
        return ""
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    return output.strip()[-limit:]


# ---------------------------------------------------------------------------
# Reading what the rest of the pipeline already determined
# ---------------------------------------------------------------------------


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_csv(
    path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: Sequence[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fieldnames), extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def successful_population(
    metrics_csv: Path, experiment: Mapping[str, Any] | None = None
) -> list[dict[str, str]]:
    """The analyzed population and family labels, as the analyzer left them.

    Ordinary attempts use `overall_success`; lineage views use explicit
    controller membership so held-out outcomes cannot re-filter a promoted
    member. Boolean values arrive as strings through `csv.DictReader`.
    """
    if not metrics_csv.is_file():
        raise SystemExit(
            f"measure_execution_consistency: no {metrics_csv}. Run\n"
            f"    python3 scripts/analyze_experiment.py --experiment {metrics_csv.parent.parent}\n"
            "first; this measurement reads its population and family labels "
            "rather than re-deriving them."
        )
    with metrics_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if (experiment or {}).get("experiment_format") == "lineage_population_view":
        required_basis = "lineage_stage_success"
        if (experiment or {}).get("population_selection_basis") != required_basis:
            raise SystemExit(
                "measure_execution_consistency: malformed lineage_population_view: "
                "experiment.json must record "
                "population_selection_basis=lineage_stage_success"
            )
        required_columns = {
            "analysis_population_member", "population_selection_basis"
        }
        missing_columns = sorted(required_columns - set(reader.fieldnames or ()))
        if missing_columns:
            raise SystemExit(
                "measure_execution_consistency: malformed lineage_population_view: "
                "per_run_metrics.csv is missing explicit population metadata: "
                + ", ".join(missing_columns)
            )
        invalid_rows = [
            row.get("run_id", "<unknown>")
            for row in rows
            if row.get("analysis_population_member") not in {"True", "False"}
            or row.get("population_selection_basis") != required_basis
        ]
        if invalid_rows:
            raise SystemExit(
                "measure_execution_consistency: malformed lineage_population_view: "
                "invalid explicit population metadata for run(s): "
                + ", ".join(invalid_rows)
            )
        return [
            row for row in rows
            if row.get("analysis_population_member") == "True"
        ]
    return [row for row in rows if row.get("overall_success") == "True"]


def cluster_label(row: Mapping[str, str], column: str) -> str | None:
    value = (row.get(column) or "").strip()
    return value or None


# ---------------------------------------------------------------------------
# Rebuild and re-judge
# ---------------------------------------------------------------------------


def visible_suite_files(suite_root: Path) -> list[Path]:
    """Every frozen suite file the checkpoint's visible pass would run.

    `MANIFEST.json` describes how the goldens were frozen and holds no cases,
    exactly as `judge_candidate.sh` excludes it.
    """
    files = sorted(
        path
        for pattern in ("*.json", "*.json.gz")
        for path in (suite_root / "suites").glob(pattern)
        if path.name != "MANIFEST.json"
    )
    if not files:
        raise SystemExit(
            f"measure_execution_consistency: no suite files under {suite_root / 'suites'}"
        )
    return files


def judge_wrapper_pins_stdin_only(suite_root: Path) -> bool:
    """Whether this suite's `judge_candidate.sh` restricts judging to stdin.

    Detected from the wrapper rather than hardcoded per utility. Only sort does
    this today -- new_sort is a bounded stdin-only utility with no file operands
    -- but a suite that gains or loses the restriction should carry this
    measurement with it instead of silently reopening the divergence this
    function exists to close.
    """
    wrapper = suite_root / "judge_candidate.sh"
    if not wrapper.is_file():
        return False
    return bool(STDIN_ONLY_INJECTION.search(wrapper.read_text(encoding="utf-8")))


def visible_scope_overrides(suite_root: Path) -> dict[str, Any]:
    """The scope the checkpoint's real visible judgement applied, per suite.

    The visible pass must reproduce the corpus the candidate was actually scored
    and repaired against, and for two suites that corpus is narrower than "every
    case whose flags are implemented":

      * `sort` and `mkdir` commit real `excluded_tags` in their own
        `config.json` (`["debug", "doc", "compress", "files0", "obsolete"]` and
        `["selinux", "doc"]`). Every `judge_candidate.sh` loads that committed
        config as its base, so those exclusions are in force during the real
        judgement. (`grep` and `chmod` commit `[]`, so nothing changes there.)
      * `sort`'s `judge_candidate.sh` additionally injects
        `scope.stdin_only = True`. `runner.py`'s `modes_for()` reads it to decide
        whether to also run the file-redirect invocation mode, so without it the
        visible pass scores invocation modes the real judgement never did.

    Without both, `visible_case_count` and the visible fingerprint would not
    describe the corpus that produced `feature_test_exit_code` and drove the
    repair loop -- numbers that may well be read side by side. Only keys that
    actually need overriding are returned.

    The held-out pass deliberately gets none of this; see `judging_config`.
    """
    overrides: dict[str, Any] = {}
    suite_config = suite_root / "config.json"
    if suite_config.is_file():
        committed = read_json(suite_config)
        # Absent means the suite declares no exclusions, which is the base
        # config's `[]` already; an empty committed list is carried through
        # identically. Only a populated list actually changes anything.
        if "excluded_tags" in committed:
            overrides["excluded_tags"] = list(committed["excluded_tags"])
    if judge_wrapper_pins_stdin_only(suite_root):
        overrides["scope"] = {"stdin_only": True}
    return overrides


def judging_config(
    suite_root: Path,
    candidate_bin: Path,
    flags: Sequence[str],
    destination: Path,
    *,
    scope_overrides: Mapping[str, Any] | None = None,
) -> Path:
    """A throwaway config for one judging pass. Nothing in the repository is modified.

    The base is the minimal shape `heldout_judge.py` writes, and the held-out
    pass must keep matching it: that script is what actually ran the held-out
    corpus during the experiment, so a held-out fingerprint judged under
    different filtering would not describe the pass the experiment recorded. The
    held-out pass therefore passes no overrides.

    Both passes carry the suite's `required_platform` when it declares one. That
    key is not a scope filter but an abort gate: sort's goldens describe Linux
    and mkdir's describe Darwin, so on the wrong host the runner must refuse
    rather than report host artifacts as behavior. Omitting it would let this
    measurement silently fingerprint the platform instead of the candidate.

    `scope_overrides` is how the visible pass narrows to the corpus the
    checkpoint was really judged on; see `visible_scope_overrides`.
    """
    config: dict[str, Any] = {
        "paths": {"candidate_bin": str(candidate_bin)},
        "implemented": list(flags),
        "unimplemented_policy": "skip",
        "excluded_tags": [],
    }
    suite_config = suite_root / "config.json"
    if suite_config.is_file():
        required_platform = read_json(suite_config).get("required_platform")
        if required_platform:
            config["required_platform"] = required_platform
    config.update(scope_overrides or {})
    destination.write_text(json.dumps(config), encoding="utf-8")
    return destination


def rebuild_candidate(
    source: Path, workdir: Path, source_workdir_path: str, build_command: str
) -> subprocess.CompletedProcess[str]:
    """Stage the retained source where the build expects it, then build it there.

    `source_path` is the flattened name the candidate was captured under;
    `source_workdir_path` is where the recorded `build_command` will look for
    it. They differ, so the source has to be placed rather than built in situ.
    """
    staged = workdir / source_workdir_path
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, staged)
    return subprocess.run(
        build_command,
        shell=True,
        cwd=str(workdir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=BUILD_TIMEOUT_SECONDS,
    )


def judge(
    suite_root: Path,
    corpora: Sequence[Path],
    config_path: Path,
    candidate_bin: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Run the suite's own runner and return its report.

    Raises `RuntimeError` when no report was produced -- a usage error, or the
    platform gate refusing to judge. A nonzero exit with a report is just a
    candidate that failed cases, which is a measurement, not a failure.
    """
    command = [
        sys.executable,
        str(suite_root / "runner.py"),
        *[str(path) for path in corpora],
        "--config",
        str(config_path),
        "--json-report",
        str(report_path),
        "--",
        str(candidate_bin),
    ]
    completed = subprocess.run(
        command,
        cwd=str(suite_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=JUDGE_TIMEOUT_SECONDS,
    )
    if not report_path.is_file():
        raise RuntimeError(
            f"runner.py wrote no report (exit {completed.returncode}): "
            f"{output_tail(completed.stdout)}"
        )
    try:
        return read_json(report_path)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"unreadable report from runner.py: {error}") from error


def measure_run(
    *,
    candidate_source: Path,
    workdir: Path,
    source_workdir_path: str,
    build_command: str,
    binary_relative_path: str,
    suite_root: Path,
    visible_corpora: Sequence[Path],
    heldout_corpus: Path,
    flags: Sequence[str],
) -> dict[str, Any]:
    """Rebuild one candidate and fingerprint the two judging passes.

    Returns either `{"status": "measured", ...}` or a status naming why the run
    could not be measured. Raising instead would abort the whole condition on
    one candidate that happens not to compile, which is information worth
    keeping rather than a reason to report nothing.
    """
    if not candidate_source.is_file():
        return {
            "status": UNMEASURED_SOURCE_MISSING,
            "detail": f"no retained candidate source at {candidate_source}",
        }

    workdir.mkdir(parents=True, exist_ok=True)
    try:
        build = rebuild_candidate(
            candidate_source, workdir, source_workdir_path, build_command
        )
    except subprocess.TimeoutExpired as error:
        # A hang deserves the same treatment as a compile error: it is one
        # candidate's outcome, recorded, not a reason to abandon the condition.
        return {
            "status": UNMEASURED_REBUILD_FAILED,
            "detail": (
                f"build timed out after {BUILD_TIMEOUT_SECONDS}s: "
                f"{output_tail(error.output)}"
            ),
        }
    binary = workdir / binary_relative_path
    if build.returncode != 0 or not binary.is_file():
        return {
            "status": UNMEASURED_REBUILD_FAILED,
            "detail": (
                f"build exited {build.returncode}: {output_tail(build.stdout)}"
            ),
        }

    # Two configs, deliberately. The visible pass reproduces the scope the
    # checkpoint was really judged and repaired under; the held-out pass keeps
    # matching `heldout_judge.py`'s config exactly.
    visible_config = judging_config(
        suite_root,
        binary,
        flags,
        workdir / "visible-config.json",
        scope_overrides=visible_scope_overrides(suite_root),
    )
    heldout_config = judging_config(
        suite_root, binary, flags, workdir / "heldout-config.json"
    )
    try:
        visible = judge(
            suite_root,
            visible_corpora,
            visible_config,
            binary,
            workdir / "visible-report.json",
        )
        heldout = judge(
            suite_root,
            [heldout_corpus],
            heldout_config,
            binary,
            workdir / "heldout-report.json",
        )
    except subprocess.TimeoutExpired as error:
        return {
            "status": UNMEASURED_JUDGE_FAILED,
            "detail": (
                f"judging timed out after {JUDGE_TIMEOUT_SECONDS}s: "
                f"{output_tail(error.output)}"
            ),
        }
    except RuntimeError as error:
        return {"status": UNMEASURED_JUDGE_FAILED, "detail": str(error)}

    try:
        visible_results = report_results(visible)
        heldout_results = report_results(heldout)
    except ValueError as error:
        return {"status": UNMEASURED_JUDGE_FAILED, "detail": str(error)}
    visible_failures = report_failures(visible)
    heldout_failures = report_failures(heldout)
    visible_scope = visible_scope_overrides(suite_root)
    visible_corpus = corpus_descriptor(
        scope=VISIBLE_NAMESPACE,
        corpora=visible_corpora,
        case_results=visible_results,
        implemented=flags,
        scope_configuration=visible_scope,
    )
    heldout_corpus_descriptor = corpus_descriptor(
        scope=HELDOUT_NAMESPACE,
        corpora=[heldout_corpus],
        case_results=heldout_results,
        implemented=flags,
        scope_configuration={},
    )
    combined_results = sorted(
        namespaced_results(VISIBLE_NAMESPACE, visible_results)
        + namespaced_results(HELDOUT_NAMESPACE, heldout_results),
        key=lambda entry: entry["case_id"],
    )
    combined_corpus_material = {
        "schema_version": 1,
        "scope": "combined",
        "component_corpus_identities": [
            visible_corpus["corpus_identity_sha256"],
            heldout_corpus_descriptor["corpus_identity_sha256"],
        ],
        "ordered_case_ids": [entry["case_id"] for entry in combined_results],
        "number_of_cases": len(combined_results),
        "implemented_checkpoint_flags": list(flags),
    }
    combined_material = json.dumps(
        combined_corpus_material, sort_keys=True, separators=(",", ":")
    )
    combined_corpus_material["corpus_identity_sha256"] = hashlib.sha256(
        ("agentic-cyber.behavioral-corpus.v1\n" + combined_material).encode("utf-8")
    ).hexdigest()
    return {
        "status": "measured",
        "visible_case_count": len(visible_results),
        "heldout_case_count": len(heldout_results),
        "visible_failure_count": len(visible_failures),
        "heldout_failure_count": len(heldout_failures),
        "visible_results": visible_results,
        "heldout_results": heldout_results,
        "combined_results": combined_results,
        "visible_corpus": visible_corpus,
        "heldout_corpus": heldout_corpus_descriptor,
        "combined_corpus": combined_corpus_material,
        "visible_corpus_identity_sha256": visible_corpus["corpus_identity_sha256"],
        "heldout_corpus_identity_sha256": heldout_corpus_descriptor["corpus_identity_sha256"],
        "combined_corpus_identity_sha256": combined_corpus_material["corpus_identity_sha256"],
        "visible_fingerprint_sha256": execution_metrics.behavioral_fingerprint_hash(
            visible_corpus["corpus_identity_sha256"], visible_results
        ),
        "heldout_fingerprint_sha256": execution_metrics.behavioral_fingerprint_hash(
            heldout_corpus_descriptor["corpus_identity_sha256"], heldout_results
        ),
        "combined_fingerprint_sha256": execution_metrics.behavioral_fingerprint_hash(
            combined_corpus_material["corpus_identity_sha256"], combined_results
        ),
    }


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def convergence_summary(
    hashes: Sequence[str], run_ids: Sequence[str]
) -> dict[str, Any]:
    """`diversity_metrics.exact_repetition_summary`, named for what it measures here.

    That function is generic over hash strings -- nothing in it is specific to
    source bytes -- so exact behavioral convergence is the identical statistic
    applied to a different hash. Reusing it keeps one definition of "distinct
    over N" in the repository rather than two that could drift.
    """
    summary = diversity_metrics.exact_repetition_summary(hashes, run_ids)
    return {
        **summary,
        "exact_behavioral_unique_rate": summary["exact_unique_rate"],
        "exact_behavioral_modal_share": summary["exact_modal_share"],
    }


def case_count_stability(measured: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Whether every measured candidate was judged on the same number of cases.

    The premise behind fingerprinting failures alone. It should always hold --
    the case set is a deterministic function of the suite files, the corpus and
    the cumulative flag list, all fixed within a condition -- so a `false` here
    means the condition was not actually held constant and the convergence
    rates below it are comparing incomparable things.
    """
    visible = sorted({int(row["visible_case_count"]) for row in measured})
    heldout = sorted({int(row["heldout_case_count"]) for row in measured})
    return {
        "case_count_stable": len(visible) <= 1 and len(heldout) <= 1,
        "distinct_visible_case_counts": visible,
        "distinct_heldout_case_counts": heldout,
    }


def pairwise_behavioral_distances(
    measured: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """All candidate pairs, refusing comparisons across different corpora."""
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for scope in ("visible", "heldout", "combined"):
        comparable_values: list[float] = []
        incompatible_pairs = 0
        for left, right in itertools.combinations(measured, 2):
            left_identity = str(left[f"{scope}_corpus_identity_sha256"])
            right_identity = str(right[f"{scope}_corpus_identity_sha256"])
            compatible = left_identity == right_identity
            disagreement: float | None = None
            reason: str | None = None
            if compatible:
                try:
                    disagreement = execution_metrics.pairwise_verdict_disagreement(
                        left[f"{scope}_results"], right[f"{scope}_results"]
                    )
                except ValueError as error:
                    compatible = False
                    reason = str(error)
            else:
                reason = "corpus identity differs"
            if compatible and disagreement is not None:
                comparable_values.append(disagreement)
            else:
                incompatible_pairs += 1
            rows.append(
                {
                    "scope": scope,
                    "left_candidate_id": left["run_id"],
                    "right_candidate_id": right["run_id"],
                    "left_corpus_identity_sha256": left_identity,
                    "right_corpus_identity_sha256": right_identity,
                    "comparable": compatible,
                    "disagreement": disagreement,
                    "incomparable_reason": reason,
                }
            )
        total_pairs = len(measured) * (len(measured) - 1) // 2
        summary[scope] = {
            "population_n": len(measured),
            "total_pairs": total_pairs,
            "comparable_pairs": len(comparable_values),
            "incomparable_pairs": incompatible_pairs,
            "mean_pairwise_disagreement": (
                sum(comparable_values) / len(comparable_values)
                if total_pairs > 0 and incompatible_pairs == 0
                else None
            ),
            "unavailable_reason": (
                "fewer than two measured candidates"
                if total_pairs == 0
                else "one or more candidate pairs used incompatible case corpora"
                if incompatible_pairs
                else None
            ),
        }
    return rows, summary


def build_summary(
    *,
    experiment_dir: Path,
    experiment: Mapping[str, Any],
    utility: str,
    flags: Sequence[str],
    binary_relative_path: str,
    heldout_corpus: Path,
    visible_corpora: Sequence[Path],
    measured: Sequence[Mapping[str, Any]],
    unmeasured: Sequence[Mapping[str, Any]],
    successful_runs: int,
    architecture_labels: Mapping[str, str],
    strategy_labels: Mapping[str, str],
) -> dict[str, Any]:
    run_ids = [str(row["run_id"]) for row in measured]
    behavioral_group = {
        str(row["run_id"]): row["combined_fingerprint_sha256"] for row in measured
    }
    convergence = {
        space: convergence_summary(
            [str(row[f"{space}_fingerprint_sha256"]) for row in measured], run_ids
        )
        for space in ("visible", "heldout", "combined")
    }
    _, disagreement = pairwise_behavioral_distances(measured)
    corpus_identity = {
        scope: {
            "compatible_population": len({
                str(row[f"{scope}_corpus_identity_sha256"]) for row in measured
            }) <= 1,
            "distinct_corpus_identities": sorted({
                str(row[f"{scope}_corpus_identity_sha256"]) for row in measured
            }),
            "ordered_case_ids": (
                [entry["case_id"] for entry in measured[0][f"{scope}_results"]]
                if measured else []
            ),
            "number_of_cases": (
                len(measured[0][f"{scope}_results"]) if measured else 0
            ),
        }
        for scope in ("visible", "heldout", "combined")
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment": str(experiment_dir),
        "utility": utility,
        "source_path": experiment.get("source_path"),
        "implemented_flags": list(flags),
        "candidate_binary": binary_relative_path,
        "heldout_corpus": str(heldout_corpus),
        "visible_suite_files": [path.name for path in visible_corpora],
        "population": {
            "selection_basis": experiment.get(
                "population_selection_basis", "overall_success"
            ),
            "successful_runs": successful_runs,
            "measured_runs": len(measured),
            "measurement_coverage": (
                len(measured) / successful_runs if successful_runs else None
            ),
            "unmeasured_runs": list(unmeasured),
        },
        **case_count_stability(measured),
        "behavioral_corpus": corpus_identity,
        "pairwise_behavioral_disagreement": disagreement,
        "exact_behavioral_convergence": convergence,
        "exact_behavioral_convergence_role": "supporting_descriptive",
        "exact_behavioral_unique_rate_caveat": "sample-size-dependent",
        "structural_behavior_agreement": {
            "architecture": execution_metrics.structural_behavior_agreement(
                run_ids, behavioral_group, architecture_labels
            ),
            "strategy": execution_metrics.structural_behavior_agreement(
                run_ids, behavioral_group, strategy_labels
            ),
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure behavioral and execution consistency across the successful "
            "candidates of one experiment condition."
        )
    )
    parser.add_argument(
        "--experiment",
        type=Path,
        required=True,
        help="An experiment directory containing experiment.json and attempt-*/.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Default: <experiment>/analysis/execution_consistency",
    )
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Delete the output directory before writing the new measurement.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    experiment_dir = args.experiment.resolve()
    experiment_json = experiment_dir / "experiment.json"
    if not experiment_json.is_file():
        raise SystemExit(
            f"measure_execution_consistency: no {experiment_json}; --experiment "
            "must name one condition's directory"
        )
    experiment = read_json(experiment_json)

    source_path = str(experiment["source_path"])
    utility = utility_from_source_path(source_path)
    flags = implemented_flags(str(experiment["feature_test_command"]))
    build_command = str(experiment["build_command"])
    binary_relative_path = binary_from_build_command(build_command)
    source_workdir_path = str(experiment["source_workdir_path"])

    suite_root = REPO / "tests" / f"{utility}-test-suite"
    if not (suite_root / "runner.py").is_file():
        raise SystemExit(
            f"measure_execution_consistency: no suite runner at {suite_root}"
        )
    heldout_corpus = heldout_contract.corpus_path(suite_root)
    if not heldout_corpus.is_file():
        raise SystemExit(
            f"measure_execution_consistency: no held-out corpus at {heldout_corpus}; "
            "held-out behavior cannot be measured for this utility"
        )
    visible_corpora = visible_suite_files(suite_root)

    output_dir = args.output_dir or (
        experiment_dir / "analysis" / "execution_consistency"
    )
    population = successful_population(
        experiment_dir / "analysis" / "per_run_metrics.csv", experiment
    )
    architecture_labels = {
        str(row["run_id"]): label
        for row in population
        if (label := cluster_label(row, "architecture_cluster_id")) is not None
    }
    strategy_labels = {
        str(row["run_id"]): label
        for row in population
        if (label := cluster_label(row, "strategy_cluster_id")) is not None
    }

    print(
        f"Measuring execution consistency: {utility}, "
        f"implemented={flags or '[]'}, {len(population)} successful run(s)"
    )

    measured: list[dict[str, Any]] = []
    unmeasured: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="execution-consistency-") as temp:
        for index, row in enumerate(population, start=1):
            run_id = str(row["run_id"])
            print(f"  [{index}/{len(population)}] {run_id}")
            result = measure_run(
                candidate_source=experiment_dir / run_id / "candidate" / source_path,
                workdir=Path(temp) / run_id.replace("/", "_"),
                source_workdir_path=source_workdir_path,
                build_command=build_command,
                binary_relative_path=binary_relative_path,
                suite_root=suite_root,
                visible_corpora=visible_corpora,
                heldout_corpus=heldout_corpus,
                flags=flags,
            )
            if result["status"] == "measured":
                measured.append(
                    {
                        "run_id": run_id,
                        **{k: v for k, v in result.items() if k != "status"},
                        "architecture_cluster_id": architecture_labels.get(run_id),
                        "strategy_cluster_id": strategy_labels.get(run_id),
                    }
                )
            else:
                print(f"      unmeasured: {result['status']}")
                unmeasured.append({"run_id": run_id, **result})

    if args.clean_output and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(output_dir / "behavioral_fingerprints.csv", measured, FINGERPRINT_CSV_FIELDS)
    write_json(
        output_dir / "behavioral_verdict_traces.json",
        {
            "schema_version": SCHEMA_VERSION,
            "population_selection_basis": experiment.get(
                "population_selection_basis", "overall_success"
            ),
            "candidates": [
                {
                    "run_id": row["run_id"],
                    "visible": {
                        "corpus": row["visible_corpus"],
                        "results": row["visible_results"],
                    },
                    "heldout": {
                        "corpus": row["heldout_corpus"],
                        "results": row["heldout_results"],
                    },
                    "combined": {
                        "corpus": row["combined_corpus"],
                        "results": row["combined_results"],
                    },
                }
                for row in measured
            ],
        },
    )
    distance_rows, _ = pairwise_behavioral_distances(measured)
    write_csv(
        output_dir / "pairwise_behavioral_distances.csv",
        distance_rows,
        (
            "scope", "left_candidate_id", "right_candidate_id",
            "left_corpus_identity_sha256", "right_corpus_identity_sha256",
            "comparable", "disagreement", "incomparable_reason",
        ),
    )
    summary = build_summary(
        experiment_dir=experiment_dir,
        experiment=experiment,
        utility=utility,
        flags=flags,
        binary_relative_path=binary_relative_path,
        heldout_corpus=heldout_corpus,
        visible_corpora=visible_corpora,
        measured=measured,
        unmeasured=unmeasured,
        successful_runs=len(population),
        architecture_labels=architecture_labels,
        strategy_labels=strategy_labels,
    )
    write_json(output_dir / "summary.json", summary)

    combined = summary["exact_behavioral_convergence"]["combined"]
    combined_disagreement = summary["pairwise_behavioral_disagreement"]["combined"]
    print(
        f"\nMeasured {len(measured)}/{len(population)} successful run(s); "
        f"{len(unmeasured)} unmeasured."
    )
    if measured:
        mean_disagreement = combined_disagreement["mean_pairwise_disagreement"]
        print(
            "Combined mean pairwise verdict disagreement: "
            + ("undefined" if mean_disagreement is None else f"{mean_disagreement:.3f}")
        )
        print(
            f"Supporting combined behavioral unique rate: "
            f"{combined['exact_behavioral_unique_rate']:.3f}  "
            f"modal share: {combined['exact_behavioral_modal_share']:.3f}"
        )
        for space in ("architecture", "strategy"):
            agreement = summary["structural_behavior_agreement"][space]
            ari = agreement["adjusted_rand_index"]
            print(
                f"{space.capitalize()}-behavior ARI: "
                + (
                    f"not reported ({agreement['unavailable_reason']})"
                    if ari is None
                    else f"{ari:.3f}"
                )
            )
    if any(
        not summary["behavioral_corpus"][scope]["compatible_population"]
        for scope in ("visible", "heldout", "combined")
    ):
        print(
            "WARNING: corpus identities differed across the measured population; "
            "pairwise disagreement is reported as incomparable, not computed.",
            file=sys.stderr,
        )
    print(f"Wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
