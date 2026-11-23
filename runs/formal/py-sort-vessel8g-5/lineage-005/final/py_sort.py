#!/usr/bin/env python3
"""py_sort — sort newline-delimited byte records from stdin in C-locale order."""

import sys


def _fold_key(record: bytes) -> bytes:
    """Fold ASCII letters to lowercase for comparison; other bytes unchanged."""
    out = bytearray(len(record))
    for i, b in enumerate(record):
        out[i] = b + 32 if 65 <= b <= 90 else b
    return bytes(out)


def sort_lines(data: bytes, reverse: bool = False, ignore_case: bool = False,
               unique: bool = False, check: bool = False) -> bytes:
    """Sort newline-separated byte records in unsigned bytewise lexicographic
    ascending order, preserving duplicates.

    - Records may contain NUL bytes, be empty, or be any arbitrary byte string.
    - Empty input produces empty output.
    - A final nonempty unterminated record (no trailing newline) is still a record.
    - Every output record is followed by a newline byte.
    """
    if check:
        code, err = _check_order(data, reverse, ignore_case, unique)
        if err:
            sys.stderr.write(err.decode())
        sys.exit(code)

    if not data:
        return b""

    records = data.split(b"\n")
    if data.endswith(b"\n"):
        records = records[:-1]

    if not records:
        return b""

    if unique:
        if ignore_case:
            seen: set[bytes] = set()
            deduped = []
            for r in records:
                k = _fold_key(r)
                if k not in seen:
                    seen.add(k)
                    deduped.append(r)
            records = deduped
        else:
            seen = set()
            deduped = []
            for r in records:
                if r not in seen:
                    seen.add(r)
                    deduped.append(r)
            records = deduped

    if ignore_case:
        records.sort(key=lambda r: (_fold_key(r), r), reverse=reverse)
    else:
        records.sort(reverse=reverse)
    return b"\n".join(records) + b"\n"


def _check_order(data: bytes, reverse: bool, ignore_case: bool, unique: bool) -> tuple[int, bytes]:
    """Check that records are in the correct order. Returns (exit_code, stderr_bytes)."""
    if not data:
        return (0, b"")

    records = data.split(b"\n")
    if data.endswith(b"\n"):
        records = records[:-1]

    if len(records) <= 1:
        return (0, b"")

    for i in range(1, len(records)):
        a = records[i - 1]
        b = records[i]
        if _is_violation(a, b, reverse, ignore_case, unique):
            return (1, f"sort: disorder on line {i + 1}\n".encode())

    return (0, b"")


def _is_violation(a: bytes, b: bytes, reverse: bool, ignore_case: bool, unique: bool) -> bool:
    """Return True if the pair (a, b) is an ordering violation."""
    if ignore_case:
        if unique:
            ka = _fold_key(a)
            kb = _fold_key(b)
            if reverse:
                return not (ka > kb)
            else:
                return not (ka < kb)
        else:
            ka = (_fold_key(a), a)
            kb = (_fold_key(b), b)
            if reverse:
                return not (ka >= kb)
            else:
                return not (ka <= kb)
    else:
        if unique:
            if reverse:
                return not (a > b)
            else:
                return not (a < b)
        else:
            if reverse:
                return not (a >= b)
            else:
                return not (a <= b)


def main() -> int:
    args = sys.argv[1:]

    reverse = False
    ignore_case = False
    unique = False
    check = False
    past_options = False
    for arg in args:
        if past_options:
            sys.stderr.write(
                f"sort: cannot read: {arg}: No such file or directory\n"
            )
            return 2

        if arg == "--":
            past_options = True
            continue

        if arg.startswith("--") and len(arg) > 2:
            if arg == "--reverse":
                reverse = True
                continue
            if arg == "--ignore-case":
                ignore_case = True
                continue
            if arg == "--unique":
                unique = True
                continue
            if arg == "--check":
                check = True
                continue
            sys.stderr.write(
                f"sort: unrecognized option '{arg}'\n"
                "Try 'sort --help' for more information.\n"
            )
            return 2

        if arg.startswith("-") and len(arg) > 1:
            for ch in arg[1:]:
                if ch == 'r':
                    reverse = True
                elif ch == 'f':
                    ignore_case = True
                elif ch == 'u':
                    unique = True
                elif ch == 'c':
                    check = True
                else:
                    sys.stderr.write(
                        f"sort: unrecognized option '{ch}'\n"
                        "Try 'sort --help' for more information.\n"
                    )
                    return 2
            continue

        sys.stderr.write(
            f"sort: cannot read: {arg}: No such file or directory\n"
        )
        return 2

    try:
        data = sys.stdin.buffer.read()
    except (OSError, MemoryError) as exc:
        sys.stderr.write(f"sort: {exc}\n")
        return 2

    try:
        result = sort_lines(data, reverse=reverse, ignore_case=ignore_case, unique=unique, check=check)
    except MemoryError:
        sys.stderr.write("sort: out of memory\n")
        return 2

    try:
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    except (OSError, MemoryError) as exc:
        sys.stderr.write(f"sort: {exc}\n")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
