"""Phase-2.7 audit safeguards; no distance implementation."""
import json
from pathlib import Path

import pytest

from scripts.ordered_diversity_clang_repro import (
    accept_ast, attribution, body_audit, canonical_ids, macro_changes,
)


@pytest.mark.parametrize("code", [1, -9, None])
def test_failed_compiler_cannot_supply_partial_measurement(code):
    tree, status = accept_ast(code, '{"kind":"TranslationUnitDecl","inner":[]}')
    assert tree is None
    assert status == "compiler_failure"


@pytest.mark.parametrize("text", ["broken JSON", "[]", '{"kind":"RecoveryExpr"}'])
def test_invalid_output_not_success(text):
    assert accept_ast(0, text)[0] is None


def test_id_canonicalization_preserves_reference_aliases_and_literal_values():
    left = {"id": "0xab", "inner": [{"referencedDecl": {"id": "0xab"}}, {"id": "0xcd", "value": "0xab"}]}
    right = {"id": "0x12", "inner": [{"referencedDecl": {"id": "0x12"}}, {"id": "0x34", "value": "0xab"}]}
    assert canonical_ids(left) == canonical_ids(right)
    right["inner"][0]["referencedDecl"]["id"] = "0x34"
    assert canonical_ids(left) != canonical_ids(right)


def test_equality_does_not_erase_child_order_operators_or_locations():
    left = {"inner": [{"opcode": "+", "loc": {"line": 1}}, {"opcode": "-"}]}
    assert canonical_ids(left) != canonical_ids({"inner": list(reversed(left["inner"]))})


def test_candidate_attribution_excludes_inline_header_and_keeps_implicit_kind():
    source = Path("/example/main.c")
    def function(identifier, file, name):
        return {"kind": "FunctionDecl", "id": identifier, "name": name,
                "loc": {"file": file, "offset": 0, "tokLen": 4},
                "inner": [{"kind": "CompoundStmt", "inner": [{"kind": "ImplicitCastExpr"}, {"kind": "CStyleCastExpr"}]}]}
    tree = {"inner": [function("h", "/include/header.h", "head"), function("m", str(source), "main")]}
    result = attribution(tree, source, b"main")
    assert [r["selected"] for r in result["definitions"]] == [False, True]
    assert result["candidate_name_offsets_verified"]
    result = body_audit(tree, source)
    assert result["implicit_kind_counts"] == {"ImplicitCastExpr": 1}
    assert result["explicit_cast_nodes"] == 1
    assert result["implicit_flag_nodes"] == 0


def test_macro_deltas_do_not_hide_changed_configuration():
    changes = macro_changes("#define A 1\n#define OLD 1\n", "#define A 2\n#define NEW 1\n")
    assert changes["A"] == {"before": "#define A 1", "after": "#define A 2"}
    assert changes["OLD"]["after"] is None
    assert changes["NEW"]["before"] is None
