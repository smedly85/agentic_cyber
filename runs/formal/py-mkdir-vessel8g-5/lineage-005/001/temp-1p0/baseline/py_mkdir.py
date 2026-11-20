#!/usr/bin/env python3
"""mkdir - create directories"""
import os
import sys


def _err(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def main() -> int:
    args = sys.argv[1:]
    operands: list[str] = []
    after_dd = False

    for arg in args:
        if not after_dd:
            if arg == '--':
                after_dd = True
                continue
            if arg.startswith('-') and len(arg) > 1:
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

    rc = 0
    for path in operands:
        try:
            os.mkdir(path, 0o777)
        except FileExistsError:
            _err(f"mkdir: cannot create directory '{path}': File exists")
            rc = 1
        except FileNotFoundError:
            _err(f"mkdir: cannot create directory '{path}': No such file or directory")
            rc = 1
        except PermissionError:
            _err(f"mkdir: cannot create directory '{path}': Permission denied")
            rc = 1
        except NotADirectoryError:
            _err(f"mkdir: cannot create directory '{path}': Not a directory")
            rc = 1
        except OSError as e:
            msg = e.strerror if e.strerror else os.strerror(e.errno) if e.errno else "Unknown error"
            _err(f"mkdir: cannot create directory '{path}': {msg}")
            rc = 1

    return rc


if __name__ == '__main__':
    sys.exit(main())
