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


# --- Mode parsing helpers ---

def _r_bit(w):
    return {'u': 0o400, 'g': 0o040, 'o': 0o004}[w]

def _w_bit(w):
    return {'u': 0o200, 'g': 0o020, 'o': 0o002}[w]

def _x_bit(w):
    return {'u': 0o100, 'g': 0o010, 'o': 0o001}[w]

def _rwx_mask(w):
    return _r_bit(w) | _w_bit(w) | _x_bit(w)


def _parse_who(who_str):
    """Parse who part. Returns set of {'u','g','o'} or empty set if omitted.
    Returns None if invalid."""
    if not who_str:
        return set()
    if 'a' in who_str:
        # Validate remaining chars are valid who chars
        for c in who_str:
            if c not in 'ugoa':
                return None
        return set('ugo')
    result = set()
    for c in who_str:
        if c in 'ugo':
            result.add(c)
        else:
            return None
    if not result:
        return None
    return result


def _apply_regular(op, who, who_omitted, perms, mode):
    """Apply a regular (non-copy) permission clause. No umask masking here."""
    affected = who

    # Compute the ordinary bits specified by perms for each affected who
    spec_ordinary = 0
    for w in affected:
        if 'r' in perms:
            spec_ordinary |= _r_bit(w)
        if 'w' in perms:
            spec_ordinary |= _w_bit(w)
        if 'x' in perms or 'X' in perms:
            spec_ordinary |= _x_bit(w)

    # Determine special bits specified
    spec_setuid = ('s' in perms) and ('u' in affected)
    spec_setgid = ('s' in perms) and ('g' in affected)
    # t always gives sticky; s gives sticky only when who is exactly {o}
    if 't' in perms:
        spec_sticky = True
    elif 's' in perms and affected == {'o'}:
        spec_sticky = True
    else:
        spec_sticky = False

    if op == '+':
        new_ordinary = (mode & 0o777) | spec_ordinary
        new_special = mode & 0o7000
        if spec_setuid:
            new_special |= 0o4000
        if spec_setgid:
            new_special |= 0o2000
        if spec_sticky:
            new_special |= 0o1000
        return (new_ordinary | new_special) & 0o7777

    elif op == '-':
        new_ordinary = (mode & 0o777) & ~spec_ordinary
        new_special = mode & 0o7000
        if spec_setuid:
            new_special &= ~0o4000
        if spec_setgid:
            new_special &= ~0o2000
        if spec_sticky:
            new_special &= ~0o1000
        return (new_ordinary | new_special) & 0o7777

    else:  # op == '='
        new_ordinary = 0
        for w in affected:
            new_ordinary |= (spec_ordinary & _rwx_mask(w))
        for w in set('ugo') - affected:
            new_ordinary |= (mode & _rwx_mask(w))

        new_special = 0
        if spec_setuid:
            new_special |= 0o4000
        elif not (('s' in perms) and ('u' in affected)):
            new_special |= (mode & 0o4000)

        if spec_setgid:
            new_special |= 0o2000
        elif not (('s' in perms) and ('g' in affected)):
            new_special |= (mode & 0o2000)

        if spec_sticky:
            new_special |= 0o1000

        return (new_ordinary | new_special) & 0o7777


def _apply_copy(op, who, who_omitted, source, mode):
    """Apply a permission-copy clause (e.g., u+g, a=u)."""
    src_bits = mode & _rwx_mask(source)

    target_bits = 0
    for w in who:
        if src_bits & _r_bit(source):
            target_bits |= _r_bit(w)
        if src_bits & _w_bit(source):
            target_bits |= _w_bit(w)
        if src_bits & _x_bit(source):
            target_bits |= _x_bit(w)

    if op == '+':
        return ((mode & 0o777) | target_bits | (mode & 0o7000)) & 0o7777
    elif op == '-':
        return ((mode & 0o777) & ~target_bits | (mode & 0o7000)) & 0o7777
    else:  # '='
        clear_mask = 0
        for w in who:
            clear_mask |= _rwx_mask(w)
        new_ordinary = (mode & 0o777) & ~clear_mask | target_bits
        new_special = mode & 0o7000
        return (new_ordinary | new_special) & 0o7777


def _apply_clause(clause, mode):
    """Apply one comma-separated clause. Returns new mode or None if invalid."""
    if not clause:
        return None

    op = None
    op_idx = -1
    for i, c in enumerate(clause):
        if c in '+-=':
            op = c
            op_idx = i
            break
    if op is None:
        return None

    who_str = clause[:op_idx]
    perms_str = clause[op_idx + 1:]

    who = _parse_who(who_str)
    if who is None:
        return None
    who_omitted = (who_str == '')
    if who_omitted:
        who = set('ugo')

    if not perms_str:
        perms = set()
    elif len(perms_str) == 1 and perms_str in 'ugo':
        return _apply_copy(op, who, who_omitted, perms_str, mode)
    else:
        valid_chars = set('rwxXst')
        if not set(perms_str).issubset(valid_chars):
            return None
        perms = set(perms_str)

    return _apply_regular(op, who, who_omitted, perms, mode)


def _initial_symbolic_mode(clauses):
    """Determine the starting mode for symbolic evaluation.
    
    If the first clause is + or - with omitted who or 'a', the base
    ordinary permissions are 0o755 (the typical mkdir default).
    Otherwise the base is 0o777 (a=rwx).
    """
    first = clauses[0]
    op = None
    for c in first:
        if c in '+-=':
            op = c
            break
    if op is None:
        return 0o777

    op_idx = first.index(op)
    who_str = first[:op_idx]

    if op in ('+', '-'):
        if who_str == '' or 'a' in who_str:
            return 0o755

    return 0o777


