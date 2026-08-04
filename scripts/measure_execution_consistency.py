#!/usr/bin/env python3
"""Measure whether repeated candidates in one condition behave the same way.

This is the evaluation's second measurement dimension. The first --
correctness and completion -- is `scripts/analyze_experiment.py` and
`scripts/analyze_lineages.py`. The third -- implementation diversity among
functionally valid outputs -- is `scripts/analyze_experiment.py` plus
`scripts/analysis/diversity_metrics.py`, documented in
`docs/diversity_methodology.md`. Neither of those answers the question this
one asks.

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

The last number is the one that tests the paper's own framing. The adjusted
Rand index between the behavioral partition and the architecture/strategy
family partitions asks whether structural family membership predicts behavioral
identity at all. If it does not, the diversity result and the consistency
result are measuring genuinely different things, and neither substitutes for
the other.

What it deliberately does not do
--------------------------------
  * It does not re-judge anything into existence. Like `heldout_judge.py`, it
    hands corpora to the suite's own `runner.py` and inherits its comparison
    semantics exactly. A second comparator could disagree with the recorded
    verdict and nobody would know which was right.

  * It does not re-derive the population or the family labels. Success and
    failure are `analyze_experiment.py`'s determination, read back out of
    `analysis/per_run_metrics.csv`; so are the architecture and strategy
    cluster ids. Reimplementing the failure taxonomy here would let two
    definitions of "successful" drift apart silently.

  * It does not change any outcome. It is strictly post-hoc and read-only with
    respect to the experiment: it never re-runs OpenCode, never enters the
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
import json
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

SCHEMA_VERSION = 1

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

FINGERPRINT_CSV_FIELDS = (
    "run_id",
    "visible_case_count",
    "visible_failure_count",
    "heldout_case_count",
    "heldout_failure_count",
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


def namespaced_failures(
    namespace: str, failures: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    return [(f"{namespace}::{name}", verdict) for name, verdict in failures]


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


def successful_population(metrics_csv: Path) -> list[dict[str, str]]:
    """The successful runs and their family labels, as `analyze_experiment.py` left them.

    Read rather than recomputed. `overall_success` arrives as the string
    `"True"`/`"False"` through `csv.DictReader`, and the cluster columns are
    blank for runs outside the corresponding primary population.
    """
    if not metrics_csv.is_file():
        raise SystemExit(
            f"measure_execution_consistency: no {metrics_csv}. Run\n"
            f"    python3 scripts/analyze_experiment.py --experiment {metrics_csv.parent.parent}\n"
            "first; this measurement reads its population and family labels "
            "rather than re-deriving them."
        )
    with metrics_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
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


def judging_config(
    suite_root: Path, candidate_bin: Path, flags: Sequence[str], destination: Path
) -> Path:
    """A throwaway config carrying this checkpoint's scope. Nothing is modified.

    The same minimal shape `heldout_judge.py` writes, plus the suite's
    `required_platform` when it declares one. That key is not a scope filter but
    an abort gate: sort's goldens describe Linux and mkdir's describe Darwin, so
    on the wrong host the runner must refuse rather than report host artifacts
    as behavior. Omitting it would let this measurement silently fingerprint the
    platform instead of the candidate.
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
    )
    if not report_path.is_file():
        raise RuntimeError(
            f"runner.py wrote no report (exit {completed.returncode}): "
            f"{(completed.stdout or '').strip()[-800:]}"
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
    build = rebuild_candidate(
        candidate_source, workdir, source_workdir_path, build_command
    )
    binary = workdir / binary_relative_path
    if build.returncode != 0 or not binary.is_file():
        return {
            "status": UNMEASURED_REBUILD_FAILED,
            "detail": (
                f"build exited {build.returncode}: "
                f"{(build.stdout or '').strip()[-800:]}"
            ),
        }

    config = judging_config(
        suite_root, binary, flags, workdir / "execution-consistency-config.json"
    )
    try:
        visible = judge(
            suite_root, visible_corpora, config, binary, workdir / "visible-report.json"
        )
        heldout = judge(
            suite_root, [heldout_corpus], config, binary, workdir / "heldout-report.json"
        )
    except RuntimeError as error:
        return {"status": UNMEASURED_JUDGE_FAILED, "detail": str(error)}

    visible_failures = report_failures(visible)
    heldout_failures = report_failures(heldout)
    combined = namespaced_failures(
        VISIBLE_NAMESPACE, visible_failures
    ) + namespaced_failures(HELDOUT_NAMESPACE, heldout_failures)
    return {
        "status": "measured",
        "visible_case_count": report_case_count(visible),
        "heldout_case_count": report_case_count(heldout),
        "visible_failure_count": len(visible_failures),
        "heldout_failure_count": len(heldout_failures),
        "visible_fingerprint_sha256": execution_metrics.behavioral_fingerprint_hash(
            visible_failures
        ),
        "heldout_fingerprint_sha256": execution_metrics.behavioral_fingerprint_hash(
            heldout_failures
        ),
        "combined_fingerprint_sha256": execution_metrics.behavioral_fingerprint_hash(
            combined
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
            "successful_runs": successful_runs,
            "measured_runs": len(measured),
            "measurement_coverage": (
                len(measured) / successful_runs if successful_runs else None
            ),
            "unmeasured_runs": list(unmeasured),
        },
        **case_count_stability(measured),
        "exact_behavioral_convergence": convergence,
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
        experiment_dir / "analysis" / "per_run_metrics.csv"
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
    print(
        f"\nMeasured {len(measured)}/{len(population)} successful run(s); "
        f"{len(unmeasured)} unmeasured."
    )
    if measured:
        print(
            f"Combined behavioral unique rate: "
            f"{combined['exact_behavioral_unique_rate']:.3f}  "
            f"modal share: {combined['exact_behavioral_modal_share']:.3f}"
        )
        for space in ("architecture", "strategy"):
            ari = summary["structural_behavior_agreement"][space]["adjusted_rand_index"]
            print(
                f"{space.capitalize()}-behavior ARI: "
                + ("undefined (fewer than 2 shared runs)" if ari is None else f"{ari:.3f}")
            )
    if not summary["case_count_stable"]:
        print(
            "WARNING: case counts differed across the measured population; the "
            "condition was not held constant and the convergence rates above "
            "compare candidates judged on different cases.",
            file=sys.stderr,
        )
    print(f"Wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
