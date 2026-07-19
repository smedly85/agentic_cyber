#!/usr/bin/env python3
"""
Canonical model of the GNU sort flag surface (coreutils 9.4).

Every flag has a stable ID (its short form where one exists, else the long
option). Long aliases normalize to that ID. Each flag records:
  - kind: "bool" | "value"  (value = takes an argument)
  - ordering: True if it is an ordering/sort-mode option that participates
    in the C1 per-key incompatibility rule
  - mode_bit: which ordering term it contributes for C1 (see constraints)
  - values: {"valid": [...], "invalid": [...]} for value flags
  - inputs: preferred corpus input names this flag should be exercised on
  - tags: default tags applied to cases using this flag (e.g. "doc")

This module is pure data + tiny helpers; no subprocess, no I/O.
"""
from __future__ import annotations

TAB = "\t"

# Ordering mode bits for the C1 rule. A key may set at most one of the
# "exclusive" group; b/f/r/s never conflict. d and i share the "ignore"
# term (they OR together, so d+i is legal). V and R also OR into a shared
# "version_random" term with the ignore term per GNU's formula:
#   1 < numeric + general_numeric + human + month + (version|random|ignore)
EXCLUSIVE_MODES = {"n", "g", "h", "M"}      # each its own term
OR_GROUP = {"V", "R", "d", "i"}             # collapse into ONE shared term
NONCONFLICT = {"b", "f", "r", "s"}          # never conflict


# flag ID -> spec
FLAGS: dict[str, dict] = {
    # --- ordering / mode options (participate in C1) ---
    "-b": {"kind": "bool", "ordering": True, "inputs": ["fields", "discrim"]},
    "-d": {"kind": "bool", "ordering": True, "inputs": ["discrim", "generic"]},
    "-f": {"kind": "bool", "ordering": True, "inputs": ["discrim", "generic"]},
    "-g": {"kind": "bool", "ordering": True, "inputs": ["numbers", "discrim"]},
    "-h": {"kind": "bool", "ordering": True, "inputs": ["numbers", "discrim"]},
    "-i": {"kind": "bool", "ordering": True, "inputs": ["discrim", "generic"]},
    "-M": {"kind": "bool", "ordering": True, "inputs": ["months", "discrim"]},
    "-n": {"kind": "bool", "ordering": True, "inputs": ["numbers", "discrim"]},
    "-R": {"kind": "bool", "ordering": True, "inputs": ["ties", "generic"],
           "nondeterministic": True},
    "-V": {"kind": "bool", "ordering": True, "inputs": ["versions", "discrim"]},
    "-r": {"kind": "bool", "ordering": True, "inputs": ["discrim", "generic"]},

    # --- other boolean options ---
    "-c": {"kind": "bool", "inputs": ["presorted", "almost_sorted"]},
    "-C": {"kind": "bool", "inputs": ["presorted", "almost_sorted"]},
    "-m": {"kind": "bool", "inputs": ["merge_a", "merge_b"]},
    "-s": {"kind": "bool", "inputs": ["ties", "fields"]},
    "-u": {"kind": "bool", "inputs": ["ties", "generic"]},
    "-z": {"kind": "bool", "inputs": ["zrecords"]},
    "--debug": {"kind": "bool", "inputs": ["discrim"], "tags": ["debug"]},
    "--help": {"kind": "bool", "inputs": ["generic"], "tags": ["doc"]},
    "--version": {"kind": "bool", "inputs": ["generic"], "tags": ["doc"]},

    # --- value options ---
    "-k": {"kind": "value", "inputs": ["fields", "discrim"], "values": {
        "valid": ["1", "1,1", "2,2", "1.3,1.5", "2n,2", "1,1r", "2b,2",
                  "1fd,1", "3,3V", "1h,1", "9,9", "1.4b,1.4b"],
        "invalid": ["0", "1.0", "1,0", "1x", "1."]}},
    "-t": {"kind": "value", "inputs": ["fields"], "values": {
        "valid": [":", TAB, ",", " ", "\\0"],
        "invalid": ["", "xy", "é"]}},   # é = 2-byte multibyte tab error
    "-o": {"kind": "value", "inputs": ["generic"], "values": {
        "valid": ["out.txt"], "invalid": []}, "writes_output": True},
    "-S": {"kind": "value", "inputs": ["generic"], "values": {
        "valid": ["32b", "1024b", "1", "1K", "10M", "1%"],
        "invalid": ["x", "1q", "%"]}},
    "-T": {"kind": "value", "inputs": ["generic"], "values": {
        "valid": ["."], "invalid": []}},
    "--batch-size": {"kind": "value", "inputs": ["merge_a", "merge_b"], "values": {
        "valid": ["2", "3", "16"], "invalid": ["0", "1"]}},
    "--parallel": {"kind": "value", "inputs": ["generic"], "values": {
        "valid": ["1", "2", "8"], "invalid": ["0", "x"]}},
    "--compress-program": {"kind": "value", "inputs": ["generic"], "values": {
        "valid": ["gzip"], "invalid": []}, "tags": ["compress"]},
    # --random-source alone does NOT shuffle; it only supplies randomness to
    # -R. So a bare --random-source sort is deterministic (golden-checkable).
    "--random-source": {"kind": "value", "inputs": ["ties"], "values": {
        "valid": ["@RANDSRC@"], "invalid": ["/nonexistent-random-source"]}},
    "--files0-from": {"kind": "value", "inputs": [], "values": {
        "valid": ["@FILES0@"], "invalid": []}, "tags": ["files0"]},
    "--sort": {"kind": "value", "inputs": ["numbers", "discrim"], "values": {
        "valid": ["numeric", "general-numeric", "human-numeric", "month",
                  "version", "random"],
        "invalid": ["foo", ""]}},
    "--check": {"kind": "value", "inputs": ["presorted"], "values": {
        "valid": ["quiet", "silent", "diagnose-first"],
        "invalid": ["foo"]}},
}

