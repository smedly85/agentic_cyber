#!/usr/bin/env python3
"""
Case builders and combinators. Produce *unfrozen* case skeletons (args,
flags, tags, input, check policy); gen/freeze.py fills in the goldens.

A skeleton always carries a bytes input via stdin_b64 (default) or files_b64
(+ explicit file operands in args). The generator resolves value-flag
placeholders (@RANDSRC@, @FILES0@) into concrete files here.
"""
from __future__ import annotations

import base64
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model import flag_model as fm          # noqa: E402
from model import constraints as ct         # noqa: E402


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


# a fixed 4 KiB random source, so --random-source is reproducible
RANDSRC_BYTES = bytes((i * 7 + 3) & 0xFF for i in range(4096))


def _flags_of(argv_ids: list[str], argv: list[str]) -> list[str]:
    """The manifest-filtering flag tag set for a case: the canonical IDs,
    plus the equivalent ordering flag for any --sort=WORD (so e.g.
    --sort=version requires -V to be implemented, not merely --sort)."""
    ids = set(argv_ids)
    for tok in argv:
        if tok.startswith("--sort="):
            eq = fm.SORT_WORD_EQUIV.get(tok.split("=", 1)[1])
            if eq:
                ids.add(eq)
    return sorted(ids)


def make_case(name, argv, flag_ids, input_name, input_bytes, *,
              tags=None, check="golden", stdin_modes=None,
              files=None, output_file=None, faults=None,
              rule_id=None, exact_stderr=False, env=None,
              timeout=None, use_stdin=True, allow_signals=None,
              nondet_exit=False):
    """Build one unfrozen skeleton. If use_stdin, input_bytes go to stdin;
    otherwise the caller has arranged file operands in `files`+`argv`."""
    tags = list(tags or [])
    case = {
        "schema": 2,
        "name": name,
        "args": list(argv),
        "flags": _flags_of(flag_ids, argv),
        "tags": tags,
        "check": check,
    }
    if use_stdin:
        case["stdin_b64"] = b64(input_bytes)
    if files:
        case["files_b64"] = {k: b64(v) for k, v in files.items()}
    if stdin_modes is not None:
        case["stdin_modes"] = stdin_modes
    if output_file is not None:
        case["output_file"] = output_file
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


def resolve_value(fid, value, files, corpus):
    """Turn a model value into (argv_tokens, extra_files, tags, check_override).
    Handles placeholder values that need materialized files."""
    tags = []
    check_override = None
    extra_files = {}
    if value == "@RANDSRC@":
        extra_files["randsrc"] = RANDSRC_BYTES
        argv = [fid, "randsrc"] if not fid.startswith("--") else [f"{fid}=randsrc"]
    elif value == "@FILES0@":
        # two NUL-terminated names -> two small presorted files
        extra_files["fa"] = b"a\nc\n"
        extra_files["fb"] = b"b\nd\n"
        extra_files["names0"] = b"fa\x00fb\x00"
        argv = [f"{fid}=names0"] if fid.startswith("--") else [fid, "names0"]
    else:
        argv = fm.to_argv(fid, value)
    return argv, extra_files, tags, check_override


# --- singles -----------------------------------------------------------------

def gen_singles(corpus):
    """Every flag in isolation. Value flags sweep their full valid pool;
    bool flags run once. Each runs against the flag's preferred inputs plus
    'discrim'. Value flags' invalid values are emitted as negatives."""
    cases = []
    for fid, spec in fm.FLAGS.items():
        base_tags = fm.tags_for(fid) + ["single"]
        input_names = _inputs_for(fid, corpus)
        if spec["kind"] == "bool":
            for iname in input_names:
                cases.append(_single_case(fid, None, iname, corpus, base_tags))
        else:
            for value in spec["values"]["valid"]:
                for iname in input_names[:2]:
                    cases.append(_single_case(fid, value, iname, corpus,
                                              base_tags))
            for value in spec["values"]["invalid"]:
                neg = _single_negative(fid, value, corpus, base_tags)
                if neg:
                    cases.append(neg)
    return cases


def _inputs_for(fid, corpus):
    names = fm.preferred_inputs(fid) or ["generic"]
    if "discrim" not in names and fid not in ("-o", "-m", "--files0-from",
                                              "--help", "--version"):
        names = names + ["discrim"]
    return [n for n in names if n in corpus]


