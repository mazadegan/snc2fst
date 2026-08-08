"""Behavioural quotient of the terminator pointer."""

from pathlib import Path

import logical_phonology as lp
import pytest

from snc2fst.alphabet import load_alphabet
from snc2fst.dsl import parse
from snc2fst.errors import CompileError
from snc2fst.models import Rule
from snc2fst.quotient import references_trm, trm_quotient

# pyright: reportArgumentType=false
# mypy: ignore-errors

_FS = lp.FeatureSystem(frozenset(["voc", "nas", "lab"]))
_INV = _FS.inventory(
    {
        "a": _FS.segment({"voc": lp.POS, "nas": lp.NEG, "lab": lp.NEG}),
        "m": _FS.segment({"voc": lp.NEG, "nas": lp.POS, "lab": lp.POS}),
        "b": _FS.segment({"voc": lp.NEG, "nas": lp.NEG, "lab": lp.POS}),
        "n": _FS.segment({"voc": lp.NEG, "nas": lp.POS, "lab": lp.NEG}),
        "p": _FS.segment({"voc": lp.NEG, "nas": lp.NEG, "lab": lp.NEG}),
    }
)

_VOTIC = (
    Path(__file__).parent.parent
    / "src"
    / "snc2fst"
    / "templates"
    / "starters"
    / "votic_vowel_harmony"
    / "alphabet.csv"
)


def q(inr, trm, out, cnd=None, direction="L", fs=_FS, inv=_INV, **kw):
    rule = Rule(
        Id="q", Inr=inr, Trm=trm, Dir=direction, Out=out, Cnd=cnd
    )
    return trm_quotient(
        rule,
        parse(out),
        parse(cnd) if cnd is not None else None,
        fs,
        inv,
        **kw,
    )


# ---------------------------------------------------------------------------
# references_trm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("INR", False),
        ("TRM", True),
        ("INR[1]", False),
        ("TRM[1]", True),
        ("TRM[1:2]", True),
        ("&a", False),
        ("{+nas}", False),
        ("(unify INR[1] {+nas})", False),
        ("(unify INR[1] (proj TRM[1] (nas)))", True),
        ("(subtract INR[1] {+lab})", False),
        ("(proj INR[1] (nas))", False),
        ("(INR[1] &a)", False),
        ("(INR[1] TRM)", True),
        ("(in? INR [{+nas}])", False),
        ("(in? TRM [{+lab}])", True),
        ("(if (in? INR [{+nas}]) &a &b)", False),
        ("(if (in? TRM [{+nas}]) &a &b)", True),
        ("(if (in? INR [{+nas}]) TRM &b)", True),
        ("(if (in? INR [{+nas}]) &a TRM)", True),
    ],
)
def test_references_trm(expr, expected):
    assert references_trm(parse(expr)) is expected


def test_references_trm_rejects_unknown_node():
    class Bogus:
        pass

    with pytest.raises(CompileError, match="unhandled AST node"):
        references_trm(Bogus())


# ---------------------------------------------------------------------------
# Degenerate shapes
# ---------------------------------------------------------------------------


def test_no_terminator_gives_one_vacuous_class():
    result = q([["+voc"]], [], "(unify INR[1] {+nas})")
    assert result.trm_blind
    assert len(result.reps) == 1
    assert list(result.reps[0]) == []
    assert result.class_of == {}
    assert result.produced


def test_unsatisfiable_trm_gives_no_classes():
    """No segment is both +BOS and +voc, so the rule can never fire."""
    result = q([["+voc"]], [["+BOS", "+voc"]], "INR")
    assert result.reps == []
    assert result.class_of == {}
    assert result.produced == []


def test_unsatisfiable_inr_still_yields_one_class():
    result = q([["+voc", "+nas"]], [["+nas"]], "(INR[1] TRM[1])")
    assert len(result.reps) == 1


# ---------------------------------------------------------------------------
# Collapsing
# ---------------------------------------------------------------------------


def test_trm_blind_rule_collapses_to_one_class():
    """Out ignores TRM, so all 5 non-boundary terminators are equivalent."""
    result = q([["+voc"]], [[]], "(unify INR[1] {+nas})")
    assert result.trm_blind
    assert len(result.reps) == 1
    # every licensed window still maps into that single class
    assert set(result.class_of.values()) == {0}
    assert len(result.class_of) == len(_INV.segment_to_name)


