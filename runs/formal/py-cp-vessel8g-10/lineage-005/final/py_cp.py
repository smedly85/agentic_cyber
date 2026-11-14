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


def copy_path(src: str, dst: str, force: bool = False, interactive: bool = False) -> None:
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

    if interactive and dst_exists:
        sys.stderr.write(f"py_cp: overwrite '{dst}'? ")
        sys.stderr.flush()
        line = sys.stdin.readline()
        if line.endswith('\n'):
            line = line[:-1]
        if line.endswith('\r'):
            line = line[:-1]
        if not line or line[0] not in ('y', 'Y'):
            raise OSError(f"not writing to '{dst}' (user declined)")

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


def _recreate_symlink(src_path: str, dst_path: str) -> None:
    target = os.readlink(src_path)
    if os.path.lexists(dst_path):
        st = os.lstat(dst_path)
        if not stat.S_ISLNK(st.st_mode):
            raise OSError(f"cannot replace '{dst_path}' with a symlink: not a symlink")
        os.unlink(dst_path)
    os.symlink(target, dst_path)


def _copy_tree_contents(src_dir: str, dst_dir: str, force: bool, interactive: bool) -> list[str]:
    errors: list[str] = []
    entries = os.listdir(src_dir)
    for name in sorted(entries):
        src_path = os.path.join(src_dir, name)
        dst_path = os.path.join(dst_dir, name)
        try:
            st = os.lstat(src_path)
            if stat.S_ISLNK(st.st_mode):
                _recreate_symlink(src_path, dst_path)
            elif stat.S_ISDIR(st.st_mode):
                if os.path.lexists(dst_path):
                    if not os.path.isdir(dst_path):
                        raise OSError(f"cannot create directory '{dst_path}': not a directory")
                else:
                    os.mkdir(dst_path, stat.S_IMODE(st.st_mode))
                errors.extend(_copy_tree_contents(src_path, dst_path, force, interactive))
            elif stat.S_ISREG(st.st_mode):
                copy_path(src_path, dst_path, force=force, interactive=interactive)
        except OSError as exc:
            errors.append(str(exc))
    return errors


def copy_tree(src: str, dst: str, force: bool = False, interactive: bool = False) -> None:
    real_src = os.path.realpath(src)
    if os.path.lexists(dst):
        real_dst = os.path.realpath(dst)
    else:
        parent = os.path.dirname(dst) or "."
        real_dst = os.path.realpath(parent)
    if real_dst == real_src or real_dst.startswith(real_src + os.sep):
        raise OSError(f"cannot copy a directory ('{src}') into itself")
    if os.path.lexists(dst):
        if not os.path.isdir(dst):
            raise OSError(f"cannot create directory '{dst}': not a directory")
    else:
        src_st = os.lstat(src)
        os.mkdir(dst, stat.S_IMODE(src_st.st_mode))
    errors = _copy_tree_contents(src, dst, force, interactive)
    if errors:
        raise OSError(errors[0])


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
    interactive = False
    recursive = False
    operands: list[str] = []
    for arg in pre:
        if arg == "-":
            operands.append(arg)
        elif arg == "-f" or arg == "--force":
            force = True
        elif arg == "-i" or arg == "--interactive":
            interactive = True
        elif arg == "-r" or arg == "--recursive":
            recursive = True
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
            st = os.lstat(src)
            if stat.S_ISLNK(st.st_mode):
                if recursive:
                    _recreate_symlink(src, dst)
                else:
                    copy_path(src, dst, force=force, interactive=interactive)
            elif stat.S_ISDIR(st.st_mode):
                if recursive:
                    copy_tree(src, dst, force=force, interactive=interactive)
                else:
                    raise OSError(f"source '{src}' is not a regular file")
            elif stat.S_ISREG(st.st_mode):
                copy_path(src, dst, force=force, interactive=interactive)
            else:
                raise OSError(f"source '{src}' is not a regular file")
        except OSError as exc:
            had_error = True
            print(f"py_cp: {exc}", file=sys.stderr)

    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()