def _random_mode(argv) -> bool:
    for tok in argv:
        if tok in ("--random-sort",) or tok == "--sort=random":
            return True
        if tok.startswith("-") and not tok.startswith("--"):
            for ch in tok[1:]:
                if ch == "R":
                    return True
                if ch in "kotST":   # value-consuming short flag
                    break
    return False


def _check_mode_only(argv) -> bool:
    """True if -c/-C/--check present (check mode), ignoring --debug."""
    for tok in argv:
        if tok in ("-c", "-C", "--check") or tok.startswith("--check="):
            return True
        if tok.startswith("-") and not tok.startswith("--"):
            for ch in tok[1:]:
                if ch in "cC":
                    return True
                if ch in "kotST":
                    break
    return False


def _check_or_debug(argv) -> bool:
    if _check_mode_only(argv):
        return True
    return "--debug" in argv


def shuffle_check(argv) -> str | None:
    """Return the check policy for a random-mode case:
      - property:shuffle  when it produces plain shuffled line output
      - none              when combined with check-mode/--debug (output is
                          empty or annotated, and exit code is nondeterministic
                          without a fixed --random-source)
      - None              when not a random-mode case
    """
    if not _random_mode(argv):
        return None
    if _check_or_debug(argv):
        return "none"
    return "property:shuffle"


def is_shuffle(argv) -> bool:
    return _random_mode(argv)


def _single_case(fid, value, iname, corpus, base_tags):
    inp = corpus[iname]
    check = "golden"

    # special-cased flags that need file operands / output files
    if fid == "-o":
        name = _cn("single", fid, value, iname)
        return make_case(name, ["-o", "out.txt"], [fid], iname, inp,
                         tags=base_tags, output_file={"path": "out.txt"},
                         stdin_modes=["pipe"])
    if fid == "-m":
        files = {"ma": corpus["merge_a"], "mb": corpus["merge_b"]}
        name = _cn("single", fid, value, "merge")
        return make_case(name, ["-m", "ma", "mb"], [fid], "merge",
                         b"", tags=base_tags, files=files,
                         stdin_modes=["pipe"], use_stdin=False)
    if fid in ("--help", "--version"):
        name = _cn("single", fid, value, "none")
        return make_case(name, [fid], [fid], "empty", b"",
                         tags=base_tags, stdin_modes=["pipe"])

    if value is not None:
        argv, extra_files, vtags, _ = resolve_value(fid, value, {}, corpus)
    else:
        argv, extra_files, vtags = [fid], {}, []
    sc = shuffle_check(argv)
    if sc:
        check = sc
    name = _cn("single", fid, value, iname)
    use_stdin = "--files0-from" not in fid
    files = extra_files or None
    if fid == "--files0-from":
        return make_case(name, argv, [fid], iname, b"", tags=base_tags + vtags,
                         files=files, stdin_modes=["pipe"], use_stdin=False,
                         check=check)
    return make_case(name, argv, [fid], iname, inp, tags=base_tags + vtags,
                     files=files, check=check,
                     stdin_modes=(["pipe"] if extra_files else None))


def _single_negative(fid, value, corpus, base_tags):
    inp = corpus.get("generic", b"a\nb\n")
    rule = _negative_rule(fid, value)
    if rule is None:
        return None
    argv = fm.to_argv(fid, value)
    name = _cn("neg", fid, value, "generic")
    return make_case(name, argv, [fid], "generic", inp,
                     tags=base_tags + ["negative"], rule_id=rule,
                     exact_stderr=True, check="golden",
                     stdin_modes=["pipe"])


def _negative_rule(fid, value):
    """Map an invalid single-flag value to its constraint rule id."""
    vals = {fid: [value]}
    verdict = ct.is_valid([fid], vals)
    if verdict == ct.OK:
        return None
    return verdict[1]


# --- pairs -------------------------------------------------------------------

def gen_pairs(corpus):
    """All unordered pairs of flags, using each flag's default value. Routed
    to positive or negative via constraints.is_valid."""
    cases = []
    ids = [f for f in fm.all_flag_ids()
           if f not in ("--help", "--version")]  # doc flags don't pair
    for a, b in itertools.combinations(ids, 2):
        case = _pair_case(a, b, corpus)
        if case:
            cases.append(case)
    return cases


