#!/usr/bin/env python3
"""py_cp - checkpoint 000: base file copy utility."""
import os
import stat
import sys


def copy_path(src: str, dst: str) -> None:
    """Copy regular file contents from src to dst, preserving bytes.

    If dst pre-exists as a regular file (or symlink to one), overwrite it
    retaining its existing rwx bits.  If dst is newly created, set its
    rwx bits to source-mode & ~umask.
    """
    umask = os.umask(0o022)

    try:
        os.stat(dst)
        dst_existed = True
    except OSError:
        dst_existed = False

    fd = os.open(src, os.O_RDONLY)
    try:
        st = os.fstat(fd)
        dfd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        try:
            _copy_fd_contents(fd, dfd)
            if not dst_existed:
                os.fchmod(dfd, stat.S_IMODE(st.st_mode) & ~umask)
        finally:
            os.close(dfd)
    finally:
        os.close(fd)


def _copy_fd_contents(srcfd: int, dstfd: int) -> None:
    """Transfer all bytes from srcfd to dstfd, handling partial writes."""
    _BUF = 1024 * 1024
    while True:
        chunk = os.read(srcfd, _BUF)
        if not chunk:
            return
        view = memoryview(chunk)
        while view:
            written = os.write(dstfd, view)
            view = view[written:]


def _parse_operands(argv: list[str]) -> tuple[list[str] | None, str | None]:
    """Extract operand list from argv, respecting -- and rejecting unknown options."""
    if "--" in argv:
        idx = argv.index("--")
        pre, post = argv[:idx], argv[idx + 1:]
    else:
        pre, post = argv, []

    operands: list[str] = []
    for arg in pre:
        if arg == "-":
            operands.append(arg)
        elif len(arg) > 1 and arg.startswith("-"):
            return None, f"unknown option: {arg}"
        else:
            operands.append(arg)
    operands.extend(post)

    if len(operands) < 2:
        return None, "missing operands"
    return operands, None


def _resolve_pairs(operands: list[str]) -> tuple[list[tuple[str, str]] | None, str | None]:
    """Build (src, dst) pairs. Returns (None, error) on invocation-wide failure."""
    sources = operands[:-1]
    target = operands[-1]

    if len(sources) > 1:
        try:
            st = os.stat(target)
        except OSError:
            return None, f"invalid destination: {target} is not an existing directory"
        if not stat.S_ISDIR(st.st_mode):
            return None, f"invalid destination: {target} is not a directory"
        return [(s, os.path.join(target, os.path.basename(s))) for s in sources], None

    # Single source
    try:
        st = os.stat(target)
    except OSError:
        return [(sources[0], target)], None
    if stat.S_ISDIR(st.st_mode):
        return [(sources[0], os.path.join(target, os.path.basename(sources[0])))], None
    return [(sources[0], target)], None


def _validate_pair(src: str, dst: str) -> str | None:
    """Return None if the pair is valid, else a diagnostic string."""
    # Source: must exist, follow symlinks, be a regular file
    try:
        st = os.stat(src)
    except OSError as exc:
        return f"py_cp: {src}: {exc.strerror or exc}"
    if stat.S_ISDIR(st.st_mode):
        return f"py_cp: {src}: is a directory"
    if not stat.S_ISREG(st.st_mode):
        return f"py_cp: {src}: is not a regular file"

    # Destination
    try:
        dst_st = os.stat(dst)
        if stat.S_ISDIR(dst_st.st_mode):
            return f"py_cp: {dst}: is a directory"
        if not stat.S_ISREG(dst_st.st_mode):
            return f"py_cp: {dst}: is not a regular file"
    except FileNotFoundError:
        if os.path.islink(dst):
            return f"py_cp: {dst}: dangling symbolic link"
        parent = os.path.dirname(dst)
        if parent:
            try:
                os.stat(parent)
            except OSError:
                return f"py_cp: {dst}: parent directory does not exist"
    except OSError as exc:
        return f"py_cp: {dst}: {exc.strerror or exc}"

    # Self-copy (including filesystem aliases via realpath)
    if os.path.realpath(src) == os.path.realpath(dst):
        return f"py_cp: {src} and {dst} are the same file"

    return None


def main() -> None:
    argv = sys.argv[1:]

    operands, err = _parse_operands(argv)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)

    pairs, err = _resolve_pairs(operands)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)

    had_error = False
    for src, dst in pairs:
        err = _validate_pair(src, dst)
        if err:
            print(err, file=sys.stderr)
            had_error = True
            continue
        try:
            copy_path(src, dst)
        except OSError as exc:
            print(f"py_cp: {src}: {exc.strerror or exc}", file=sys.stderr)
            had_error = True

    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()
