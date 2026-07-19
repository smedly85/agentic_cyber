#!/usr/bin/env python3
"""
Differential fuzzer: candidate vs GNU sort, live, seeded, time-boxed.

Each round: sample a valid flag combo (weighted toward the manifest's
implemented flags) and an input (a corpus file or a mutation of one). Run
both binaries through the shared engine under identical conditions and
compare. A candidate signal-death / timeout / sanitizer hit is a CRASH
regardless of what GNU did; otherwise compare exit code + stdout bytes
(permutation property when the combo shuffles).

On any mismatch the input is minimized by line-bisection and a frozen
schema-v2 repro case is appended to suites/fuzz_regressions.json(.gz), so
every finding becomes a permanent regression test.

Both the oracle binary and the candidate default to the paths declared in
config.json (paths.oracle_bin / paths.candidate_bin) -- nothing is
hardcoded; pass --candidate/--oracle explicitly to override.

Usage:
  diff_fuzz.py --config config.json --time-budget 60 --seed 1
  diff_fuzz.py --candidate ./my-sort --oracle /usr/bin/sort --time-budget 60
"""
from __future__ import annotations

import argparse
import base64
import difflib
import gzip
import json
import os
import random
import sys
import time

import engine
import props
from corpus import corpus as corpus_mod
from gen import combos
from model import flag_model as fm
from model import constraints as ct
import config as cfgmod


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


FUZZ_POOL = ["-b", "-d", "-f", "-g", "-h", "-i", "-M", "-n", "-r", "-V",
             "-R", "-s", "-u", "-z", "-c", "-C", "-k", "-t", "-S",
             "--parallel", "--batch-size"]

# Oracle binary path -- set once in main() from config/CLI, read by
# run_both()/minimize() so their call signatures stay unchanged.
_ORACLE_BIN = "/usr/bin/sort"


def load_manifest(config_path):
    if not config_path or not os.path.exists(config_path):
        return None
    cfg = cfgmod.load(config_path)
    impl = cfgmod.get(cfg, "implemented")
    return set(impl) if impl else None


def sample_combo(rng, implemented):
    """Sample a VALID combo. With a manifest, draw ONLY from implemented
    flags so every stdout deviation is a genuine correctness bug (not an
    unimplemented-feature artifact); crashes are caught either way."""
    pool = [f for f in FUZZ_POOL if f in implemented] if implemented \
        else list(FUZZ_POOL)
    if not pool:
        pool = list(FUZZ_POOL)
    for _ in range(50):
        k = rng.randint(1, min(6, len(pool)))
        chosen = []
        for _ in range(k):
            f = rng.choice(pool)
            if f not in chosen:
                chosen.append(f)
        values, argv = {}, []
        for fid in chosen:
            v = fm.default_value(fid)
            if v is not None and v.startswith("@"):
                v = None
            if v is not None:
                values.setdefault(fid, []).append(v)
            argv += fm.to_argv(fid, v) if v is not None else [fid]
        if ct.is_valid(chosen, values) == ct.OK:
            return chosen, argv
    return ["-n"], ["-n"]


def mutate(rng, data: bytes) -> bytes:
    """Cheap byte/line mutations to escape the fixed corpus."""
    op = rng.randint(0, 5)
    lines = data.split(b"\n")
    if op == 0 and len(lines) > 1:                       # drop a line
        del lines[rng.randrange(len(lines))]
    elif op == 1:                                        # duplicate a line
        if lines:
            lines.append(lines[rng.randrange(len(lines))])
    elif op == 2 and data:                               # flip a byte
        i = rng.randrange(len(data))
        b = bytearray(data)
        b[i] ^= 1 << rng.randint(0, 7)
        return bytes(b)
    elif op == 3:                                        # insert a NUL
        i = rng.randrange(len(data) + 1)
        return data[:i] + b"\x00" + data[i:]
    elif op == 4:                                        # shuffle lines
        rng.shuffle(lines)
    else:                                                # splice random digits
        lines.append(str(rng.randint(-10**9, 10**9)).encode())
    return b"\n".join(lines)


def make_probe(argv, data, check):
    return {"schema": 2, "name": "fuzz", "args": list(argv),
            "stdin_b64": _b64(data), "check": check, "timeout": 10}


def run_both(cand, argv, data):
    # reuse the generator's exact policy: property:shuffle / "none" (random +
    # check-mode/--debug: nondeterministic) / golden.
    check = combos.shuffle_check(argv) or "golden"
    nondet_exit = combos._random_mode(argv) and combos._check_mode_only(argv)
    probe = make_probe(argv, data, check)
    probe["_nondet_exit"] = nondet_exit
    rc = engine.execute(probe, [cand], stdin_mode="pipe")
    rg = engine.execute(probe, [_ORACLE_BIN], stdin_mode="pipe")
    return rc, rg, check, probe


