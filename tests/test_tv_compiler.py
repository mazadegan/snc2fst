import sys
from pathlib import Path

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.evaluator import evaluate_rule_on_bundles
from snc2fst.rules import Rule
from snc2fst.tv_compiler import (
    _encode_label,
    _enumerate_sigma,
    _project_tuple,
    compile_tv,
    run_tv_machine,
)


def test_encode_label_base3() -> None:
    assert _encode_label((0,)) == 1
    assert _encode_label((1,)) == 2
    assert _encode_label((2,)) == 3
    assert _encode_label((0, 1)) == 1 + 0 + 1 * 3
    assert _encode_label((2, 2)) == 1 + 2 + 2 * 3


def test_enumerate_sigma_size() -> None:
    assert len(_enumerate_sigma(0)) == 1
    assert len(_enumerate_sigma(2)) == 9


def test_project_tuple() -> None:
    assert _project_tuple((0, 1, 2), (2, 0)) == (2, 0)


def test_compile_tv_basic_counts() -> None:
    rule = Rule(
        id="r1",
        dir="LEFT",
        inr=[("+", "Voice")],
        trm=[("-", "Continuant")],
        cnd=[],
        out="(proj INR (Voice))",
    )
    machine = compile_tv(rule)
    v_size = len(machine.v_order)
    p_size = len(machine.p_order)
    assert len(machine.final_states) == 1 + 3**p_size
    assert len(machine.arcs) == (1 + 3**p_size) * (3**v_size)


def test_run_tv_machine_matches_reference() -> None:
    rule = Rule(
        id="r1",
        dir="LEFT",
        inr=[("+", "Voice")],
        trm=[("+", "Consonantal")],
        cnd=[],
        out="(proj TRM (Voice))",
    )
    machine = compile_tv(rule)
    v_order = machine.v_order
    inputs = [
        _tuple_for(v_order, {"Voice": "+", "Consonantal": "0"}),
        _tuple_for(v_order, {"Voice": "-", "Consonantal": "+"}),
        _tuple_for(v_order, {"Voice": "+", "Consonantal": "0"}),
    ]
    bundles = [
        {"Voice": "+", "Consonantal": "0"},
        {"Voice": "-", "Consonantal": "+"},
        {"Voice": "+", "Consonantal": "0"},
    ]
    expected_bundles = evaluate_rule_on_bundles(rule, bundles)
    expected = [_tuple_for(v_order, bundle) for bundle in expected_bundles]
    assert run_tv_machine(machine, inputs) == expected


def _tuple_for(order: tuple[str, ...], bundle: dict[str, str]) -> tuple[int, ...]:
    values: list[int] = []
    for feature in order:
        polarity = bundle.get(feature, "0")
        if polarity == "+":
            values.append(1)
        elif polarity == "-":
            values.append(2)
        else:
            values.append(0)
    return tuple(values)
