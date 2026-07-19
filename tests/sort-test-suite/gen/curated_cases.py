#!/usr/bin/env python3
"""
Hand-written cases the generic combinators can't express well:
  - every constraint-table error, with exact stderr frozen from GNU
  - semantic quirks worth pinning (-c -m, -Ru, in-place -o f f, +POS)
  - adversarial-input tier (build_adversarial)
  - I/O fault-injection tier (build_faults)

build(corpus) -> curated positive+negative cases
build_adversarial(corpus) -> adversarial-input cases
build_faults(corpus) -> fault-injection cases
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gen.combos import make_case, b64, RANDSRC_BYTES     # noqa: E402
from corpus import corpus as corpus_mod                  # noqa: E402


# --- curated: constraint errors + quirks ------------------------------------

def build(corpus):
    cases = []
    g = corpus["generic"]
    ties = corpus["ties"]

    # --- negative: constraint-table errors, exact stderr ---
    negs = [
        ("err-n-g", ["-n", "-g"], "C1_mode_incompat"),
        ("err-h-n", ["-h", "-n"], "C1_mode_incompat"),
        ("err-M-n", ["-M", "-n"], "C1_mode_incompat"),
        ("err-key-ng", ["-k1ng,1"], "C1_mode_incompat"),
        ("err-cC", ["-c", "-C"], "C2_cC"),
        ("err-t-empty", ["-t", ""], "C6_empty_tab"),
        ("err-t-multi", ["-t", "xy"], "C7_multichar_tab"),
        ("err-t-incompat", ["-t", ":", "-t", ","], "C8_incompat_tabs"),
        ("err-batch-1", ["--batch-size=1"], "C11_batch_small"),
        ("err-parallel-0", ["--parallel=0"], "C13_parallel_zero"),
        ("err-S-bad", ["-S", "1q"], "C14_bad_size"),
        ("err-k-zero", ["-k0"], "C15_bad_key"),
        ("err-k-charzero", ["-k1.0"], "C15_bad_key"),
        ("err-k-stray", ["-k1x"], "C15_bad_key"),
        ("err-sort-word", ["--sort=foo"], "C18_bad_sort_word"),
        ("err-check-word", ["--check=foo"], "C18_bad_check_word"),
        ("err-unknown", ["--no-such-flag"], "unknown_flag"),
    ]
    for name, argv, rule in negs:
        cases.append(make_case(name, argv, _ids(argv), "generic", g,
                               tags=["curated", "negative"], rule_id=rule,
                               exact_stderr=True, stdin_modes=["pipe"]))

    # errors that need file operands (frozen with exact stderr)
    cases.append(make_case(
        "err-c-multifile", ["-c", "fa", "fb"], ["-c"], "files",
        b"", tags=["curated", "negative"], rule_id="C3_check_multifile",
        exact_stderr=True, files={"fa": b"a\n", "fb": b"b\n"},
        use_stdin=False, stdin_modes=["pipe"]))
    cases.append(make_case(
        "err-c-output", ["-c", "-o", "out", "fa"], ["-c", "-o"], "files",
        b"", tags=["curated", "negative"], rule_id="C4_check_output",
        exact_stderr=True, files={"fa": b"a\n"}, use_stdin=False,
        stdin_modes=["pipe"]))
    cases.append(make_case(
        "err-debug-output", ["--debug", "-o", "out"], ["--debug", "-o"],
        "generic", g, tags=["curated", "negative", "debug"],
        rule_id="C5_debug_incompat", exact_stderr=True, stdin_modes=["pipe"]))
    cases.append(make_case(
        "err-multi-output", ["-o", "a", "-o", "b"], ["-o"], "generic", g,
        tags=["curated", "negative"], rule_id="C9_multi_output",
        exact_stderr=True, stdin_modes=["pipe"]))

    # --- positive quirks (golden) ---
    # -c -m : check mode wins, merge ignored, exit 0 on sorted input
    cases.append(make_case("quirk-c-m", ["-c", "-m", "fa"], ["-c", "-m"],
                           "files", b"", tags=["curated"],
                           files={"fa": b"a\nb\nc\n"}, use_stdin=False,
                           stdin_modes=["pipe"]))
    # -y0 obsolete: accepted, ignored, plain sort
    cases.append(make_case("quirk-y0", ["-y0"], [], "generic", g,
                           tags=["curated"], stdin_modes=["pipe"]))
    # -t '\0' : NUL field separator (legal)
    cases.append(make_case("quirk-t-nul", ["-t", "\\0", "-k2,2"],
                           ["-t", "-k"], "fields", corpus["fields"],
                           tags=["curated"], stdin_modes=["pipe"]))
    # repeated identical -t : legal
    cases.append(make_case("quirk-t-dup-ok", ["-t:", "-t:", "-k2,2"],
                           ["-t", "-k"], "fields", corpus["fields"],
                           tags=["curated"], stdin_modes=["pipe"]))
    # --sort=numeric must equal -n  (paired; both golden, same input)
    cases.append(make_case("quirk-sort-numeric", ["--sort=numeric"],
                           ["--sort"], "numbers", corpus["numbers"],
                           tags=["curated"], stdin_modes=["pipe"]))
    cases.append(make_case("quirk-n-equiv", ["-n"], ["-n"], "numbers",
                           corpus["numbers"], tags=["curated"],
                           stdin_modes=["pipe"]))
    # -Ru : one representative per distinct line (property check)
    cases.append(make_case("quirk-Ru", ["-R", "-u", "--random-source=rs"],
                           ["-R", "-u", "--random-source"], "ties", ties,
                           tags=["curated"], check="property:shuffle",
                           files={"rs": RANDSRC_BYTES}, stdin_modes=["pipe"]))
    # in-place: sort -o f f
    cases.append(make_case("quirk-inplace", ["-o", "f", "f"], ["-o"],
                           "generic", b"", tags=["curated"],
                           files={"f": corpus["generic"]},
                           output_file={"path": "f"}, use_stdin=False,
                           stdin_modes=["pipe"]))
    # multiple -T : legal
    cases.append(make_case("quirk-multi-T", ["-T", ".", "-T", "."], ["-T"],
                           "generic", g, tags=["curated"],
                           stdin_modes=["pipe"]))
    # --stable curated combo: -t: -k2,2n -r -u
    cases.append(make_case("combo-t-k-r-u", ["-t:", "-k2,2n", "-r", "-u"],
                           ["-t", "-k", "-r", "-u"], "fields",
                           corpus["fields"], tags=["curated"],
                           stdin_modes=["pipe"]))
    # -b -t' ' -k2b,3
    cases.append(make_case("combo-b-t-k", ["-b", "-t", " ", "-k2b,3"],
                           ["-b", "-t", "-k"], "fields", corpus["fields"],
                           tags=["curated"], stdin_modes=["pipe"]))
    # -m -u -o out a b c
    cases.append(make_case(
        "combo-m-u-o", ["-m", "-u", "-o", "out", "ma", "mb", "mc"],
        ["-m", "-u", "-o"], "merge", b"", tags=["curated"],
        files={"ma": corpus["merge_a"], "mb": corpus["merge_b"],
               "mc": corpus["merge_c"]}, output_file={"path": "out"},
        use_stdin=False, stdin_modes=["pipe"]))

    # --- +POS obsolete syntax (both env variants) ---
    fld = corpus["fields"]
    cases.append(make_case(
        "obs-pos", ["+1", "-2"], [], "fields", fld,
        tags=["curated", "obsolete"], env={"_POSIX2_VERSION": "199209"},
        stdin_modes=["pipe"]))
    # under POSIXLY_CORRECT, +1 is a filename -> error (nonempty stderr, exit 2)
    cases.append(make_case(
        "obs-pos-posixly", ["+1"], [], "fields", fld,
        tags=["curated", "obsolete"], env={"POSIXLY_CORRECT": "1"},
        exact_stderr=True, rule_id=None, stdin_modes=["pipe"]))

    return cases


# --- adversarial-input tier --------------------------------------------------

def build_adversarial(corpus, seed=1):
    adv = corpus_mod.build_adversarial(seed)
    # flag sets to cross adversarial inputs with
    flag_sets = [
        ("def", [], []),
        ("n", ["-n"], ["-n"]),
        ("u", ["-u"], ["-u"]),
        ("k-t", ["-k2,3", "-t:"], ["-k", "-t"]),
        ("z", ["-z"], ["-z"]),
        ("c", ["-c"], ["-c"]),
        ("r-u", ["-r", "-u"], ["-r", "-u"]),
        ("zu", ["-z", "-u"], ["-z", "-u"]),
        ("Ssmall", ["-S", "32b"], ["-S"]),
    ]
    slow = {"hugeline", "manylines", "widefield"}
    cases = []
    for iname, data in adv.items():
        for sname, argv, ids in flag_sets:
            # -z only meaningful with zrecords-like data; still safe to run
            name = f"adv-{iname}-{sname}"
            tags = ["adversarial"] + (["slow"] if iname in slow else [])
            timeout = 60 if iname in slow else 10
            cases.append(make_case(name, argv, ids, iname, data,
                                   tags=tags, timeout=timeout,
                                   stdin_modes=["pipe"]))
    return cases


# --- fault-injection tier ----------------------------------------------------

def build_faults(corpus):
    cases = []
    g = corpus["generic"]

    # -o into an unwritable directory
    cases.append(make_case(
        "fault-o-unwritable", ["-o", "ro_out_dir/out"], ["-o"], "generic",
        g, tags=["fault"], faults={"unwritable_dir_output": True},
        exact_stderr=True, stdin_modes=["pipe"]))
    # directory given as input file
    cases.append(make_case(
        "fault-dir-input", ["adir"], [], "generic", b"",
        tags=["fault"], faults={"dir_input": ["adir"]}, use_stdin=False,
        exact_stderr=True, stdin_modes=["pipe"]))
    # unreadable input file
    cases.append(make_case(
        "fault-unreadable", ["secret"], [], "generic", b"",
        tags=["fault"], faults={"unreadable": ["secret"]}, use_stdin=False,
        exact_stderr=True, stdin_modes=["pipe"]))
    # missing input file
    cases.append(make_case(
        "fault-missing", ["nope.txt"], [], "generic", b"",
        tags=["fault"], faults={"missing": ["nope.txt"]}, use_stdin=False,
        exact_stderr=True, stdin_modes=["pipe"]))
    # write to /dev/full (ENOSPC on output)
    cases.append(make_case(
        "fault-devfull", [], [], "generic", g,
        tags=["fault"], faults={"stdout": "/dev/full"},
        exact_stderr=True, check="none", stdin_modes=["pipe"]))
    # EPIPE: downstream reader closed
    cases.append(make_case(
        "fault-epipe", [], [], "manylines",
        corpus_mod.build_adversarial(1)["manylines"],
        tags=["fault"], faults={"stdout": "closed-pipe"},
        check="none", stdin_modes=["pipe"], timeout=30,
        allow_signals=["SIGPIPE"]))
    # bad TMPDIR forcing external merge (many lines + tiny buffer)
    # stderr embeds the (randomized) temp path, so match by class not exact.
    cases.append(make_case(
        "fault-tmpdir-missing", ["-S", "32b"], ["-S"], "manylines",
        corpus_mod.build_adversarial(1)["manylines"],
        tags=["fault", "slow"], faults={"tmpdir": "missing"},
        check="none", stdin_modes=["pipe"], timeout=60))
    # fd exhaustion during merge
    cases.append(make_case(
        "fault-fdlimit-merge", ["-m", "--batch-size=2",
                                "f0", "f1", "f2", "f3", "f4", "f5"],
        ["-m", "--batch-size"], "merge", b"",
        tags=["fault"], faults={"rlimit_nofile": 16},
        files={f"f{i}": b"%d\n" % i for i in range(6)},
        use_stdin=False, check="none", stdin_modes=["pipe"]))

    return cases


def _ids(argv):
    out = set()
    for tok in argv:
        if tok.startswith("--"):
            out.add(tok.split("=")[0])
        elif tok.startswith("-") and len(tok) >= 2:
            # take the leading option letter cluster's known flags
            for ch in tok[1:]:
                cand = "-" + ch
                out.add(cand)
                if ch in "kotST":  # value-consuming; rest is value
                    break
    return sorted(out)
