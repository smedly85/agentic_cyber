#!/usr/bin/env python3
"""Bounded fixed-substring grep over lines."""
import sys


def search_stream(pattern: bytes, stream, prefix: bytes) -> int:
    """Read lines from stream; write each line containing pattern to stdout
    with the given prefix and a trailing newline. Return the number of
    matched lines."""
    out = sys.stdout.buffer
    count = 0
    while True:
        line = stream.readline()
        if not line:
            break
        content = line[:-1] if line.endswith(b'\n') else line
        if pattern in content:
            out.write(prefix + content + b'\n')
            count += 1
    return count


def _diagnose(name: str, err: OSError) -> None:
    sys.stderr.write(f"py_grep: {name}: {err.strerror or 'error'}\n")


def main() -> int:
    args = sys.argv[1:]

    operands: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--':
            operands.extend(args[i + 1:])
            break
        if arg.startswith('-') and arg != '-':
            sys.stderr.write(f"py_grep: unsupported option: {arg}\n")
            return 2
        operands.append(arg)
        i += 1

    if not operands:
        sys.stderr.write("py_grep: missing PATTERN\n")
        return 2

    pattern = operands[0].encode('utf-8', 'surrogateescape')
    file_operands = operands[1:]

    total_matches = 0
    had_error = False

    try:
        if not file_operands:
            try:
                total_matches += search_stream(pattern, sys.stdin.buffer, b'')
            except OSError:
                had_error = True
        else:
            multi = len(file_operands) >= 2
            for operand in file_operands:
                name_bytes = operand.encode('utf-8', 'surrogateescape')
                prefix = name_bytes + b':' if multi else b''
                try:
                    with open(operand, 'rb') as f:
                        total_matches += search_stream(pattern, f, prefix)
                except OSError as e:
                    _diagnose(operand, e)
                    had_error = True
    except MemoryError:
        had_error = True

    sys.stdout.buffer.flush()

    if had_error:
        return 2
    return 0 if total_matches > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
