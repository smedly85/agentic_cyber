"""Fail-closed helpers for reproducibly reconstructed downstream source trees."""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping


class DownstreamSourceError(ValueError):
    pass


@dataclass(frozen=True)
class RPMPatchApplication:
    """One statically resolved RPM ``%patch`` application."""

    number: int
    path: str
    strip_level: int


def _contained_file(root: Path, relative_name: str) -> Path:
    relative = PurePosixPath(relative_name)
    if (
        not relative_name
        or "\\" in relative_name
        or relative.is_absolute()
        or PureWindowsPath(relative_name).drive
        or ".." in relative.parts
    ):
        raise DownstreamSourceError(
            f"unsafe downstream packaging path: {relative_name}"
        )
    candidate = root.joinpath(*relative.parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise DownstreamSourceError(
            f"downstream packaging path escapes checkout: {relative_name}"
        ) from error
    if not candidate.is_file():
        raise DownstreamSourceError(
            f"downstream packaging component is missing: {relative_name}"
        )
    return candidate


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_packaging_components(
    checkout: Path, metadata: Mapping[str, Any],
) -> dict[str, Path]:
    """Verify the frozen spec and security patch in an exported package commit."""
    verified: dict[str, Path] = {}
    for label, path_field, digest_field in (
        ("spec", "spec_file", "spec_sha256"),
        ("security_patch", "security_patch_file", "security_patch_sha256"),
    ):
        relative = metadata.get(path_field)
        expected = metadata.get(digest_field)
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise DownstreamSourceError(
                f"downstream metadata lacks {path_field}/{digest_field}"
            )
        path = _contained_file(checkout, relative)
        observed = file_sha256(path)
        if observed != expected:
            raise DownstreamSourceError(
                f"{label} checksum mismatch: observed {observed}, expected {expected}"
            )
        verified[label] = path
    return verified


_RPM_SECTIONS = {
    "%build", "%check", "%clean", "%description", "%files", "%generate_buildrequires",
    "%install", "%package", "%post", "%posttrans", "%postun", "%pre", "%prep",
    "%pretrans", "%preun", "%triggerin", "%triggerpostun", "%triggerprein",
    "%triggerun", "%verifyscript",
}
_RPM_IF_DIRECTIVE = re.compile(r"%(?:if|ifarch|ifnarch|ifos|ifnos)\b", re.IGNORECASE)


def _patch_application(line: str, declarations: Mapping[int, str]) -> RPMPatchApplication:
    match = re.fullmatch(r"\s*%patch(?P<inline>\d*)\b(?P<arguments>.*)", line)
    if match is None:
        raise DownstreamSourceError(f"unsupported RPM patch directive: {line.strip()}")
    try:
        arguments = shlex.split(match.group("arguments"), comments=True, posix=True)
    except ValueError as error:
        raise DownstreamSourceError(
            f"malformed RPM patch directive: {line.strip()}"
        ) from error
    if any("%{" in item for item in arguments):
        raise DownstreamSourceError(
            f"macro-dependent RPM patch directive is unsupported: {line.strip()}"
        )

    inline = match.group("inline")
    number = int(inline) if inline else 0
    explicit_number: int | None = None
    strip_level = 0
    strip_level_seen = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-P":
            if explicit_number is not None:
                raise DownstreamSourceError(
                    f"RPM patch number is specified more than once: {line.strip()}"
                )
            index += 1
            if index >= len(arguments) or not arguments[index].isdigit():
                raise DownstreamSourceError(
                    f"%patch -P requires a numeric patch number: {line.strip()}"
                )
            explicit_number = int(arguments[index])
        elif re.fullmatch(r"-P\d+", argument):
            if explicit_number is not None:
                raise DownstreamSourceError(
                    f"RPM patch number is specified more than once: {line.strip()}"
                )
            explicit_number = int(argument[2:])
        elif argument == "-p":
            if strip_level_seen:
                raise DownstreamSourceError(
                    f"RPM patch strip level is specified more than once: {line.strip()}"
                )
            index += 1
            if index >= len(arguments) or not arguments[index].isdigit():
                raise DownstreamSourceError(
                    f"%patch -p requires a numeric strip level: {line.strip()}"
                )
            strip_level = int(arguments[index])
            strip_level_seen = True
        elif re.fullmatch(r"-p\d+", argument):
            if strip_level_seen:
                raise DownstreamSourceError(
                    f"RPM patch strip level is specified more than once: {line.strip()}"
                )
            strip_level = int(argument[2:])
            strip_level_seen = True
        elif argument in {"-b", "-z", "-d"}:
            index += 1
            if index >= len(arguments):
                raise DownstreamSourceError(
                    f"{argument} requires a value in RPM patch directive: {line.strip()}"
                )
        elif argument in {"-E", "-R", "-s"}:
            pass
        else:
            raise DownstreamSourceError(
                f"unsupported RPM patch argument {argument!r}: {line.strip()}"
            )
        index += 1

    if explicit_number is not None:
        if inline and explicit_number != number:
            raise DownstreamSourceError(
                f"conflicting RPM patch numbers in directive: {line.strip()}"
            )
        number = explicit_number
    if number not in declarations:
        raise DownstreamSourceError(
            f"%patch for Patch{number} has no matching declaration"
        )
    return RPMPatchApplication(number, declarations[number], strip_level)


def rpm_patch_sequence(spec_text: str) -> list[RPMPatchApplication]:
    """Resolve a static, unconditional ``%prep`` patch sequence or fail closed.

    This intentionally does not evaluate RPM conditionals or macros. Bare
    ``%patch`` denotes Patch0, and both ``%patchN`` and ``%patch -P N`` are
    supported. The effective strip level is retained for reconstruction.
    """
    declarations: dict[int, str] = {}
    declaration_conditional_depth = 0
    for line in spec_text.splitlines():
        stripped = line.strip()
        directive = stripped.split(maxsplit=1)[0].lower() if stripped.startswith("%") else ""
        if _RPM_IF_DIRECTIVE.fullmatch(directive):
            declaration_conditional_depth += 1
            continue
        if directive == "%endif":
            declaration_conditional_depth = max(0, declaration_conditional_depth - 1)
            continue
        match = re.match(r"\s*Patch(?P<number>\d*)\s*:\s*(?P<path>\S+)", line)
        if not match:
            continue
        number = int(match.group("number") or "0")
        path = match.group("path")
        if declaration_conditional_depth:
            raise DownstreamSourceError(
                f"conditional Patch{number} declaration is unsupported"
            )
        if "%{" in path:
            raise DownstreamSourceError(
                f"macro-dependent Patch{number} declaration is unsupported"
            )
        if number in declarations:
            raise DownstreamSourceError(f"duplicate Patch{number} declaration")
        declarations[number] = path

    sequence: list[RPMPatchApplication] = []
    conditional_stack: list[bool] = []
    in_prep = False
    saw_prep = False
    for line_number, line in enumerate(spec_text.splitlines(), start=1):
        stripped = line.strip()
        directive = stripped.split(maxsplit=1)[0].lower() if stripped.startswith("%") else ""
        if _RPM_IF_DIRECTIVE.fullmatch(directive):
            if in_prep:
                raise DownstreamSourceError(
                    f"conditional %prep sequencing is unsupported at line {line_number}"
                )
            conditional_stack.append(False)
            continue
        if directive == "%else":
            if not conditional_stack or conditional_stack[-1]:
                raise DownstreamSourceError(
                    f"malformed RPM conditional %else at line {line_number}"
                )
            if in_prep:
                raise DownstreamSourceError(
                    f"conditional %prep sequencing is unsupported at line {line_number}"
                )
            conditional_stack[-1] = True
            continue
        if directive == "%endif":
            if not conditional_stack:
                raise DownstreamSourceError(
                    f"malformed RPM conditional %endif at line {line_number}"
                )
            if in_prep:
                raise DownstreamSourceError(
                    f"conditional %prep sequencing is unsupported at line {line_number}"
                )
            conditional_stack.pop()
            continue
        if directive == "%prep":
            if saw_prep:
                raise DownstreamSourceError("RPM spec contains multiple %prep sections")
            if conditional_stack:
                raise DownstreamSourceError(
                    "conditional %prep section is unsupported"
                )
            saw_prep = True
            in_prep = True
            continue
        if in_prep and directive in _RPM_SECTIONS:
            in_prep = False
        if in_prep and "%patch" in stripped.lower():
            if conditional_stack:
                raise DownstreamSourceError(
                    f"conditional %patch sequencing is unsupported at line {line_number}"
                )
            if not re.match(r"\s*%patch(?:\d+)?\b", line, re.IGNORECASE):
                raise DownstreamSourceError(
                    f"macro-dependent RPM patch sequencing is unsupported at line {line_number}"
                )
            sequence.append(_patch_application(line, declarations))
    if conditional_stack:
        raise DownstreamSourceError("unterminated RPM conditional structure")
    if not saw_prep:
        raise DownstreamSourceError("RPM spec contains no %prep section")
    if not sequence:
        raise DownstreamSourceError("RPM spec contains no unconditional %patch sequence")
    numbers = [item.number for item in sequence]
    if len(numbers) != len(set(numbers)):
        raise DownstreamSourceError("RPM spec applies a patch more than once")
    return sequence
