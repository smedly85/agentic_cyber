#!/usr/bin/env python3
"""py_sort — sort records read from stdin in unsigned bytewise lexicographic order.

Checkpoint 000: base sort, no options, no file operands.
"""
import sys


def sort_lines(data: bytes) -> bytes:
    """Split stdin bytes into newline-delimited records, sort them in
    unsigned bytewise lexicographic order, and rejoin with trailing newline.

    - Empty input → empty output.
    - A trailing newline in input does not create an extra empty record.
    - A final nonempty unterminated record is still a record.
    - Duplicates are preserved.
    - Record contents are never modified.
    """
    if not data:
        return b""
    parts = data.split(b"\n")
    if parts[-1] == b"":
        parts = parts[:-1]
    parts.sort()
    return b"\n".join(parts) + b"\n"


def main() -> int:
    # --- argument validation ---
    # At this checkpoint no options are implemented. The only recognized
    # tokens are "--" (end-of-options) and "-" (stdin). Any other token
    # starting with "-" (length > 1) is an unrecognized option. Any other
    # token is a file operand.
    operands = []
    for arg in sys.argv[1:]:
        if arg == "--" or arg == "-":
            continue
        if arg.startswith("-") and len(arg) > 1:
            sys.stderr.buffer.write(
                ("sort: unrecognized option '%s'\n" % arg).encode("utf-8")
                + b"Try 'sort --help' for more information.\n"
            )
            sys.stderr.buffer.flush()
            return 2
        operands.append(arg)

    # --- read input ---
    try:
        if operands:
            data = b""
            for op in operands:
                with open(op, "rb") as f:
                    data += f.read()
        else:
            data = sys.stdin.buffer.read()
    except OSError as e:
        name = operands[0] if operands else "<stdin>"
        strerror = e.strerror if e.strerror else "No such file or directory"
        sys.stderr.buffer.write(
            ("sort: cannot read: %s: %s\n" % (name, strerror)).encode("utf-8")
        )
        sys.stderr.buffer.flush()
        return 2
    except (ValueError, AttributeError):
        name = operands[0] if operands else "<stdin>"
        sys.stderr.buffer.write(
            ("sort: cannot read: %s: No such file or directory\n" % name).encode("utf-8")
        )
        sys.stderr.buffer.flush()
        return 2

    # --- sort ---
    try:
        result = sort_lines(data)
    except Exception:
        sys.stderr.buffer.write(b"sort: internal error\n")
        sys.stderr.buffer.flush()
        return 2

    # --- write output ---
    try:
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    except (OSError, ValueError):
        sys.stderr.buffer.write(b"sort: error writing output\n")
        sys.stderr.buffer.flush()
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
