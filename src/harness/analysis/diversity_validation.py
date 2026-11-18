"""Construct-validation distances kept separate from structural clustering."""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


@dataclass
class ParsedSource:
    root: Any
    data: bytes


_PARSER: Any = None
_PARSE_CACHE: dict[bytes, ParsedSource] = {}
MAX_AST_NODES = 20_000


def _parser() -> Any:
    global _PARSER
    if _PARSER is not None:
        return _PARSER
    from tree_sitter import Language, Parser
    import tree_sitter_c

    language = Language(tree_sitter_c.language())
    try:
        _PARSER = Parser(language)
    except TypeError:
        _PARSER = Parser()
        try:
            _PARSER.language = language
        except AttributeError:
            _PARSER.set_language(language)
    return _PARSER


def parse_source(source: bytes | str) -> ParsedSource:
    data = source.encode() if isinstance(source, str) else source
    key = hashlib.sha256(data).digest()
    if key not in _PARSE_CACHE:
        _PARSE_CACHE[key] = ParsedSource(_parser().parse(data).root_node, data)
    return _PARSE_CACHE[key]


def iter_nodes(node: Any) -> Iterable[Any]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def normalized_source(parsed: ParsedSource) -> str:
    spans = sorted(
        (node.start_byte, node.end_byte)
        for node in iter_nodes(parsed.root)
        if node.type == "comment"
    )
    output = bytearray()
    cursor = 0
    for start, end in spans:
        output += parsed.data[cursor:start]
        cursor = end
    output += parsed.data[cursor:]
    return re.sub(r"\s+", " ", output.decode("utf-8", errors="replace")).strip()


def lexical_distance(left: ParsedSource, right: ParsedSource) -> float:
    from rapidfuzz.distance import Levenshtein

    return float(Levenshtein.normalized_distance(normalized_source(left), normalized_source(right)))


_LITERAL_TYPES = {"number_literal": "NUM", "string_literal": "STR", "char_literal": "CHAR"}


def type2_token_stream(parsed: ParsedSource) -> list[str]:
    tokens: list[str] = []
    for node in iter_nodes(parsed.root):
        if node.children or node.type == "comment":
            continue
        if node.type == "identifier":
            tokens.append("ID")
        elif node.type in _LITERAL_TYPES:
            tokens.append(_LITERAL_TYPES[node.type])
        else:
            tokens.append(node.type)
    return tokens


def winnowing_fingerprints(tokens: Sequence[str], k: int = 5, w: int = 4) -> set[int]:
    if not tokens:
        return set()
    k = min(k, len(tokens))
    hashes = [
        int.from_bytes(hashlib.sha256("\x1f".join(tokens[i : i + k]).encode()).digest()[:8], "big")
        for i in range(len(tokens) - k + 1)
    ]
    fingerprints: set[int] = set()
    for start in range(max(1, len(hashes) - w + 1)):
        window = hashes[start : start + w] or hashes[start:]
        minimum = min(window)
        rightmost = max(index for index, value in enumerate(window) if value == minimum)
        fingerprints.add(hashes[start + rightmost])
    return fingerprints


def jaccard_similarity(left: set[Any], right: set[Any]) -> float:
    return len(left & right) / len(left | right) if left or right else 1.0


def token_winnowing_distance(left: ParsedSource, right: ParsedSource) -> float:
    left_tokens = type2_token_stream(left)
    right_tokens = type2_token_stream(right)
    common_k = max(1, min(5, len(left_tokens), len(right_tokens)))
    return 1.0 - jaccard_similarity(
        winnowing_fingerprints(left_tokens, common_k),
        winnowing_fingerprints(right_tokens, common_k),
    )


def _apted_tree(node: Any) -> Any:
    from apted.helpers import Tree

    return Tree(
        node.type,
        *[_apted_tree(child) for child in node.children if child.is_named and child.type != "comment"],
    )


def _ast_size(root: Any) -> int:
    return sum(node.is_named and node.type != "comment" for node in iter_nodes(root))


def apted_distance(left: ParsedSource, right: ParsedSource) -> float | None:
    from apted import APTED, Config

    left_size = _ast_size(left.root)
    right_size = _ast_size(right.root)
    if max(left_size, right_size) > MAX_AST_NODES:
        return None
    edit_distance = APTED(_apted_tree(left.root), _apted_tree(right.root), Config()).compute_edit_distance()
    return min(1.0, float(edit_distance) / max(left_size, right_size, 1))


def _call_name(node: Any, data: bytes) -> str | None:
    function = node.child_by_field_name("function")
    if function is not None and function.type == "identifier":
        return data[function.start_byte : function.end_byte].decode("utf-8", errors="replace")
    return None


def called_function_set(parsed: ParsedSource) -> set[str]:
    return {
        name
        for node in iter_nodes(parsed.root)
        if node.type == "call_expression"
        for name in [_call_name(node, parsed.data)]
        if name
    }


def api_callset_distance(left: ParsedSource, right: ParsedSource) -> float:
    return 1.0 - jaccard_similarity(called_function_set(left), called_function_set(right))


def validation_distances(left_source: bytes, right_source: bytes) -> dict[str, float | None]:
    left = parse_source(left_source)
    right = parse_source(right_source)
    return {
        "lexical_distance": lexical_distance(left, right),
        "token_winnowing_distance": token_winnowing_distance(left, right),
        "apted_distance": apted_distance(left, right),
        "api_callset_distance": api_callset_distance(left, right),
    }


def pairwise_spearman_correlations(
    rows: Sequence[Mapping[str, Any]], metric_names: Sequence[str]
) -> list[dict[str, Any]]:
    from scipy.stats import spearmanr

    output: list[dict[str, Any]] = []
    for left_name, right_name in itertools.product(metric_names, repeat=2):
        pairs = [
            (float(row[left_name]), float(row[right_name]))
            for row in rows
            if isinstance(row.get(left_name), (int, float))
            and isinstance(row.get(right_name), (int, float))
            and math.isfinite(float(row[left_name]))
            and math.isfinite(float(row[right_name]))
        ]
        correlation = None
        if left_name == right_name and pairs:
            correlation = 1.0
        elif len(pairs) >= 2 and len({pair[0] for pair in pairs}) > 1 and len({pair[1] for pair in pairs}) > 1:
            value, _ = spearmanr([pair[0] for pair in pairs], [pair[1] for pair in pairs])
            correlation = float(value) if math.isfinite(float(value)) else None
        output.append(
            {
                "left_metric": left_name,
                "right_metric": right_name,
                "spearman_correlation": correlation,
                "supporting_pairs": len(pairs),
            }
        )
    return output