def mismatch(rc, rg, check, probe):
    """Return a reason string if candidate deviates, else None. Candidate
    crash/timeout is always a finding."""
    if rc.timed_out:
        return "candidate TIMEOUT"
    if rc.crashed:
        return f"candidate CRASH {rc.signal_name}"
    if rc.sanitizer:
        return f"candidate SANITIZER {rc.sanitizer[:80]}"
    # if GNU itself crashed/timed out on this input, skip (not comparable)
    if rg.timed_out or rg.crashed:
        return None
    # random + check-mode: exit code and output are both nondeterministic;
    # only crashes matter (handled above).
    if check == "none" and probe.get("_nondet_exit"):
        return None
    if rc.exit_code != rg.exit_code:
        return f"exit {rc.exit_code} vs GNU {rg.exit_code}"
    if check == "property:shuffle":
        ok, detail = props.check_shuffle(probe, rc)
        return None if ok else f"property: {detail}"
    if check == "none":
        return None
    if rc.stdout != rg.stdout:
        return "stdout differs"
    return None


def _repr_lines(data: bytes, limit: int = 4000) -> list[str]:
    """Split on b'\\n' and repr() each line so a diff is safe on arbitrary
    bytes (NUL, invalid UTF-8) and unambiguous about whitespace."""
    return [repr(l) for l in data[:limit].split(b"\n")]


def explain(rc: "engine.Result", rg: "engine.Result", reason: str,
            check: str) -> str:
    """Human-readable, indented detail block for one mismatch: the actual
    outputs/diff, not just the one-line reason. Safe on arbitrary bytes."""
    lines: list[str] = []
    if reason.startswith("candidate CRASH") or reason == "candidate TIMEOUT":
        lines.append(f"candidate: exit={rc.exit_code} signal={rc.signal_name}")
        if rc.stderr:
            lines.append(f"candidate stderr: {rc.stderr[:300]!r}")
    elif reason.startswith("candidate SANITIZER"):
        lines.append(f"sanitizer report: {(rc.sanitizer or '')[:500]}")
    elif reason.startswith("exit "):
        lines.append(f"candidate: exit={rc.exit_code}  stderr={rc.stderr[:200]!r}")
        lines.append(f"gnu:       exit={rg.exit_code}  stderr={rg.stderr[:200]!r}")
        if rc.stdout != rg.stdout:
            lines.append(f"candidate stdout: {rc.stdout[:200]!r}")
            lines.append(f"gnu stdout:       {rg.stdout[:200]!r}")
    elif reason.startswith("property:"):
        lines.append(f"detail: {reason}")
        lines.append(f"candidate stdout: {rc.stdout[:300]!r}")
    elif reason == "stdout differs":
        a, b = _repr_lines(rc.stdout), _repr_lines(rg.stdout)
        diff = list(difflib.unified_diff(
            a, b, fromfile="candidate", tofile="gnu", lineterm="", n=1))
        if len(diff) > 24:
            diff = diff[:24] + [f"... ({len(diff) - 24} more diff lines)"]
        lines.extend(diff or ["(no line-level diff -- check trailing bytes)"])
    return "\n".join(f"      {l}" for l in lines)


def minimize(cand, argv, data, orig_reason):
    """Line-bisection minimization: repeatedly drop halves of the lines while
    the same class of deviation persists."""
    def still_bad(d):
        rc, rg, check, probe = run_both(cand, argv, d)
        return mismatch(rc, rg, check, probe) is not None
    lines = data.split(b"\n")
    changed = True
    while changed and len(lines) > 1:
        changed = False
        half = max(1, len(lines) // 2)
        for cut in (lines[:half], lines[half:]):
            cand_data = b"\n".join(cut)
            if still_bad(cand_data):
                lines = cut
                changed = True
                break
    return b"\n".join(lines)


def _regressions_path() -> str:
    """Whichever of the plain/gzipped forms already exists wins; if neither
    exists yet, default to the gzipped form (matches the shipped suites)."""
    base = os.path.join(os.path.dirname(__file__), "suites",
                        "fuzz_regressions.json")
    if os.path.exists(base):
        return base
    return base + ".gz"


def _load_regressions(path):
    if not os.path.exists(path):
        return {"header": {"note": "auto-recorded fuzz findings"}, "cases": []}
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        return json.load(f)


def _save_regressions(path, doc):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "wt") as f:
        json.dump(doc, f, indent=1, sort_keys=True)


