"""Versioned attributed-program-graph extraction from textual LLVM IR.

LLVM basic blocks and terminators are compiler CFG objects.  This module never
describes an AST-derived graph as a CFG.  Source-to-IR compilation is deliberately
outside this parser so callers can enforce the repository's Docker/provenance
policy and pass the exact compiler command and version into the artifact.
"""
from __future__ import annotations

from hashlib import sha256
import re
from typing import Any, Iterable

SCHEMA_VERSION = "unified-program-graph-v1"
EXTRACTOR_VERSION = "llvm-ir-cfg-extractor-v1"


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def unavailable(reason: str, **details: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "status": "unavailable",
            "reason": reason, "details": details}


def _name(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return bytes(value[1:-1], "utf-8").decode("unicode_escape")
    return value


def _strip_metadata(line: str) -> str:
    line = re.sub(r",?\s*![-\w.]+\s+![0-9]+", "", line)
    return line.strip()


def _value_category(value: str) -> str:
    value = value.strip()
    if value.startswith("%"):
        return "ssa"
    if value.startswith("@"):
        return "global"
    if value in {"null", "zeroinitializer"}:
        return "zero"
    if value in {"true", "false"}:
        return "bool"
    if re.fullmatch(r"[-+]?\d+", value):
        return "zero" if int(value) == 0 else "one" if abs(int(value)) == 1 else "int"
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:e[-+]?\d+)?", value, re.I):
        return "float"
    return "other"


def _split_args(text: str) -> list[str]:
    output, start, depth, quoted = [], 0, 0, False
    for i, char in enumerate(text):
        if char == '"' and (i == 0 or text[i - 1] != "\\"):
            quoted = not quoted
        elif not quoted and char in "([{<":
            depth += 1
        elif not quoted and char in ")]}>":
            depth -= 1
        elif char == "," and not quoted and depth == 0:
            output.append(text[start:i].strip()); start = i + 1
    if text[start:].strip():
        output.append(text[start:].strip())
    return output


def _type_category(argument: str) -> str:
    head = argument.split(None, 1)[0] if argument.split() else "unknown"
    if head == "ptr" or "*" in head:
        return "ptr"
    if re.fullmatch(r"i\d+", head):
        return "int"
    if head in {"float", "double", "half", "fp128"}:
        return "float"
    if head.startswith(("{", "[", "<")):
        return "aggregate"
    return head


def instruction_signature(line: str, defined: set[str]) -> str | None:
    """Canonical local-computation atom; SSA/source-local names are erased."""
    text = _strip_metadata(line)
    text = re.sub(r"^(?:%[^=]+)\s*=\s*", "", text).strip()
    if not text or text.startswith((";", "!")):
        return None
    opcode_match = re.match(r"(?:tail\s+|musttail\s+|notail\s+)?([a-z][\w.]*)\b", text)
    if not opcode_match:
        return None
    opcode = opcode_match.group(1)
    if opcode in {"call", "invoke", "callbr"} or re.search(r"\b(?:call|invoke|callbr)\b", text):
        actual = re.search(r"\b(call|invoke|callbr)\b", text)
        opcode = actual.group(1) if actual else opcode
        target = re.search(r"@((?:\"(?:[^\"\\]|\\.)*\")|[-$._A-Za-z0-9]+)\s*\((.*)\)", text)
        if target:
            name = _name(target.group(1))
            args = _split_args(target.group(2))
            identity = "internal" if name in defined else "api:" + name
            roles = ",".join(f"a{i}:{_type_category(arg)}:{_value_category(arg.rsplit(None, 1)[-1])}"
                             for i, arg in enumerate(args))
            return f"{opcode}|target:{identity}|argc:{len(args)}|{roles}"
        return f"{opcode}|target:indirect"
    if opcode in {"icmp", "fcmp"}:
        predicate = re.search(r"\b(?:icmp|fcmp)\s+([a-z]+)\b", text)
        return f"{opcode}|pred:{predicate.group(1) if predicate else 'unknown'}"
    if opcode == "br":
        return "br|conditional" if re.search(r"\bbr\s+i1\b", text) else "br|unconditional"
    if opcode == "switch":
        return f"switch|cases:{max(0, len(re.findall(r'\blabel\s+%', text)) - 1)}"
    if opcode == "phi":
        return f"phi|incoming:{text.count('[')}"
    flags = [flag for flag in ("nsw", "nuw", "exact", "inbounds", "volatile", "atomic")
             if re.search(rf"\b{flag}\b", text)]
    if opcode in {"add", "sub", "mul", "sdiv", "udiv", "srem", "urem", "fadd", "fsub", "fmul", "fdiv",
                  "and", "or", "xor", "shl", "lshr", "ashr"}:
        return opcode + ("|" + ",".join(flags) if flags else "")
    if opcode in {"ret", "unreachable", "resume"}:
        return opcode
    if opcode in {"load", "store", "alloca", "getelementptr", "select", "extractvalue", "insertvalue",
                  "trunc", "zext", "sext", "fptrunc", "fpext", "fptoui", "fptosi", "uitofp", "sitofp",
                  "ptrtoint", "inttoptr", "bitcast", "addrspacecast", "freeze"}:
        return opcode + ("|" + ",".join(flags) if flags else "")
    return opcode


