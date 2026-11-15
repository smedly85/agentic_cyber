#!/usr/bin/env python3
"""py_cp — checkpoint 003: basic file copy utility with recursive support."""
import os
import stat
import sys


def parse_args(argv):
    operands = []
    after_ddash = False
    force = False
    interactive = False
    recursive = False
    for token in argv:
        if not after_ddash and token == '--':
            after_ddash = True
            continue
        if after_ddash:
            operands.append(token)
        else:
            if token in ('-f', '--force'):
                force = True
            elif token in ('-i', '--interactive'):
                interactive = True
            elif token in ('-r', '--recursive'):
                recursive = True
            elif token.startswith('-') and token != '-':
                return None, None, None, None, f"unknown option: {token}"
            else:
                operands.append(token)
    return operands, force, interactive, recursive, None


def copy_path(src, dst, force=False):
    src_fd = os.open(src, os.O_RDONLY)
    try:
        src_stat = os.fstat(src_fd)
        try:
            dst_fd = os.open(dst, os.O_WRONLY | os.O_TRUNC)
        except OSError as open_err:
            try:
                dst_info = os.lstat(dst)
            except OSError:
                dst_info = None

            if dst_info is not None:
                if stat.S_ISDIR(dst_info.st_mode):
                    raise open_err
                elif force:
                    os.unlink(dst)
                    dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                    mode = stat.S_IMODE(src_stat.st_mode) & ~0o022
                    os.fchmod(dst_fd, mode)
                else:
                    raise open_err
            else:
                dst_fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                mode = stat.S_IMODE(src_stat.st_mode) & ~0o022
                os.fchmod(dst_fd, mode)
        try:
            while True:
                chunk = os.read(src_fd, 131072)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    n = os.write(dst_fd, view)
                    view = view[n:]
        finally:
            os.close(dst_fd)
    finally:
        os.close(src_fd)


def _prompt_overwrite(dst):
    sys.stderr.write(f"py_cp: overwrite '{dst}'? (y/n) ")
    sys.stderr.flush()
    answer = sys.stdin.readline()
    return bool(answer) and answer[0] in ('y', 'Y')


def _copy_regular(src, dst, force, interactive):
    """Copy a single regular file. Returns 0 on success, 1 on failure."""
    dst_exists = False
    try:
        dst_stat = os.stat(dst)
        if not stat.S_ISREG(dst_stat.st_mode):
            print(f"py_cp: {dst}: Not a regular file", file=sys.stderr)
            return 1
        dst_exists = True
        src_stat = os.stat(src)
        if (src_stat.st_dev == dst_stat.st_dev
                and src_stat.st_ino == dst_stat.st_ino):
            print(f"py_cp: '{src}' and '{dst}' are the same file", file=sys.stderr)
            return 1
    except FileNotFoundError:
        if os.path.lexists(dst) and not force:
            print(f"py_cp: {dst}: Dangling symbolic link", file=sys.stderr)
            return 1
    except PermissionError:
        print(f"py_cp: {dst}: Permission denied", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"py_cp: {dst}: {e.strerror or e}", file=sys.stderr)
        return 1

    if interactive and dst_exists:
        if not _prompt_overwrite(dst):
            return 1

    try:
        copy_path(src, dst, force=force)
    except (OSError, MemoryError) as e:
        print(f"py_cp: {src}: {e.strerror or e}", file=sys.stderr)
        return 1
    return 0


def _recreate_symlink(src, dst):
    """Recreate symlink dst to have the same target as src. Returns 0 or 1."""
    try:
        target = os.readlink(src)
    except OSError as e:
        print(f"py_cp: {src}: {e.strerror or e}", file=sys.stderr)
        return 1
    try:
        os.lstat(dst)
        os.unlink(dst)
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f"py_cp: {dst}: {e.strerror or e}", file=sys.stderr)
        return 1
    try:
        os.symlink(target, dst)
    except OSError as e:
        print(f"py_cp: {dst}: {e.strerror or e}", file=sys.stderr)
        return 1
    return 0


def copy_tree(src, dst, force, interactive):
    """Copy contents of directory src into existing directory dst. Returns 0 or 1."""
    exit_status = 0
    try:
        entries = os.listdir(src)
    except OSError as e:
        print(f"py_cp: {src}: {e.strerror or e}", file=sys.stderr)
        return 1

    for name in entries:
        src_entry = os.path.join(src, name)
        dst_entry = os.path.join(dst, name)

        try:
            st = os.lstat(src_entry)
        except OSError as e:
            print(f"py_cp: {src_entry}: {e.strerror or e}", file=sys.stderr)
            exit_status = 1
            continue

        if stat.S_ISLNK(st.st_mode):
            exit_status |= _recreate_symlink(src_entry, dst_entry)

        elif stat.S_ISDIR(st.st_mode):
            try:
                dst_st = os.lstat(dst_entry)
                if not stat.S_ISDIR(dst_st.st_mode):
                    print(f"py_cp: {dst_entry}: Not a directory", file=sys.stderr)
                    exit_status = 1
                    continue
            except FileNotFoundError:
                mode = stat.S_IMODE(st.st_mode) & ~0o022
                try:
                    os.mkdir(dst_entry, mode)
                except OSError as e:
                    print(f"py_cp: {dst_entry}: {e.strerror or e}", file=sys.stderr)
                    exit_status = 1
                    continue
            except OSError as e:
                print(f"py_cp: {dst_entry}: {e.strerror or e}", file=sys.stderr)
                exit_status = 1
                continue
            exit_status |= copy_tree(src_entry, dst_entry, force, interactive)

        elif stat.S_ISREG(st.st_mode):
            exit_status |= _copy_regular(src_entry, dst_entry, force, interactive)

        else:
            print(f"py_cp: {src_entry}: unsupported file type", file=sys.stderr)
            exit_status = 1

    return exit_status


