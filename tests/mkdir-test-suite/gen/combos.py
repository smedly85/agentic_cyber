#!/usr/bin/env python3
"""
Case builders and combinators. Produce *unfrozen* case skeletons (args,
flags, tags, fixture, umask, check policy); gen/freeze.py fills in the
goldens.

Unlike sort, a mkdir case's "input" is a path-operand target (see
corpus.py) plus a starting fixture, not stdin bytes. Exhaustiveness for
mkdir centers on sweeping -m's full mode-value pool CROSSED with a umask
sweep (gen_singles), since the resulting directory mode depends on both --
that interaction is the heart of mkdir correctness.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model import flag_model as fm          # noqa: E402
from model import constraints as ct         # noqa: E402

UMASK_SWEEP = ["0000", "0022", "0077"]


def make_case(name, argv, flag_ids, fixture, *, tags=None, check="golden",
             umask=None, abs_targets=None, faults=None, rule_id=None,
             exact_stderr=False, env=None, timeout=None,
             allow_signals=None, nondet_exit=False):
    """Build one unfrozen skeleton."""
    case = {
        "schema": 2,
        "name": name,
        "args": list(argv),
        "flags": sorted(set(flag_ids)),
        "tags": list(tags or []),
        "check": check,
    }
    if fixture:
        case["fixture"] = list(fixture)
    if umask is not None:
        case["umask"] = umask
    if abs_targets:
        case["abs_targets"] = list(abs_targets)
    if faults is not None:
        case["faults"] = faults
    if rule_id is not None:
        case["rule_id"] = rule_id
    if exact_stderr:
        case["exact_stderr"] = True
    if env is not None:
        case["env"] = env
    if timeout is not None:
        case["timeout"] = timeout
    if allow_signals is not None:
        case["allow_signals"] = allow_signals
    if nondet_exit:
        case["nondet_exit"] = True
    return case


def _target_argv(flag_argv, target):
    """Combine rendered flag tokens with a corpus target's operand args,
    inserting '--' first if the target's operands need it (leading-dash
    names)."""
    args = list(target["args"])
    if target.get("needs_dashdash"):
        return flag_argv + ["--"] + args
    return flag_argv + args


# --- singles -----------------------------------------------------------------

def _targets_for(fid, corpus):
    names = fm.preferred_inputs(fid) or ["simple"]
    names = [n for n in names if n in corpus]
    return names or ["simple"]


def gen_singles(corpus):
    """Every flag in isolation, plus a bare `mkdir TARGET` baseline. Value
    flags sweep their full valid pool; -m additionally crosses that pool
    with a umask sweep (the umask x -m interaction IS mkdir correctness).
    Invalid values are emitted as negatives."""
    cases = []
    for fid, spec in fm.FLAGS.items():
        base_tags = fm.tags_for(fid) + ["single"]
        if fid in ("--help", "--version"):
            cases.append(_single_case(fid, None, "none", corpus, base_tags))
            continue
        target_names = _targets_for(fid, corpus)
        if spec["kind"] == "bool":
            for tname in target_names:
                cases.append(_single_case(fid, None, tname, corpus, base_tags))
        elif fid == "-m":
            base_target = target_names[0]
            for value in spec["values"]["valid"]:
                for um in UMASK_SWEEP:
                    cases.append(_single_case(fid, value, base_target, corpus,
                                              base_tags, umask=um))
            for value in spec["values"]["invalid"]:
                neg = _single_negative(fid, value, corpus, base_tags)
                if neg:
                    cases.append(neg)
        else:
            for value in spec["values"]["valid"]:
                for tname in target_names[:2]:
                    cases.append(_single_case(fid, value, tname, corpus,
                                              base_tags))
            for value in spec["values"]["invalid"]:
                neg = _single_negative(fid, value, corpus, base_tags)
                if neg:
                    cases.append(neg)

    for tname in ("simple", "multi"):
        if tname in corpus:
            for um in UMASK_SWEEP:
                cases.append(_bare_case(tname, corpus, um))
    return cases


def _single_case(fid, value, tname, corpus, base_tags, umask=None):
    if fid in ("--help", "--version"):
        name = _cn("single", fid, None, "none")
        return make_case(name, [fid], [fid], None, tags=base_tags,
                         check="golden")
    target = corpus[tname]
    flag_argv = fm.to_argv(fid, value) if value is not None else [fid]
    argv = _target_argv(flag_argv, target)
    name = _cn("single", fid, value, tname, umask)
    return make_case(name, argv, [fid], target.get("fixture"),
                     tags=base_tags, check="golden", umask=umask,
                     abs_targets=target.get("abs_targets"))


def _single_negative(fid, value, corpus, base_tags):
    rule = _negative_rule(fid, value)
    if rule is None:
        return None
    target = corpus.get("simple", {"args": ["negdir"], "fixture": []})
    argv = _target_argv(fm.to_argv(fid, value), target)
    name = _cn("neg", fid, value, "simple")
    return make_case(name, argv, [fid], target.get("fixture"),
                     tags=base_tags + ["negative"], rule_id=rule,
                     exact_stderr=True, check="golden")


def _negative_rule(fid, value):
    vals = {fid: [value]}
    verdict = ct.is_valid([fid], vals)
    if verdict == ct.OK:
        return None
    return verdict[1]


def _bare_case(tname, corpus, umask):
    target = corpus[tname]
    argv = _target_argv([], target)
    name = f"bare-{tname}-um{umask}"
    return make_case(name, argv, [], target.get("fixture"),
                     tags=["single", "bare"], check="golden", umask=umask,
                     abs_targets=target.get("abs_targets"))


# --- pairs -------------------------------------------------------------------

def gen_pairs(corpus):
    """All unordered pairs of flags (doc flags don't pair). mkdir has no
    flag-combination conflicts (only -m's own VALUE can be invalid), so
    every pair with a valid -m default routes positive."""
    cases = []
    ids = [f for f in fm.all_flag_ids() if f not in ("--help", "--version")]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            case = _pair_case(ids[i], ids[j], corpus)
            if case:
                cases.append(case)
    return cases


def _pair_target(a, b, corpus):
    ids = {a, b}
    if "-p" in ids and "nested" in corpus:
        return corpus["nested"]
    if "-v" in ids and "multi" in corpus:
        return corpus["multi"]
    return corpus["simple"]


def _pair_case(a, b, corpus):
    va, vb = fm.default_value(a), fm.default_value(b)
    values = {}
    flag_argv = []
    for fid, v in ((a, va), (b, vb)):
        if v is not None:
            values.setdefault(fid, []).append(v)
        flag_argv += fm.to_argv(fid, v) if v is not None else [fid]

    target = _pair_target(a, b, corpus)
    verdict = ct.is_valid([a, b], values)
    tags = ["pair"] + fm.tags_for(a) + fm.tags_for(b)
    argv = _target_argv(flag_argv, target)
    tname = "nested" if target is corpus.get("nested") else (
        "multi" if target is corpus.get("multi") else "simple")

    if verdict == ct.OK:
        name = _cn("pair", a, b, tname)
        return make_case(name, argv, [a, b], target.get("fixture"),
                         tags=tags, check="golden",
                         abs_targets=target.get("abs_targets"))
    rule = verdict[1]
    name = _cn("pairneg", a, b, tname)
    return make_case(name, argv, [a, b], target.get("fixture"),
                     tags=tags + ["negative"], rule_id=rule,
                     exact_stderr=True)


# --- random higher-order combos ---------------------------------------------

# mkdir's flag surface is tiny (unlike sort's 20+ flags), so the "random"
# tier's exhaustiveness comes from crossing a small flag pool against many
# targets and umasks, not from a huge flag combinatorial space.
_RANDOM_POOL = ["-p", "-v", "-m"]
_RANDOM_TARGETS = ["simple", "multi", "nested", "existing", "partial",
                   "trailing_slash", "dot_segments"]


def gen_random(corpus, seed, n_valid=60, n_invalid=20):
    """Seeded combos over {-p,-v,-m} x target x umask. Occasionally forces
    an invalid -m value so the tier also exercises negative routing.
    Deterministic for a fixed seed."""
    import random as _r
    rng = _r.Random(seed)
    cases = []
    got_valid = got_invalid = 0
    attempts = 0
    want = n_valid + n_invalid
    targets = [t for t in _RANDOM_TARGETS if t in corpus]

    while (got_valid < n_valid or got_invalid < n_invalid) and attempts < want * 60:
        attempts += 1
        k = rng.randint(1, len(_RANDOM_POOL))
        chosen = rng.sample(_RANDOM_POOL, k)
        force_invalid = "-m" in chosen and rng.random() < 0.3
        values = {}
        flag_argv = []
        for fid in chosen:
            if fid == "-m":
                pool = (fm.FLAGS["-m"]["values"]["invalid"] if force_invalid
                       else fm.FLAGS["-m"]["values"]["valid"])
                v = rng.choice(pool)
            else:
                v = fm.default_value(fid)
            if v is not None:
                values.setdefault(fid, []).append(v)
            flag_argv += fm.to_argv(fid, v) if v is not None else [fid]

        tname = rng.choice(targets)
        target = corpus[tname]
        um = rng.choice(UMASK_SWEEP)
        argv = _target_argv(flag_argv, target)
        verdict = ct.is_valid(chosen, values)
        tags = ["random"] + [t for f in chosen for t in fm.tags_for(f)]
        sig = "-".join(sorted(f.lstrip("-") for f in chosen))

        if verdict == ct.OK:
            if got_valid >= n_valid:
                continue
            got_valid += 1
            name = f"rand-ok-{got_valid:03d}-{sig[:30]}-{tname}"
            cases.append(make_case(name, argv, chosen, target.get("fixture"),
                                   tags=tags, check="golden", umask=um,
                                   abs_targets=target.get("abs_targets")))
        else:
            if got_invalid >= n_invalid:
                continue
            got_invalid += 1
            name = f"rand-neg-{got_invalid:03d}-{sig[:30]}-{tname}"
            cases.append(make_case(name, argv, chosen, target.get("fixture"),
                                   tags=tags + ["negative"],
                                   rule_id=verdict[1], exact_stderr=True,
                                   umask=um))
    return cases


# --- naming ------------------------------------------------------------------

def _cn(prefix, *parts):
    def clean(p):
        if p is None:
            return "x"
        s = str(p)
        return (s.replace("--", "").replace("-", "").replace(",", "_")
                 .replace(".", "d").replace("\t", "TAB").replace(" ", "SP")
                 .replace("\n", "NL").replace("/", "_").replace(":", "_")
                 or "e")
    return prefix + "-" + "-".join(clean(p) for p in parts)
