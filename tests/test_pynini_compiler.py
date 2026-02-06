import sys
from pathlib import Path

import pytest

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.feature_analysis import compute_p_features, compute_v_features
from snc2fst.compile_pynini_fst import compile_pynini_fst, evaluate_with_pynini
from snc2fst.rules import Rule


pytest.importorskip("pywrapfst")


def test_compile_pynini_fst_state_count() -> None:
    rule = Rule(
        id="r1",
        dir="LEFT",
        inr=[("+", "Voice")],
        trm=[("+", "Consonantal")],
        cnd=[],
        out="(proj TRM (Voice))",
    )
    v_features = compute_v_features(rule)
    p_features = compute_p_features(rule)
    machine = compile_pynini_fst(
        rule, v_features=v_features, p_features=p_features
    )
    expected_states = 1 + (3 ** len(p_features))
    assert machine.fst.num_states() == expected_states


def test_evaluate_with_pynini_matches_reference_small() -> None:
    rules = {
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+","Voice"]],
                "trm": [["+","Consonantal"]],
                "cnd": [],
                "out": "(proj TRM (Voice))",
            }
        ]
    }
    rule = Rule.model_validate(rules["rules"][0])
    alphabet = {
        "symbols": ["a", "b", "c", "d"],
        "features": ["Voice", "Consonantal"],
        "values": [
            ["+", "-", "0", "-"],
            ["0", "+", "-", "0"],
        ],
    }
    feature_order = tuple(alphabet["features"])
    symbol_to_bundle = {
        sym: {
            feature: value
            for feature, value in zip(feature_order, row)
            if value != "0"
        }
        for sym, row in zip(alphabet["symbols"], zip(*alphabet["values"]))
    }
    bundle_to_symbol = {}
    for sym, bundle in symbol_to_bundle.items():
        key = tuple(bundle.get(feature, "0") for feature in feature_order)
        bundle_to_symbol[key] = sym

    words = [["a", "b", "c", "a"]]
    output = evaluate_with_pynini(
        rule=rule,
        words=words,
        feature_order=feature_order,
        symbol_to_bundle=symbol_to_bundle,
        bundle_to_symbol=bundle_to_symbol,
        strict=True,
    )
    assert output == [["d", "b", "c", "a"]]


def test_evaluate_with_pynini_reconstructs_non_v_features() -> None:
    rule = Rule(
        id="r_recon",
        dir="LEFT",
        inr=[],
        trm=[["+","Voice"]],
        cnd=[],
        out="(proj TRM (Voice))",
    )
    alphabet = {
        "symbols": ["a", "b", "c", "d"],
        "features": ["Voice", "F1"],
        "values": [
            ["+", "-", "+", "-"],
            ["+", "+", "-", "-"],
        ],
    }
    feature_order = tuple(alphabet["features"])
    symbol_to_bundle = {
        sym: {
            feature: value
            for feature, value in zip(feature_order, row)
            if value != "0"
        }
        for sym, row in zip(alphabet["symbols"], zip(*alphabet["values"]))
    }
    bundle_to_symbol = {}
    for sym, bundle in symbol_to_bundle.items():
        key = tuple(bundle.get(feature, "0") for feature in feature_order)
        bundle_to_symbol[key] = sym

    words = [["a", "d"]]
    output = evaluate_with_pynini(
        rule=rule,
        words=words,
        feature_order=feature_order,
        symbol_to_bundle=symbol_to_bundle,
        bundle_to_symbol=bundle_to_symbol,
        strict=True,
    )
    assert output == [["a", "c"]]
