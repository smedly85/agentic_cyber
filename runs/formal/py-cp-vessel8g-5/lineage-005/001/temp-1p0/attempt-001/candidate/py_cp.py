#!/usr/bin/env python3
"""py_cp — copy regular files."""
import os
import stat
import sys


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def copy_path(src: str, dst: str, force: bool = False) -> None:
    real_src = os.path.realpath(src)
    src_stat = os.stat(real_src)
    if not stat.S_ISREG(src_stat.st_mode):
        raise OSError(f"source '{src}' is not a regular file")

    try:
        os.lstat(dst)
        dst_exists = True
    except OSError:
        dst_exists = False

    real_dst = os.path.realpath(dst)

    if dst_exists:
        dst_stat = os.stat(real_dst)
        if not stat.S_ISREG(dst_stat.st_mode):
            raise OSError(f"destination '{dst}' is not a regular file")
        if (src_stat.st_dev, src_stat.st_ino) == (dst_stat.st_dev, dst_stat.st_ino):
            raise OSError(f"source and destination are the same file ('{src}')")
    else:
        parent = os.path.dirname(real_dst)
        if not os.path.isdir(parent or "."):
            raise OSError(f"no such directory for destination '{dst}'")

    fd_src = os.open(real_src, os.O_RDONLY)
    try:
        if dst_exists:
            try:
                fd_dst = os.open(real_dst, os.O_WRONLY | os.O_TRUNC)
            except OSError:
                if not force:
                    raise
                if os.path.isdir(real_dst):
                    raise
                os.unlink(real_dst)
                mode = stat.S_IMODE(src_stat.st_mode)
                fd_dst = os.open(real_dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        else:
            mode = stat.S_IMODE(src_stat.st_mode)
            fd_dst = os.open(real_dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            while True:
                chunk = os.read(fd_src, 65536)
                if not chunk:
                    break
                _write_all(fd_dst, chunk)
        finally:
            os.close(fd_dst)
    finally:
        os.close(fd_src)


def main() -> None:
    argv = sys.argv[1:]

    if "--" in argv:
        sep = argv.index("--")
        pre = argv[:sep]
        post = argv[sep + 1:]
    else:
        pre = argv
        post = []

    force = False
    operands: list[str] = []
    for arg in pre:
        if arg == "-":
            operands.append(arg)
        elif arg == "-f" or arg == "--force":
            force = True
        elif arg.startswith("-") and len(arg) > 1:
            print(f"py_cp: unknown option: {arg}", file=sys.stderr)
            sys.exit(1)
        else:
            operands.append(arg)

    operands.extend(post)

    if len(operands) < 2:
        print("py_cp: missing operand(s)", file=sys.stderr)
        sys.exit(1)

    sources = operands[:-1]
    dest = operands[-1]

    pairs: list[tuple[str, str]] = []
    if len(sources) > 1:
        if not os.path.isdir(dest):
            print(f"py_cp: destination '{dest}' is not an existing directory",
                  file=sys.stderr)
            sys.exit(1)
        for src in sources:
            base = os.path.basename(src) or src
            pairs.append((src, os.path.join(dest, base)))
    else:
        src = sources[0]
        if os.path.isdir(dest):
            base = os.path.basename(src) or src
            pairs.append((src, os.path.join(dest, base)))
        else:
            pairs.append((src, dest))

    had_error = False
    for src, dst in pairs:
        try:
            copy_path(src, dst, force=force)
        except OSError as exc:
            had_error = True
            print(f"py_cp: {exc}", file=sys.stderr)

    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()
