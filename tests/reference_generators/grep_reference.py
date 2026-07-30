#!/usr/bin/env python3
"""Specification model for new_grep.

The sort and mkdir suites freeze their goldens from a GNU oracle. new_grep has
no oracle: it is a deliberately bounded utility (fixed-string matching, five
options, no regular expressions) whose behavior is defined by the checkpoint
prompts, not by any shipping grep. So this module *is* the oracle -- an
executable restatement of the prompt contract, from which `gen/generate.py`
computes every frozen golden.

Keeping the oracle in one place matters for the same reason it matters in the
other suites: a golden is only trustworthy if it was produced by the same rules
the candidate is judged against, and those rules must be readable in one file.

`gen/verify.py` re-derives every frozen case from this module and additionally
checks model-independent invariants on each golden, so a hand-edited suite or a
drifted model is caught rather than quietly accepted.

Scope covered here, matching the checkpoint sequence 000 -> -H -> -h -> -r -> -i:

  * PATTERN is a fixed byte string; a line matches when PATTERN occurs as a
    contiguous byte substring. An empty PATTERN matches every line.
  * Input is byte-oriented and newline-delimited. A final line with no trailing
    newline is still a line. Every emitted line ends with a newline.
  * With no file operands, standard input is searched.
  * Filename prefixes are `NAME:` immediately before the line's bytes.
  * Exit status: 0 when at least one line was selected and no error occurred,
    1 when no line was selected and no error occurred, 2 when any error
    occurred (regardless of matches).
"""

from __future__ import annotations

from dataclasses import dataclass, field

STDIN_NAME = b"(standard input)"

SHORT_OPTIONS = {
    "-H": "with_filename",
    "-h": "no_filename",
    "-r": "recursive",
    "-i": "ignore_case",
}
LONG_OPTIONS = {
    "--with-filename": "with_filename",
    "--no-filename": "no_filename",
    "--recursive": "recursive",
    "--ignore-case": "ignore_case",
}

# Which checkpoint flag introduces each feature. `parse_args` uses it to model a
# checkpoint that has not introduced an option yet: at 000 every one of these is
# an unknown option and must be rejected, which is what lets the suite freeze a
# case asserting a feature is NOT there. Without it the model always accepts the
# whole ladder and a candidate that implemented -i at 000 would look correct.
FEATURE_FLAG = {
    "with_filename": "-H",
    "no_filename": "-h",
    "recursive": "-r",
    "ignore_case": "-i",
}

EXIT_MATCH = 0
EXIT_NO_MATCH = 1
EXIT_ERROR = 2


class UsageError(Exception):
    """Argument-level rejection: nothing is searched and nothing is selected."""


@dataclass
class Options:
    pattern: bytes = b""
    operands: list[str] = field(default_factory=list)
    recursive: bool = False
    ignore_case: bool = False
    # Which of -H / -h appeared last, or None when neither did. Both are
    # idempotent when repeated; the later one on the command line wins.
    filename_override: str | None = None


@dataclass
class Entry:
    """One node of a case's starting filesystem."""

    kind: str  # "file" | "dir" | "symlink"
    contents: bytes = b""
    target: str = ""
    readable: bool = True


def fold(data: bytes) -> bytes:
    """ASCII-only, locale-independent case folding. Bytes >= 0x80 are left
    alone, so UTF-8 sequences are never altered."""
    return bytes(
        byte + 32 if 0x41 <= byte <= 0x5A else byte for byte in data
    )


def split_lines(data: bytes) -> list[bytes]:
    """Newline-delimited records without their terminators. A trailing newline
    does not create an empty final record; a missing one does not lose the
    final record."""
    if not data:
        return []
    records = data.split(b"\n")
    if records and records[-1] == b"":
        records.pop()
    return records


def parse_args(argv: list[str], implemented: set[str] | None = None) -> Options:
    """Parse argv as the checkpoint whose cumulative flags are `implemented`.

    `implemented=None` means the complete ladder, which is what every ordinary
    case is frozen against. Passing a smaller set models an earlier checkpoint,
    where a later checkpoint's option is simply unknown.
    """
    def recognized(name: str) -> bool:
        return implemented is None or FEATURE_FLAG[name] in implemented

    options = Options()
    operands: list[str] = []
    saw_terminator = False
    index = 0

    while index < len(argv):
        argument = argv[index]
        if not saw_terminator and argument == "--":
            saw_terminator = True
            index += 1
            continue
        if (
            not saw_terminator
            and argument.startswith("-")
            and argument != "-"
        ):
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
        operands.append(argument)
        index += 1

    if not operands:
        raise UsageError("missing PATTERN")
    options.pattern = operands[0].encode("utf-8", "surrogateescape")
    options.operands = operands[1:]
    return options


def _apply(options: Options, name: str) -> None:
    if name == "with_filename":
        options.filename_override = "with_filename"
    elif name == "no_filename":
        options.filename_override = "no_filename"
    elif name == "recursive":
        options.recursive = True
    elif name == "ignore_case":
        options.ignore_case = True


