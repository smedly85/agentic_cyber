#!/usr/bin/env python3
"""
Property checks for cases whose output cannot be golden-diffed across
implementations. Primarily -R / --random-source: the hash function is
implementation-defined, so GNU's output ordering is not a valid oracle.
Instead we assert the invariants that MUST hold for any correct shuffle.

A check function takes (input_bytes, result, case) and returns
(ok: bool, detail: str).
"""
from __future__ import annotations

from collections import Counter

from engine import Result, case_stdin_bytes, case_files_bytes


def _records(data: bytes, zero_terminated: bool) -> list[bytes]:
    if not data:
        return []
    sep = b"\0" if zero_terminated else b"\n"
    # GNU sort treats a missing final separator as if present.
    parts = data.split(sep)
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    return parts


def _input_records(case: dict, zero_terminated: bool) -> list[bytes]:
    """Reconstruct the multiset of input lines the same way sort sees them.
    Prefer stdin when present (shuffle cases feed input via stdin and may
    also carry auxiliary files like a --random-source that are NOT sort
    input). Otherwise, count only files listed in `input_files`, or all
    declared files as a last resort."""
    stdin = case_stdin_bytes(case)
    if stdin is not None:
        return _records(stdin, zero_terminated)
    files = case_files_bytes(case)
    named = case.get("input_files")
    if named:
        return [r for n in named for r in _records(files.get(n, b""),
                                                   zero_terminated)]
    recs: list[bytes] = []
    for _, contents in files.items():
        recs += _records(contents, zero_terminated)
    return recs


def check_shuffle(case: dict, res: Result) -> tuple[bool, str]:
    """Output of -R must be a permutation of the input, and equal keys must
    be grouped (adjacent). We check the strong, key-agnostic form: output is
    a multiset permutation of input, and equal *lines* are grouped. (Key-
    based grouping is a superset property; line grouping is what the corpus
    exercises, since our -R inputs use whole-line keys.)"""
    z = "-z" in case.get("args", []) or "--zero-terminated" in case.get("args", [])
    unique = _has_unique(case)
    inp = _input_records(case, z)
    out = _records(res.stdout, z)

    if unique:
        got = Counter(out)
        # sound in all cases: each kept line came from the input, and no
        # full line is repeated (one representative per equal-key run).
        in_set = set(inp)
        extra = [r for r in got if r not in in_set]
        if extra:
            return False, f"-Ru emitted lines not in input: {extra[:3]}"
        if any(c != 1 for c in got.values()):
            return False, "-Ru produced duplicate lines"
        # stronger check only when uniqueness is by WHOLE LINE (no key/fold
        # flag changes what 'equal' means): every distinct line is kept.
        if not _key_affecting(case):
            if set(got) != in_set:
                return False, (f"-Ru set mismatch: in={len(in_set)} distinct, "
                               f"out={len(set(got))}")
        return True, ""

    if Counter(inp) != Counter(out):
        return False, (f"not a permutation: in={len(inp)} lines, "
                       f"out={len(out)} lines, multisets differ")
    # equal lines grouped
    seen = set()
    prev = object()
    for r in out:
        if r == prev:
            continue
        if r in seen:
            return False, f"equal lines not grouped: {r!r} appears in >1 run"
        seen.add(r)
        prev = r
    return True, ""


def check_shuffle_determinism(case: dict, res_a: Result,
                              res_b: Result) -> tuple[bool, str]:
    """With a fixed --random-source, the SAME binary must produce identical
    output across two runs."""
    if res_a.stdout != res_b.stdout:
        return False, "fixed --random-source: two runs of same binary differ"
    return True, ""


# short flags that consume the rest of the token (and possibly next arg) as
# a value, so any 'u' after them is data, not the --unique flag.
_VALUE_SHORTS = set("kotSTs")  # note: -s is boolean but harmless to include


def _has_unique(case: dict) -> bool:
    for tok in case.get("args", []):
        if tok == "--unique":
            return True
        if tok.startswith("--") or not tok.startswith("-") or tok == "-":
            continue
        # bundled short flags, e.g. -Ru ; stop scanning at the first flag
        # that takes a value (its remainder is the value).
        for ch in tok[1:]:
            if ch == "u":
                return True
            if ch in _VALUE_SHORTS:
                break
    return False


_KEY_AFFECTING_LONG = {"--ignore-case", "--dictionary-order",
                       "--ignore-nonprinting", "--ignore-leading-blanks",
                       "--numeric-sort", "--general-numeric-sort",
                       "--human-numeric-sort", "--month-sort",
                       "--version-sort", "--key", "--field-separator"}
_KEY_AFFECTING_SHORT = set("fidbnghMVkt")


def _key_affecting(case: dict) -> bool:
    """True if any flag changes what 'equal' means for -u (folding, key
    selection, numeric/mode comparison), so uniqueness is by key not line."""
    for tok in case.get("args", []):
        if tok in _KEY_AFFECTING_LONG or any(
                tok.startswith(l + "=") for l in _KEY_AFFECTING_LONG):
            return True
        if tok.startswith("-") and not tok.startswith("--") and tok != "-":
            for ch in tok[1:]:
                if ch in _KEY_AFFECTING_SHORT:
                    return True
                if ch in "kotST":
                    break
    return False


CHECKS = {
    "property:shuffle": check_shuffle,
}
