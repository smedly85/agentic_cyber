"""Audits for the synthetic instrument only; no lexical call-edge construction."""
import re


def debug_inventory(ir):
    """Read identities from DISubprogram metadata, never calls from source/IR text."""
    metadata = dict(re.findall(r"^!(\d+) = (.*)$", ir, re.M))
    result = {}
    for symbol, quoted, reference in re.findall(
            r'^define .*?@(?:"([^"]+)"|([^ (]+))\(.*?!dbg !(\d+) \{', ir, re.M):
        info = metadata[reference]
        name = re.search(r'name: "([^"]+)"', info).group(1)
        line = int(re.search(r'\bline: (\d+)', info).group(1))
        file_ref = re.search(r'\bfile: !(\d+)', info).group(1)
        filename = re.search(r'filename: "([^"]+)"', metadata[file_ref]).group(1)
        scope = re.search(r'\bscope: !(\d+)', info)
        names = []
        visited = set()
        while scope:
            key = scope.group(1)
            if key in visited:
                raise ValueError("cyclic debug scope")
            visited.add(key)
            value = metadata[key]
            item = re.search(r'name: "([^"]+)"', value)
            if item:
                names.append(item.group(1))
            scope = re.search(r'\bscope: !(\d+)', value)
        result[symbol or quoted] = {"debug_name": name, "source_file": filename,
            "line": line, "scope": list(reversed(names)), "disubprogram": info}
    # A definition without debug metadata must not silently disappear.
    definitions = re.findall(r'^define .*?@(?:"([^"]+)"|([^ (]+))\(', ir, re.M)
    if set(result) != {a or b for a, b in definitions}:
        raise ValueError("LLVM definitions missing debug identities")
    return result


def check_graph(graph):
    """Independently check recorded BFS paths and complete emitted target sets."""
    edges = graph["call_edges"]
    functions = {f["identity"]: f for f in graph["functions"]}
    for edge in edges:
        if edge["edge_type"] not in {"direct", "indirect_resolved"}:
            raise ValueError("invalid semantic edge kind")
        if edge["edge_type"] == "indirect_resolved":
            targets = edge["indirect_target_set"]
            if targets != sorted(set(targets)) or edge["callee"] not in targets:
                raise ValueError("invalid may-target set")
            if len(targets) != edge["indirect_target_count"]:
                raise ValueError("wrong may-target cardinality")
            emitted = {e["callee"] for e in edges if e["caller"] == edge["caller"]
                       and e["callsite"] == edge["callsite"]
                       and e["edge_type"] == "indirect_resolved"}
            if emitted != set(targets):
                raise ValueError("missing may-target edge")
    for f in functions.values():
        depth = f["raw_call_depth"]
        path = f["shortest_call_path"]
        if depth is None:
            if f["reachable_from_entry"] or path["edges"] is not None:
                raise ValueError("missing observation represented as reachable")
            continue
        if len(path["edges"]) != depth or len(path["function_identities"]) != depth + 1:
            raise ValueError("path length mismatch")
        if path["function_identities"][0] != graph["entry_point"]["resolved_identity"]:
            raise ValueError("wrong path entry")
        if path["function_identities"][-1] != f["identity"]:
            raise ValueError("wrong path target")
        for index, edge in enumerate(path["edges"]):
            if edge not in edges or [edge["caller"], edge["callee"]] != path["function_identities"][index:index + 2]:
                raise ValueError("path contains a nonexistent edge")
    # Paths plus this relaxation condition establish shortest distances.
    for e in edges:
        a = functions[e["caller"]]["raw_call_depth"]
        b = functions[e["callee"]]["raw_call_depth"]
        if a is not None and (b is None or b > a + 1):
            raise ValueError("non-shortest or incomplete reachability")


def audit_case(case, graph):
    check_graph(graph)
    functions = graph["functions"]
    by_id = {f["identity"]: f for f in functions}
    def named(name):
        return [f for f in functions if f["name"].split("<")[0] == name]
    def targets(caller):
        return {by_id[e["callee"]]["name"] for e in graph["call_edges"]
                if by_id[e["caller"]]["name"] == caller and e["edge_type"] == "indirect_resolved"}
    checks = {"expected_depth": case["measured_depth"] == case["expected_depth"]}
    kind = case["case"]
    if kind in {"function_pointer", "multi_target"}:
        # Both entries share the same context-insensitive whole-program invoke.
        checks["complete_may_targets"] = targets("invoke") == {"target", "alternate"}
    if kind == "struct_pointer":
        checks["complete_may_targets"] = targets("invoke_holder") == {"target"}
    if kind == "cross_crate_indirect":
        checks["complete_may_targets"] = targets("cross_indirect") == {"cross_target"}
    if kind == "dynamic_trait":
        methods = {f["identity"] for f in named("operation")}
        actual = {e["callee"] for e in graph["call_edges"]
                  if by_id[e["caller"]]["name"] == "dynamic_dispatch"
                  and e["edge_type"] == "indirect_resolved"}
        checks["both_vtable_targets_resolved"] = len(methods) == 2 and actual == methods
    if kind == "recursion":
        checks["self_edge_preserved"] = any(e["caller"] == e["callee"] and
            by_id[e["caller"]]["name"] == "recurse" for e in graph["call_edges"])
    if kind == "closure":
        checks["semantic_closure_node_preserved"] = any(
            by_id[e["callee"]]["name"] == "{closure#0}"
            for f in case["target_instances"] for e in f["shortest_call_path"]["edges"] or [])
    if kind == "duplicate_names":
        duplicates = named("duplicate")
        checks["distinct_debug_source_identities"] = (len(duplicates) == 2 and
            len({(f["source_file"], f["definition"]["line"]) for f in duplicates}) == 2 and
            {tuple(f["debug_metadata"]["scope"]) for f in duplicates} ==
            {("semantic_instrument", "left"), ("semantic_instrument", "right")})
    if kind == "multiple_instances":
        instances = named("generic")
        checks["same_source_distinct_instances_retained"] = (len(instances) == 2 and
            len({(f["source_file"], f["definition"]["line"], tuple(f["debug_metadata"]["scope"]))
                 for f in instances}) == 1 and
            len({f["llvm_symbol"] for f in instances}) == 2 and
            all(f["raw_call_depth"] == 1 for f in instances))
    case["checks"] = checks
    case["status"] = "passed" if all(checks.values()) else "failed"
    case["unresolved_indirect_sites"] = [u for u in graph["unresolved_indirect_callsites"]
                                        if by_id[u["caller"]]["reachable_from_entry"]]
    return case
