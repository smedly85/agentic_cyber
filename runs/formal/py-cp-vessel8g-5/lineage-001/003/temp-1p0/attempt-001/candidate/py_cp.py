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


def _copy_tree(src: str, dst: str, force: bool, interactive: bool, declines: list, errors: list) -> None:
    """Recursively copy contents of directory src into directory dst.

    dst is created if missing (mode = src rwx & ~umask).
    Symlinks in the tree are recreated with identical target bytes, never followed.
    Regular files are copied via copy_path with force semantics.
    Interactive declines are appended to declines (not raised).
    Sub-failures are appended to errors; traversal continues.
    Raises OSError only on fatal top-level conflicts.
    """
    # Ensure dst directory exists
    try:
        d_st = os.stat(dst)
        if not stat.S_ISDIR(d_st.st_mode):
            raise OSError("destination is not a directory")
    except FileNotFoundError:
        os.mkdir(dst)
        src_st = os.lstat(src)
        os.chmod(dst, stat.S_IMODE(src_st.st_mode) & ~_UMASK)

    for name in os.listdir(src):
        src_child = os.path.join(src, name)
        dst_child = os.path.join(dst, name)

        try:
            child_lstat = os.lstat(src_child)
        except OSError:
            continue

        if stat.S_ISLNK(child_lstat.st_mode):
            try:
                target = os.readlink(src_child)
                if os.path.lexists(dst_child):
                    os.unlink(dst_child)
                os.symlink(target, dst_child)
            except OSError as e:
                errors.append(f"{src_child}: {e.strerror or 'cannot create symlink'}")

        elif stat.S_ISDIR(child_lstat.st_mode):
            # Validate destination type for this subdirectory
            try:
                d_st = os.stat(dst_child)
                if not stat.S_ISDIR(d_st.st_mode):
                    errors.append(f"{dst_child}: is a file")
                    continue
            except FileNotFoundError:
                if os.path.islink(dst_child):
                    errors.append(f"{dst_child}: dangling symlink")
                    continue
            except OSError:
                errors.append(f"{dst_child}: cannot access")
                continue
            try:
                _copy_tree(src_child, dst_child, force, interactive, declines, errors)
            except OSError as e:
                errors.append(f"{src_child}: {e.strerror or 'directory copy failed'}")

        elif stat.S_ISREG(child_lstat.st_mode):
            # Validate destination for this file
            dst_exists = False
            try:
                d_st = os.stat(dst_child)
                if stat.S_ISDIR(d_st.st_mode):
                    errors.append(f"{dst_child}: is a directory")
                    continue
                dst_exists = True
            except FileNotFoundError:
                if os.path.islink(dst_child):
                    errors.append(f"{dst_child}: dangling symlink")
                    continue
                parent = os.path.dirname(dst_child)
                if parent and not os.path.isdir(parent):
                    errors.append(f"{dst_child}: no such file or directory")
                    continue
            except OSError as e:
                errors.append(f"{dst_child}: {e.strerror or 'cannot access'}")
                continue

            if interactive and dst_exists:
                print(f"py_cp: overwrite '{dst_child}'? ", file=sys.stderr, end="")
                sys.stderr.flush()
                try:
                    line = sys.stdin.readline()
                except (EOFError, OSError):
                    line = ""
                if not line or line[0] not in ('y', 'Y'):
                    declines.append(dst_child)
                    continue

            try:
                copy_path(src_child, dst_child, force=force)
            except OSError as e:
                errors.append(f"{src_child}: {e.strerror or 'copy failed'}")

        else:
            errors.append(f"{src_child}: unsupported file type")


def _parse_operands(argv: list[str]) -> tuple[list[str], bool, bool, bool]:
    """Extract operand list and force/interactive/recursive flags; reject unknown options before --."""
    operands: list[str] = []
    force = False
    interactive = False
    recursive = False
    seen_ddash = False
    for arg in argv:
        if not seen_ddash:
            if arg == "--":
                seen_ddash = True
                continue
            if arg == "-f" or arg == "--force":
                force = True
                continue
            if arg == "-i" or arg == "--interactive":
                interactive = True
                continue
            if arg == "-r" or arg == "--recursive":
                recursive = True
                continue
            if arg.startswith("-") and len(arg) > 1:
                print(f"py_cp: unknown option: {arg}", file=sys.stderr)
                raise SystemExit(1)
        operands.append(arg)
    return operands, force, interactive, recursive


