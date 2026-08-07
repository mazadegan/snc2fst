import pytest

from snc2fst.errors import CompileError
from snc2fst.models import Rule
from snc2fst.wellformed import (
    check_wellformed,
    offsets_to_check,
    specs_incompatible,
    wellformedness_errors,
)


def rule(inr, trm, direction="L", rule_id="r"):
    return Rule(Id=rule_id, Inr=inr, Trm=trm, Dir=direction, Out="INR")


# ---------------------------------------------------------------------------
# offsets_to_check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "m,n,direction,expected",
    [
        # n = 0: nothing to overlap with, whatever m and Dir are.
        (1, 0, "L", []),
        (3, 0, "L", []),
        (3, 0, "R", []),
        # Dir = R: {1, ..., m-1}, independent of n.
        (1, 1, "R", []),
        (2, 1, "R", [1]),
        (3, 1, "R", [1, 2]),
        (3, 2, "R", [1, 2]),
        # Dir = L: {-(n-1), ..., -1} u {0, ..., m-n-1}.
        (1, 1, "L", []),
        (2, 1, "L", [0]),
        (3, 1, "L", [0, 1]),
        (1, 2, "L", [-1]),
        (2, 2, "L", [-1]),
        (3, 2, "L", [-1, 0]),
        (2, 3, "L", [-2, -1]),
    ],
)
def test_offsets_to_check(m, n, direction, expected):
    assert offsets_to_check(m, n, direction) == expected


def test_offsets_empty_exactly_in_the_legacy_single_class_cases():
    """D is empty precisely where the pre-sequence rule shapes live."""
    assert offsets_to_check(1, 1, "R") == []
    assert offsets_to_check(1, 1, "L") == []
    # ...and non-empty as soon as the target window grows.
    assert offsets_to_check(2, 1, "R") != []
    assert offsets_to_check(2, 1, "L") != []


def test_dir_left_conservative_when_m_less_than_n():
    """The negative band is kept even though it is not operationally
    reachable when m < n; it is what reconciles the declarative search with
    the streaming pointer."""
    assert offsets_to_check(1, 3, "L") == [-2, -1]


# ---------------------------------------------------------------------------
# specs_incompatible
# ---------------------------------------------------------------------------


def test_direct_clash():
    assert specs_incompatible([("+", "Syl")], [("-", "Syl")])
    assert specs_incompatible([("-", "Syl")], [("+", "Syl")])


def test_same_value_is_compatible():
    assert not specs_incompatible([("+", "Syl")], [("+", "Syl")])


def test_disjoint_features_are_compatible():
    assert not specs_incompatible([("+", "Syl")], [("+", "Voice")])


def test_universal_class_is_compatible_with_everything():
    assert not specs_incompatible([], [("+", "Syl")])
    assert not specs_incompatible([("+", "Syl")], [])
    assert not specs_incompatible([], [])


def test_star_never_clashes_with_a_valued_slot():
    """'*f' expands to [+f] u [-f], so it is satisfiable either way."""
    assert not specs_incompatible([("*", "Syl")], [("+", "Syl")])
    assert not specs_incompatible([("*", "Syl")], [("-", "Syl")])
    assert not specs_incompatible([("+", "Syl")], [("*", "Syl")])


def test_clash_found_among_several_features():
    a = [("+", "Syl"), ("+", "Voice"), ("-", "Nasal")]
    b = [("+", "Syl"), ("+", "Nasal")]
    assert specs_incompatible(a, b)


# --- boundary exclusivity ---------------------------------------------------


def test_bos_excludes_any_other_demand():
    assert specs_incompatible([("+", "BOS")], [("+", "Syl")])
    assert specs_incompatible([("+", "Syl")], [("+", "BOS")])
    assert specs_incompatible([("+", "BOS")], [("-", "Syl")])


def test_bos_and_eos_are_mutually_exclusive():
    assert specs_incompatible([("+", "BOS")], [("+", "EOS")])
    assert specs_incompatible([("+", "EOS")], [("+", "BOS")])


def test_bos_is_compatible_with_itself_and_the_universal_class():
    assert not specs_incompatible([("+", "BOS")], [("+", "BOS")])
    assert not specs_incompatible([("+", "BOS")], [])


def test_bos_excludes_a_star_slot():
    """'*f' still demands that f be specified, which BOS never is."""
    assert specs_incompatible([("+", "BOS")], [("*", "Syl")])


# ---------------------------------------------------------------------------
# wellformedness_errors
# ---------------------------------------------------------------------------


def test_empty_inr_is_rejected():
    errors = wellformedness_errors(rule([], []))
    assert len(errors) == 1
    assert "Inr is empty" in errors[0]


