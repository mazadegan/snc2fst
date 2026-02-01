import sys
from pathlib import Path

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.evaluator import evaluate_rule_on_bundles
from snc2fst.rules import Rule


def test_evaluate_rule_right_direction() -> None:
    rule = Rule(
        id="r1",
        dir="RIGHT",
        inr=[("+", "Voice")],
        trm=[("+", "Consonantal")],
        cnd=[],
        out="(proj TRM (Voice))",
    )
    segments = [
        {"Voice": "+", "Consonantal": "0"},
        {"Voice": "-", "Consonantal": "+"},
        {"Voice": "+", "Consonantal": "0"},
    ]

    result = evaluate_rule_on_bundles(rule, segments)

    assert result[0]["Voice"] == "-"
    assert result[1]["Voice"] == "-"
    assert result[2]["Voice"] == "+"


def test_evaluate_rule_left_direction() -> None:
    rule = Rule(
        id="r1",
        dir="LEFT",
        inr=[("+", "Voice")],
        trm=[("+", "Consonantal")],
        cnd=[],
        out="(proj TRM (Voice))",
    )
    segments = [
        {"Voice": "+", "Consonantal": "0"},
        {"Voice": "-", "Consonantal": "+"},
        {"Voice": "+", "Consonantal": "0"},
    ]

    result = evaluate_rule_on_bundles(rule, segments)

    assert result[0]["Voice"] == "+"
    assert result[1]["Voice"] == "-"
    assert result[2]["Voice"] == "-"
