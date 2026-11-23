#!/usr/bin/env python3
"""py_sort — sort newline-delimited byte records from stdin in C-locale order."""

import sys


def _fold_key(record: bytes) -> bytes:
    """Fold ASCII letters to lowercase for comparison; other bytes unchanged."""
    out = bytearray(len(record))
    for i, b in enumerate(record):
        out[i] = b + 32 if 65 <= b <= 90 else b
    return bytes(out)


def sort_lines(data: bytes, reverse: bool = False, ignore_case: bool = False, unique: bool = False) -> bytes:
    """Sort newline-separated byte records in unsigned bytewise lexicographic
    ascending order, preserving duplicates.

    - Records may contain NUL bytes, be empty, or be any arbitrary byte string.
    - Empty input produces empty output.
    - A final nonempty unterminated record (no trailing newline) is still a record.
    - Every output record is followed by a newline byte.
    """
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


def main() -> int:
    args = sys.argv[1:]

    reverse = False
    ignore_case = False
    unique = False
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
        result = sort_lines(data, reverse=reverse, ignore_case=ignore_case, unique=unique)
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
