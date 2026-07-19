#!/usr/bin/env python3
"""
Constraint table for GNU sort 9.4 option combinations.

is_valid(flag_ids, values) -> Verdict
    Verdict is OK, or (CONFLICT, rule_id). Used by the generator to route a
    combo to the positive suite (freeze a golden) or the negative suite
    (freeze a golden AND assert exit code / error-ness).

predict_error(rule_id) -> ExpectedError(exit_code)
    The expected process exit code for a rule violation. Exact stderr text
    is NOT hardcoded here -- freeze.py captures it from GNU sort through the
    engine (so argv[0]="sort" wording is always correct). predict_error is
    cross-checked against observed GNU exit codes during freeze; a mismatch
    aborts generation (it means the model is wrong).

All rules and exit codes were confirmed empirically against
/usr/bin/sort (GNU coreutils 9.4); see the plan's constraint table.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import flag_model as fm

OK = "OK"
CONFLICT = "CONFLICT"


@dataclass
class ExpectedError:
    exit_code: int
    # a substring that must appear in stderr (loose cross-check only)
    stderr_contains: str = ""


# rule_id -> ExpectedError. Usage errors exit 2; the argmatch family
# (--sort=BAD / --check=BAD) exits 1.
RULES: dict[str, ExpectedError] = {
    "C1_mode_incompat": ExpectedError(2, "are incompatible"),
    "C2_cC": ExpectedError(2, "'-cC' are incompatible"),
    "C3_check_multifile": ExpectedError(2, "not allowed with -"),
    "C4_check_output": ExpectedError(2, "are incompatible"),
    "C5_debug_incompat": ExpectedError(2, "are incompatible"),
    "C6_empty_tab": ExpectedError(2, "empty tab"),
    "C7_multichar_tab": ExpectedError(2, "multi-character tab"),
    "C8_incompat_tabs": ExpectedError(2, "incompatible tabs"),
    "C9_multi_output": ExpectedError(2, "multiple output files"),
    "C10_multi_compress": ExpectedError(2, "multiple"),
    "C10_multi_randsrc": ExpectedError(2, "multiple random sources"),
    "C11_batch_small": ExpectedError(2, "batch-size"),
    "C12_batch_large": ExpectedError(2, "batch-size"),
    "C13_parallel_zero": ExpectedError(2, "parallel"),
    "C14_bad_size": ExpectedError(2, "-S"),
    "C15_bad_key": ExpectedError(2, "invalid"),
    "C16_files0_operand": ExpectedError(2, "files0-from"),
    "C18_bad_sort_word": ExpectedError(1, "for '--sort'"),
    "C18_bad_check_word": ExpectedError(1, "for '--check'"),
    "unknown_flag": ExpectedError(2, "unrecognized option"),
}


def predict_error(rule_id: str) -> ExpectedError:
    return RULES[rule_id]


# --- helpers to extract mode terms from a key modifier string or globals ---

def _mode_terms(letters: set[str]) -> int:
    """Count of distinct C1 ordering terms present in `letters`. The formula
    (sort.c check_ordering_compatibility) is:
        numeric + general_numeric + human + month
        + (version | random | ignore)
    where ignore = d or i. b/f/r/s do not count. >1 => incompatible."""
    terms = 0
    for m in fm.EXCLUSIVE_MODES:            # n g h M -> each own term
        if m in letters:
            terms += 1
    if letters & fm.OR_GROUP:               # V R d i -> ONE shared term
        terms += 1
    return terms


def _global_ordering_letters(flag_ids: list[str]) -> set[str]:
    out = set()
    for f in flag_ids:
        if f == "--sort":
            continue  # value handled separately
        if len(f) == 2 and f[0] == "-" and f[1] in "bdfghiMnRVr":
            out.add(f[1])
    return out


def is_valid(flag_ids: list[str], values: dict[str, list[str]]):
    """flag_ids: canonical IDs present. values: id -> list of the actual
    values supplied (a list because a flag may repeat, e.g. two -t).
    Returns OK or (CONFLICT, rule_id)."""
    ids = list(flag_ids)
    ids_set = set(ids)

    # C1: global ordering-mode incompatibility (n/g/h/M vs each other/OR group)
    gletters = _global_ordering_letters(ids)
    # fold --sort=WORD into the equivalent letter
    for v in values.get("--sort", []):
        eq = fm.SORT_WORD_EQUIV.get(v)
        if eq:
            gletters.add(eq[1])
    if _mode_terms(gletters) > 1:
        return (CONFLICT, "C1_mode_incompat")

    # C1 within a single -k spec's modifier letters
    for kv in values.get("-k", []):
        mods = _key_modifier_letters(kv)
        if _mode_terms(mods) > 1:
            return (CONFLICT, "C1_mode_incompat")

    # C2: -c and -C together
    if "-c" in ids_set and "-C" in ids_set:
        return (CONFLICT, "C2_cC")

    check_mode = bool(ids_set & {"-c", "-C"}) or bool(
        set(values.get("--check", [])))
    # C4: check + -o
    if check_mode and "-o" in ids_set:
        return (CONFLICT, "C4_check_output")

    # C5: --debug + (check or -o)
    if "--debug" in ids_set and (check_mode or "-o" in ids_set):
        return (CONFLICT, "C5_debug_incompat")

    # C8/C9/C10: multiple *different* values of single-value flags
    for fid, rule in (("-t", "C8_incompat_tabs"),
                      ("-o", "C9_multi_output"),
                      ("--compress-program", "C10_multi_compress"),
                      ("--random-source", "C10_multi_randsrc")):
        vs = values.get(fid, [])
        norm = {_norm_tab(v) if fid == "-t" else v for v in vs}
        if len(norm) > 1:
            return (CONFLICT, rule)

    # C6/C7: -t value validity
    for v in values.get("-t", []):
        r = _tab_error(v)
        if r:
            return (CONFLICT, r)

    # C11: --batch-size < 2
    for v in values.get("--batch-size", []):
        if _int_or_none(v) is not None and _int_or_none(v) < 2:
            return (CONFLICT, "C11_batch_small")

    # C13: --parallel = 0 or non-numeric
    for v in values.get("--parallel", []):
        n = _int_or_none(v)
        if n == 0 or (n is None):
            return (CONFLICT, "C13_parallel_zero")

    # C14: -S invalid size
    for v in values.get("-S", []):
        if not _valid_size(v):
            return (CONFLICT, "C14_bad_size")

    # C15: -k spec validity
    for v in values.get("-k", []):
        if not _valid_key(v):
            return (CONFLICT, "C15_bad_key")

    # C18: --sort / --check invalid word
    for v in values.get("--sort", []):
        if v not in fm.SORT_WORD_EQUIV:
            return (CONFLICT, "C18_bad_sort_word")
    for v in values.get("--check", []):
        if v not in ("quiet", "silent", "diagnose-first"):
            return (CONFLICT, "C18_bad_check_word")

    return OK


# --- value validators (mirror GNU behavior) ---------------------------------

def _norm_tab(v: str) -> str:
    return "\0" if v == "\\0" else v


def _tab_error(v: str) -> str | None:
    if v == "\\0":
        return None            # literal backslash-zero = NUL separator (ok)
    if v == "":
        return "C6_empty_tab"
    if len(v.encode()) > 1:    # multi-byte or multi-char
        return "C7_multichar_tab"
    return None


def _key_modifier_letters(kv: str) -> set[str]:
    """Extract ordering-modifier letters from a -k spec like '2n,3r' or
    '1nh,1'. Digits, dots, and commas are structure, not modifiers."""
    out = set()
    for ch in kv:
        if ch in fm.KEY_MODIFIER_LETTERS:
            out.add(ch)
    return out


def _valid_key(v: str) -> bool:
    """Validate a -k KEYDEF: F[.C][opts][,F[.C][opts]]. Field/char must be
    >=1 (char offset zero is only allowed in the STOP position). We keep this
    aligned with GNU's diagnostics (field zero / char offset zero / stray
    char)."""
    parts = v.split(",")
    if len(parts) > 2:
        return False
    for idx, part in enumerate(parts):
        if not _valid_key_part(part, is_stop=(idx == 1)):
            return False
    return True


def _valid_key_part(part: str, is_stop: bool) -> bool:
    if part == "":
        return False
    # split off trailing modifier letters
    i = 0
    fc = ""
    while i < len(part) and (part[i].isdigit() or part[i] == "."):
        fc += part[i]
        i += 1
    mods = part[i:]
    if any(c not in fm.KEY_MODIFIER_LETTERS for c in mods):
        return False           # stray character
    if fc == "" or fc == ".":
        return False
    if "." in fc:
        f_str, c_str = fc.split(".", 1)
        if f_str == "" or c_str == "":
            return False
        if not f_str.isdigit() or not c_str.isdigit():
            return False
        if int(f_str) == 0:
            return False
        if int(c_str) == 0 and not is_stop:
            return False       # char offset zero only valid in stop pos
    else:
        if not fc.isdigit():
            return False
        if int(fc) == 0:
            return False
    return True


def _int_or_none(v: str):
    try:
        return int(v)
    except ValueError:
        return None


_SIZE_SUFFIXES = set("bkKmMGTPEZYRQ%")


def _valid_size(v: str) -> bool:
    if v == "":
        return False
    # optional digits then optional single suffix
    i = 0
    while i < len(v) and v[i].isdigit():
        i += 1
    digits = v[:i]
    rest = v[i:]
    if digits == "" and rest not in ("%",):
        # GNU accepts a bare suffix? e.g. "-S %" is invalid; require digits.
        return False
    if rest == "":
        return True
    if len(rest) == 1 and rest in _SIZE_SUFFIXES:
        return True
    return False
