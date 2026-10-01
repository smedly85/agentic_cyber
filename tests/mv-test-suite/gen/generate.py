#!/usr/bin/env python3
"""Offline suite tooling; never copied into checkpoint bundles."""
from pathlib import Path
import sys

SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE.parent))
from reference_generators.transfer_oracle import main

if __name__ == "__main__":
    raise SystemExit(main(SUITE, "mv"))

