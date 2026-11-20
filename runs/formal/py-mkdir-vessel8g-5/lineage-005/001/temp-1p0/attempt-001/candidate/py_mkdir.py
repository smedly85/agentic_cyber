#!/usr/bin/env python3
"""mkdir - create directories"""
import os
import sys


def _err(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def _get_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _create_dir_p(path: str, umask: int) -> int:
    """Create directory path with -p semantics. Returns 0 or 1."""
    parts = [p for p in path.split('/') if p and p != '.']

    if not parts:
        return 0

    is_absolute = path.startswith('/')
    current = '/' if is_absolute else ''

    for i, part in enumerate(parts):
        current = current + '/' + part if current else part
        is_last = (i == len(parts) - 1)

        try:
            exists = os.path.lexists(current)
        except (OSError, ValueError):
            exists = False

        if exists:
            try:
                if os.path.isdir(current):
                    continue
            except (OSError, ValueError):
                pass
            _err(f"mkdir: cannot create directory '{path}': Not a directory")
            return 1

        try:
            os.mkdir(current, 0o777)
        except FileExistsError:
            try:
                if os.path.isdir(current):
                    continue
            except (OSError, ValueError):
                pass
            _err(f"mkdir: cannot create directory '{path}': File exists")
            return 1
        except PermissionError:
            _err(f"mkdir: cannot create directory '{path}': Permission denied")
            return 1
        except FileNotFoundError:
            _err(f"mkdir: cannot create directory '{path}': No such file or directory")
            return 1
        except OSError as e:
            msg = e.strerror if e.strerror else (os.strerror(e.errno) if e.errno else "Unknown error")
            _err(f"mkdir: cannot create directory '{path}': {msg}")
            return 1

        if not is_last:
            try:
                os.chmod(current, (0o777 & ~umask) | 0o700)
            except OSError:
                pass

    return 0


def main() -> int:
    args = sys.argv[1:]
    operands: list[str] = []
    after_dd = False
    parents = False

    for arg in args:
        if not after_dd:
            if arg == '--':
                after_dd = True
                continue
            if arg.startswith('-') and len(arg) > 1:
                if arg == '-p' or arg == '--parents':
                    parents = True
                    continue
                if arg.startswith('--'):
                    _err(f"mkdir: unrecognized option '{arg}'")
                else:
                    _err(f"mkdir: invalid option -- '{arg[1]}'")
                _err("Try 'mkdir --help' for more information.")
                return 1
        operands.append(arg)

    if not operands:
        _err("mkdir: missing operand")
        _err("Try 'mkdir --help' for more information.")
        return 1

    umask = _get_umask()
    rc = 0

    for path in operands:
        if parents:
            r = _create_dir_p(path, umask)
        else:
            try:
                os.mkdir(path, 0o777)
                r = 0
            except FileExistsError:
                _err(f"mkdir: cannot create directory '{path}': File exists")
                r = 1
            except FileNotFoundError:
                _err(f"mkdir: cannot create directory '{path}': No such file or directory")
                r = 1
            except PermissionError:
                _err(f"mkdir: cannot create directory '{path}': Permission denied")
                r = 1
            except NotADirectoryError:
                _err(f"mkdir: cannot create directory '{path}': Not a directory")
                r = 1
            except OSError as e:
                msg = e.strerror if e.strerror else (os.strerror(e.errno) if e.errno else "Unknown error")
                _err(f"mkdir: cannot create directory '{path}': {msg}")
                r = 1

        if r != 0:
            rc = 1

    return rc


if __name__ == '__main__':
    sys.exit(main())