def matches(line: bytes, pattern: bytes, ignore_case: bool) -> bool:
    if not pattern:
        return True
    if ignore_case:
        return fold(pattern) in fold(line)
    return pattern in line


def join_path(prefix: str, name: str) -> str:
    if prefix.endswith("/"):
        return prefix + name
    return f"{prefix}/{name}"


def _sorted_children(filesystem: dict[str, Entry], directory: str) -> list[str]:
    """Immediate child names of `directory`, ascending by raw byte value."""
    prefix = directory if directory.endswith("/") else directory + "/"
    names = set()
    for path in filesystem:
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix):]
        if not remainder:
            continue
        names.add(remainder.split("/", 1)[0])
    return sorted(names, key=lambda name: name.encode("utf-8", "surrogateescape"))


def prefix_filenames(options: Options, filesystem: dict[str, Entry]) -> bool:
    """Decided from argv plus one lookup per operand, before any output.

    The rule is deliberately lookahead-free: an implementation never has to
    expand a directory tree to know whether the first emitted line carries a
    prefix.
    """
    if options.filename_override == "no_filename":
        return False
    if options.filename_override == "with_filename":
        return True
    if len(options.operands) > 1:
        return True
    if options.recursive:
        return any(
            _resolve(filesystem, operand) is not None
            and _resolve(filesystem, operand).kind == "dir"
            for operand in options.operands
        )
    return False


def _resolve(filesystem: dict[str, Entry], path: str) -> Entry | None:
    """Look a path up, following symlinks (an explicit operand naming a symlink
    is opened through it, exactly as open(2) would)."""
    seen = 0
    current = path.rstrip("/") or path
    while seen < 16:
        entry = filesystem.get(current) or filesystem.get(path)
        if entry is None:
            return None
        if entry.kind != "symlink":
            return entry
        current = entry.target
        seen += 1
    return None


def run(
    argv: list[str],
    stdin: bytes = b"",
    filesystem: dict[str, Entry] | None = None,
    implemented: set[str] | None = None,
) -> tuple[bytes, list[str], int]:
    """Return (stdout, diagnostic_subjects, exit_code).

    `diagnostic_subjects` names the operands a diagnostic was written about.
    The suite asserts that stderr is empty or non-empty and that it mentions
    the subject, rather than pinning exact wording: the prompts specify which
    conditions are diagnosed, not the phrasing.

    `implemented` restricts the option set to one checkpoint's cumulative flags;
    None (the default) is the complete ladder. See parse_args.
    """
    filesystem = filesystem or {}
    try:
        options = parse_args(argv, implemented)
    except UsageError:
        return b"", ["usage"], EXIT_ERROR

    prefix = prefix_filenames(options, filesystem)
    out = bytearray()
    subjects: list[str] = []
    selected = False
    errored = False

    def emit(name: bytes, line: bytes) -> None:
        if prefix:
            out.extend(name)
            out.extend(b":")
        out.extend(line)
        out.extend(b"\n")

    def search_file(name: str, contents: bytes) -> None:
        nonlocal selected
        for line in split_lines(contents):
            if matches(line, options.pattern, options.ignore_case):
                selected = True
                emit(name.encode("utf-8", "surrogateescape"), line)

    if not options.operands:
        for line in split_lines(stdin):
            if matches(line, options.pattern, options.ignore_case):
                selected = True
                emit(STDIN_NAME, line)
        return bytes(out), subjects, _status(selected, errored)

    for operand in options.operands:
        entry = _resolve(filesystem, operand)
        if entry is None:
            errored = True
            subjects.append(operand)
            continue
        if entry.kind == "dir":
            if not options.recursive:
                errored = True
                subjects.append(operand)
                continue
            errored |= _walk(
                filesystem, operand, options, search_file, subjects
            )
            continue
        if not entry.readable:
            errored = True
            subjects.append(operand)
            continue
        search_file(operand, entry.contents)

    return bytes(out), subjects, _status(selected, errored)


def _walk(
    filesystem: dict[str, Entry],
    directory: str,
    options: Options,
    search_file,
    subjects: list[str],
) -> bool:
    """Pre-order traversal in ascending byte order of entry name. Symlinks
    reached during traversal are skipped rather than followed, so a link cycle
    can never turn a bounded walk unbounded."""
    errored = False
    for name in _sorted_children(filesystem, directory):
        path = join_path(directory, name)
        entry = filesystem.get(path)
        if entry is None:
            continue
        if entry.kind == "symlink":
            continue
        if entry.kind == "dir":
            errored |= _walk(filesystem, path, options, search_file, subjects)
            continue
        if not entry.readable:
            errored = True
            subjects.append(path)
            continue
        search_file(path, entry.contents)
    return errored


def _status(selected: bool, errored: bool) -> int:
    if errored:
        return EXIT_ERROR
    return EXIT_MATCH if selected else EXIT_NO_MATCH
