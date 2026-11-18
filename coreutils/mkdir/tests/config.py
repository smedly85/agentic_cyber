#!/usr/bin/env python3
"""
Central config loader for the mkdir exhaustive test suite.

Every path this suite needs (the oracle binary, the candidate binary, the
optional ASan-instrumented candidate build) and the manifest of which flags
the candidate implements live in ONE JSON file -- by default config.json
next to this script. No script in this suite hardcodes a binary or source
path; they all resolve through here, so pointing the suite at a different
mkdir-like binary is a one-file edit.

Usage as a library (from any .py file in this suite):
    from config import load, get
    cfg = load("config.json")
    oracle = get(cfg, "paths.oracle_bin", "/usr/bin/mkdir")

Usage from shell (so run_all.sh / build_asan.sh / selfcheck.sh never have
to hand-parse JSON):
    python3 config.py config.json paths.oracle_bin
    python3 config.py config.json paths.candidate_src --default ""
    python3 config.py config.json paths.cc_flags --join " "

Exit codes (CLI mode only): 0 = printed a value; 1 = key missing and no
--default was given (the caller almost certainly needs to configure it).
"""
from __future__ import annotations

import argparse
import json
import sys


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def get(cfg: dict, dotted_key: str, default=None):
    """Navigate a dict via a dotted key path, e.g. 'paths.oracle_bin'."""
    node = cfg
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config_path")
    ap.add_argument("dotted_key")
    ap.add_argument("--default", default=None)
    ap.add_argument("--join", default=None,
                    help="if the value is a list, join it with this "
                         "separator (for passing as shell words/flags)")
    args = ap.parse_args()

    cfg = load(args.config_path)
    value = get(cfg, args.dotted_key, args.default)
    if value is None:
        print(f"config.py: '{args.dotted_key}' is not set in "
              f"{args.config_path} and no --default was given",
              file=sys.stderr)
        sys.exit(1)
    if isinstance(value, list):
        print((args.join or " ").join(str(v) for v in value))
    else:
        print(value)


if __name__ == "__main__":
    _main()
