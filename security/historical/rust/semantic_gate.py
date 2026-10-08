"""Immutable Rust population/mapping fingerprints; no analysis backend gate."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPECTED = {
    "population.json": "a2334cebe8257ee0df548e5dade512777652a3fc9b721e7de46af0ac28844e9b",
    "vulnerable_function_mappings.json": "95466302c81129dc9ed5fa743f09937aad5b9829b58f4fe372383fb6a97b97ef",
    "source_manifest.json": "8798e5be3f4002790c1d07bbbef6747ce68e3a52ee69d97133505463a4a3e20c",
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def verify_frozen(directory=HERE):
    actual = {name: fingerprint(json.loads((directory / name).read_text(encoding="utf-8")))
              for name in EXPECTED}
    if actual != EXPECTED:
        raise ValueError("FROZEN FINGERPRINT MISMATCH: no build or measurement permitted")
    return actual


if __name__ == "__main__":
    print(json.dumps(verify_frozen(), indent=2))
