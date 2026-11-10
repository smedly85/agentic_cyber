"""Dotted-key configuration reader, compatible with the existing suites."""
import argparse
import json
from pathlib import Path

def load(path="config.json"):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def get(config, key, default=None):
    value = config
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("key")
    parser.add_argument("--default", default=None)
    args = parser.parse_args()
    value = get(load(args.config), args.key, args.default)
    if value is None:
        raise SystemExit(1)
    print(value)

