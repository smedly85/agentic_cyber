#!/usr/bin/env python3
"""Specification model for new_chmod.

The sort and mkdir suites freeze their goldens from a GNU oracle. new_chmod has
no oracle: it is a deliberately bounded utility (no `s`/`t` in symbolic clauses,
no umask involvement, five options) whose behavior is defined by the checkpoint
prompts, not by any shipping chmod. So this module *is* the oracle -- an
executable restatement of the prompt contract, from which `gen/generate.py`
computes every frozen golden: expected stdout, expected exit status, whether a
diagnostic was written, and the mode every fixture path ends up with.

Keeping the oracle in one place matters for the same reason it matters in the
other suites: a golden is only trustworthy if it was produced by the same rules
the candidate is judged against, and those rules must be readable in one file.

`gen/verify.py` re-derives every frozen case from this module and additionally
checks model-independent invariants on each golden, so a hand-edited suite or a
drifted model is caught rather than quietly accepted.

Scope covered here, matching the checkpoint sequence 000 -> -R -> -c -> -v -> -f:

  * MODE is one to four octal digits (absolute, including setuid/setgid/sticky)
    or comma-separated symbolic clauses `[ugoa...][+-=][rwxX...]` applied to the
    file's current mode. An empty class list means all three classes. The umask
    plays no part. `s` and `t` are not symbolic permission letters here, and no
    symbolic clause changes those three bits.
  * Every operand is attempted; a failure is diagnosed and does not stop the
    rest. Exit status is 0 when everything succeeded and 1 otherwise.
  * -R walks a directory operand pre-order with entries in ascending byte order
    of name, skipping symbolic links found during traversal.
  * -c reports changed files, -v reports every processed file, last one wins.
  * -f suppresses per-operand diagnostics *and* their effect on the exit status,
    but never suppresses a usage error or an invalid MODE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EXIT_OK = 0
EXIT_FAIL = 1

CLASS_BITS = {"u": 0o700, "g": 0o070, "o": 0o007}
PERM_BITS = {"r": 0o444, "w": 0o222, "x": 0o111}

SETUID = 0o4000
SETGID = 0o2000
STICKY = 0o1000
SPECIAL = SETUID | SETGID | STICKY
PERMISSION_MASK = 0o777

SHORT_OPTIONS = {
    "-R": "recursive",
    "-c": "changes",
    "-v": "verbose",
    "-f": "silent",
}
LONG_OPTIONS = {
    "--recursive": "recursive",
    "--changes": "changes",
    "--verbose": "verbose",
    "--silent": "silent",
    "--quiet": "silent",
}

# Which checkpoint flag introduces each feature. `parse_args` uses it to model a
# checkpoint that has not introduced an option yet: at 000 every one of these is
# an unknown option and must be rejected, which is what lets the suite freeze a
# case asserting a feature is NOT there. Without it the model always accepts the
# whole ladder and a candidate that implemented -v at 000 would look correct.
FEATURE_FLAG = {
    "recursive": "-R",
    "changes": "-c",
    "verbose": "-v",
    "silent": "-f",
}


class UsageError(Exception):
    """Argument-level rejection: nothing is attempted."""


class InvalidMode(Exception):
    """MODE could not be parsed: nothing is attempted."""


@dataclass
class Entry:
    """One node of a case's starting filesystem."""

    kind: str  # "file" | "dir" | "symlink"
    mode: int = 0o644
    target: str = ""


@dataclass
class Options:
    mode: str = ""
    operands: list[str] = field(default_factory=list)
    recursive: bool = False
    silent: bool = False
    # Which of -c / -v appeared last, or None when neither did. Both are
    # idempotent when repeated; the later one on the command line wins.
    report: str | None = None


@dataclass
class Clause:
    classes: str  # a subset of "ugo", already expanded from "a"/empty
    operator: str  # "+", "-", "="
    perms: str  # a subset of "rwxX"


@dataclass
class ModeSpec:
    """A parsed MODE: either an absolute octal value or a clause list."""

    octal: int | None = None
    clauses: list[Clause] = field(default_factory=list)


