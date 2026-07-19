#!/usr/bin/env python3
"""
Differential fuzzer: candidate vs GNU mkdir, live, seeded, time-boxed.

Each round: sample a flag combo (weighted toward the manifest's implemented
flags) and a target -- a corpus path/fixture pair, mutated to escape the
fixed corpus (extra/dropped path components, injected "..", pre-created
blockers, trailing slashes, umask changes). Run both binaries through the
shared engine under identical conditions and compare: a candidate signal-
death / timeout / sanitizer hit is always a finding; otherwise compare exit
code, the full filesystem tree, and stdout (for -v).

On any mismatch the target is minimized (shrink the fixture, then shorten
the path) and a frozen schema-v2 repro case is appended to
suites/fuzz_regressions.json(.gz), so every finding becomes a permanent
regression test.

Both the oracle binary and the candidate default to the paths declared in
config.json (paths.oracle_bin / paths.candidate_bin) -- pass
--candidate/--oracle explicitly to override.

Usage:
  diff_fuzz.py --config config.json --time-budget 60 --seed 1
  diff_fuzz.py --candidate ./my-mkdir --oracle /usr/bin/mkdir --time-budget 60
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import random
import sys
import time

import engine
from corpus import corpus as corpus_mod
from gen import combos
from gen import freeze
from model import flag_model as fm
from model import constraints as ct
from runner import _tree_diff
import config as cfgmod


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


FUZZ_POOL = ["-p", "-v", "-m"]
_UMASKS = ["0000", "0022", "0077"]

# Oracle binary path -- set once in main() from config/CLI, read by
# run_both()/minimize() so their call signatures stay unchanged.
_ORACLE_BIN = "/usr/bin/mkdir"


def load_manifest(config_path):
    if not config_path or not os.path.exists(config_path):
        return None
    cfg = cfgmod.load(config_path)
    impl = cfgmod.get(cfg, "implemented")
    return set(impl) if impl else None


def sample_combo(rng, implemented):
    """Sample a flag combo, drawing only from implemented flags when a
    manifest is given (so every deviation is a genuine correctness bug, not
    an unimplemented-feature artifact); crashes are caught either way. -m's
    value is mostly valid, occasionally deliberately invalid."""
    pool = [f for f in FUZZ_POOL if f in implemented] if implemented \
        else list(FUZZ_POOL)
    if not pool:
        pool = list(FUZZ_POOL)
    k = rng.randint(1, len(pool))
    chosen = rng.sample(pool, k)
    values, flag_argv = {}, []
    for fid in chosen:
        if fid == "-m":
            invalid = rng.random() < 0.2
            pool_v = (fm.FLAGS["-m"]["values"]["invalid"] if invalid
                     else fm.FLAGS["-m"]["values"]["valid"])
            v = rng.choice(pool_v)
        else:
            v = fm.default_value(fid)
        if v is not None:
            values.setdefault(fid, []).append(v)
        flag_argv += fm.to_argv(fid, v) if v is not None else [fid]
    return chosen, flag_argv


def sample_target(rng, corpus_all):
    name = rng.choice(list(corpus_all))
    t = corpus_all[name]
    return {"args": list(t["args"]), "fixture": [dict(e) for e in t.get("fixture", [])],
           "needs_dashdash": t.get("needs_dashdash", False)}


def mutate_target(rng, target):
    """Cheap path/fixture mutations to escape the fixed corpus."""
    args = list(target["args"])
    fixture = [dict(e) for e in target["fixture"]]
    if not args:
        return target
    idx = rng.randrange(len(args))
    path = args[idx]
    parts = [p for p in path.split("/") if p != ""] or ["x"]
    op = rng.randint(0, 5)
    if op == 0:                                   # add a component
        parts.append(f"x{rng.randint(0, 999)}")
    elif op == 1 and len(parts) > 1:               # drop a component
        del parts[rng.randrange(len(parts))]
    elif op == 2:                                  # inject a self-cancelling
        # "x/.." pair: exercises dot-segment handling WITHOUT ever making
        # the path resolve outside the sandboxed temp dir (a bare ".."
        # would have mkdir operate on the real filesystem above td -- see
        # the safety note on _safe_join in engine.py).
        pos = rng.randrange(len(parts) + 1)
        parts[pos:pos] = [f"tmp{rng.randint(0, 999)}", ".."]
    elif op == 3:                                  # trailing slash toggle
        path = "/".join(parts)
        args[idx] = path if path.endswith("/") else path + "/"
        return {"args": args, "fixture": fixture,
               "needs_dashdash": target["needs_dashdash"]}
    elif op == 4:                                  # pre-create this path
        fixture.append({"path": "/".join(parts), "type": "dir", "mode": "0755"})
    else:                                           # a FILE blocks a middle component
        if len(parts) > 1:
            blocker = "/".join(parts[:-1])
            fixture.append({"path": blocker, "type": "file", "mode": "0644",
                            "contents_b64": ""})
    args[idx] = "/".join(parts)
    return {"args": args, "fixture": fixture,
           "needs_dashdash": target["needs_dashdash"]}


def make_probe(flag_argv, target, umask):
    args = combos._target_argv(flag_argv, target)
    return {"schema": 2, "name": "fuzz", "args": args,
           "fixture": target["fixture"], "umask": umask, "timeout": 10}


def run_both(cand, flag_argv, target, umask):
    probe = make_probe(flag_argv, target, umask)
    rc = engine.execute(probe, [cand])
    rg = engine.execute(probe, [_ORACLE_BIN])
    return rc, rg, probe


def mismatch(rc, rg, probe):
    """Return a reason string if candidate deviates, else None. Candidate
    crash/timeout is always a finding."""
    if rc.timed_out:
        return "candidate TIMEOUT"
    if rc.crashed:
        return f"candidate CRASH {rc.signal_name}"
    if rc.sanitizer:
        return f"candidate SANITIZER {rc.sanitizer[:80]}"
    if rg.timed_out or rg.crashed:
        return None  # GNU itself couldn't handle this input; not comparable
    if rc.exit_code != rg.exit_code:
        return f"exit {rc.exit_code} vs GNU {rg.exit_code}"
    diff = _tree_diff(rg.tree, rc.tree)
    if diff:
        return f"tree differs: {diff}"
    if rc.stdout != rg.stdout:
        return "stdout differs"
    return None


def explain(rc: "engine.Result", rg: "engine.Result", reason: str) -> str:
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
    elif reason.startswith("tree differs"):
        lines.append(f"detail: {reason}")
    elif reason == "stdout differs":
        lines.append(f"candidate stdout: {rc.stdout[:300]!r}")
        lines.append(f"gnu stdout:       {rg.stdout[:300]!r}")
    return "\n".join(f"      {l}" for l in lines)


def minimize(cand, flag_argv, target, umask):
    """Shrink the fixture (drop entries), then shorten the first operand's
    path (drop components), while the same class of deviation persists."""
    def still_bad(t):
        try:
            rc, rg, probe = run_both(cand, flag_argv, t, umask)
        except (engine.SandboxEscapeError, OSError):
            # shrinking a path/fixture can unbalance a self-cancelling
            # "x/.." pair or produce a colliding fixture entry -- treat as
            # "not a valid/reproducible shrink", not a bug.
            return False
        return mismatch(rc, rg, probe) is not None

    fixture = list(target["fixture"])
    changed = True
    while changed and fixture:
        changed = False
        for i in range(len(fixture)):
            trial = fixture[:i] + fixture[i + 1:]
            t2 = {"args": target["args"], "fixture": trial,
                 "needs_dashdash": target["needs_dashdash"]}
            if still_bad(t2):
                fixture = trial
                changed = True
                break
    target = {"args": target["args"], "fixture": fixture,
             "needs_dashdash": target["needs_dashdash"]}

    args = list(target["args"])
    if args:
        parts = args[0].split("/")
        changed = True
        while changed and len(parts) > 1:
            changed = False
            for i in range(len(parts)):
                trial_parts = parts[:i] + parts[i + 1:]
                if not trial_parts:
                    continue
                trial_args = ["/".join(trial_parts)] + args[1:]
                t2 = {"args": trial_args, "fixture": fixture,
                     "needs_dashdash": target["needs_dashdash"]}
                if still_bad(t2):
                    parts = trial_parts
                    args = trial_args
                    changed = True
                    break
        target = {"args": args, "fixture": fixture,
                 "needs_dashdash": target["needs_dashdash"]}
    return target


def _regressions_path() -> str:
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


def append_regression(flag_argv, target, umask, reason, seed):
    path = _regressions_path()
    doc = _load_regressions(path)
    n = len(doc["cases"])
    full_args = combos._target_argv(flag_argv, target)
    case = {"schema": 2, "name": f"fuzz-{seed}-{n:04d}",
            "args": full_args, "tags": ["fuzz-regression"], "check": "golden",
            "umask": umask,
            "flags": sorted({_id(t) for t in flag_argv if t.startswith("-")}),
            "_reason": reason}
    if target.get("fixture"):
        case["fixture"] = target["fixture"]
    try:
        case = freeze.freeze_case(case, mkdir_bin=_ORACLE_BIN)
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
                         "(default /usr/bin/mkdir)")
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
                                             "/usr/bin/mkdir")

    cand = os.path.abspath(candidate)
    implemented = load_manifest(args.config)
    rng = random.Random(args.seed)
    corpus_all = dict(corpus_mod.build_core())
    corpus_all.update(corpus_mod.build_adversarial(args.seed))

    known_before = set()
    for c in _load_regressions(_regressions_path()).get("cases", []):
        known_before.add((tuple(c.get("args", [])),
                          c.get("_reason", "").split(":")[0]))

    deadline = time.time() + args.time_budget
    rounds = findings = new_regressions = 0
    seen_reasons = set()
    while time.time() < deadline:
        rounds += 1
        chosen, flag_argv = sample_combo(rng, implemented)
        target = sample_target(rng, corpus_all)
        for _ in range(rng.randint(0, 3)):
            target = mutate_target(rng, target)
        umask = rng.choice(_UMASKS)

        try:
            rc, rg, probe = run_both(cand, flag_argv, target, umask)
        except (engine.SandboxEscapeError, OSError):
            # a mutation produced either a path that would escape the
            # sandboxed temp dir, or a self-contradictory fixture (e.g. two
            # entries whose paths collide after normalization, like "p" and
            # "p/."). Both are harness-generated-probe defects, not
            # candidate bugs -- skip the round rather than crash the fuzzer.
            continue
        reason = mismatch(rc, rg, probe)
        if reason is None:
            continue
        findings += 1
        mini = minimize(cand, flag_argv, target, umask)
        rc2, rg2, probe2 = run_both(cand, flag_argv, mini, umask)
        final_reason = mismatch(rc2, rg2, probe2) or reason
        key = (tuple(flag_argv), final_reason.split(":")[0])
        novel = key not in seen_reasons
        seen_reasons.add(key)
        tag = "NEW" if novel else "dup"
        print(f"[{tag}] flags={flag_argv} target={mini['args']!r} "
              f"umask={umask} -> {final_reason}")
        if novel:
            print(explain(rc2, rg2, final_reason))
            if key not in known_before:
                append_regression(flag_argv, mini, umask, final_reason, args.seed)
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
