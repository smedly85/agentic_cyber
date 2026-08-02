#!/usr/bin/env python3
"""Live differential fuzzer for `new_grep`, modelled on sort's diff_fuzz.py.

Each round samples a flag combination, builds a random or mutated input, runs
two implementations side by side, and compares **exit status and stdout bytes**.
A disagreement is minimized by line bisection and appended to
`suites/fuzz_regressions.json.gz` as a permanent, frozen regression case.

Two things it compares, selected by `--against`
-----------------------------------------------
``candidate``
    A candidate binary against the oracle -- the same thing sort's fuzzer does,
    and the mode to use once a `new_grep` exists. The candidate is invoked with
    the case's own argv; the oracle is invoked through the pinned translation.

``model``
    The suite's specification model (`tests/reference_generators/
    grep_reference.py`) against the oracle. This is the freeze-time
    model/oracle agreement check from `gen/generate.py:freeze_case`, run on
    random inputs instead of the 88 curated ones. A disagreement here is a real
    defect in the contract model or in the pinned invocation's fidelity, and it
    would silently corrupt any future golden frozen over that input.

    This is the default, because this repository currently has no `new_grep`
    candidate at all -- no `src/new_grep/`, no build artifact, no experiment
    output. Fuzzing "the candidate" would mean inventing one, and a fuzzer run
    against a target chosen to make it pass is not evidence of anything.

The oracle is never invoked directly here
-----------------------------------------
Every oracle result comes from `gen/generate.py:oracle_case`, which is the same
function `freeze_case` uses. That keeps the pinned invocation -- `grep -a -F -e
PATTERN -- OPERAND`, `-i` when folding, `-H`/`-h` resolved from the contract,
`LC_ALL=C` and friends -- defined in exactly one place (`gen/oracle.py`). A
fuzzer that rebuilt the argv itself could drift from the generator and report
its own drift as a candidate bug.

Byte fidelity is the point, not an edge case
--------------------------------------------
`new_grep`'s contract is over bytes: NUL is ordinary data, bytes >= 0x80 are
never folded, and a missing trailing newline is preserved. The seed corpus is
`gen/curated_cases.py`'s fixtures (which include a NUL/invalid-UTF-8 payload, a
CRLF payload and an unterminated payload), and the mutators are written to
preserve rather than launder those properties -- see `mutate`.

Usage:
  GREP_ORACLE_BIN=/usr/bin/grep python3 diff_fuzz.py --time-budget 120
  python3 diff_fuzz.py --against candidate --candidate build/new_grep
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SUITE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE_ROOT))
sys.path.insert(0, str(SUITE_ROOT.parent))

from reference_generators import grep_reference as reference  # noqa: E402
from gen import curated_cases, generate                       # noqa: E402
from gen import oracle as oracle_module                       # noqa: E402

# The bounded ladder. Sampling is restricted to flags the config declares
# implemented, for sort's reason: a stdout deviation on an unimplemented flag
# is an unimplemented-feature artifact, not a correctness bug.
FUZZ_POOL = ["-H", "-h", "-r", "-i"]

# Seed payloads, reused from the curated tier so the fuzzer starts from inputs
# already known to discriminate the contract's corners.
SEED_PAYLOADS = {
    "ALPHA": curated_cases.ALPHA,
    "BETA": curated_cases.BETA,
    "MIXED": curated_cases.MIXED,
    "BINARY": curated_cases.BINARY,
    "NO_TRAILING": curated_cases.NO_TRAILING,
    "CRLF": curated_cases.CRLF,
}

# NUL never appears in a pattern: argv strings are NUL-terminated, so execve
# cannot carry one and no grep -- oracle or candidate -- can be handed such a
# pattern at all. NUL belongs in the DATA, where the contract does make a
# promise about it, and `mutate` puts it there.
SEED_PATTERNS = [b"alpha", b"needle", b"beta", b"ALPHA", b"a", b"",
                 b"nothing", b"\xff\xfe", b"needle", b"a.c", b"[abc]"]


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --- input generation --------------------------------------------------------

def random_bytes(rng: random.Random, length: int) -> bytes:
    """Uniform over all 256 byte values, newline included.

    Not restricted to printable ASCII: NUL and high bytes are exactly the
    region where a candidate is most likely to diverge, and where a fuzzer that
    only produced text would never look.
    """
    return bytes(rng.randrange(256) for _ in range(length))


def mutate(rng: random.Random, data: bytes) -> bytes:
    """Cheap mutations that keep the byte-fidelity properties in play.

    Deliberately includes operations that CREATE the awkward cases rather than
    only preserving them: inserting NUL, inserting a high byte, and stripping
    the trailing newline are all things the contract makes promises about.
    """
    operation = rng.randrange(8)
    lines = data.split(b"\n")
    if operation == 0 and len(lines) > 1:
        del lines[rng.randrange(len(lines))]
    elif operation == 1 and lines:
        lines.append(lines[rng.randrange(len(lines))])
    elif operation == 2 and data:
        index = rng.randrange(len(data))
        mutable = bytearray(data)
        mutable[index] ^= 1 << rng.randrange(8)
        return bytes(mutable)
    elif operation == 3:
        index = rng.randrange(len(data) + 1)
        return data[:index] + b"\x00" + data[index:]
    elif operation == 4:
        index = rng.randrange(len(data) + 1)
        return data[:index] + bytes([rng.randrange(0x80, 0x100)]) + data[index:]
    elif operation == 5:
        # Drop the trailing newline: an unterminated final line is its own
        # contract clause, and mutations that always end in b"\n" never test it.
        return data[:-1] if data.endswith(b"\n") else data + b"\n"
    elif operation == 6:
        lines.append(random_bytes(rng, rng.randrange(1, 12)).replace(b"\n", b"x"))
    else:
        rng.shuffle(lines)
    return b"\n".join(lines)


def sample_flags(rng: random.Random, implemented: set[str] | None) -> list[str]:
    pool = [f for f in FUZZ_POOL
            if implemented is None or f in implemented]
    if not pool:
        return []
    chosen: list[str] = []
    for flag in pool:
        if rng.random() < 0.4:
            chosen.append(flag)
    # -H and -h are mutually contradictory only in the sense that the last one
    # wins; keeping both is a deliberate probe of that rule, so nothing is
    # filtered out here.
    return chosen


def sample_case(rng: random.Random, implemented: set[str] | None,
                seed_index: int) -> dict:
    """One random case definition in the suite's own schema."""
    flags = sample_flags(rng, implemented)
    pattern = (rng.choice(SEED_PATTERNS) if rng.random() < 0.7
               else random_bytes(rng, rng.randrange(1, 6)))
    # Newline would split it into two -e patterns; NUL cannot cross execve.
    pattern = pattern.replace(b"\n", b"").replace(b"\x00", b"")
    # A pattern starting with `-` is parsed as an option, which puts the case in
    # the suite's ORACLE-EXEMPT region: those cases assert which options
    # new_grep rejects, and GNU grep implements a different option set, so they
    # are model-only by design and there is nothing to compare against. Keeping
    # generated patterns out of that region spends the budget where the oracle
    # can actually speak.
    while pattern.startswith(b"-"):
        pattern = pattern[1:]

    def payload() -> bytes:
        data = SEED_PAYLOADS[rng.choice(list(SEED_PAYLOADS))]
        if rng.random() < 0.25:
            data = random_bytes(rng, rng.randrange(0, 64))
        for _ in range(rng.randrange(0, 4)):
            data = mutate(rng, data)
        return data

    recursive = "-r" in flags
    shape = rng.random()
    definition: dict = {
        "schema": 2,
        "name": f"fuzz-probe-{seed_index}",
        "args": [],
        "tags": ["fuzz"],
    }
    arguments = list(flags)

    if shape < 0.4 and not recursive:
        # stdin: no operands
        definition["stdin"] = payload()
        definition["args"] = arguments + [pattern.decode("utf-8", "surrogateescape")]
        return definition

    fixture: list[dict] = []
    operands: list[str] = []
    if recursive and shape < 0.8:
        fixture.append({"path": "t", "type": "dir", "mode": "0755"})
        for name in ("a.txt", "b.txt"):
            fixture.append({"path": f"t/{name}", "type": "file",
                            "contents": payload(), "mode": "0644"})
        if rng.random() < 0.5:
            fixture.append({"path": "t/sub", "type": "dir", "mode": "0755"})
            fixture.append({"path": "t/sub/z.txt", "type": "file",
                            "contents": payload(), "mode": "0644"})
        operands = ["t"]
    else:
        count = 1 if rng.random() < 0.6 else 2
        for index in range(count):
            name = f"f{index}.txt"
            fixture.append({"path": name, "type": "file",
                            "contents": payload(), "mode": "0644"})
            operands.append(name)

    definition["fixture"] = fixture
    definition["args"] = (arguments
                          + [pattern.decode("utf-8", "surrogateescape")]
                          + operands)
    return definition