@dataclass
class Result:
    stdout: bytes
    subjects: list[str]
    exit_code: int
    modes: dict[str, int]


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: list[str], implemented: set[str] | None = None) -> Options:
    """Options are recognized only before MODE. The first argument that is not
    an option is MODE; everything after it is an operand, even if it starts with
    a dash. `--` ends option processing, which is how a leading-dash mode such
    as `-w` is written.

    `implemented=None` means the complete ladder, which is what every ordinary
    case is frozen against. Passing a smaller set models an earlier checkpoint,
    where a later checkpoint's option is simply unknown.
    """
    def recognized(name: str) -> bool:
        return implemented is None or FEATURE_FLAG[name] in implemented

    options = Options()
    index = 0

    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            index += 1
            break
        if argument.startswith("-") and argument != "-":
            if argument in LONG_OPTIONS and recognized(LONG_OPTIONS[argument]):
                _apply(options, LONG_OPTIONS[argument])
            elif argument.startswith("--"):
                raise UsageError(f"unrecognized option {argument!r}")
            else:
                for letter in argument[1:]:
                    flag = f"-{letter}"
                    if flag not in SHORT_OPTIONS or not recognized(
                        SHORT_OPTIONS[flag]
                    ):
                        raise UsageError(f"invalid option {flag!r}")
                    _apply(options, SHORT_OPTIONS[flag])
            index += 1
            continue
        break

    if index >= len(argv):
        raise UsageError("missing operand")
    options.mode = argv[index]
    options.operands = argv[index + 1:]
    if not options.operands:
        raise UsageError("missing file operand")
    return options


def _apply(options: Options, name: str) -> None:
    if name == "recursive":
        options.recursive = True
    elif name == "silent":
        options.silent = True
    elif name in ("changes", "verbose"):
        options.report = name


# ---------------------------------------------------------------------------
# MODE parsing
# ---------------------------------------------------------------------------


def parse_mode(text: str) -> ModeSpec:
    if not text:
        raise InvalidMode("empty mode")

    if all(character in "01234567" for character in text):
        if len(text) > 4:
            raise InvalidMode(f"octal mode too long: {text!r}")
        return ModeSpec(octal=int(text, 8))

    clauses: list[Clause] = []
    for piece in text.split(","):
        clauses.append(_parse_clause(piece))
    return ModeSpec(clauses=clauses)


def _parse_clause(piece: str) -> Clause:
    index = 0
    classes = ""
    while index < len(piece) and piece[index] in "ugoa":
        if piece[index] == "a":
            classes = "ugo"
        elif piece[index] not in classes:
            classes += piece[index]
        index += 1
    if index >= len(piece) or piece[index] not in "+-=":
        raise InvalidMode(f"missing operator in clause {piece!r}")
    operator = piece[index]
    index += 1
    perms = piece[index:]
    for letter in perms:
        if letter not in "rwxX":
            raise InvalidMode(f"invalid permission letter {letter!r}")
    # An empty class list means every class; the umask plays no part here.
    return Clause(classes=classes or "ugo", operator=operator, perms=perms)


def apply_mode(spec: ModeSpec, current: int, is_directory: bool) -> int:
    if spec.octal is not None:
        return spec.octal & (SPECIAL | PERMISSION_MASK)

    mode = current
    for clause in spec.clauses:
        class_mask = 0
        for letter in clause.classes:
            class_mask |= CLASS_BITS[letter]

        perm_mask = 0
        for letter in clause.perms:
            if letter == "X":
                # Execute only for a directory, or when the mode as it stands at
                # this point in the clause chain already carries an execute bit.
                if is_directory or (mode & 0o111):
                    perm_mask |= PERM_BITS["x"]
                continue
            perm_mask |= PERM_BITS[letter]

        bits = class_mask & perm_mask
        if clause.operator == "+":
            mode |= bits
        elif clause.operator == "-":
            mode &= ~bits
        else:  # "="
            # Clear only the affected classes' permission bits, then set the
            # listed ones. Special bits are never touched by a symbolic clause.
            mode &= ~(class_mask & PERMISSION_MASK)
            mode |= bits
    return mode & (SPECIAL | PERMISSION_MASK)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_octal(mode: int) -> str:
    return f"{mode & (SPECIAL | PERMISSION_MASK):04o}"


def render_symbolic(mode: int) -> str:
    letters = []
    for shift, special, low, high in (
        (6, SETUID, "s", "S"),
        (3, SETGID, "s", "S"),
        (0, STICKY, "t", "T"),
    ):
        triple = (mode >> shift) & 0o7
        letters.append("r" if triple & 0o4 else "-")
        letters.append("w" if triple & 0o2 else "-")
        if mode & special:
            letters.append(low if triple & 0o1 else high)
        else:
            letters.append("x" if triple & 0o1 else "-")
    return "".join(letters)