def _parse_mode(mode_str, umask):
    """Parse a mode string. Returns the mode as int, or None if invalid."""
    if not mode_str:
        return None

    # Try numeric (all octal digits)
    if all(c in '01234567' for c in mode_str):
        try:
            val = int(mode_str, 8)
        except ValueError:
            return None
        if val > 0o7777:
            return None
        return val & 0o7777

    # Symbolic mode
    clauses = mode_str.split(',')
    mode = _initial_symbolic_mode(clauses)

    for clause in clauses:
        new_mode = _apply_clause(clause, mode)
        if new_mode is None:
            return None
        mode = new_mode

    return mode


# --- Directory creation ---

def _create_dir(path, mode):
    """Create a single directory (no -p). mode is the exact desired mode,
    or None for default (0o777 masked by umask)."""
    try:
        if mode is None:
            os.mkdir(path, 0o777)
        else:
            os.mkdir(path, 0o777)
            os.chmod(path, mode)
        return 0
    except FileExistsError:
        _err(f"mkdir: cannot create directory '{path}': File exists")
        return 1
    except FileNotFoundError:
        _err(f"mkdir: cannot create directory '{path}': No such file or directory")
        return 1
    except PermissionError:
        _err(f"mkdir: cannot create directory '{path}': Permission denied")
        return 1
    except NotADirectoryError:
        _err(f"mkdir: cannot create directory '{path}': Not a directory")
        return 1
    except OSError as e:
        msg = e.strerror if e.strerror else (os.strerror(e.errno) if e.errno else "Unknown error")
        _err(f"mkdir: cannot create directory '{path}': {msg}")
        return 1


def _create_dir_p(path, umask, mode):
    """Create directory path with -p semantics. mode is the exact desired mode
    for the FINAL directory (None for default). Returns 0 or 1."""
    # Normalize: handle trailing slashes, dot components
    # Use os.path normalization but preserve the original for error messages
    normalized = path
    if not normalized.startswith('/'):
        # relative path
        parts = [p for p in normalized.split('/') if p and p != '.']
        if not parts:
            return 0
        normalized = '/'.join(parts)
    else:
        parts = [p for p in normalized.split('/') if p and p != '.']
        if not parts:
            return 0
        normalized = '/' + '/'.join(parts)

    is_absolute = normalized.startswith('/')
    comp_parts = [p for p in normalized.split('/') if p and p != '.']

    if not comp_parts:
        return 0

    current = ''
    for i, part in enumerate(comp_parts):
        if current:
            current = current + '/' + part
        else:
            current = ('/' if is_absolute else '') + part
            if is_absolute:
                current = '/' + part
            else:
                current = part

        is_last = (i == len(comp_parts) - 1)

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

        # Create this component
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
        except NotADirectoryError:
            _err(f"mkdir: cannot create directory '{path}': Not a directory")
            return 1
        except OSError as e:
            msg = e.strerror if e.strerror else (os.strerror(e.errno) if e.errno else "Unknown error")
            _err(f"mkdir: cannot create directory '{path}': {msg}")
            return 1

        if not is_last:
            # Intermediate: ensure owner write and search
            inter_mode = (0o777 & ~umask) | 0o300
            try:
                os.chmod(current, inter_mode)
            except OSError:
                pass
        else:
            # Final directory: apply the requested mode
            if mode is not None:
                try:
                    os.chmod(current, mode)
                except OSError:
                    pass
            # If mode is None, the default (0o777 & ~umask) is already set by the kernel

    return 0


def main() -> int:
    args = sys.argv[1:]
    operands = []
    after_dd = False
    parents = False
    mode_str = None

    i = 0
    while i < len(args):
        arg = args[i]
        if not after_dd:
            if arg == '--':
                after_dd = True
                i += 1
                continue
            if arg == '-':
                operands.append(arg)
                i += 1
                continue
            if arg.startswith('-') and len(arg) > 1:
                if arg == '-p' or arg == '--parents':
                    parents = True
                    i += 1
                    continue
                if arg == '-m' or arg == '--mode':
                    i += 1
                    if i >= len(args):
                        short = arg[1] if arg == '-m' else 'm'
                        _err(f"mkdir: option requires an argument -- '{short}'")
                        _err("Try 'mkdir --help' for more information.")
                        return 1
                    mode_str = args[i]
                    i += 1
                    continue
                if arg.startswith('-m') and len(arg) > 2:
                    mode_str = arg[2:]
                    i += 1
                    continue
                if arg.startswith('--mode='):
                    mode_str = arg[7:]
                    i += 1
                    continue
                # Unknown option
                if arg.startswith('--'):
                    _err(f"mkdir: unrecognized option '{arg}'")
                else:
                    _err(f"mkdir: invalid option -- '{arg[1]}'")
                _err("Try 'mkdir --help' for more information.")
                return 1
            else:
                operands.append(arg)
                i += 1
                continue
        else:
            operands.append(arg)
            i += 1
            continue
        i += 1

    if not operands:
        _err("mkdir: missing operand")
        _err("Try 'mkdir --help' for more information.")
        return 1

    # Validate mode before any filesystem mutation
    umask = _get_umask()
    mode = None
    if mode_str is not None:
        mode = _parse_mode(mode_str, umask)
        if mode is None:
            _err(f"mkdir: invalid mode '{mode_str}'")
            return 1

    rc = 0
    for path in operands:
        if parents:
            r = _create_dir_p(path, umask, mode)
        else:
            r = _create_dir(path, mode)
        if r != 0:
            rc = 1

    return rc


if __name__ == '__main__':
    sys.exit(main())