def main() -> None:
    os.umask(_UMASK)
    operands, force, interactive, recursive = _parse_operands(sys.argv[1:])

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
        if recursive:
            # --- recursive mode: use lstat to see symlinks ---
            try:
                src_lstat = os.lstat(src)
            except OSError:
                print(f"py_cp: {src}: no such file or directory", file=sys.stderr)
                any_failure = True
                continue

            if stat.S_ISLNK(src_lstat.st_mode):
                # Recreate the symlink itself; do not follow
                try:
                    target = os.readlink(src)
                except OSError as e:
                    print(f"py_cp: {src}: {e.strerror or 'readlink failed'}", file=sys.stderr)
                    any_failure = True
                    continue
                try:
                    if os.path.lexists(dst):
                        os.unlink(dst)
                    parent = os.path.dirname(dst)
                    if parent and not os.path.isdir(parent):
                        raise OSError("no such file or directory")
                    os.symlink(target, dst)
                except OSError as e:
                    print(f"py_cp: {dst}: {e.strerror or 'cannot create symlink'}", file=sys.stderr)
                    any_failure = True

            elif stat.S_ISDIR(src_lstat.st_mode):
                # Validate destination parent
                parent = os.path.dirname(dst)
                if parent and not os.path.isdir(parent):
                    print(f"py_cp: {dst}: no such file or directory", file=sys.stderr)
                    any_failure = True
                    continue

                # Self-copy / descendant check (before any changes)
                src_real = os.path.realpath(src)
                dst_real = os.path.realpath(dst)
                if src_real == dst_real:
                    print(f"py_cp: {src}: refusing to copy a directory into itself", file=sys.stderr)
                    any_failure = True
                    continue
                if dst_real.startswith(src_real + os.sep):
                    print(f"py_cp: {src}: refusing to copy a directory into its descendant", file=sys.stderr)
                    any_failure = True
                    continue

                # Validate dest type
                try:
                    dst_st = os.stat(dst)
                    if stat.S_ISREG(dst_st.st_mode):
                        print(f"py_cp: {dst}: is a file", file=sys.stderr)
                        any_failure = True
                        continue
                except FileNotFoundError:
                    if os.path.islink(dst):
                        print(f"py_cp: {dst}: dangling symlink", file=sys.stderr)
                        any_failure = True
                        continue

                declines: list = []
                errors: list = []
                try:
                    _copy_tree(src, dst, force, interactive, declines, errors)
                except OSError as e:
                    print(f"py_cp: {src}: {e.strerror or 'copy failed'}", file=sys.stderr)
                    any_failure = True
                if declines:
                    any_failure = True
                if errors:
                    any_failure = True
                    for err in errors:
                        print(f"py_cp: {err}", file=sys.stderr)

            elif stat.S_ISREG(src_lstat.st_mode):
                # Single regular file with -r: same as non-recursive path
                # Self-copy check
                if os.path.realpath(src) == os.path.realpath(dst):
                    print(f"py_cp: {src}: refusing to copy a file to itself", file=sys.stderr)
                    any_failure = True
                    continue

                # Validate destination
                dst_exists = False
                try:
                    dst_st = os.stat(dst)
                    if stat.S_ISDIR(dst_st.st_mode):
                        print(f"py_cp: {dst}: is a directory", file=sys.stderr)
                        any_failure = True
                        continue
                    dst_exists = True
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

                if interactive and dst_exists:
                    print(f"py_cp: overwrite '{dst}'? ", file=sys.stderr, end="")
                    sys.stderr.flush()
                    try:
                        line = sys.stdin.readline()
                    except (EOFError, OSError):
                        line = ""
                if not line or line[0] not in ('y', 'Y'):
                    any_failure = True
                    continue

                try:
                    copy_path(src, dst, force=force)
                except OSError as e:
                    print(f"py_cp: {src}: {e.strerror or 'copy failed'}", file=sys.stderr)
                    any_failure = True

            else:
                print(f"py_cp: {src}: unsupported file type", file=sys.stderr)
                any_failure = True

        else:
            # --- non-recursive mode: existing behavior (stat follows symlinks) ---
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

            if os.path.realpath(src) == os.path.realpath(dst):
                print(f"py_cp: {src}: refusing to copy a file to itself", file=sys.stderr)
                any_failure = True
                continue

            dst_exists = False
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
                dst_exists = True
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

            if interactive and dst_exists:
                print(f"py_cp: overwrite '{dst}'? ", file=sys.stderr, end="")
                sys.stderr.flush()
                try:
                    line = sys.stdin.readline()
                except (EOFError, OSError):
                    line = ""
                if not line or line[0] not in ('y', 'Y'):
                    any_failure = True
                    continue

            try:
                copy_path(src, dst, force=force)
            except OSError as e:
                print(f"py_cp: {src}: {e.strerror or 'copy failed'}", file=sys.stderr)
                any_failure = True

    raise SystemExit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