def describe(mode: int) -> str:
    return f"{render_octal(mode)} ({render_symbolic(mode)})"


def changed_line(path: str, before: int, after: int) -> bytes:
    text = (
        f"mode of '{path}' changed from {describe(before)} to {describe(after)}\n"
    )
    return text.encode("utf-8", "surrogateescape")


def retained_line(path: str, mode: int) -> bytes:
    text = f"mode of '{path}' retained as {describe(mode)}\n"
    return text.encode("utf-8", "surrogateescape")


# ---------------------------------------------------------------------------
# Filesystem view
# ---------------------------------------------------------------------------


def normalize(path: str) -> str:
    return path.rstrip("/") or path


def join_path(prefix: str, name: str) -> str:
    if prefix.endswith("/"):
        return prefix + name
    return f"{prefix}/{name}"


def sorted_children(filesystem: dict[str, Entry], directory: str) -> list[str]:
    """Immediate child names of `directory`, ascending by raw byte value."""
    prefix = normalize(directory) + "/"
    names = set()
    for path in filesystem:
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix):]
        if not remainder:
            continue
        names.add(remainder.split("/", 1)[0])
    return sorted(names, key=lambda name: name.encode("utf-8", "surrogateescape"))


def resolve(filesystem: dict[str, Entry], path: str) -> str | None:
    """Follow a symlink chain and return the real path, or None if it dangles.

    An operand naming a symlink is followed, exactly as chmod(2) would; the skip
    rule for links applies only to links discovered during traversal.
    """
    current = normalize(path)
    for _ in range(16):
        entry = filesystem.get(current)
        if entry is None:
            return None
        if entry.kind != "symlink":
            return current
        current = normalize(entry.target)
    return None


def listable(mode: int) -> bool:
    """Whether the model considers a directory's contents reachable.

    Fixtures are owned by the user running the suite, so the owner bits decide:
    read to enumerate the entries, execute to stat them.
    """
    return (mode & 0o500) == 0o500


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run(
    argv: list[str],
    filesystem: dict[str, Entry] | None = None,
    implemented: set[str] | None = None,
) -> Result:
    """Return the stdout bytes, the operands a diagnostic was written about, the
    exit status, and the mode every path ends up with.

    `subjects` names what the diagnostics are about. The suite asserts that
    stderr is empty or non-empty and that it mentions the subject, rather than
    pinning exact wording: the prompts specify which conditions are diagnosed,
    not the phrasing.

    `implemented` restricts the option set to one checkpoint's cumulative flags;
    None (the default) is the complete ladder. See parse_args.
    """
    source = filesystem or {}
    modes = {path: entry.mode for path, entry in source.items()}

    try:
        options = parse_args(list(argv), implemented)
    except UsageError:
        return Result(b"", ["usage"], EXIT_FAIL, modes)

    try:
        spec = parse_mode(options.mode)
    except InvalidMode:
        return Result(b"", ["invalid mode"], EXIT_FAIL, modes)

    out = bytearray()
    subjects: list[str] = []
    state = {"failed": False}

    def fail(subject: str) -> None:
        state["failed"] = True
        if not options.silent:
            subjects.append(subject)

    def report(display: str, before: int, after: int) -> None:
        if options.report is None:
            return
        if before != after:
            out.extend(changed_line(display, before, after))
        elif options.report == "verbose":
            out.extend(retained_line(display, before))

    def touch(real: str, display: str) -> int:
        entry = source[real]
        before = modes[real]
        after = apply_mode(spec, before, entry.kind == "dir")
        modes[real] = after
        report(display, before, after)
        return after

    def walk(real: str, display: str, mode_after: int) -> None:
        if not listable(mode_after):
            fail(display)
            return
        for name in sorted_children(source, real):
            child_real = join_path(normalize(real), name)
            child_display = join_path(display, name)
            child = source[child_real]
            if child.kind == "symlink":
                # Neither followed nor modified, so a link cycle cannot make the
                # walk unbounded.
                continue
            child_mode = touch(child_real, child_display)
            if child.kind == "dir":
                walk(child_real, child_display, child_mode)

    for operand in options.operands:
        real = resolve(source, operand)
        if real is None:
            fail(operand)
            continue
        after = touch(real, operand)
        if options.recursive and source[real].kind == "dir":
            walk(real, operand, after)

    exit_code = EXIT_FAIL if (state["failed"] and not options.silent) else EXIT_OK
    return Result(bytes(out), subjects, exit_code, modes)
