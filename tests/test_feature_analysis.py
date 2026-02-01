import sys
from pathlib import Path

import pytest

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.feature_analysis import compute_p_features, compute_v_features
from snc2fst.out_dsl import (
    OutDslError,
    extract_out_features,
    extract_trm_dependent_features,
)
from snc2fst.rules import Rule


def test_extract_out_features_collects_lit_and_proj() -> None:
    expr = "(unify (lit + Voice) (proj INR (Continuant)))"

    assert extract_out_features(expr) == {"Voice", "Continuant"}


def test_extract_trm_dependent_features_proj_trm() -> None:
    expr = "(proj TRM (Voice Continuant))"

    assert extract_trm_dependent_features(expr) == {"Voice", "Continuant"}


def test_extract_trm_dependent_features_lit_with_trm() -> None:
    expr = "(unify TRM (lit + Voice))"

    assert extract_trm_dependent_features(expr) == {"Voice"}


def test_extract_trm_dependent_features_ignores_inr_only() -> None:
    expr = "(unify TRM (proj INR (Voice)))"

    assert extract_trm_dependent_features(expr) == set()


def test_extract_trm_dependent_features_lit_subtract_trm() -> None:
    expr = "(subtract (proj TRM (Voice)) (lit + Continuant))"

    assert extract_trm_dependent_features(expr) == {"Voice", "Continuant"}


def test_extract_trm_dependent_features_lit_without_trm() -> None:
    expr = "(lit + Voice)"

    assert extract_trm_dependent_features(expr) == set()


def test_compute_v_features_includes_rule_classes_and_out() -> None:
    rule = Rule(
        id="r1",
        dir="LEFT",
        inr=[("+", "Voice")],
        trm=[("-", "Continuant")],
        cnd=[("+", "Nasal")],
        out="(proj INR (Continuant Consonantal))",
    )

    assert compute_v_features(rule) == {
        "Voice",
        "Continuant",
        "Nasal",
        "Consonantal",
    }


def test_compute_p_features_matches_out_dsl_analysis() -> None:
    rule = Rule(
        id="r2",
        dir="LEFT",
        inr=[],
        trm=[],
        cnd=[],
        out="(unify TRM (lit + Voice))",
    )

    assert compute_p_features(rule) == {"Voice"}


def test_extract_out_features_rejects_unknown_atom() -> None:
    with pytest.raises(OutDslError):
        extract_out_features("VOICE")