def _successors(instruction: str) -> list[tuple[str, str]]:
    text = _strip_metadata(instruction)
    labels = [_name(value) for value in re.findall(r"\blabel\s+%((?:\"(?:[^\"\\]|\\.)*\")|[-$._A-Za-z0-9]+)", text)]
    if re.match(r"(?:%[^=]+\s*=\s*)?br\s+i1\b", text) and len(labels) >= 2:
        return [(labels[0], "cfg:true"), (labels[1], "cfg:false")]
    if re.match(r"(?:%[^=]+\s*=\s*)?br\s+label\b", text) and labels:
        return [(labels[0], "cfg:unconditional")]
    if re.match(r"(?:%[^=]+\s*=\s*)?switch\b", text) and labels:
        return [(labels[0], "cfg:default"), *[(label, "cfg:case") for label in labels[1:]]]
    if re.search(r"\binvoke\b", text) and len(labels) >= 2:
        return [(labels[-2], "cfg:normal"), (labels[-1], "cfg:exception")]
    if re.match(r"(?:%[^=]+\s*=\s*)?indirectbr\b", text):
        return [(label, "cfg:indirect") for label in labels]
    return []


def _logical_lines(ir: str) -> Iterable[str]:
    pending = ""
    depth = 0
    for raw in ir.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        pending = (pending + " " + line).strip() if pending else line
        depth += line.count("[") - line.count("]")
        if depth <= 0:
            yield pending
            pending, depth = "", 0
    if pending:
        yield pending


