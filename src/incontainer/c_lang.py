"""C function location, splicing and compiler-based checks (runs in agent-c).

Everything is derived from `clang -Xclang -ast-dump=json`, so locations and
signatures are the compiler's view, not regex guesses.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

BASE_FLAGS = ["-std=gnu11", "-fsyntax-only", "-Xclang", "-ast-dump=json", "-fno-color-diagnostics"]
INCLUDE_RE = re.compile(r"^\s*#\s*include\b.*$", re.M)


class CLangError(RuntimeError):
    pass


# ---------------------------------------------------------------- AST plumbing

def clang_ast(project: Path, tu: str, flags: Iterable[str] = ()) -> dict[str, Any]:
    argv = ["clang", *BASE_FLAGS, *flags, tu]
    proc = subprocess.run(argv, cwd=project, capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise CLangError(_first_errors(proc.stderr) or f"clang failed with {proc.returncode}")
    ast = json.loads(proc.stdout)
    _resolve_files(ast)
    return ast


def _first_errors(stderr: str, limit: int = 20) -> str:
    lines = [l for l in stderr.splitlines() if "error" in l or l.startswith(" ")]
    return "\n".join(lines[:limit]) if lines else stderr[-3000:]


def _is_loc(node: dict) -> bool:
    return any(k in node for k in ("offset", "spellingLoc", "expansionLoc")) and "kind" not in node


def _resolve_files(ast: dict) -> None:
    """clang's JSON only prints `file` when it changes; resolve it on every loc."""
    state = {"file": None}

    def visit_loc(loc: dict) -> None:
        for sub in ("spellingLoc", "expansionLoc"):
            if sub in loc:
                visit_loc(loc[sub])
        if "file" in loc:
            state["file"] = loc["file"]
        if "offset" in loc:
            loc["_file"] = state["file"]

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if _is_loc(node):
                visit_loc(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(ast)


def _point(loc: dict, prefer: str = "spellingLoc") -> dict:
    if prefer in loc:
        return loc[prefer]
    return loc.get("expansionLoc", loc)


@dataclass
class FnDef:
    name: str
    file: str  # path as clang printed it (relative to project when invoked there)
    start: int  # byte offset of definition start
    end: int  # byte offset one past the closing brace
    line: int
    macro: bool
    signature: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _signature(node: dict) -> dict[str, Any]:
    params = [p.get("name", "") for p in node.get("inner", []) if p.get("kind") == "ParmVarDecl"]
    attrs = sorted(
        (p["kind"], _attr_detail(p)) for p in node.get("inner", []) if p.get("kind", "").endswith("Attr") and not p.get("implicit")
    )
    qual = node.get("type", {}).get("qualType", "")
    return {
        "name": node.get("name"),
        "type": qual,
        "param_names": params,
        "storage_class": node.get("storageClass", "none"),
        "inline": bool(node.get("inline")),
        "variadic": qual.rstrip().endswith("...)"),
        "attributes": [list(a) for a in attrs],
    }


def _attr_detail(node: dict) -> str:
    return json.dumps({k: v for k, v in node.items() if k not in ("id", "range", "loc", "kind", "inner")}, sort_keys=True)


def _has_body(node: dict) -> bool:
    return any(child.get("kind") == "CompoundStmt" for child in node.get("inner", []))


def function_definitions(ast: dict, project: Path) -> list[FnDef]:
    out = []
    for node in ast.get("inner", []):
        if node.get("kind") != "FunctionDecl" or node.get("isImplicit") or not _has_body(node):
            continue
        rng = node.get("range", {})
        begin, end = rng.get("begin", {}), rng.get("end", {})
        macro = "expansionLoc" in begin or "expansionLoc" in end
        prefer = "expansionLoc" if macro else "spellingLoc"
        b, e = _point(begin, prefer), _point(end, prefer)
        file = b.get("_file")
        if file is None or "offset" not in b or "offset" not in e:
            continue
        path = (project / file).resolve()
        if not str(path).startswith(str(project.resolve())):
            continue  # system header
        out.append(
            FnDef(
                name=node["name"],
                file=str(path.relative_to(project.resolve())),
                start=b["offset"],
                end=e["offset"] + e.get("tokLen", 1),
                line=b.get("line") or _point(node.get("loc", {}), prefer).get("line") or 0,
                macro=macro,
                signature=_signature(node),
            )
        )
    return out


def top_level_decls(ast: dict, project: Path) -> list[dict[str, Any]]:
    """Every top-level declaration located in the project (for classification)."""
    out = []
    for node in ast.get("inner", []):
        if node.get("isImplicit"):
            continue
        rng = node.get("range", {})
        b = _point(rng.get("begin", {}), "expansionLoc")
        e = _point(rng.get("end", {}), "expansionLoc")
        file = b.get("_file")
        if file is None or "offset" not in b:
            continue
        path = (project / file).resolve()
        if not str(path).startswith(str(project.resolve())):
            continue
        out.append(
            {
                "kind": node.get("kind"),
                "name": node.get("name"),
                "file": str(path.relative_to(project.resolve())),
                "start": b["offset"],
                "end": e.get("offset", b["offset"]) + e.get("tokLen", 1),
                "has_body": _has_body(node),
            }
        )
    return out


def translation_units(project: Path, sources: list[str]) -> list[str]:
    return sources


def locate(project: Path, sources: list[str], flags: list[str], name: str, file: str | None) -> FnDef:
    """Find the unique definition of `name` (optionally in `file`)."""
    found: dict[tuple[str, int], FnDef] = {}
    errors = []
    for tu in sources:
        try:
            ast = clang_ast(project, tu, flags)
        except CLangError as exc:
            errors.append(f"{tu}: {exc}")
            continue
        for fn in function_definitions(ast, project):
            if fn.name == name and (file is None or _same_file(fn.file, file)):
                found[(fn.file, fn.start)] = fn
    if not found:
        raise CLangError(f"definition of {name!r} not found" + (f" ({'; '.join(errors)})" if errors else ""))
    if len(found) > 1:
        raise CLangError(f"multiple definitions of {name!r}: {sorted(found)}")
    return next(iter(found.values()))


def list_definitions(project: Path, sources: list[str], flags: list[str]) -> list[FnDef]:
    seen: dict[tuple[str, str], FnDef] = {}
    for tu in sources:
        for fn in function_definitions(clang_ast(project, tu, flags), project):
            seen.setdefault((fn.file, fn.name), fn)
    return sorted(seen.values(), key=lambda f: (f.file, f.start))


def _same_file(a: str, b: str) -> bool:
    return Path(a).as_posix().lstrip("./") == Path(b).as_posix().lstrip("./")


# ---------------------------------------------------------------- function file

def function_text(project: Path, fn: FnDef) -> str:
    data = (project / fn.file).read_bytes()
    return data[fn.start : fn.end].decode()


def tu_for(project: Path, sources: list[str], fn_file: str) -> list[str]:
    """Translation units that see `fn_file` (itself if .c, else every TU)."""
    if fn_file.endswith(".c"):
        return [fn_file]
    return list(sources)


# ---------------------------------------------------------------- splice + checks

@dataclass
class SpliceOutcome:
    ok: bool
    stage: str
    message: str
    additions: dict[str, list[str]] = field(default_factory=dict)


def splice(
    project: Path,
    sources: list[str],
    flags: list[str],
    target: dict[str, Any],
    edited: str,
    allow: dict[str, bool],
) -> SpliceOutcome:
    """Replace target bytes in `project` (a scratch copy) with `edited` and check it."""
    path = project / target["file"]
    original = path.read_bytes()
    start, end = target["start"], target["end"]
    if original[start:end].decode(errors="replace") != target["original_text"]:
        return SpliceOutcome(False, "splice", "internal: target bytes changed underneath the splice")

    includes = INCLUDE_RE.findall(edited)
    body = INCLUDE_RE.sub("", edited).strip("\n") + "\n"
    new_bytes = original[:start] + body.encode() + original[end:]
    if includes:
        new_bytes = _hoist_includes(new_bytes, includes)
        shift = len(new_bytes) - len(original[:start] + body.encode() + original[end:])
    else:
        shift = 0
    path.write_bytes(new_bytes)
    region = (start + shift, start + shift + len(body.encode()))

    errors = []
    defs_in_region: list[dict] = []
    others_in_region: list[dict] = []
    target_sigs = []
    for tu in tu_for(project, sources, target["file"]):
        try:
            ast = clang_ast(project, tu, flags)
        except CLangError as exc:
            errors.append(f"{tu}:\n{exc}")
            continue
        for decl in top_level_decls(ast, project):
            if not _same_file(decl["file"], target["file"]) or not (region[0] <= decl["start"] < region[1]):
                continue
            (defs_in_region if decl["kind"] == "FunctionDecl" else others_in_region).append(decl)
        for fn in function_definitions(ast, project):
            if fn.name == target["name"] and _same_file(fn.file, target["file"]):
                target_sigs.append(fn.signature)
    if errors:
        return SpliceOutcome(False, "build", "compilation failed after splicing:\n" + "\n".join(errors))

    names_defined = {d["name"] for d in defs_in_region if d["has_body"]}
    if target["name"] not in names_defined:
        return SpliceOutcome(False, "signature", f"the function file no longer defines `{target['name']}`")
    helpers = sorted({d["name"] for d in defs_in_region if d["name"] != target["name"]})
    globals_types = sorted({f"{d['kind']}:{d['name'] or '<anonymous>'}" for d in others_in_region})
    additions = {"helpers": helpers, "includes": [i.strip() for i in includes], "globals_types": globals_types}

    violations = []
    if helpers and not allow.get("allow_new_helpers", True):
        violations.append(f"new helper functions are not allowed: {', '.join(helpers)}")
    if includes and not allow.get("allow_new_includes", True):
        violations.append("new #include directives are not allowed")
    if globals_types and not allow.get("allow_new_globals_types", True):
        violations.append(f"new globals/types are not allowed: {', '.join(globals_types)}")
    if violations:
        return SpliceOutcome(False, "additions", "; ".join(violations), additions)

    want = target["signature"]
    for sig in target_sigs:
        diff = signature_diff(want, sig)
        if diff:
            return SpliceOutcome(False, "signature", "signature changed: " + "; ".join(diff), additions)
    return SpliceOutcome(True, "spliced", "ok", additions)


def _hoist_includes(data: bytes, includes: list[str]) -> bytes:
    text = data.decode()
    existing = {line.strip() for line in INCLUDE_RE.findall(text)}
    new = [inc.strip() for inc in includes if inc.strip() not in existing]
    if not new:
        return data
    matches = list(INCLUDE_RE.finditer(text))
    pos = matches[-1].end() + 1 if matches else 0
    block = "\n".join(new) + "\n"
    return (text[:pos] + block + text[pos:]).encode()


SIG_FIELDS = ("name", "type", "param_names", "storage_class", "inline", "variadic", "attributes")


def signature_diff(want: dict[str, Any], got: dict[str, Any]) -> list[str]:
    out = []
    for key in SIG_FIELDS:
        if want.get(key) != got.get(key):
            out.append(f"{key}: expected {want.get(key)!r}, got {got.get(key)!r}")
    return out
