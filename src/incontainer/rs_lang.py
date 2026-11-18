"""Rust function location, splicing and compiler-based checks (runs in agent-rust).

Locations and signatures come from `rs-items` (a rustc_private driver, see
rs_items.rs): rustc's own def paths, spans, fn_sig and predicates.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ATTR_LINE = re.compile(r"^\s*(#\[|///|//!|/\*\*)")
USE_START = re.compile(r"^(pub(\([^)]*\))?\s+)?use\s")


class RustLangError(RuntimeError):
    pass


# ---------------------------------------------------------------- inventory

def _sysroot() -> str:
    version = os.environ.get("AGENT_RUST_VERSION", "1.93.0")
    return subprocess.run(["rustc", f"+{version}", "--print", "sysroot"], capture_output=True, text=True, check=True).stdout.strip()


def _cargo_has_deps(project: Path) -> bool:
    manifest = project / "Cargo.toml"
    if not manifest.is_file():
        return False
    data = tomllib.loads(manifest.read_text())
    return bool(data.get("dependencies"))


def inventory(project: Path, crate_root: str, crate_name: str) -> dict[str, Any]:
    """Run rs-items over the crate; returns {"crate", "functions", "items"}."""
    project = project.resolve()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "items.jsonl"
        env = dict(os.environ, AGENT_RS_ITEMS_OUT=str(out), RUSTC_BOOTSTRAP="1")
        if _cargo_has_deps(project):
            env.update(RUSTC_WORKSPACE_WRAPPER="rs-items", CARGO_TARGET_DIR=str(Path(tmp) / "target"))
            proc = subprocess.run(["cargo", "check", "--offline", "--quiet"], cwd=project, capture_output=True, text=True, env=env)
        else:
            argv = [
                "rs-items", str(project / crate_root), "--edition=2021", "--crate-type=bin",
                f"--crate-name={crate_name}", "--sysroot", _sysroot(), "-o", str(Path(tmp) / "out"),
            ]
            edition = _edition(project)
            if edition:
                argv[2] = f"--edition={edition}"
            proc = subprocess.run(argv, cwd=project, capture_output=True, text=True, env=env)
        docs = [json.loads(line) for line in out.read_text().splitlines() if line.strip()] if out.is_file() else []
        docs = [d for d in docs if d.get("crate") == crate_name] or docs
        if not docs:
            raise RustLangError(_errors(proc.stderr) or f"rs-items produced no output (exit {proc.returncode})")
        doc = docs[-1]
    for row in doc["functions"] + doc["items"]:
        row["file"] = _relative(project, row["file"])
    return doc


def _edition(project: Path) -> str | None:
    manifest = project / "Cargo.toml"
    if manifest.is_file():
        return tomllib.loads(manifest.read_text()).get("package", {}).get("edition")
    return None


def _errors(stderr: str, limit: int = 60) -> str:
    lines = stderr.splitlines()
    keep, take = [], False
    for line in lines:
        if line.startswith("error"):
            take = True
        elif line.startswith("warning"):
            take = False
        if take:
            keep.append(line)
    return "\n".join(keep[: limit]) if keep else stderr[-3000:]


def _relative(project: Path, path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = (project / p).resolve()
    try:
        return p.resolve().relative_to(project).as_posix()
    except ValueError:
        return p.as_posix()


# ---------------------------------------------------------------- locate

def _line_of(data: bytes, offset: int) -> int:
    return data.count(b"\n", 0, offset) + 1


def _extend_over_attributes(data: bytes, lo: int) -> int:
    """Move `lo` back over preceding attribute / doc-comment lines."""
    line_start = data.rfind(b"\n", 0, lo) + 1
    start = line_start if data[line_start:lo].strip() == b"" else lo
    while start > 0:
        prev_end = start - 1  # the '\n' before `start`
        prev_start = data.rfind(b"\n", 0, prev_end) + 1
        prev = data[prev_start:prev_end].decode(errors="replace")
        if ATTR_LINE.match(prev):
            start = prev_start
        else:
            break
    return start


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _signature(fn: dict[str, Any], data: bytes, start: int) -> dict[str, Any]:
    header = data[start : fn["body_lo"]].decode(errors="replace") if fn.get("body_lo") is not None else ""
    attr_text = data[start : fn["lo"]].decode(errors="replace")
    return {
        "path": fn["path"],
        "fn_sig": fn["fn_sig"],
        "predicates": sorted(fn["predicates"]),
        "generics": fn["generics"],
        "param_patterns": fn["param_patterns"],
        "visibility": re.sub(r"\[[0-9a-f]+\]", "", fn["visibility"]),
        "asyncness": fn["asyncness"],
        "header": _normalize(header),
        "attributes": [_normalize(l) for l in attr_text.splitlines() if l.strip()],
    }


def describe(project: Path, fn: dict[str, Any]) -> dict[str, Any]:
    data = (project / fn["file"]).read_bytes()
    start = _extend_over_attributes(data, fn["lo"])
    end = fn["hi"]
    return {
        "language": "rust",
        "key": fn["verbose"],
        "name": fn["path"],
        "file": fn["file"],
        "start": start,
        "end": end,
        "line": _line_of(data, fn["lo"]),
        "parent_kind": fn["parent_kind"],
        "original_text": data[start:end].decode(),
        "signature": _signature(fn, data, start),
    }


def list_functions(project: Path, crate_root: str, crate_name: str) -> list[dict[str, Any]]:
    doc = inventory(project, crate_root, crate_name)
    out = []
    for fn in doc["functions"]:
        if not fn["has_body"] or fn["file"].startswith("/"):
            continue
        out.append(describe(project, fn))
    return out


def locate(project: Path, crate_root: str, crate_name: str, key: str) -> dict[str, Any]:
    hits = [f for f in inventory(project, crate_root, crate_name)["functions"] if f["verbose"] == key and f["has_body"]]
    if len(hits) != 1:
        raise RustLangError(f"expected one definition for {key!r}, found {len(hits)}")
    return describe(project, hits[0])


# ---------------------------------------------------------------- splice + checks

@dataclass
class SpliceOutcome:
    ok: bool
    stage: str
    message: str
    additions: dict[str, list[str]] = field(default_factory=dict)


def _split_uses(edited: str) -> tuple[list[str], str]:
    """Pull column-0 `use ...;` statements (possibly multi-line) out of the file."""
    uses, kept = [], []
    lines = edited.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        if USE_START.match(line):
            chunk = [line]
            while not chunk[-1].rstrip().endswith(";") and i + 1 < len(lines):
                i += 1
                chunk.append(lines[i])
            uses.append("".join(chunk).rstrip("\n"))
        else:
            kept.append(line)
        i += 1
    return uses, "".join(kept)


def _hoist_uses(text: str, uses: list[str]) -> tuple[str, int]:
    """Insert `use` items after leading inner attributes/comments; returns (text, bytes inserted before rest)."""
    existing = {_normalize(u) for u in re.findall(r"^(?:pub(?:\([^)]*\))?\s+)?use\s[^;]*;", text, re.M)}
    new = [u for u in uses if _normalize(u) not in existing]
    if not new:
        return text, 0
    pos = 0
    for match in re.finditer(r"^(#!\[[^\n]*\]|//[^\n]*)\n", text, re.M):
        if match.start() != pos:
            break
        pos = match.end()
    block = "\n".join(new) + "\n"
    return text[:pos] + block + text[pos:], len(block.encode())


def splice(project: Path, crate_root: str, crate_name: str, target: dict[str, Any], edited: str, allow: dict[str, bool]) -> SpliceOutcome:
    path = project / target["file"]
    original = path.read_bytes()
    start, end = target["start"], target["end"]
    if original[start:end].decode(errors="replace") != target["original_text"]:
        return SpliceOutcome(False, "splice", "internal: target bytes changed underneath the splice")
    uses, body = _split_uses(edited)
    body = body.strip("\n")
    new_text = (original[:start] + body.encode() + original[end:]).decode()
    region_start = start
    if uses:
        root = project / crate_root
        if root.resolve() == path.resolve():
            new_text, shift = _hoist_uses(new_text, uses)
            region_start += shift
        else:
            root.write_text(_hoist_uses(root.read_text(), uses)[0])
    path.write_text(new_text)
    region = (region_start, region_start + len(body.encode()))

    try:
        doc = inventory(project, crate_root, crate_name)
    except RustLangError as exc:
        return SpliceOutcome(False, "build", f"compilation failed after splicing:\n{exc}")

    def inside(row: dict[str, Any]) -> bool:
        return row["file"] == target["file"] and region[0] <= row["lo"] < region[1]

    fns = [f for f in doc["functions"] if inside(f)]
    target_rows = [f for f in fns if f["path"] == target["signature"]["path"]]
    if len(target_rows) != 1:
        return SpliceOutcome(False, "signature", f"the function file must define `{target['name']}` exactly once (found {len(target_rows)})")
    helpers = sorted(f["path"] for f in fns if f is not target_rows[0])
    globals_types = sorted(f"{i['kind']}:{i['path']}" for i in doc["items"] if inside(i) and i["kind"] not in ("use", "impl"))
    impls = [i for i in doc["items"] if inside(i) and i["kind"] == "impl"]
    globals_types += sorted(f"impl:{i['path']}" for i in impls)
    additions = {"helpers": helpers, "includes": uses, "globals_types": globals_types}

    violations = []
    if helpers and not allow.get("allow_new_helpers", True):
        violations.append(f"new helper functions are not allowed: {', '.join(helpers)}")
    if uses and not allow.get("allow_new_includes", True):
        violations.append("new `use` declarations are not allowed")
    if globals_types and not allow.get("allow_new_globals_types", True):
        violations.append(f"new globals/types are not allowed: {', '.join(globals_types)}")
    if violations:
        return SpliceOutcome(False, "additions", "; ".join(violations), additions)

    data = path.read_bytes()
    got = _signature(target_rows[0], data, _extend_over_attributes(data, target_rows[0]["lo"]))
    diff = signature_diff(target["signature"], got)
    if diff:
        return SpliceOutcome(False, "signature", "signature changed: " + "; ".join(diff), additions)
    return SpliceOutcome(True, "spliced", "ok", additions)


SIG_FIELDS = ("path", "fn_sig", "predicates", "generics", "param_patterns", "visibility", "asyncness", "header", "attributes")


def signature_diff(want: dict[str, Any], got: dict[str, Any]) -> list[str]:
    return [f"{k}: expected {want.get(k)!r}, got {got.get(k)!r}" for k in SIG_FIELDS if want.get(k) != got.get(k)]
