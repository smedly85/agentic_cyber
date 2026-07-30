#!/usr/bin/env python3
"""Build the visible test bundle for one lineage checkpoint.

A checkpoint's sandbox must contain the tests for that checkpoint and the
regression tests for the checkpoints before it -- and nothing that describes a
checkpoint the agent has not reached. Copying a whole
`tests/<utility>-test-suite/` fails that: the frozen corpora carry every later
checkpoint's cases *with their expected outputs*, `gen/curated_cases.py` names
and groups them, the READMEs tabulate the full flag ladder, and the flag models
enumerate option surfaces the prompts have not introduced yet. Filtering which
cases the judge *runs* does not help, because the agent can still read the files.

So a stage's visible tests are built, not copied:

  * an explicit allowlist decides which suite files ship. It names the runtime
    judging path only -- nothing under `gen/`, `model/`, `corpus/`, no
    generator, no fuzzer, no README, no self-check, no prior run logs.
  * `suites/` is re-frozen to contain only the cases whose required flags are
    all implemented at this checkpoint. A later checkpoint's case is absent from
    the bundle, not merely skipped.
  * `config.json` is rewritten to the minimal judging configuration, with
    `implemented` set to this checkpoint's cumulative flags. Oracle paths and
    sanitizer-build settings are dropped: the judge needs neither, and an oracle
    path is a hint.
  * `props.py` is pruned to the property checks the retained cases actually
    dispatch to, plus their transitive local dependencies. A property function
    no retained case can reach is dead code in the sandbox that still describes
    a later checkpoint's behavior -- the mkdir suite's `-p`/`-m` idempotency
    check and the chmod suite's `-c`/`-v` report-line regexes are exactly that
    -- so it is removed rather than shipped unused. The module is regenerated
    from its AST, which also drops comments and the module docstring; both are
    prose about the full flag ladder, and neither is needed to judge.

The result can be handed to `run_experiment.sh --test-dir SRC:DEST`, so the
agent sees it at the path its prompt and its validation command name.

A bundle is built as an in-memory payload first, so its fingerprint can be taken
without writing anything. `scripts/lineage_plan.py` folds that fingerprint into
the run's configuration fingerprint, which is what makes regenerated goldens or
an edited allowlist invalidate a resume instead of silently mixing bundles.

Usage:
  python3 scripts/stage_test_bundle.py --utility grep --checkpoint 001 \\
      --output /tmp/bundle
  python3 scripts/stage_test_bundle.py --utility grep --checkpoint 001 \\
      --emit fingerprint
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1

# The runtime judging path, and only that. Every suite is built the same way, so
# one allowlist serves all four. A file absent here never reaches a sandbox --
# which is the point, so this list is deny-by-default and must stay short.
ALLOWED_FILES = (
    "judge_candidate.sh",  # the checkpoint entry point
    "runner.py",           # case selection, execution, comparison, verdicts
    "engine.py",           # fixtures, argv/env pinning, the single subprocess path
    "props.py",            # runtime property checks, pruned per checkpoint
                           # (never the golden invariants) -- see prune_props
    "config.py",           # dotted-key config reader used by the shell wrappers
)

# props.py is the only optional member: a suite without one has no runtime
# property checks. Everything else is required, so a renamed or deleted runtime
# file fails loudly rather than producing a bundle the judge cannot run.
OPTIONAL_FILES = frozenset({"props.py"})

# Deliberately excluded, with the reason each one would leak:
#   gen/           case definitions grouped by checkpoint, with future groups
#   model/         flag models and specification models (the answer sheet)
#   corpus/        input corpora chosen per flag
#   README.md      tabulates the whole checkpoint ladder
#   selfcheck.sh   runs gen/verify.py, which needs the excluded modules
#   run_all.sh, diff_fuzz.py, build_asan.sh, report_summary.py
#                  developer tooling that reaches the oracle or the generators
#   run_logs/      results of previous runs of this very suite
#   suites/*       shipped only after per-checkpoint filtering


class BundleError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"stage_test_bundle: {message}")


def selectable(case: Mapping[str, Any], implemented: set[str]) -> bool:
    """The judge's own rule, applied at build time instead of at run time.

    Mirrors `case_selected` in every suite's runner.py: a case runs only when
    every flag it needs is implemented, and none of the flags it requires to be
    ABSENT are. Applying it here is what turns "not executed" into "not
    present".

    `absent_flags` is what lets a checkpoint assert that a later checkpoint's
    feature has not been built yet -- "at 000, `-H` must be rejected as an
    unknown option" -- while that same case disappears once `-H` is introduced.
    Without it the ladder is only ever tested from below, and a model that
    implemented the whole sequence at 000 would pass every checkpoint.
    """
    flags = set(case.get("flags", []))
    absent = set(case.get("absent_flags", []))
    return flags <= implemented and not (absent & implemented)


def filter_suite(payload: Any, implemented: set[str]) -> tuple[Any, int, int]:
    """Return (filtered_payload, kept, dropped) for one suite file."""
    if isinstance(payload, dict) and "cases" in payload:
        cases = payload["cases"]
        kept = [case for case in cases if selectable(case, implemented)]
        filtered = dict(payload)
        filtered["cases"] = kept
        return filtered, len(kept), len(cases) - len(kept)
    if isinstance(payload, list):
        kept = [case for case in payload if selectable(case, implemented)]
        return kept, len(kept), len(payload) - len(kept)
    raise BundleError("suite file is neither a case list nor a {'cases': [...]} object")


def read_suite(path: Path) -> Any:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def encode_suite(payload: Any) -> bytes:
    """The canonical, uncompressed bytes of a suite file.

    Digests are taken over these rather than over the gzip stream a `.json.gz`
    member is finally written as. Compression is an encoding, not content, so
    hashing before it is equally faithful -- and it keeps fingerprinting cheap
    enough to run whenever a plan is resolved, which for the 14M sort corpus is
    the difference between a fraction of a second and several seconds.
    """
    return (json.dumps(payload, indent=1, sort_keys=True) + "\n").encode("utf-8")


def compress(data: bytes) -> bytes:
    # mtime=0 so an identical bundle is byte-identical across builds; gzip
    # otherwise stamps the current time into the header.
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(data)
    return buffer.getvalue()


def bundle_config(source: Path, implemented: list[str]) -> bytes:
    """The minimum configuration runner.py actually reads.

    Everything else in a suite's config.json describes generation or sanitizer
    builds. `paths.oracle_bin` in particular names the reference binary the
    goldens were frozen from, which has no business in a sandbox.
    """
    original = json.loads(source.read_text(encoding="utf-8"))
    config: dict[str, Any] = {
        "_comment": (
            "Per-checkpoint judging configuration, generated by "
            "scripts/stage_test_bundle.py. 'implemented' lists exactly the "
            "flags this checkpoint is responsible for, cumulatively. The cases "
            "under suites/ are already restricted to those flags."
        ),
        "paths": {"candidate_bin": "/path/to/your/candidate"},
        "implemented": list(implemented),
        "unimplemented_policy": original.get("unimplemented_policy", "skip"),
        "excluded_tags": list(original.get("excluded_tags", [])),
    }
    # scope pins a suite-wide restriction (new_sort is stdin-only) that the
    # judge re-applies at run time; carrying it keeps the bundle self-describing.
    if isinstance(original.get("scope"), dict):
        config["scope"] = original["scope"]
    return (json.dumps(config, indent=1, sort_keys=True) + "\n").encode("utf-8")


def case_checks(cases: list[Any]) -> set[str]:
    """The `property:<name>` checks a set of retained cases dispatches to."""
    checks = set()
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        check = case.get("check")
        if isinstance(check, str) and check.startswith("property:"):
            checks.add(check)
    return checks


def _referenced_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _definition_name(node: ast.AST) -> str | None:
    """The single top-level name a statement binds, if it binds exactly one."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def prune_props(source: bytes, needed: set[str], utility: str,
                checkpoint_id: str) -> bytes:
    """Rebuild props.py containing only the checks `needed` can reach.

    The suites ship one props.py describing every property the full flag ladder
    ever needs. A checkpoint's bundle must not carry the ones it cannot reach:
    they are unreachable at run time (no retained case names them) but perfectly
    readable, and they describe later checkpoints -- mkdir's `check_idempotent_p`
    spells out the `-p`/`-m` contract, and chmod's report-line regexes spell out
    the exact `-c`/`-v` output format.

    Every suite's runner.py does `import props` at module scope, so the module
    stays present and importable; it is emptied of what this checkpoint cannot
    use, not omitted. Imports are kept verbatim so the module still resolves,
    and `CHECKS` is rebuilt with only the needed entries.

    Regenerating from the AST is deliberate: it drops comments and the module
    docstring too, and in these suites both are prose about the whole ladder.
    """
    try:
        module = ast.parse(source.decode("utf-8"))
    except (UnicodeError, SyntaxError) as error:
        raise BundleError(f"cannot parse props.py: {error}") from error

    # Locate CHECKS and map each check name to the function implementing it.
    entry_points: dict[str, str] = {}
    checks_found = False
    for node in module.body:
        if _definition_name(node) != "CHECKS":
            continue
        checks_found = True
        value = node.value
        if not isinstance(value, ast.Dict):
            raise BundleError("props.py CHECKS must be a dict literal")
        for key, target in zip(value.keys, value.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise BundleError("props.py CHECKS keys must be string literals")
            if not isinstance(target, ast.Name):
                raise BundleError(
                    f"props.py CHECKS[{key.value!r}] must name a function"
                )
            entry_points[key.value] = target.id
    if not checks_found:
        raise BundleError("props.py defines no CHECKS mapping")

    missing = sorted(needed - set(entry_points))
    if missing:
        raise BundleError(
            f"{utility} checkpoint {checkpoint_id} retains cases needing "
            f"{missing}, which props.py does not define"
        )

    # Everything reachable from the needed entry points, transitively.
    definitions = {
        name: node for node in module.body
        if (name := _definition_name(node)) is not None and name != "CHECKS"
    }
    keep: set[str] = set()
    pending = [entry_points[check] for check in sorted(needed)]
    while pending:
        name = pending.pop()
        if name in keep or name not in definitions:
            continue
        keep.add(name)
        pending.extend(_referenced_names(definitions[name]))

    header = ast.parse(
        '"""Runtime property checks available to this checkpoint.\n\n'
        "Generated by scripts/stage_test_bundle.py from the suite's props.py,\n"
        "reduced to the checks the cases in this bundle actually dispatch to.\n"
        'Checks for other checkpoints are absent, not merely unused.\n"""\n'
    ).body

    body: list[ast.stmt] = list(header)
    for node in module.body:
        # Imports are kept verbatim: the pruned module must still resolve, and
        # an import names a bundle-internal module, never a flag.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            body.append(node)
            continue
        name = _definition_name(node)
        if name is not None and name in keep:
            body.append(node)

    checks_dict = ast.Dict(
        keys=[ast.Constant(value=check) for check in sorted(needed)],
        values=[ast.Name(id=entry_points[check], ctx=ast.Load())
                for check in sorted(needed)],
    )
    body.append(
        ast.Assign(
            targets=[ast.Name(id="CHECKS", ctx=ast.Store())], value=checks_dict
        )
    )

    pruned = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(pruned)
    return (ast.unparse(pruned) + "\n").encode("utf-8")


def build_payload(
    repo: Path,
    test_dir: str,
    checkpoint: Mapping[str, Any],
    utility: str,
) -> dict[str, Any]:
    """Assemble a bundle in memory.

    Returns {"files": {relative_path: bytes}, "manifest": {...}}. Nothing is
    written, so a caller that only wants the fingerprint pays no I/O.

    A `.json.gz` member is carried uncompressed here and gzipped by
    write_bundle; digests are over the uncompressed form. See encode_suite.
    """
    suite_root = repo / test_dir
    if not suite_root.is_dir():
        raise BundleError(f"test suite not found: {suite_root}")

    implemented = list(checkpoint["implemented_flags"])
    implemented_set = set(implemented)
    files: dict[str, bytes] = {}

    for name in ALLOWED_FILES:
        source = suite_root / name
        if not source.is_file():
            if name in OPTIONAL_FILES:
                continue
            raise BundleError(f"{test_dir}/{name} is missing")
        if name == "props.py":
            # Deferred: what it may contain depends on which cases survive
            # filtering, which is not known until the suites are read.
            continue
        files[name] = source.read_bytes()

    files["config.json"] = bundle_config(suite_root / "config.json", implemented)

    kept_total = dropped_total = 0
    per_suite: dict[str, int] = {}
    needed_checks: set[str] = set()
    for source in sorted((suite_root / "suites").glob("*")):
        if not source.is_file():
            continue
        if source.name == "MANIFEST.json":
            # Describes how the FULL corpus was frozen, including per-group
            # counts for later checkpoints. BUNDLE.json replaces it.
            continue
        if not (source.name.endswith(".json") or source.name.endswith(".json.gz")):
            continue
        filtered, kept, dropped = filter_suite(read_suite(source), implemented_set)
        kept_total += kept
        dropped_total += dropped
        per_suite[source.name] = kept
        if kept == 0:
            # A suite file contributing nothing here is a future-checkpoint
            # group; shipping an empty shell would still name it.
            continue
        retained = filtered["cases"] if isinstance(filtered, dict) else filtered
        needed_checks |= case_checks(retained)
        files[f"suites/{source.name}"] = encode_suite(filtered)

    if kept_total == 0:
        raise BundleError(
            f"{utility} checkpoint {checkpoint['id']} selects no cases at all; "
            "the bundle would give the agent nothing to check against"
        )

    props_source = suite_root / "props.py"
    if props_source.is_file():
        files["props.py"] = prune_props(
            props_source.read_bytes(), needed_checks, utility, checkpoint["id"]
        )

    digests = {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())
    }
    fingerprint = hashlib.sha256(
        json.dumps(digests, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "utility": utility,
        "checkpoint_id": checkpoint["id"],
        "checkpoint_name": checkpoint.get("name", checkpoint["id"]),
        "implemented_flags": implemented,
        "source_suite": test_dir,
        "visible_at": test_dir,
        "judge_command": checkpoint.get("feature_test_command"),
        "cases_included": kept_total,
        "cases_withheld": dropped_total,
        "cases_per_suite": per_suite,
        # props.py carries only these; a check no retained case dispatches to
        # is pruned out rather than shipped unused.
        "property_checks_included": sorted(needed_checks),
        "files": digests,
        "_files_comment": (
            "SHA-256 of each member's uncompressed content; a .json.gz member "
            "is written compressed, so its on-disk bytes hash differently."
        ),
        "bundle_fingerprint": fingerprint,
        "_comment": (
            "Generated by scripts/stage_test_bundle.py. Cases requiring a flag "
            "this checkpoint has not introduced are absent from this bundle, "
            "not merely skipped, and no generator, flag model, specification "
            "model or corpus is included."
        ),
    }
    return {"files": files, "manifest": manifest}


_FINGERPRINT_CACHE: dict[tuple[Any, ...], str] = {}


def _suite_inventory(suite_root: Path) -> tuple[tuple[str, int, int], ...]:
    """A cheap identity for the suite's current contents.

    Path, size and modification time for every file under the suite. Two builds
    that see the same inventory produce the same bundle, so the fingerprint can
    be memoized against it -- and any edit, including one that leaves the size
    unchanged, moves the mtime and invalidates the entry.
    """
    return tuple(
        (
            str(path.relative_to(suite_root).as_posix()),
            path.stat().st_size,
            path.stat().st_mtime_ns,
        )
        for path in sorted(suite_root.rglob("*"))
        if path.is_file()
    )


def fingerprint(
    repo: Path, test_dir: str, checkpoint: Mapping[str, Any], utility: str
) -> str:
    """The bundle fingerprint, computed without touching the filesystem.

    Memoized per process: `scripts/lineage_plan.py` resolves a plan more than
    once per invocation, and re-deriving the 14M sort corpus each time is
    several seconds of pure waste. The cache key includes the suite's file
    inventory, so an edited suite is never served from it.
    """
    suite_root = repo / test_dir
    key = (
        str(suite_root),
        tuple(checkpoint["implemented_flags"]),
        ALLOWED_FILES,
        _suite_inventory(suite_root) if suite_root.is_dir() else (),
    )
    if key not in _FINGERPRINT_CACHE:
        _FINGERPRINT_CACHE[key] = build_payload(
            repo, test_dir, checkpoint, utility
        )["manifest"]["bundle_fingerprint"]
    return _FINGERPRINT_CACHE[key]


def write_bundle(payload: Mapping[str, Any], output: Path) -> dict[str, Any]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for name, data in payload["files"].items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(compress(data) if name.endswith(".gz") else data)
    # The judge is invoked as an executable path, so it has to stay one.
    judge = output / "judge_candidate.sh"
    if judge.is_file():
        judge.chmod(0o755)
    manifest = dict(payload["manifest"])
    (output / "BUNDLE.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def resolve_checkpoint(
    repo: Path, utility: str, checkpoint_id: str
) -> tuple[str, dict[str, Any]]:
    """(test_dir, checkpoint) from the utility manifest.

    Imported lazily: scripts/lineage_plan.py depends on this module for
    fingerprints, so a module-level import back into it would be circular.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lineage_plan

    plan = lineage_plan.resolve_plan(repo, utility, "", "0", "build", 0, 0)
    checkpoints = {entry["id"]: entry for entry in plan["checkpoints"]}
    if checkpoint_id not in checkpoints:
        raise BundleError(
            f"{utility} has no checkpoint {checkpoint_id!r}; "
            f"available: {', '.join(checkpoints)}"
        )
    return plan["test_dir"], checkpoints[checkpoint_id]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--utility", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", type=Path,
                        help="Bundle directory. Omit to compute the "
                             "fingerprint or manifest without writing.")
    parser.add_argument("--emit", choices=("manifest", "fingerprint", "path"),
                        default="manifest")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()
    test_dir, checkpoint = resolve_checkpoint(repo, args.utility, args.checkpoint)
    payload = build_payload(repo, test_dir, checkpoint, args.utility)

    if args.output is None:
        if args.emit == "path":
            raise BundleError("--emit path requires --output")
        manifest = payload["manifest"]
    else:
        manifest = write_bundle(payload, args.output.resolve())

    if args.emit == "fingerprint":
        print(manifest["bundle_fingerprint"])
    elif args.emit == "path":
        print(args.output.resolve())
    else:
        print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BundleError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from error
