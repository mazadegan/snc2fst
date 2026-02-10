import pytest

pytest.importorskip("pywrapfst")

from snc2fst.main import _has_epsilon_arcs


def test_has_epsilon_arcs_detects_epsilons() -> None:
    import pywrapfst as fst

    f = fst.VectorFst()
    s0 = f.add_state()
    s1 = f.add_state()
    f.set_start(s0)
    f.set_final(s1)

    weight = fst.Weight.one(f.weight_type())
    # Epsilon on input label
    f.add_arc(s0, fst.Arc(0, 1, weight, s1))

    assert _has_epsilon_arcs(f) is True


def test_has_epsilon_arcs_false_for_non_eps() -> None:
    import pywrapfst as fst

    f = fst.VectorFst()
    s0 = f.add_state()
    s1 = f.add_state()
    f.set_start(s0)
    f.set_final(s1)

    weight = fst.Weight.one(f.weight_type())
    f.add_arc(s0, fst.Arc(1, 2, weight, s1))

    assert _has_epsilon_arcs(f) is False
