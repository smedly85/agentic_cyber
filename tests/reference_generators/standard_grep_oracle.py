#!/usr/bin/env python3
"""Trusted GNU grep 3.12 adapter for the standardized bounded grep corpus.

This module is controller-only and is never staged into a candidate bundle.
GNU grep supplies every matching result through ``-a -F`` under ``LC_ALL=C``.
The adapter supplies only the benchmark's deliberately bounded argument grammar
and deterministic recursive file ordering.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

VERSION = "grep (GNU grep) 3.12"
FLAGS = {"H": "-H", "h": "-h", "r": "-r", "i": "-i"}
LONG = {"--with-filename": "-H", "--no-filename": "-h",
        "--recursive": "-r", "--ignore-case": "-i"}
ENV = {"LC_ALL": "C", "LANG": "C", "LANGUAGE": "C", "TZ": "UTC"}


class UsageError(ValueError):
    pass


def parse(argv: list[str], implemented: set[str]) -> tuple[dict, str, list[str]]:
    operands: list[str] = []
    state = {"recursive": False, "ignore_case": False, "filename": None}
    terminated = False
    for token in argv:
        if not terminated and token == "--":
            terminated = True
            continue
        if not terminated and token.startswith("-") and token != "-":
            if token.startswith("--"):
                flag = LONG.get(token)
                if flag is None or flag not in implemented:
                    raise UsageError(token)
                options = [flag]
            else:
                options = []
                for letter in token[1:]:
                    flag = FLAGS.get(letter)
                    if flag is None or flag not in implemented:
                        raise UsageError("-" + letter)
                    options.append(flag)
            for flag in options:
                if flag == "-r":
                    state["recursive"] = True
                elif flag == "-i":
                    state["ignore_case"] = True
                else:
                    state["filename"] = flag
            continue
        operands.append(token)
    if not operands:
        raise UsageError("missing PATTERN")
    return state, operands[0], operands[1:]


def _children(directory: str) -> list[str]:
    names = os.listdir(directory)
    return sorted(names, key=os.fsencode)


def walk(directory: str) -> list[str]:
    """Pre-order regular-file traversal, byte-sorted, never following links."""
    root = directory.rstrip("/") or directory
    found: list[str] = []

    def visit(path: str) -> None:
        for name in _children(path):
            child = os.path.join(path, name)
            if os.path.islink(child):
                continue
            if os.path.isdir(child):
                visit(child)
            else:
                found.append(child)

    visit(root)
    return found


def _invoke(binary: str, pattern: str, operand: str | None, *, prefix: bool,
            ignore_case: bool, stdin: bytes | None = None,
            label: str | None = None) -> tuple[int, bytes, bytes]:
    args = [binary, "-a", "-F"]
    if ignore_case:
        args.append("-i")
    args.append("-H" if prefix else "-h")
    if label is not None:
        args.append("--label=" + label)
    args += ["-e", pattern, "--"]
    if operand is not None:
        args.append(operand)
    completed = subprocess.run(
        args, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, **ENV}, timeout=60,
    )
    if completed.returncode not in (0, 1, 2):
        raise RuntimeError(f"GNU grep terminated abnormally: {completed.returncode}")
    return completed.returncode, completed.stdout, completed.stderr


def run(binary: str, implemented: set[str], argv: list[str],
        stdin: bytes) -> tuple[int, bytes, bytes]:
    try:
        state, pattern, operands = parse(argv, implemented)
    except UsageError as error:
        return 2, b"", ("grep: " + str(error) + "\n").encode()

    recursive = bool(state["recursive"])
    prefix = state["filename"] == "-H"
    if state["filename"] is None:
        prefix = len(operands) > 1 or (
            recursive and any(os.path.isdir(path) and not os.path.islink(path)
                              for path in operands)
        )

    if not operands:
        return _invoke(binary, pattern, None, prefix=prefix,
                       ignore_case=bool(state["ignore_case"]), stdin=stdin)

    output = bytearray()
    diagnostics = bytearray()
    matched = False
    errored = False

    def one(path: str, shown: str | None = None) -> None:
        nonlocal matched, errored
        if path == "-":
            try:
                data = Path(path).read_bytes()
            except OSError as error:
                diagnostics.extend(f"grep: {path}: {error.strerror}\n".encode())
                errored = True
                return
            code, out, err = _invoke(binary, pattern, None, prefix=prefix,
                                     ignore_case=bool(state["ignore_case"]),
                                     stdin=data, label=shown or path)
        else:
            code, out, err = _invoke(binary, pattern, path, prefix=prefix,
                                     ignore_case=bool(state["ignore_case"]))
        output.extend(out)
        diagnostics.extend(err)
        matched |= code == 0
        errored |= code == 2

    for operand in operands:
        if recursive and os.path.isdir(operand) and not os.path.islink(operand):
            try:
                members = walk(operand)
            except OSError as error:
                diagnostics.extend(f"grep: {operand}: {error.strerror}\n".encode())
                errored = True
                continue
            for member in members:
                one(member)
        else:
            one(operand)

    return (2 if errored else 0 if matched else 1), bytes(output), bytes(diagnostics)


def verify(binary: str) -> dict:
    """Fail closed unless the binary and the contract-critical behavior match."""
    version = subprocess.check_output([binary, "--version"], text=True,
                                      env={**os.environ, **ENV}).splitlines()[0]
    if version != VERSION:
        raise RuntimeError(f"GNU grep oracle identity mismatch: {version!r}")
    probes = [
        (["a.c"], b"abc\na.c\n", b"a.c\n"),
        (["-i", "GAMMA"], b"Gamma\ngamma\n" + bytes.fromhex("c389") + b"GAMMA\n",
         b"Gamma\ngamma\n" + bytes.fromhex("c389") + b"GAMMA\n"),
        (["needle"], b"pre\x00needle\x00post\n", b"pre\x00needle\x00post\n"),
        (["last"], b"first\nlast-no-newline", b"last-no-newline\n"),
    ]
    for argv, data, expected in probes:
        status, out, err = run(binary, {"-H", "-h", "-r", "-i"}, argv, data)
        if status != 0 or out != expected or err:
            raise RuntimeError(f"GNU grep behavioral probe failed: {argv!r}")
    with tempfile.TemporaryDirectory() as directory:
        previous = os.getcwd()
        try:
            os.chdir(directory)
            Path("b.txt").write_bytes(b"needle b\n")
            Path("a.txt").write_bytes(b"needle a\n")
            Path("tree/z").parent.mkdir()
            Path("tree/z").write_bytes(b"needle z\n")
            Path("tree/a").write_bytes(b"needle a\n")
            file_probes = [
                (["needle", "a.txt", "b.txt"], b"", b"a.txt:needle a\nb.txt:needle b\n"),
                (["-H", "needle", "a.txt"], b"", b"a.txt:needle a\n"),
                (["-h", "needle", "a.txt", "b.txt"], b"", b"needle a\nneedle b\n"),
                (["-r", "needle", "tree"], b"", b"tree/a:needle a\ntree/z:needle z\n"),
            ]
            for argv, data, expected in file_probes:
                status, out, err = run(binary, {"-H", "-h", "-r", "-i"}, argv, data)
                if status != 0 or out != expected or err:
                    raise RuntimeError(f"GNU grep file/traversal probe failed: {argv!r}")
        finally:
            os.chdir(previous)
    return {"version": version,
            "sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
            "adapter": "-a -F; LC_ALL=C; deterministic byte-sorted recursion"}


def main() -> int:
    if len(sys.argv) < 3:
        print("oracle adapter usage error", file=sys.stderr)
        return 2
    binary = sys.argv[1]
    implemented = set(filter(None, sys.argv[2].split(",")))
    status, out, err = run(binary, implemented, sys.argv[3:], sys.stdin.buffer.read())
    sys.stdout.buffer.write(out)
    sys.stderr.buffer.write(err)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