def _pair_case(a, b, corpus):
    va, vb = fm.default_value(a), fm.default_value(b)
    values = {}
    if va is not None:
        values.setdefault(a, []).append(va)
    if vb is not None:
        values.setdefault(b, []).append(vb)

    # skip pairs needing bespoke file setup in the simple pair tier; those
    # are covered by curated/adversarial tiers.
    bespoke = {"-o", "-m", "--files0-from", "--random-source",
               "--compress-program", "-T"}
    if a in bespoke or b in bespoke:
        return None

    argv = []
    for fid, v in ((a, va), (b, vb)):
        if v is not None and v.startswith("@"):
            return None
        argv += fm.to_argv(fid, v)

    iname = _pair_input(a, b, corpus)
    inp = corpus[iname]
    verdict = ct.is_valid([a, b], values)
    tags = ["pair"] + fm.tags_for(a) + fm.tags_for(b)

    if verdict == ct.OK:
        check = shuffle_check(argv) or "golden"
        # random + check-mode has a nondeterministic exit code without a
        # fixed --random-source; don't assert it.
        nondet_exit = _random_mode(argv) and _check_mode_only(argv)
        name = _cn("pair", a, b, iname)
        return make_case(name, argv, [a, b], iname, inp, tags=tags,
                         check=check, stdin_modes=["pipe"],
                         nondet_exit=nondet_exit)
    else:
        rule = verdict[1]
        name = _cn("pairneg", a, b, iname)
        return make_case(name, argv, [a, b], iname, inp,
                         tags=tags + ["negative"], rule_id=rule,
                         exact_stderr=True, stdin_modes=["pipe"])


# --- random higher-order combos ---------------------------------------------

# flags safe to combine without bespoke file/output setup in the random tier
_RANDOM_POOL = ["-b", "-d", "-f", "-g", "-h", "-i", "-M", "-n", "-r", "-V",
                "-R", "-s", "-u", "-z", "-c", "-C", "--debug", "-k", "-t",
                "-S", "--parallel", "--batch-size"]


def gen_random(corpus, seed, n_valid=150, n_invalid=50):
    """Seeded k-order (k in 3..6) combos. Rejection-sample the pool; route
    to positive (property/golden) or negative via is_valid. Deterministic
    for a fixed seed."""
    import random as _r
    rng = _r.Random(seed)
    cases = []
    got_valid = got_invalid = 0
    attempts = 0
    want = n_valid + n_invalid
    while (got_valid < n_valid or got_invalid < n_invalid) and attempts < want * 60:
        attempts += 1
        k = rng.randint(3, 6)
        chosen = rng.sample(_RANDOM_POOL, k)
        values = {}
        argv = []
        for fid in chosen:
            v = fm.default_value(fid)
            if v is not None and v.startswith("@"):
                v = None
            if v is not None:
                values.setdefault(fid, []).append(v)
            argv += fm.to_argv(fid, v) if v is not None else [fid]
        verdict = ct.is_valid(chosen, values)
        iname = "discrim"
        for fid in chosen:
            for n in fm.preferred_inputs(fid):
                if n in corpus:
                    iname = n
                    break
        inp = corpus[iname]
        tags = ["random"] + [t for f in chosen for t in fm.tags_for(f)]
        sig = "-".join(sorted(chosen)).replace("--", "").replace("-", "")
        if verdict == ct.OK:
            if got_valid >= n_valid:
                continue
            got_valid += 1
            check = shuffle_check(argv) or "golden"
            nde = _random_mode(argv) and _check_mode_only(argv)
            name = f"rand-ok-{got_valid:03d}-{sig[:40]}"
            cases.append(make_case(name, argv, chosen, iname, inp, tags=tags,
                                   check=check, stdin_modes=["pipe"],
                                   nondet_exit=nde))
        else:
            if got_invalid >= n_invalid:
                continue
            got_invalid += 1
            name = f"rand-neg-{got_invalid:03d}-{sig[:40]}"
            cases.append(make_case(name, argv, chosen, iname, inp,
                                   tags=tags + ["negative"],
                                   rule_id=verdict[1], exact_stderr=True,
                                   stdin_modes=["pipe"]))
    return cases


def _pair_input(a, b, corpus):
    for fid in (a, b):
        for n in fm.preferred_inputs(fid):
            if n in corpus:
                return n
    return "discrim"


# --- naming ------------------------------------------------------------------

def _cn(prefix, *parts):
    def clean(p):
        if p is None:
            return "x"
        s = str(p)
        return (s.replace("--", "").replace("-", "").replace(",", "_")
                 .replace(".", "d").replace("\t", "TAB").replace(" ", "SP")
                 .replace("\\0", "NUL").replace("%", "pct").replace("/", "_")
                 or "e")
    return prefix + "-" + "-".join(clean(p) for p in parts)