def test_trm_empty_is_vacuously_wellformed():
    r = rule([["+Syl"], ["-Syl"], ["+Syl"]], [])
    assert wellformedness_errors(r) == []


def test_single_class_shapes_are_vacuously_wellformed():
    assert wellformedness_errors(rule([["+Syl"]], [["-Syl"]], "L")) == []
    assert wellformedness_errors(rule([["+Syl"]], [["+Syl"]], "R")) == []


def test_right_consonant_cluster_with_vowel_terminator_is_wellformed():
    """Paper's illustration: Inr = [C, C], Trm = [V], Dir = R.

    D_Right = {1}; at d=1 the shared pair is (Inr[2], Trm[1]) = (C, V),
    incompatible, so no vowel can occupy the second consonant slot.
    """
    r = rule([["-Syl"], ["-Syl"]], [["+Syl"]], "R")
    assert wellformedness_errors(r) == []


def test_right_consonant_cluster_with_consonant_terminator_is_illformed():
    """Same shape with Trm = [C] instead: compatible at d=1, so rejected."""
    r = rule([["-Syl"], ["-Syl"]], [["-Syl"]], "R")
    errors = wellformedness_errors(r)
    assert len(errors) == 1
    assert "offset 1" in errors[0]


def test_left_nonnegative_offset_is_caught():
    """Paper's second illustration: Dir = L, Inr = [V, C], Trm = [V].

    m > n, so D_Left = {0}; the shared pair (Inr[1], Trm[1]) = (V, V) is
    compatible, so the rule is ill-formed. A direction-blind version of the
    condition would have missed this.
    """
    r = rule([["+Syl"], ["-Syl"]], [["+Syl"]], "L")
    errors = wellformedness_errors(r)
    assert len(errors) == 1
    assert "offset 0" in errors[0]


def test_left_nonnegative_offset_blocked_by_incompatibility():
    """Same shape but Trm = [C], which clashes with Inr[1] = V at d=0."""
    r = rule([["+Syl"], ["-Syl"]], [["-Syl"]], "L")
    assert wellformedness_errors(r) == []


def test_worked_trace_rule_is_wellformed():
    """Paper's worked trace: Inr = [V, C, V], Trm = [C, C], Dir = R.

    D_Right = {1, 2}; d=1 is blocked by (Inr[3], Trm[2]) = (V, C) and d=2 by
    (Inr[3], Trm[1]) = (V, C).
    """
    r = rule([["+Syl"], ["-Syl"], ["+Syl"]], [["-Syl"], ["-Syl"]], "R")
    assert wellformedness_errors(r) == []


def test_no_length_one_terminator_suffices_for_that_inr():
    """Noted in the paper: with Inr = [V, C, V] and Dir = R, a single-class
    Trm would have to be incompatible with both C and V at once."""
    for trm in ([["-Syl"]], [["+Syl"]], [[]]):
        assert wellformedness_errors(
            rule([["+Syl"], ["-Syl"], ["+Syl"]], trm, "R")
        )


def test_boundary_anchored_rule_is_accepted():
    """The strengthened boundary test is what makes this well-formed: a
    +BOS slot cannot also be a vowel, so d=0 is blocked."""
    r = rule([["+BOS"], ["-Syl"], ["+Syl"]], [["+Syl"]], "L")
    assert wellformedness_errors(r) == []


def test_multiple_bad_offsets_are_all_reported():
    r = rule([["+Syl"], ["+Syl"], ["+Syl"]], [["+Syl"]], "R")
    assert len(wellformedness_errors(r)) == 2  # d = 1 and d = 2


def test_error_messages_name_the_rule():
    errors = wellformedness_errors(
        rule([["-Syl"], ["-Syl"]], [["-Syl"]], "R", rule_id="R7")
    )
    assert all(e.startswith("Rule 'R7':") for e in errors)


# ---------------------------------------------------------------------------
# check_wellformed
# ---------------------------------------------------------------------------


def test_check_wellformed_silent_on_good_rule():
    check_wellformed(rule([["+Syl"]], [["-Syl"]]))


def test_check_wellformed_raises_compile_error_by_default():
    with pytest.raises(CompileError):
        check_wellformed(rule([["-Syl"], ["-Syl"]], [["-Syl"]], "R"))


def test_check_wellformed_honours_the_exception_type():
    class Custom(Exception):
        pass

    with pytest.raises(Custom):
        check_wellformed(rule([], []), Custom)


def test_check_wellformed_agrees_with_accumulating_form():
    bad = rule([["+Syl"], ["+Syl"], ["+Syl"]], [["+Syl"]], "R")
    message = str(pytest.raises(CompileError, check_wellformed, bad).value)
    for err in wellformedness_errors(bad):
        assert err in message