# long option -> canonical ID (for parsing / normalization)
LONG_ALIASES = {
    "--ignore-leading-blanks": "-b", "--dictionary-order": "-d",
    "--ignore-case": "-f", "--general-numeric-sort": "-g",
    "--human-numeric-sort": "-h", "--ignore-nonprinting": "-i",
    "--month-sort": "-M", "--numeric-sort": "-n", "--random-sort": "-R",
    "--version-sort": "-V", "--reverse": "-r", "--check": "-c",
    "--merge": "-m", "--stable": "-s", "--unique": "-u",
    "--zero-terminated": "-z", "--key": "-k", "--field-separator": "-t",
    "--output": "-o", "--buffer-size": "-S", "--temporary-directory": "-T",
}

# --sort=WORD equivalence to a short ordering flag (for pairing/assertions)
SORT_WORD_EQUIV = {
    "numeric": "-n", "general-numeric": "-g", "human-numeric": "-h",
    "month": "-M", "version": "-V", "random": "-R",
}

# Every ordering-mode single-letter that can appear as a -k modifier.
KEY_MODIFIER_LETTERS = set("bdfgiMhnRrV")


def all_flag_ids() -> list[str]:
    return list(FLAGS.keys())


def is_value_flag(fid: str) -> bool:
    return FLAGS.get(fid, {}).get("kind") == "value"


def default_value(fid: str) -> str | None:
    """First valid value for a value flag (used in combos)."""
    if not is_value_flag(fid):
        return None
    return FLAGS[fid]["values"]["valid"][0]


def tags_for(fid: str) -> list[str]:
    return list(FLAGS.get(fid, {}).get("tags", []))


def preferred_inputs(fid: str) -> list[str]:
    return list(FLAGS.get(fid, {}).get("inputs", []))


def is_nondeterministic(fids) -> bool:
    return any(FLAGS.get(f, {}).get("nondeterministic") for f in fids)


def to_argv(fid: str, value: str | None) -> list[str]:
    """Render a flag+value as argv tokens. Value flags for long options use
    --opt=value; short options use separate tokens (-t ':')."""
    if not is_value_flag(fid):
        return [fid]
    if fid.startswith("--"):
        return [f"{fid}={value}"]
    return [fid, value]