def test_cnd_alone_makes_a_rule_trm_sensitive():
    """Even a TRM-blind Out is not blind if Cnd reads TRM."""
    result = q([["+voc"]], [[]], "(unify INR[1] {+nas})", "(in? TRM [{+lab}])")
    assert not result.trm_blind
    # two behaviours: licensed (+lab) and not
    assert len(result.reps) == 2


def test_projection_collapses_to_the_projected_feature():
    """Out reads only TRM's nas value, so the 7 terminators collapse to 3.

    Three, not two: BOS/EOS carry no nas feature at all, so projecting nas
    off them is empty and leaves the target unchanged — a third behaviour,
    distinct from both +nas and -nas.
    """
    result = q(
        [["+voc"]],
        [[]],
        "(unify (subtract INR[1] {-nas}) (proj TRM[1] (nas)))",
    )
    assert not result.trm_blind
    groups = {}
    for names, index in result.class_of.items():
        groups.setdefault(index, set()).add(names[0])
    assert sorted(map(sorted, groups.values())) == [
        ["a", "b", "p"],  # -nas
        ["m", "n"],  # +nas
        ["⋉", "⋊"],  # nas unspecified
    ]


def test_bare_trm_in_output_collapses_nothing():
    """A bare TRM copies the window verbatim, so every window is distinct."""
    result = q([["+voc"]], [[]], "(INR[1] TRM)")
    assert not result.trm_blind
    assert len(result.reps) == len(result.class_of)
    assert len(result.reps) == len(_INV.segment_to_name)


def test_class_representatives_are_word_order():
    """reps must be usable directly as the TRM binding, so TRM[1] is the
    leftmost segment of the window."""
    result = q(
        [["+voc"]],
        [["+nas"], ["+lab"]],
        "(INR[1] TRM[1])",
    )
    for rep in result.reps:
        assert len(rep) == 2
        assert rep[0] in _FS.natural_class({"nas": lp.POS})
        assert rep[1] in _FS.natural_class({"lab": lp.POS})


def test_every_licensed_window_is_classified():
    result = q([["+voc"]], [["+nas"]], "(INR[1] TRM[1])")
    trm_words = list(
        Rule(Id="q", Inr=[["+voc"]], Trm=[["+nas"]], Dir="L", Out="INR")
        .trm_as_ncs(_FS)
        .over(_INV, filter_boundaries=False)
    )
    assert len(result.class_of) == len(trm_words)
    assert set(result.class_of.values()) == set(range(len(result.reps)))


# ---------------------------------------------------------------------------
# Real grammar: votic
# ---------------------------------------------------------------------------


def _votic():
    return load_alphabet(_VOTIC)


def test_votic_r1_collapses_to_three_back_classes():
    """votic R1 reads only TRM's Back value: +Back, -Back, unspecified."""
    fs, inv = _votic()
    result = q(
        [["+Syllabic"]],
        [["+Syllabic", "-High"]],
        "(unify INR[1] (proj TRM[1] (Back)))",
        fs=fs,
        inv=inv,
    )
    assert len(result.reps) == 3
    assert len(result.class_of) == 8  # 8 licensed windows collapse to 3


def test_votic_r3_is_trm_blind():
    """R3 uses the terminator purely as a licenser."""
    fs, inv = _votic()
    result = q(
        [["+Syllabic"]], [[]], "(unify INR[1] {-Back})", fs=fs, inv=inv
    )
    assert result.trm_blind
    assert len(result.reps) == 1


def test_votic_r1_at_n2_still_collapses_to_three():
    """Widening Trm to two slots multiplies windows by 8 but not classes."""
    fs, inv = _votic()
    result = q(
        [["+Syllabic"]],
        [["+Syllabic", "-High"], ["+Syllabic", "-High"]],
        "(unify INR[1] (proj TRM[1] (Back)))",
        fs=fs,
        inv=inv,
    )
    assert len(result.class_of) == 64
    assert len(result.reps) == 3


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


def test_max_pairs_guard_fires_before_the_work():
    with pytest.raises(CompileError, match="Out evaluations"):
        q([["+voc"]], [[]], "(INR[1] TRM)", max_pairs=3)


def test_max_pairs_guard_not_consulted_when_trm_blind():
    """A blind rule skips the quadratic pass, so the guard is irrelevant."""
    result = q([["+voc"]], [[]], "(unify INR[1] {+nas})", max_pairs=1)
    assert result.trm_blind


def test_boolean_out_is_rejected():
    with pytest.raises(CompileError, match="evaluated to a boolean"):
        q([["+voc"]], [["+nas"]], "(in? TRM [{+lab}])")
