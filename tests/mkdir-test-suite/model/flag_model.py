#!/usr/bin/env python3
"""
Canonical model of the GNU mkdir flag surface (coreutils 9.x).

Every flag has a stable ID (its short form where one exists, else the long
option). Long aliases normalize to that ID. Each flag records:
  - kind: "bool" | "value"  (value = takes an argument)
  - values: {"valid": [...], "invalid": [...]} for value flags
  - inputs: preferred corpus target names this flag should be exercised on
  - tags: default tags applied to cases using this flag (e.g. "selinux")

mkdir's flag surface is tiny compared to sort's -- there is essentially one
value flag (-m/--mode) whose exhaustiveness comes from sweeping its full
valid/invalid pool AND crossing it against a umask sweep (see gen/combos.py
gen_singles), since the resulting directory mode depends on both.

This module is pure data + tiny helpers; no subprocess, no I/O.
"""
from __future__ import annotations

# flag ID -> spec
FLAGS: dict[str, dict] = {
    "-p": {"kind": "bool", "inputs": ["nested", "existing", "partial"]},
    "-v": {"kind": "bool", "inputs": ["simple", "multi"]},
    "-m": {"kind": "value", "inputs": ["simple", "nested"], "values": {
        # octal: plain perms, all-zero, all-open, setuid, sticky, setgid,
        # execute-only, world-writable-sticky; symbolic: additive/subtractive/
        # assignment forms, special bits (+t sticky, g+s setgid, u+s setuid).
        "valid": ["0000", "0700", "0755", "0644", "0777", "4755", "1777",
                  "2755", "0111",
                  "u+rwx", "a=rx", "go-w", "u=rwx,g=rx,o=", "+t", "g+s",
                  "a-w", "o+w", "u+s"],
        # confirmed empirically against GNU mkdir: "+" alone (no perm chars)
        # is accepted (a no-op clause), so it is NOT in this invalid pool.
        "invalid": ["", "8", "9", "0999", "08", "u+z", ","]}},
    # -Z / --context are SELinux/SMACK-only; on a kernel without either they
    # are accepted and silently ignored (or warn) by GNU mkdir, so they are
    # tagged "selinux" and excluded by default (see config.json
    # excluded_tags) -- their observable behavior is platform-dependent, not
    # a property of the mkdir implementation under test.
    "-Z": {"kind": "bool", "inputs": ["simple"], "tags": ["selinux"]},
    "--context": {"kind": "value", "inputs": ["simple"], "values": {
        "valid": ["unconfined_u:object_r:default_t:s0"], "invalid": []},
        "tags": ["selinux"]},
    "--help": {"kind": "bool", "inputs": ["none"], "tags": ["doc"]},
    "--version": {"kind": "bool", "inputs": ["none"], "tags": ["doc"]},
}

# long option -> canonical ID (for parsing / normalization)
LONG_ALIASES = {
    "--parents": "-p",
    "--verbose": "-v",
    "--mode": "-m",
}


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


def to_argv(fid: str, value: str | None) -> list[str]:
    """Render a flag+value as argv tokens. Value flags for long options use
    --opt=value; short options use separate tokens (-m '0700')."""
    if not is_value_flag(fid):
        return [fid]
    if fid.startswith("--"):
        return [f"{fid}={value}"]
    return [fid, value]
