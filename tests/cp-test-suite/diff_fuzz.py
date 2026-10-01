#!/usr/bin/env python3
"""Offline suite tooling; never copied into checkpoint bundles."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True

SUITE = Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE.parent))
from reference_generators.transfer_oracle import main

if __name__ == "__main__":
    sys.argv.insert(1, "--fuzz")
    raise SystemExit(main(SUITE, "cp"))