# --- running the two sides ---------------------------------------------------

class Outcome:
    __slots__ = ("stdout", "exit_code", "error")

    def __init__(self, stdout: bytes, exit_code: int, error: str | None = None):
        self.stdout = stdout
        self.exit_code = exit_code
        self.error = error


def run_oracle(oracle_bin: str, definition: dict) -> Outcome:
    """The pinned invocation, via the same helper freeze_case uses."""
    try:
        result = generate.oracle_case(oracle_bin, definition)
    except oracle_module.OracleFailure as error:
        return Outcome(b"", -1, f"oracle failed: {error}")
    return Outcome(result.stdout, result.exit_code)


def run_model(definition: dict) -> Outcome:
    filesystem = generate.build_filesystem(definition.get("fixture"))
    implemented = generate.model_option_set(definition)
    stdout, _subjects, exit_code = reference.run(
        list(definition["args"]), definition.get("stdin") or b"",
        filesystem, implemented,
    )
    return Outcome(stdout, exit_code)


def run_candidate(binary: str, definition: dict) -> Outcome:
    """The candidate under its own argv, in a throwaway tree."""
    fixture = definition.get("fixture")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        oracle_module.materialize(fixture, root)
        try:
            completed = subprocess.run(
                [os.path.abspath(binary), *definition["args"]],
                cwd=str(root),
                input=definition.get("stdin") or b"",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={**os.environ, **oracle_module.ORACLE_ENV},
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return Outcome(b"", -1, "candidate timed out")
        finally:
            oracle_module.restore_modes(fixture, root)
    return Outcome(completed.stdout, completed.returncode)


def compare(left: Outcome, right: Outcome) -> str | None:
    """What differs, or None. `left` is the implementation under test."""
    if left.error or right.error:
        return left.error or right.error
    if left.exit_code != right.exit_code:
        return f"exit status: under-test={left.exit_code} oracle={right.exit_code}"
    if left.stdout != right.stdout:
        return "stdout differs"
    return None


# --- minimization ------------------------------------------------------------

def _payloads(definition: dict) -> list[tuple]:
    """Addresses of every byte payload in a case, for bisection."""
    spots: list[tuple] = []
    if definition.get("stdin") is not None:
        spots.append(("stdin",))
    for index, entry in enumerate(definition.get("fixture") or []):
        if entry.get("type") == "file":
            spots.append(("fixture", index))
    return spots


def _get(definition: dict, spot: tuple) -> bytes:
    if spot[0] == "stdin":
        return definition["stdin"]
    return definition["fixture"][spot[1]]["contents"]


def _with(definition: dict, spot: tuple, data: bytes) -> dict:
    clone = _shallow(definition)
    if spot[0] == "stdin":
        clone["stdin"] = data
    else:
        clone["fixture"][spot[1]]["contents"] = data
    return clone


def _shallow(definition: dict) -> dict:
    clone = dict(definition)
    if "fixture" in clone:
        clone["fixture"] = [dict(e) for e in clone["fixture"]]
    return clone


def minimize(definition: dict, still_bad) -> dict:
    """Line-bisection, one payload at a time -- sort's approach, generalised.

    sort's cases have exactly one payload (stdin); grep's may have several
    files, so each is bisected in turn while the same class of deviation
    persists.
    """
    current = _shallow(definition)
    for spot in _payloads(current):
        lines = _get(current, spot).split(b"\n")
        changed = True
        while changed and len(lines) > 1:
            changed = False
            half = max(1, len(lines) // 2)
            for cut in (lines[:half], lines[half:]):
                probe = _with(current, spot, b"\n".join(cut))
                if still_bad(probe):
                    current = probe
                    lines = cut
                    changed = True
                    break
    return current


# --- regression recording ----------------------------------------------------

REGRESSIONS = SUITE_ROOT / "suites" / "fuzz_regressions.json.gz"


def load_regressions() -> dict:
    if not REGRESSIONS.is_file():
        return {"header": {
            "note": "auto-recorded fuzz findings",
            "generator": "diff_fuzz.py",
            "_provenance": (
                "Appended by diff_fuzz.py when the live differential fuzzer "
                "finds a disagreement between the implementation under test "
                "and the pinned GNU grep oracle. NOT reproducible by "
                "gen/generate.py: this file accretes across runs and is "
                "verified by replay, not by regeneration."),
        }, "cases": []}
    with gzip.open(REGRESSIONS, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def save_regressions(doc: dict) -> None:
    REGRESSIONS.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")
    # mtime=0 for the reason gen/generate.py pins it: a byte-reproducible
    # container, so re-saving an unchanged corpus is not a diff.
    REGRESSIONS.write_bytes(gzip.compress(payload, mtime=0))


def append_regression(doc: dict, definition: dict, reason: str,
                      oracle_bin: str, seed: int) -> dict:
    """Freeze the minimized repro through the ordinary generator path."""
    index = len(doc["cases"])
    case = dict(definition)
    case["name"] = f"fuzz-{seed}-{index:04d}"
    case["tags"] = ["fuzz-regression"]
    case["_reason"] = reason
    try:
        frozen = generate.freeze_case(case, oracle_bin)
    except Exception as error:                                # noqa: BLE001
        # Recorded rather than dropped: a repro the generator refuses to freeze
        # is itself a finding, and losing it would hide the disagreement. Note
        # that a model/oracle disagreement is EXACTLY what freeze_case raises
        # on, so in `--against model` mode this branch is the normal path.
        frozen = dict(case)
        frozen["_freeze_error"] = str(error)
        if isinstance(frozen.get("stdin"), bytes):
            frozen["stdin_b64"] = b64(frozen.pop("stdin"))
        for entry in frozen.get("fixture") or []:
            if isinstance(entry.get("contents"), bytes):
                entry["contents_b64"] = b64(entry.pop("contents"))
    doc["cases"].append(frozen)
    return frozen


# --- main --------------------------------------------------------------------

def implemented_flags(config_path: Path) -> set[str] | None:
    if not config_path.is_file():
        return None
    data = json.loads(config_path.read_text(encoding="utf-8"))
    flags = data.get("implemented")
    return set(flags) if isinstance(flags, list) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--against", choices=("model", "candidate"),
                        default="model")
    parser.add_argument("--candidate", help="candidate grep binary")
    parser.add_argument("--oracle-bin", default=None,
                        help="GNU grep; defaults to $GREP_ORACLE_BIN")
    parser.add_argument("--time-budget", type=float, default=60)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--record", action="store_true",
                        help="append findings to suites/fuzz_regressions.json.gz")
    parser.add_argument("--json-report")
    args = parser.parse_args(argv)

    oracle_bin = (args.oracle_bin or os.environ.get("GREP_ORACLE_BIN")
                  or generate.resolve_oracle(None))
    if args.against == "candidate" and not args.candidate:
        print("error: --against candidate needs --candidate PATH",
              file=sys.stderr)
        return 2

    implemented = implemented_flags(SUITE_ROOT / "config.json")
    rng = random.Random(args.seed)

    def under_test(definition: dict) -> Outcome:
        if args.against == "candidate":
            return run_candidate(args.candidate, definition)
        return run_model(definition)

    def evaluate(definition: dict) -> str | None:
        return compare(under_test(definition), run_oracle(oracle_bin, definition))

    print(f"oracle:  {oracle_bin}")
    print(f"under test: {args.against}"
          + (f" ({args.candidate})" if args.against == "candidate" else
             " (tests/reference_generators/grep_reference.py)"))
    print(f"budget: {args.time_budget}s  seed: {args.seed}  "
          f"implemented: {sorted(implemented) if implemented else 'all'}")

    doc = load_regressions()
    known = {(tuple(c.get("args", [])), c.get("_reason", "").split(":")[0])
             for c in doc.get("cases", [])}

    deadline = time.time() + args.time_budget
    rounds = findings = recorded = skipped = 0
    seen: set[tuple] = set()
    while time.time() < deadline:
        rounds += 1
        definition = sample_case(rng, implemented, rounds)
        # Belt and braces alongside the pattern sanitising above: anything the
        # model rejects at the argument level is oracle-exempt by design, and
        # `oracle.run_case` would raise rather than return a comparable result.
        try:
            reference.parse_args(list(definition["args"]))
        except reference.UsageError:
            skipped += 1
            continue
        reason = evaluate(definition)
        if reason is None:
            continue
        findings += 1
        smaller = minimize(definition, lambda d: evaluate(d) is not None)
        final = evaluate(smaller) or reason
        key = (tuple(smaller["args"]), final.split(":")[0])
        novel = key not in seen
        seen.add(key)
        print(f"[{'NEW' if novel else 'dup'}] args={smaller['args']} -> {final}")
        if novel and args.record and key not in known:
            append_regression(doc, smaller, final, oracle_bin, args.seed)
            known.add(key)
            recorded += 1

    if recorded:
        save_regressions(doc)

    print()
    print(f"rounds: {rounds}")
    print(f"skipped (argument-grammar, oracle-exempt): {skipped}")
    print(f"disagreements: {findings}")
    print(f"distinct (args, kind): {len(seen)}")
    print(f"new regression cases recorded: {recorded}"
          + ("" if args.record else "   (--record not given; nothing written)"))
    if findings == 0:
        print("\nRESULT: CLEAN -- no disagreement found in this budget.")
    else:
        print("\nRESULT: DISAGREEMENTS FOUND (listed above).")

    if args.json_report:
        Path(args.json_report).write_text(json.dumps({
            "rounds": rounds, "disagreements": findings,
            "distinct": len(seen), "recorded": recorded,
            "against": args.against, "oracle": oracle_bin,
            "seed": args.seed, "time_budget": args.time_budget,
        }, indent=1) + "\n", encoding="utf-8")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
