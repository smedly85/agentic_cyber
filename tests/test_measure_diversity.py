"""Unit tests for scripts/measure_diversity.py.

Focus: metric *properties* rather than exact values - symmetry,
self-similarity, and (for the levels that claim it) invariance to
identifier renaming - on small fixture programs, per the plan's
validity-controls section (docs/diversity_methodology.md).

Run with: python3 -m pytest tests/test_measure_diversity.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import measure_diversity as md  # noqa: E402

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_c")
pytest.importorskip("rapidfuzz")
pytest.importorskip("apted")


FIXTURE_A = b"""\
#include <stdio.h>
int add(int a, int b) {
    int result = a + b;
    return result;
}
int main(void) {
    printf("%d\\n", add(2, 3));
    return 0;
}
"""

# Same logic, different variable/function names and formatting - a
# Type-2/near-Type-3 clone of FIXTURE_A.
FIXTURE_B = b"""\
#include <stdio.h>
int sum_two(int x, int y) {
    int total = x + y;
    return total;
}
int main(void) {
    printf("%d\\n", sum_two(2, 3));
    return 0;
}
"""

# Genuinely different implementation of "print a number": different
# control flow, different calls, different constructs entirely.
FIXTURE_C = b"""\
#include <stdio.h>
#include <string.h>
int main(void) {
    char buf[32];
    strcpy(buf, "5");
    for (int i = 0; i < 1; i++) {
        printf("%s\\n", buf);
    }
    return 0;
}
"""


def _variant(label: str, source: bytes) -> md.Variant:
    return md.Variant(label=label, path=Path(f"<fixture:{label}>"), source=source)


@pytest.fixture(autouse=True)
def _clear_parse_cache():
    md._PARSE_CACHE.clear()
    yield
    md._PARSE_CACHE.clear()


CLASSICAL_METRIC_FACTORIES = {
    "lexical_levenshtein": md._metric_lexical_levenshtein,
    "lexical_winnowing": md._metric_lexical_winnowing,
    "ast_ted": md._metric_ast_ted,
    "api_callset": md._metric_api_callset,
    "attack_surface": md._metric_attack_surface,
}


@pytest.mark.parametrize("name,fn", CLASSICAL_METRIC_FACTORIES.items())
def test_self_similarity_is_one(name, fn):
    a = _variant("a", FIXTURE_A)
    a_copy = _variant("a_copy", FIXTURE_A)
    sim = fn(a, a_copy)
    assert sim == pytest.approx(1.0, abs=1e-9), f"{name} self-similarity != 1.0"


@pytest.mark.parametrize("name,fn", CLASSICAL_METRIC_FACTORIES.items())
def test_symmetry(name, fn):
    a = _variant("a", FIXTURE_A)
    c = _variant("c", FIXTURE_C)
    assert fn(a, c) == pytest.approx(fn(c, a), abs=1e-9), f"{name} is not symmetric"


@pytest.mark.parametrize("name,fn", CLASSICAL_METRIC_FACTORIES.items())
def test_similarity_bounded_in_unit_interval(name, fn):
    a = _variant("a", FIXTURE_A)
    c = _variant("c", FIXTURE_C)
    sim = fn(a, c)
    assert -1e-9 <= sim <= 1.0 + 1e-9, f"{name} out of [0,1]: {sim}"


def test_renamed_clone_is_ast_and_winnowing_invariant():
    """FIXTURE_B is FIXTURE_A with every identifier renamed (Type-2 clone).
    The AST-shape and Type-2-token-normalized metrics must not notice;
    the raw-text metric must."""
    a = _variant("a", FIXTURE_A)
    b = _variant("b", FIXTURE_B)

    assert md._metric_ast_ted(a, b) == pytest.approx(1.0, abs=1e-9)
    assert md._metric_lexical_winnowing(a, b) == pytest.approx(1.0, abs=1e-9)
    assert md._metric_lexical_levenshtein(a, b) < 0.999


def test_different_implementation_is_less_similar_than_renamed_clone():
    """A genuinely different implementation (FIXTURE_C) should score lower
    on every structural metric than a mere renamed clone (FIXTURE_B) of
    the same program - the core sanity property the whole tool rests on."""
    a = _variant("a", FIXTURE_A)
    b = _variant("b", FIXTURE_B)
    c = _variant("c", FIXTURE_C)

    for name, fn in CLASSICAL_METRIC_FACTORIES.items():
        renamed_sim = fn(a, b)
        different_sim = fn(a, c)
        assert different_sim <= renamed_sim + 1e-9, (
            f"{name}: differently-implemented pair scored more similar "
            f"({different_sim}) than a renamed clone ({renamed_sim})"
        )


def test_attack_surface_detects_unsafe_construct_divergence():
    """FIXTURE_C uses strcpy into a fixed-size stack buffer; FIXTURE_A/B
    use neither. The attack-surface vector must reflect that difference -
    this is the property the security-diversity claim depends on."""
    a_parsed = md.parse_source(FIXTURE_A)
    c_parsed = md.parse_source(FIXTURE_C)
    va = md.attack_surface_vector(a_parsed)
    vc = md.attack_surface_vector(c_parsed)
    assert va["unsafe_calls"] == 0
    assert vc["unsafe_calls"] >= 1
    assert va["fixed_stack_buffers"] == 0
    assert vc["fixed_stack_buffers"] >= 1


def test_call_set_extraction():
    parsed = md.parse_source(FIXTURE_C)
    calls = md.call_set(parsed)
    assert "strcpy" in calls
    assert "printf" in calls


def test_winnowing_fingerprints_nonempty_for_nontrivial_input():
    parsed = md.parse_source(FIXTURE_A)
    tokens = md.type2_token_stream(parsed)
    assert len(tokens) > 10
    fps = md.winnowing_fingerprints(tokens)
    assert len(fps) > 0


def test_jaccard_edge_cases():
    assert md.jaccard(set(), set()) == 1.0
    assert md.jaccard({1, 2}, {1, 2}) == 1.0
    assert md.jaccard({1}, {2}) == 0.0


def test_load_variants_derives_temp_dir_label(tmp_path):
    run_dir = tmp_path / "runs" / "mkdir" / "temp-0p2" / "workdir" / "src"
    run_dir.mkdir(parents=True)
    f = run_dir / "new_mkdir.c"
    f.write_bytes(FIXTURE_A)
    variants = md.load_variants([str(f)])
    assert len(variants) == 1
    assert variants[0].label == "temp-0p2"


def test_calibration_passes():
    assert md.run_calibration() is True
