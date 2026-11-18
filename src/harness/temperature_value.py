#!/usr/bin/env python3
"""Canonical numeric temperatures and their experiment-directory slugs.

Both shell runners call this module.  Keeping the float materialization and
the path spelling here prevents a controller from looking in a directory that
the stage runner could never create.
"""

from __future__ import annotations

import argparse
import math
import sys


class TemperatureError(ValueError):
    """A command-line temperature is not a usable finite number."""


def canonicalize(raw: str | float) -> str:
    """Return the shortest stable spelling of the represented Python float.

    Integer-valued floats deliberately retain ``.0``.  Thus 0, 0.0 and 0.00
    all become 0.0, while values such as 0.125 and 1.2 retain their value.
    Negative zero is collapsed to zero because it is the same numeric
    experimental condition.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise TemperatureError(f"temperature must be numeric: {raw!r}") from error
    if not math.isfinite(value):
        raise TemperatureError(f"temperature must be finite: {raw!r}")
    if value == 0.0:
        value = 0.0
    return repr(value)


def slug(raw: str | float) -> str:
    """Return the directory component corresponding to ``canonicalize``."""
    return canonicalize(raw).replace(".", "p").replace("+", "plus")


def canonical_list(raw: str) -> str:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    if not values:
        raise TemperatureError("--temp-list must name at least one temperature")
    canonical = [canonicalize(value) for value in values]
    if len(set(canonical)) != len(canonical):
        raise TemperatureError("--temp-list repeats a numeric temperature")
    return ",".join(canonical)


def range_values(points: int, minimum: str, maximum: str) -> list[str]:
    lo = float(canonicalize(minimum))
    hi = float(canonicalize(maximum))
    if points < 1:
        raise TemperatureError("temperature point count must be positive")
    if points == 1:
        return [canonicalize(lo)]
    step = (hi - lo) / (points - 1)
    return [canonicalize(lo + step * index) for index in range(points)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("canonical", "slug"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("value")
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("values")
    range_parser = subparsers.add_parser("range")
    range_parser.add_argument("points", type=int)
    range_parser.add_argument("minimum")
    range_parser.add_argument("maximum")

    args = parser.parse_args(argv)
    try:
        if args.command == "canonical":
            print(canonicalize(args.value))
        elif args.command == "slug":
            print(slug(args.value))
        elif args.command == "list":
            print(canonical_list(args.values))
        else:
            print("\n".join(range_values(args.points, args.minimum, args.maximum)))
    except TemperatureError as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
