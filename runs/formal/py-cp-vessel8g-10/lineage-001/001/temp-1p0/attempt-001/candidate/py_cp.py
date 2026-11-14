#!/usr/bin/env python3
"""py_cp — checkpoint 000: basic regular-file copy."""
import os
import stat
import sys

_UMASK = 0o022
_BUF = 1024 * 1024


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def copy_path(src: str, dst: str, force: bool = False) -> None:
    """Copy regular file src to dst.

    New dst: permissions = src rwx masked by umask.
    Existing dst (regular file or symlink to one): its rwx is retained.
    With force=True: if opening an existing dst for write fails, unlink
    it and create a replacement with source rwx masked by umask.
    Raises OSError on any failure.
    """
    src_st = os.stat(src)
    src_mode = stat.S_IMODE(src_st.st_mode)

    src_fd = os.open(src, os.O_RDONLY)
    try:
        try:
            os.stat(dst)
            is_new = False
        except FileNotFoundError:
            is_new = True

        if is_new:
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        else:
            try:
                fd = os.open(dst, os.O_WRONLY | os.O_TRUNC)
            except OSError:
                if not force:
                    raise
                os.unlink(dst)
                fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
                is_new = True

        try:
            while True:
                buf = os.read(src_fd, _BUF)
                if not buf:
                    break
                _write_all(fd, buf)
            if is_new:
                os.fchmod(fd, src_mode & ~_UMASK)
        finally:
            os.close(fd)
    finally:
        os.close(src_fd)


def _parse_operands(argv: list[str]) -> tuple[list[str], bool]:
    """Extract operand list and force flag; reject unknown options before --."""
    operands: list[str] = []
    force = False
    seen_ddash = False
    for arg in argv:
        if not seen_ddash:
            if arg == "--":
                seen_ddash = True
                continue
            if arg == "-f" or arg == "--force":
                force = True
                continue
            if arg.startswith("-") and len(arg) > 1:
                print(f"py_cp: unknown option: {arg}", file=sys.stderr)
                raise SystemExit(1)
        operands.append(arg)
    return operands, force


def main() -> None:
    os.umask(_UMASK)
    operands, force = _parse_operands(sys.argv[1:])

    if len(operands) < 2:
        print("py_cp: missing operand", file=sys.stderr)
        raise SystemExit(1)

    sources = operands[:-1]
    dest = operands[-1]

    # Multi-source: dest must be an existing directory
    if len(sources) > 1:
        try:
            if not stat.S_ISDIR(os.stat(dest).st_mode):
                raise OSError("not a directory")
        except OSError:
            print(f"py_cp: {dest}: not a directory", file=sys.stderr)
            raise SystemExit(1)

    # Compute effective destinations
    dests: list[str] = []
    for src in sources:
        if len(sources) > 1 or os.path.isdir(dest):
            base = os.path.basename(os.path.normpath(src))
            dests.append(os.path.join(dest, base))
        else:
            dests.append(dest)

    any_failure = False
    for src, dst in zip(sources, dests):
        # --- validate source ---
        try:
            src_st = os.stat(src)
        except OSError:
            print(f"py_cp: {src}: no such file or directory", file=sys.stderr)
            any_failure = True
            continue
        if not stat.S_ISREG(src_st.st_mode):
            print(f"py_cp: {src}: is a directory", file=sys.stderr)
            any_failure = True
            continue

        # --- self-copy check (before any destructive change) ---
        if os.path.realpath(src) == os.path.realpath(dst):
            print(f"py_cp: {src}: refusing to copy a file to itself", file=sys.stderr)
            any_failure = True
            continue

        # --- validate destination ---
        try:
            dst_st = os.stat(dst)
            if stat.S_ISDIR(dst_st.st_mode):
                print(f"py_cp: {dst}: is a directory", file=sys.stderr)
                any_failure = True
                continue
            if not stat.S_ISREG(dst_st.st_mode):
                print(f"py_cp: {dst}: not a regular file", file=sys.stderr)
                any_failure = True
                continue
        except FileNotFoundError:
            if os.path.islink(dst):
                print(f"py_cp: {dst}: dangling symlink", file=sys.stderr)
                any_failure = True
                continue
            parent = os.path.dirname(dst)
            if parent and not os.path.isdir(parent):
                print(f"py_cp: {dst}: no such file or directory", file=sys.stderr)
                any_failure = True
                continue
        except OSError as e:
            print(f"py_cp: {dst}: {e.strerror or 'cannot access'}", file=sys.stderr)
            any_failure = True
            continue

        # --- perform copy ---
        try:
            copy_path(src, dst, force=force)
        except OSError as e:
            print(f"py_cp: {src}: {e.strerror or 'copy failed'}", file=sys.stderr)
            any_failure = True

    raise SystemExit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
