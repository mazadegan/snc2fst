import sys
from pathlib import Path

import pytest

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.out_dsl import OutDslError, evaluate_out_dsl


def test_evaluate_out_dsl_complex_expression() -> None:
    features = {"Voice", "Consonantal", "Continuant"}
    inr = {"Voice": "+", "Consonantal": "-"}
    trm = {"Voice": "-", "Continuant": "+"}
    expr = "(unify (subtract (expand TRM) (proj TRM (Voice))) (proj INR (Voice)))"

    result = evaluate_out_dsl(expr, inr=inr, trm=trm, features=features)

    assert result == {"Continuant": "+", "Voice": "+"}


def test_evaluate_out_dsl_projection_empty() -> None:
    features = {"Voice"}
    inr = {"Voice": "+"}
    trm = {"Voice": "-"}
    expr = "(proj INR ())"

    result = evaluate_out_dsl(expr, inr=inr, trm=trm, features=features)

    assert result == {}


def test_evaluate_out_dsl_unknown_feature() -> None:
    features = {"Voice"}
    inr = {"Voice": "+"}
    trm = {"Voice": "-"}
    expr = "(lit + Continuant)"

    with pytest.raises(OutDslError):
        evaluate_out_dsl(expr, inr=inr, trm=trm, features=features)


def test_evaluate_out_dsl_unknown_atom() -> None:
    features = {"Voice"}
    inr = {"Voice": "+"}
    trm = {"Voice": "-"}
    expr = "VOICE"

    with pytest.raises(OutDslError):
        evaluate_out_dsl(expr, inr=inr, trm=trm, features=features)


def test_evaluate_out_dsl_unify_arbitrary_bundle() -> None:
    features = {"Voice", "Continuant", "Consonantal"}
    inr = {}
    trm = {}
    expr = "(unify (unify (lit + Voice) (lit - Consonantal)) (lit + Continuant))"

    result = evaluate_out_dsl(expr, inr=inr, trm=trm, features=features)

    assert result == {
        "Voice": "+",
        "Consonantal": "-",
        "Continuant": "+",
    }


def test_evaluate_out_dsl_subtract_arbitrary_bundle() -> None:
    features = {"Voice", "Continuant", "Consonantal"}
    inr = {}
    trm = {}
    expr = (
        "(subtract (unify (lit + Voice) (lit - Consonantal)) (lit + Voice))"
    )

    result = evaluate_out_dsl(expr, inr=inr, trm=trm, features=features)

    assert result == {"Consonantal": "-"}