def append_regression(argv, data, check, reason, seed):
    path = _regressions_path()
    doc = _load_regressions(path)
    # freeze GNU golden for the (minimized) repro
    from gen import freeze
    n = len(doc["cases"])
    case = {"schema": 2, "name": f"fuzz-{seed}-{n:04d}",
            "args": list(argv), "stdin_b64": _b64(data),
            "tags": ["fuzz-regression"], "check": check,
            "flags": sorted({_id(t) for t in argv if t.startswith("-")}),
            "_reason": reason}
    try:
        case = freeze.freeze_case(case, sort_bin=_ORACLE_BIN, stdin_mode="pipe")
    except Exception as e:                              # noqa: BLE001
        case["_freeze_error"] = str(e)
    doc["cases"].append(case)
    _save_regressions(path, doc)
    return path


def _id(tok):
    return tok.split("=")[0] if tok.startswith("--") else tok[:2]


def main():
    global _ORACLE_BIN
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json",
                    help="path to config.json (default: ./config.json)")
    ap.add_argument("--candidate",
                    help="defaults to paths.candidate_bin in --config")
    ap.add_argument("--oracle",
                    help="defaults to paths.oracle_bin in --config "
                         "(default /usr/bin/sort)")
    ap.add_argument("--time-budget", type=float, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json-report", help="write machine-readable summary here")
    args = ap.parse_args()

    cfg = cfgmod.load(args.config) if os.path.exists(args.config) else {}
    candidate = args.candidate or cfgmod.get(cfg, "paths.candidate_bin")
    if not candidate:
        print("error: no candidate binary -- pass --candidate or set "
              "paths.candidate_bin in config.json", file=sys.stderr)
        sys.exit(2)
    _ORACLE_BIN = args.oracle or cfgmod.get(cfg, "paths.oracle_bin",
                                             "/usr/bin/sort")

    cand = os.path.abspath(candidate)
    implemented = load_manifest(args.config)
    rng = random.Random(args.seed)
    corpus = corpus_mod.build_core()
    names = list(corpus)

    # Cross-run dedup: a bug already captured as a regression case in an
    # earlier run must not be re-appended just because this run tripped
    # over it again -- otherwise suites/fuzz_regressions.json (and the
    # golden pass/fail totals that replay it) grow every single run even
    # though no new bug was found.
    known_before = set()
    for c in _load_regressions(_regressions_path()).get("cases", []):
        known_before.add((tuple(c.get("args", [])),
                          c.get("_reason", "").split(":")[0]))

    deadline = time.time() + args.time_budget
    rounds = findings = new_regressions = 0
    seen_reasons = set()
    while time.time() < deadline:
        rounds += 1
        chosen, argv = sample_combo(rng, implemented)
        data = corpus[rng.choice(names)]
        for _ in range(rng.randint(0, 3)):
            data = mutate(rng, data)
        rc, rg, check, probe = run_both(cand, argv, data)
        reason = mismatch(rc, rg, check, probe)
        if reason is None:
            continue
        findings += 1
        mini = minimize(cand, argv, data, reason)
        rc2, rg2, check2, probe2 = run_both(cand, argv, mini)
        final_reason = mismatch(rc2, rg2, check2, probe2) or reason
        key = (tuple(argv), final_reason.split(":")[0])
        novel = key not in seen_reasons
        seen_reasons.add(key)
        tag = "NEW" if novel else "dup"
        print(f"[{tag}] args={argv} input={mini[:40]!r} -> {final_reason}")
        if novel:
            print(explain(rc2, rg2, final_reason, check2))
            if key not in known_before:
                append_regression(argv, mini, check2, final_reason, args.seed)
                known_before.add(key)
                new_regressions += 1
            else:
                print("      (already recorded from a previous fuzz run; "
                      "not re-appended)")
        else:
            print("      (repeat of an already-reported bug for this "
                  "flag combo/category -- see prior [NEW] block above)")

    pass_n = rounds - findings
    pass_pct = 100.0 * pass_n / rounds if rounds else 100.0
    fail_pct = 100.0 * findings / rounds if rounds else 0.0
    print("\n=== fuzz summary ===")
    print(f"  rounds:          {rounds}")
    print(f"  pass:            {pass_n} ({pass_pct:.1f}%)")
    print(f"  fail (raw):      {findings} ({fail_pct:.1f}%)   "
          f"<- one per round; includes repeated hits of the same bug")
    print(f"  distinct issues: {len(seen_reasons)}   "
          f"<- unique (flags, failure-type) pairs -- use THIS for a bug "
          f"count, not 'fail (raw)'")
    print(f"  new regressions recorded: {new_regressions} "
          f"(suites/fuzz_regressions.json)")

    if args.json_report:
        with open(args.json_report, "w") as f:
            json.dump({
                "rounds": rounds, "pass": pass_n, "fail": findings,
                "pass_pct": pass_pct, "fail_pct": fail_pct,
                "distinct_issues": len(seen_reasons),
                "new_regressions": new_regressions,
            }, f, indent=1)
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
