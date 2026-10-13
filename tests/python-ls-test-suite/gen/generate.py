#!/usr/bin/env python3
"""Offline GNU reference generation; excluded from every agent bundle."""
from pathlib import Path
import sys
SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE.parent))
from reference_generators.python_oracle import main
if __name__ == '__main__':
    raise SystemExit(main(SUITE, 'ls'))
