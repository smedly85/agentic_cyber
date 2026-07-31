#!/usr/bin/env python3
"""Freeze the curated new_grep cases into suites/*.json.

Reads the input-only case definitions from gen/curated_cases.py and derives each
case's expected stdout, exit status and stderr class from a REAL GNU grep --
`grep -aF` under `LC_ALL=C`, which is a literal-substring matcher with no binary
suppression and ASCII-only folding, i.e. exactly `new_grep`'s contract. See
gen/oracle.py for why each of those three adjustments is needed and how each was
verified against the live binary.

Ten cases cannot come from any real grep, because they are statements about
`new_grep`'s bounded option set rather than about fixed-string matching (at
checkpoint 000 `-H` must be an *unknown option*; `-` is an ordinary pathname
rather than standard input). Those keep goldens derived from
tests/reference_generators/grep_reference.py, and gen/oracle.py records the
reason for each. Everything else must agree with the oracle byte for byte:
regeneration fails loudly on any disagreement rather than picking a winner.

Two derivations, one corpus
---------------------------
Writing requires the oracle. `--check` does not, and stays offline and
platform-independent so `gen/verify.py`, `selfcheck.sh` and CI keep running on a
host with no GNU grep -- which matters because the model and the oracle are held
byte-identical for every non-exempt case at freeze time. If they ever diverge,
the freeze is what fails; `--check` can then be trusted to compare against the
model alone.

Usage:
  python3 gen/generate.py                      # rewrite suites/ from the oracle
  python3 gen/generate.py --check              # fail if suites/ is out of date
  python3 gen/generate.py --oracle-bin ggrep   # explicit oracle
  GREP_ORACLE_BIN=/usr/bin/grep python3 gen/generate.py
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import tempfile
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent.parent
SUITE_DIR = SUITE_ROOT / "suites"
sys.path.insert(0, str(SUITE_ROOT))
# The specification model, the oracle contract and the model-dependent
# invariants live outside this suite so they can never be copied into an
# experimental sandbox; reaching them needs tests/ on the path.
sys.path.insert(0, str(SUITE_ROOT.parent))

from reference_generators import grep_reference as reference  # noqa: E402
from reference_generators import oracle_contract  # noqa: E402
from gen import curated_cases  # noqa: E402
from gen import oracle as oracle_module  # noqa: E402

SCHEMA_VERSION = 1

# What `oracle_bin` is invoked as, recorded in the manifest so the frozen corpus
# says how it was produced and not merely by what.
ORACLE_INVOCATION = "grep -a -F [-i] [-H|-h] -e PATTERN -- OPERAND (LC_ALL=C)"

# The frozen corpus is a byte-exact artifact: scripts/stage_test_bundle.py
# hashes these files as bytes, so their line terminator is part of the lineage
# configuration fingerprint. Left to the default, Python would write CRLF on
# Windows and LF elsewhere, and merely regenerating on a different host would
# change every fingerprint without changing a single golden. Pinned to the
# terminator the committed corpus already uses.
CORPUS_NEWLINE = "\r\n"

GROUP_FILES = {
    "base": "base.json",
    "with_filename": "with_filename.json",
    "no_filename": "no_filename.json",
    "recursive": "recursive.json",
    "ignore_case": "ignore_case.json",
}


def encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def build_filesystem(fixture: list[dict] | None) -> dict[str, reference.Entry]:
    """Turn a case's fixture list into the model's filesystem view.

    A fixture mode with no read bits is what makes a file unreadable on the real
    filesystem, so the model must see the same thing or its goldens would claim
    a successful read where the candidate gets EACCES.
    """
    filesystem: dict[str, reference.Entry] = {}
    for entry in fixture or []:
        path = entry["path"].rstrip("/") or entry["path"]
        kind = entry["type"]
        if kind == "file":
            mode = entry.get("mode", "0644")
            filesystem[path] = reference.Entry(
                kind="file",
                contents=entry.get("contents", b""),
                readable=bool(int(mode, 8) & 0o444),
            )
        elif kind == "dir":
            mode = entry.get("mode", "0755")
            filesystem[path] = reference.Entry(
                kind="dir", readable=bool(int(mode, 8) & 0o444)
            )
        elif kind == "symlink":
            filesystem[path] = reference.Entry(kind="symlink", target=entry["target"])
        else:
            raise SystemExit(f"unknown fixture type: {kind!r}")
    return filesystem


def model_option_set(definition: dict) -> set[str] | None:
    """The option set the model should parse this case under.

    None -- the complete ladder -- for an ordinary case. A case carrying
    `absent_flags` describes a checkpoint that has not introduced those flags,
    so the model must treat them as unknown options; otherwise it would happily
    honour `-H` and freeze a success golden for a case whose whole purpose is to
    assert that `-H` is still rejected.
    """
    absent = set(definition.get("absent_flags") or [])
    if not absent:
        return None
    return set(reference.FEATURE_FLAG.values()) - absent


class OracleDisagreement(SystemExit):
    """The live oracle and the specification model produced different goldens.

    Never resolved silently in either direction. One of the two is wrong about
    the contract, and which one it is cannot be decided by this script: if the
    model drifted, fix the model; if the contract genuinely changed, the prompt
    changed with it and the case belongs in gen/oracle.py's exemption table with
    a written reason.
    """


def oracle_case(binary: str, definition: dict) -> oracle_module.Result:
    """Run the live oracle for one case in a throwaway tree."""
    fixture = definition.get("fixture")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        oracle_module.materialize(fixture, root)
        try:
            return oracle_module.run_case(binary, definition, root)
        finally:
            # A 0000 entry would otherwise defeat the cleanup.
            oracle_module.restore_modes(fixture, root)


def freeze_case(definition: dict, oracle_bin: str | None = None) -> dict:
    fixture = definition.get("fixture")
    filesystem = build_filesystem(fixture)
    stdin = definition.get("stdin")
    implemented = model_option_set(definition)

    stdout, subjects, exit_code = reference.run(
        list(definition["args"]), stdin or b"", filesystem, implemented
    )

    # The oracle is authoritative where it can speak at all. The model result is
    # still computed first and compared against it, so a drifted model is caught
    # at freeze time rather than silently replaced -- which is what keeps the
    # offline --check path (model-only) trustworthy on a host with no GNU grep.
    if oracle_bin and not oracle_module.model_only_reason(definition):
        try:
            observed = oracle_case(oracle_bin, definition)
        except oracle_module.OracleFailure as error:
            raise OracleDisagreement(
                f"oracle could not run case {definition['name']!r}: {error}"
            ) from error
        differences = []
        if observed.stdout != stdout:
            differences.append(
                f"stdout: oracle={observed.stdout!r} model={stdout!r}")
        if observed.exit_code != exit_code:
            differences.append(
                f"exit status: oracle={observed.exit_code} model={exit_code}")
        # Compared as lists, not merely empty/non-empty: the subject is what the
        # frozen `stderr_regex` is built from, so the two must agree on WHICH
        # operand was diagnosed, not just on whether something was.
        if observed.subjects != subjects:
            differences.append(
                f"diagnostic subjects: oracle={observed.subjects} "
                f"model={subjects}")
        if differences:
            raise OracleDisagreement(
                f"case {definition['name']!r} disagrees with the oracle "
                f"({oracle_bin}):\n  " + "\n  ".join(differences)
                + "\nNothing was written. Fix the model, or exempt the case in "
                  "gen/oracle.py with a written reason."
            )
        stdout, exit_code = observed.stdout, observed.exit_code

    # A usage rejection never reaches the prefix decision, so there is nothing
    # to record for it.
    try:
        options = reference.parse_args(list(definition["args"]), implemented)
        prefixed = reference.prefix_filenames(options, filesystem)
    except reference.UsageError:
        prefixed = False

    case: dict = {
        "name": definition["name"],
        "args": list(definition["args"]),
        "flags": list(definition["flags"]),
        "tags": list(definition["tags"]),
        "exit_code": exit_code,
        "stdout_b64": encode(stdout),
        "stderr_class": "nonempty" if subjects else "empty",
        "expect_filename_prefix": prefixed,
    }

    if definition.get("absent_flags"):
        case["absent_flags"] = list(definition["absent_flags"])

    if subjects and subjects != ["usage"]:
        # Require the diagnostic to name what it is about, without pinning the
        # surrounding wording: the prompts specify which conditions are
        # diagnosed, not how the sentence reads.
        case["stderr_regex"] = re.escape(subjects[0])

    if stdin is not None:
        case["stdin_b64"] = encode(stdin)
    if "stdin_modes" in definition:
        case["stdin_modes"] = list(definition["stdin_modes"])
    if "timeout" in definition:
        case["timeout"] = definition["timeout"]
    if fixture is not None:
        case["fixture"] = [_encode_fixture(entry) for entry in fixture]
    return case


def _encode_fixture(entry: dict) -> dict:
    out = {"path": entry["path"], "type": entry["type"]}
    if entry["type"] == "file":
        out["contents_b64"] = encode(entry.get("contents", b""))
    if entry["type"] == "symlink":
        out["target"] = entry["target"]
    if "mode" in entry:
        out["mode"] = entry["mode"]
    return out


def build_suites(oracle_bin: str | None = None) -> dict[str, dict]:
    suites: dict[str, dict] = {}
    seen: set[str] = set()
    for group, definitions in curated_cases.GROUPS.items():
        cases = []
        for definition in definitions:
            if definition["name"] in seen:
                raise SystemExit(f"duplicate case name: {definition['name']}")
            seen.add(definition["name"])
            cases.append(freeze_case(definition, oracle_bin))
        suites[GROUP_FILES[group]] = {
            "schema_version": SCHEMA_VERSION,
            "group": group,
            "cases": cases,
        }
    return suites


def model_only_cases() -> dict[str, str]:
    """Every case whose golden comes from the model, and why."""
    return {
        definition["name"]: reason
        for definitions in curated_cases.GROUPS.values()
        for definition in definitions
        if (reason := oracle_module.model_only_reason(definition))
    }


def recorded_version() -> str:
    """The oracle version the committed corpus was frozen from.

    Read back from the corpus rather than recomputed, so `--check` describes the
    goldens on disk without needing a GNU grep to be installed.
    """
    path = SUITE_DIR / "MANIFEST.json"
    if not path.is_file():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get(
            "grep_version", ""))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""


def manifest(suites: dict[str, dict], grep_version: str = "") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "oracle": (
            "GNU grep (see grep_version): -F fixed strings, -a so NUL bytes "
            "are ordinary data, LC_ALL=C so -i folds ASCII only. Traversal "
            "order for -r is computed from the contract rather than taken from "
            "grep -r, which follows raw readdir order. "
            "tests/reference_generators/grep_reference.py supplies only the "
            "cases listed under model_only_cases, which no real grep can "
            "produce. Neither is ever copied into a sandbox."
        ),
        "grep_version": grep_version,
        "oracle_invocation": ORACLE_INVOCATION,
        # Recorded by name so the exemptions are auditable from the frozen
        # corpus alone, without reading the generator.
        "model_only_cases": model_only_cases(),
        "counts": {
            data["group"]: len(data["cases"]) for data in suites.values()
        },
        "total_cases": sum(len(data["cases"]) for data in suites.values()),
    }


def total(suites: dict[str, dict]) -> int:
    return sum(len(data["cases"]) for data in suites.values())


def render(value: dict) -> str:
    return json.dumps(value, indent=1, sort_keys=True) + "\n"


def resolve_oracle(explicit: str | None) -> str:
    """The oracle to freeze against, verified before anything is written.

    Both gates run: `oracle_contract` establishes that the binary IS GNU grep at
    the pinned version, and `gen/oracle.precheck` establishes that it and the
    filesystem underneath it actually behave the way the contract needs. The
    second is not redundant -- a build can report the right version and still
    drop CR from its output or abort under `LC_ALL=C -i`.
    """
    config = SUITE_ROOT / "config.json"
    binary = oracle_contract.resolve("grep", config, explicit)
    problems = oracle_contract.verify("grep", SUITE_ROOT, binary, config)
    if problems:
        for problem in problems:
            print(f"oracle_contract: {problem}", file=sys.stderr)
        raise SystemExit(2)

    with tempfile.TemporaryDirectory() as temp:
        problems = oracle_module.precheck(binary, Path(temp))
    if problems:
        print(f"oracle {binary} is not fit to freeze this suite's goldens:",
              file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(2)
    return binary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit nonzero when suites/ differs from the "
             "committed goldens. Offline: needs no oracle binary",
    )
    parser.add_argument(
        "--oracle-bin",
        default=None,
        help="GNU grep to freeze against (else $GREP_ORACLE_BIN, else "
             "config.json paths.oracle_bin, else a conventional location)",
    )
    args = parser.parse_args()

    if args.check:
        # Model-derived, and legitimately so: freezing asserts the model
        # reproduces the oracle byte for byte for every non-exempt case, so a
        # difference found here is a difference from the oracle too.
        suites = build_suites()
        payloads = {name: render(data) for name, data in suites.items()}
        payloads["MANIFEST.json"] = render(manifest(suites, recorded_version()))
    else:
        oracle_bin = resolve_oracle(args.oracle_bin)
        version = oracle_contract.version_line(oracle_bin)
        print(f"oracle: {oracle_bin} -- {version}")
        suites = build_suites(oracle_bin)
        payloads = {name: render(data) for name, data in suites.items()}
        payloads["MANIFEST.json"] = render(manifest(suites, version))

    if args.check:
        stale = []
        for name, text in payloads.items():
            path = SUITE_DIR / name
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        extra = sorted(
            path.name
            for path in SUITE_DIR.glob("*.json")
            if path.name not in payloads
        )
        if stale or extra:
            for name in stale:
                print(f"stale: suites/{name}", file=sys.stderr)
            for name in extra:
                print(f"unexpected: suites/{name}", file=sys.stderr)
            return 1
        print(f"suites/ is up to date ({total(suites)} cases)")
        return 0

    SUITE_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in payloads.items():
        (SUITE_DIR / name).write_text(text, encoding="utf-8",
                                      newline=CORPUS_NEWLINE)
    exempt = len(model_only_cases())
    print(
        f"wrote {len(payloads)} files to {SUITE_DIR} "
        f"({total(suites)} cases: {total(suites) - exempt} from the oracle, "
        f"{exempt} from the specification model)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
