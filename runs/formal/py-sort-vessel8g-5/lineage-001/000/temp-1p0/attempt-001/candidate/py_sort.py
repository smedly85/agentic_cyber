#!/usr/bin/env python3
"""py_sort checkpoint 000: sort stdin records bytewise (C locale)."""

import os
import sys


def _die_option_long(arg: str) -> None:
    sys.stderr.write(f"sort: unrecognized option '{arg}'\n")
    sys.stderr.write("Try 'sort --help' for more information.\n")
    raise SystemExit(2)


def _die_option_short(arg: str) -> None:
    ch = arg[1]
    sys.stderr.write(f"sort: invalid option -- '{ch}'\n")
    sys.stderr.write("Try 'sort --help' for more information.\n")
    raise SystemExit(2)


def _parse_args(argv: list) -> list[str]:
    """Validate command-line arguments.  Returns the list of file operands.

    Long options (``--...``) are unrecognised; short options (``-x``) are
    invalid.  ``--`` ends option parsing.  Everything else is a file operand
    (including a bare ``-``, which means stdin).
    """
    operands: list[str] = []
    after_ddash = False
    for arg in argv:
        if after_ddash:
            operands.append(arg)
        elif arg == "--":
            after_ddash = True
        elif len(arg) > 1 and arg[0] == "-":
            if arg.startswith("--"):
                _die_option_long(arg)
            else:
                _die_option_short(arg)
        else:
            operands.append(arg)
    return operands


def sort_lines(data: bytes) -> bytes:
    """Split *data* into newline-delimited records, sort bytewise ascending,
    and return the sorted bytes with each record terminated by newline.

    This is the core semantic anchor for the checkpoint's sorting behaviour.
    """
    if not data:
        return b""

    records = data.split(b"\n")
    if data.endswith(b"\n"):
        records = records[:-1]

    records.sort()

    out = bytearray()
    for r in records:
        out.extend(r)
        out.append(0x0A)
    return bytes(out)


def _read_input(operands: list[str]) -> bytes:
    """Assemble the full input from operands (or stdin when no operands)."""
    chunks: list[bytes] = []
    if not operands:
        try:
            chunks.append(sys.stdin.buffer.read())
        except (OSError, MemoryError) as exc:
            sys.stderr.write(f"sort: error reading input: {exc}\n")
            raise SystemExit(2)
    else:
        for op in operands:
            if op == "-":
                try:
                    chunks.append(sys.stdin.buffer.read())
                except (OSError, MemoryError) as exc:
                    sys.stderr.write(f"sort: error reading input: {exc}\n")
                    raise SystemExit(2)
            else:
                try:
                    with open(op, "rb") as f:
                        chunks.append(f.read())
                except OSError as e:
                    strerror = e.strerror or os.strerror(e.errno) or str(e)
                    sys.stderr.write(
                        f"sort: cannot read: {op}: {strerror}\n"
                    )
                    raise SystemExit(2)
    return b"".join(chunks)


def main() -> None:
    operands = _parse_args(sys.argv[1:])

    data = _read_input(operands)

    try:
        result = sort_lines(data)
    except (OSError, MemoryError) as exc:
        sys.stderr.write(f"sort: error: {exc}\n")
        raise SystemExit(2)

    try:
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    except (OSError, MemoryError) as exc:
        sys.stderr.write(f"sort: error writing output: {exc}\n")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