def extract_llvm_ir(ir: str, *, source_bytes: bytes, source_path: str,
                    compiler_version: str, compiler_sha256: str | None,
                    command: list[str], profile: str = "c11-posix2008-v1") -> dict[str, Any]:
    if not isinstance(ir, str) or not ir.strip():
        return unavailable("llvm_ir_missing")
    lines = list(_logical_lines(ir))
    defined_names = {_name(m.group(1)) for line in lines
                     if (m := re.match(r"define\b.*@((?:\"(?:[^\"\\]|\\.)*\")|[-$._A-Za-z0-9]+)\s*\(", line))}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    functions: list[dict[str, Any]] = []
    current = None
    for line in lines:
        definition = re.match(r"define\b.*@((?:\"(?:[^\"\\]|\\.)*\")|[-$._A-Za-z0-9]+)\s*\(", line)
        if definition:
            name = _name(definition.group(1)); fid = f"fn:{len(functions)}"
            current = {"name": name, "id": fid, "blocks": [], "current": None}
            functions.append(current)
            nodes.append({"id": fid, "kind": "function", "label": "function:entry:main" if name == "main" else "function:helper",
                          "owner": None, "content": [], "audit": {"original_name": name}})
            continue
        if current is None:
            continue
        if line == "}":
            current = None; continue
        label_match = re.match(r"((?:\"(?:[^\"\\]|\\.)*\")|[-$._A-Za-z0-9]+):(?:\s*;.*)?$", line)
        if label_match:
            label = _name(label_match.group(1)); bid = f"{current['id']}:bb:{len(current['blocks'])}"
            block = {"label": label, "id": bid, "instructions": []}
            current["blocks"].append(block); current["current"] = block
            continue
        if current["current"] is None:
            bid = f"{current['id']}:bb:0"
            current["current"] = {"label": "entry", "id": bid, "instructions": []}
            current["blocks"].append(current["current"])
        current["current"]["instructions"].append(line)

    function_ids = {f["name"]: f["id"] for f in functions}
    called_names = set()
    for function in functions:
        for block in function["blocks"]:
            for inst in block["instructions"]:
                match = re.search(r"\b(?:call|invoke|callbr)\b.*@((?:\"(?:[^\"\\]|\\.)*\")|[-$._A-Za-z0-9]+)\s*\(", inst)
                if match:
                    called_names.add(_name(match.group(1)))
    # A declaration alone is not a program relationship.  Materialize only
    # externally called identities; unused header/IR declarations are audit noise.
    api_names = sorted(called_names - defined_names)
    api_ids = {name: f"api:{i}" for i, name in enumerate(api_names)}
    for name, identifier in api_ids.items():
        nodes.append({"id": identifier, "kind": "api", "label": "api:" + name,
                      "owner": None, "content": [], "audit": {"external_name": name}})
    edge_index = 0
    def add_edge(source: str, target: str, label: str) -> None:
        nonlocal edge_index
        edges.append({"id": f"e:{edge_index}", "source": source, "target": target, "label": label}); edge_index += 1
    for function in functions:
        block_ids = {b["label"]: b["id"] for b in function["blocks"]}
        for index, block in enumerate(function["blocks"]):
            signatures = [signature for inst in block["instructions"]
                          if (signature := instruction_signature(inst, defined_names)) is not None]
            terminal = signatures[-1].split("|", 1)[0] if signatures else "empty"
            nodes.append({"id": block["id"], "kind": "block", "label": "block:" + terminal,
                          "owner": function["id"], "content": signatures,
                          "audit": {"llvm_label": block["label"], "block_index": index,
                                    "instruction_count": len(block["instructions"])}})
            add_edge(function["id"], block["id"], "contains")
            if index == 0:
                add_edge(function["id"], block["id"], "entry")
            if block["instructions"]:
                for target, label in _successors(block["instructions"][-1]):
                    if target not in block_ids:
                        return unavailable("invalid_cfg_target", function=function["name"], target=target)
                    add_edge(block["id"], block_ids[target], label)
            for inst in block["instructions"]:
                call = re.search(r"\b(?:call|invoke|callbr)\b.*@((?:\"(?:[^\"\\]|\\.)*\")|[-$._A-Za-z0-9]+)\s*\(", inst)
                if call:
                    target_name = _name(call.group(1))
                    add_edge(block["id"], function_ids.get(target_name, api_ids.get(target_name, "")), "call")
    artifact = {
        "schema_version": SCHEMA_VERSION, "status": "success", "language": "c",
        "backend": "llvm-ir-cfg-v1", "extractor_version": EXTRACTOR_VERSION,
        "source": {"path": source_path, "sha256": _hash(source_bytes)},
        "compiler": {"version": compiler_version, "binary_sha256": compiler_sha256,
                     "profile": profile, "command": command},
        "llvm_ir_sha256": _hash(ir.encode("utf-8")), "entry_points": ["main"] if "main" in defined_names else [],
        "nodes": sorted(nodes, key=lambda n: n["id"]), "edges": sorted(edges, key=lambda e: e["id"]),
        "limitations": ["direct LLVM calls only", "no path-feasibility or data-flow equivalence claim",
                        "local content is a canonical LLVM-instruction signature sequence"],
    }
    return artifact