def main():
    operands, force, interactive, recursive, err = parse_args(sys.argv[1:])
    if err is not None:
        print(f"py_cp: {err}", file=sys.stderr)
        sys.exit(1)

    if len(operands) < 2:
        print("py_cp: missing required operand", file=sys.stderr)
        sys.exit(1)

    multi = len(operands) > 2
    if multi:
        dest_dir = operands[-1]
        sources = operands[:-1]
        try:
            st = os.stat(dest_dir)
        except OSError:
            print(f"py_cp: {dest_dir}: Not a directory", file=sys.stderr)
            sys.exit(1)
        if not stat.S_ISDIR(st.st_mode):
            print(f"py_cp: {dest_dir}: Not a directory", file=sys.stderr)
            sys.exit(1)
        into_dir = True
    else:
        sources = [operands[0]]
        dest_dir = operands[1]
        try:
            st = os.stat(dest_dir)
            into_dir = stat.S_ISDIR(st.st_mode)
        except OSError:
            into_dir = False

    exit_status = 0

    for src in sources:
        base = os.path.basename(src)
        if not base:
            base = os.path.basename(os.path.abspath(src))
        dst = os.path.join(dest_dir, base) if into_dir else dest_dir

        try:
            src_lstat = os.lstat(src)
        except FileNotFoundError:
            print(f"py_cp: {src}: No such file or directory", file=sys.stderr)
            exit_status = 1
            continue
        except PermissionError:
            print(f"py_cp: {src}: Permission denied", file=sys.stderr)
            exit_status = 1
            continue
        except OSError as e:
            print(f"py_cp: {src}: {e.strerror or e}", file=sys.stderr)
            exit_status = 1
            continue

        if stat.S_ISLNK(src_lstat.st_mode):
            if recursive:
                exit_status |= _recreate_symlink(src, dst)
            else:
                try:
                    os.stat(src)
                except FileNotFoundError:
                    print(f"py_cp: {src}: Dangling symbolic link", file=sys.stderr)
                    exit_status = 1
                    continue
                except OSError as e:
                    print(f"py_cp: {src}: {e.strerror or e}", file=sys.stderr)
                    exit_status = 1
                    continue
                exit_status |= _copy_regular(src, dst, force, interactive)

        elif stat.S_ISDIR(src_lstat.st_mode):
            if not recursive:
                print(f"py_cp: {src}: Is a directory", file=sys.stderr)
                exit_status = 1
                continue
            try:
                src_real = os.path.realpath(src)
                dst_real = os.path.realpath(dst)
                if dst_real == src_real or dst_real.startswith(src_real + os.sep):
                    print(f"py_cp: {src}: cannot copy a directory into itself",
                          file=sys.stderr)
                    exit_status = 1
                    continue
            except OSError:
                pass
            try:
                dst_st = os.lstat(dst)
                if not stat.S_ISDIR(dst_st.st_mode):
                    print(f"py_cp: {dst}: Not a directory", file=sys.stderr)
                    exit_status = 1
                    continue
            except FileNotFoundError:
                mode = stat.S_IMODE(src_lstat.st_mode) & ~0o022
                try:
                    os.mkdir(dst, mode)
                except OSError as e:
                    print(f"py_cp: {dst}: {e.strerror or e}", file=sys.stderr)
                    exit_status = 1
                    continue
            except OSError as e:
                print(f"py_cp: {dst}: {e.strerror or e}", file=sys.stderr)
                exit_status = 1
                continue
            exit_status |= copy_tree(src, dst, force, interactive)

        elif stat.S_ISREG(src_lstat.st_mode):
            exit_status |= _copy_regular(src, dst, force, interactive)

        else:
            print(f"py_cp: {src}: unsupported file type", file=sys.stderr)
            exit_status = 1

    sys.exit(exit_status)


if __name__ == "__main__":
    try:
        main()
    except (OSError, MemoryError) as e:
        print(f"py_cp: {e.strerror or e}", file=sys.stderr)
        sys.exit(1)
    except RecursionError:
        print("py_cp: resource limit exceeded", file=sys.stderr)
        sys.exit(1)
