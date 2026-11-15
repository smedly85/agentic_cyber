#!/usr/bin/env python3
"""py_cp - checkpoint 000: base file copy utility."""
import os
import stat
import sys


def copy_path(src: str, dst: str, force: bool = False) -> None:
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
        try:
            dfd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        except OSError:
            if not force:
                raise
            os.unlink(dst)
            dfd = os.open(dst, os.O_WRONLY | os.O_CREAT, 0o666)
            try:
                _copy_fd_contents(fd, dfd)
                os.fchmod(dfd, stat.S_IMODE(st.st_mode) & ~umask)
            finally:
                os.close(dfd)
            return
        try:
            _copy_fd_contents(fd, dfd)
            if not dst_existed:
                os.fchmod(dfd, stat.S_IMODE(st.st_mode) & ~umask)
        finally:
            os.close(dfd)
    finally:
        os.close(fd)


def _interactive_prompt(dst: str) -> bool:
    """Prompt on stderr; read one line from stdin. Return True only if the
    initial character is ASCII 'y' or 'Y'."""
    print(f"overwrite '{dst}'? ", file=sys.stderr, end="")
    sys.stderr.flush()
    line = sys.stdin.readline()
    line = line.rstrip('\r\n')
    if not line:
        return False
    return line[0] in ('y', 'Y')


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


def _parse_operands(argv: list[str]) -> tuple[list[str] | None, bool, bool, bool, str | None]:
    """Extract operand list from argv, respecting -- and rejecting unknown options."""
    if "--" in argv:
        idx = argv.index("--")
        pre, post = argv[:idx], argv[idx + 1:]
    else:
        pre, post = argv, []

    operands: list[str] = []
    force = False
    interactive = False
    recursive = False
    for arg in pre:
        if arg == "-":
            operands.append(arg)
        elif arg == "-f" or arg == "--force":
            force = True
        elif arg == "-i" or arg == "--interactive":
            interactive = True
        elif arg == "-r" or arg == "--recursive":
            recursive = True
        elif len(arg) > 1 and arg.startswith("-"):
            return None, False, False, False, f"unknown option: {arg}"
        else:
            operands.append(arg)
    operands.extend(post)

    if len(operands) < 2:
        return None, False, False, False, "missing operands"
    return operands, force, interactive, recursive, None


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


def _copy_file(src: str, dst: str, force: bool, interactive: bool) -> bool:
    """Copy a single regular file. Returns True on success, False on failure."""
    err = _validate_pair(src, dst)
    if err:
        print(err, file=sys.stderr)
        return False

    if interactive:
        try:
            os.stat(dst)
            dst_exists = True
        except OSError:
            dst_exists = False
        if dst_exists:
            if not _interactive_prompt(dst):
                return False

    try:
        copy_path(src, dst, force=force)
    except OSError as exc:
        print(f"py_cp: {src}: {exc.strerror or exc}", file=sys.stderr)
        return False
    return True


def _copy_symlink(src: str, dst: str) -> bool:
    """Recreate symlink src at dst. Returns True on success."""
    try:
        target = os.readlink(src)
    except OSError as exc:
        print(f"py_cp: {src}: {exc.strerror or exc}", file=sys.stderr)
        return False
    try:
        if os.path.lexists(dst):
            os.unlink(dst)
        os.symlink(target, dst)
    except OSError as exc:
        print(f"py_cp: {dst}: {exc.strerror or exc}", file=sys.stderr)
        return False
    return True


def _copy_tree(src: str, dst: str, force: bool, interactive: bool) -> bool:
    """Recursively copy directory tree src into dst. Returns True on success."""
    src_real = os.path.realpath(src)
    dst_real = os.path.realpath(dst)
    if dst_real == src_real:
        print(f"py_cp: {src}: cannot copy a directory into itself", file=sys.stderr)
        return False
    if dst_real.startswith(src_real + os.sep):
        print(f"py_cp: {src}: cannot copy a directory into its descendant", file=sys.stderr)
        return False

    try:
        os.stat(dst)
        dst_existed = True
    except OSError:
        dst_existed = False
        try:
            os.mkdir(dst)
        except OSError as exc:
            print(f"py_cp: {dst}: {exc.strerror or exc}", file=sys.stderr)
            return False
        umask = os.umask(0o022)
        try:
            st = os.stat(src)
            os.chmod(dst, stat.S_IMODE(st.st_mode) & ~umask)
        except OSError:
            pass

    had_error = False
    try:
        entries = os.listdir(src)
    except OSError as exc:
        print(f"py_cp: {src}: {exc.strerror or exc}", file=sys.stderr)
        return False

    for name in sorted(entries):
        src_path = os.path.join(src, name)
        dst_path = os.path.join(dst, name)

        try:
            st = os.lstat(src_path)
        except OSError:
            had_error = True
            continue

        if stat.S_ISLNK(st.st_mode):
            if not _copy_symlink(src_path, dst_path):
                had_error = True
        elif stat.S_ISDIR(st.st_mode):
            if not _copy_tree(src_path, dst_path, force, interactive):
                had_error = True
        elif stat.S_ISREG(st.st_mode):
            if not _copy_file(src_path, dst_path, force, interactive):
                had_error = True
        # Special files (fifos, sockets, devices): skip, excluded from scope

    return not had_error


def main() -> None:
    argv = sys.argv[1:]

    operands, force, interactive, recursive, err = _parse_operands(argv)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)

    pairs, err = _resolve_pairs(operands)
    if err:
        print(err, file=sys.stderr)
        sys.exit(1)

    had_error = False
    for src, dst in pairs:
        if recursive:
            try:
                st = os.lstat(src)
            except OSError as exc:
                print(f"py_cp: {src}: {exc.strerror or exc}", file=sys.stderr)
                had_error = True
                continue

            if stat.S_ISLNK(st.st_mode):
                if not _copy_symlink(src, dst):
                    had_error = True
            elif stat.S_ISDIR(st.st_mode):
                try:
                    dst_st = os.stat(dst)
                    if not stat.S_ISDIR(dst_st.st_mode):
                        print(f"py_cp: {src}: destination is not a directory", file=sys.stderr)
                        had_error = True
                        continue
                except FileNotFoundError:
                    if os.path.islink(dst):
                        print(f"py_cp: {dst}: dangling symbolic link", file=sys.stderr)
                        had_error = True
                        continue
                except OSError as exc:
                    print(f"py_cp: {dst}: {exc.strerror or exc}", file=sys.stderr)
                    had_error = True
                    continue
                if not _copy_tree(src, dst, force, interactive):
                    had_error = True
            elif stat.S_ISREG(st.st_mode):
                if not _copy_file(src, dst, force, interactive):
                    had_error = True
            else:
                print(f"py_cp: {src}: is not a regular file, directory, or symlink", file=sys.stderr)
                had_error = True
        else:
            if not _copy_file(src, dst, force, interactive):
                had_error = True

    sys.exit(1 if had_error else 0)


if __name__ == "__main__":
    main()
