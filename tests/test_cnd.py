"""The optional Cnd licensing expression.

Cnd exists to express a licensing condition that, when false, makes the
matched INR-window *slide* rather than fire. Writing the same condition
inside Out cannot do that: a window matching INR always fires and is consumed
whole, even when Out returns its input unchanged. The difference is invisible
at m=1 and shows up as soon as INR-windows can overlap each other.
"""

import logical_phonology as lp
import pytest

from snc2fst.dsl import parse
from snc2fst.errors import EvalError
from snc2fst.evaluator import apply_rule
from snc2fst.models import Rule

FS = lp.FeatureSystem(frozenset(["F", "G"]))


def w(*segs: lp.Segment) -> lp.Word:
    return FS.word(list(segs))


A = FS.segment({"F": lp.POS, "G": lp.POS})
B = FS.segment({"F": lp.POS, "G": lp.NEG})
C = FS.segment({"F": lp.NEG, "G": lp.POS})
D = FS.segment({"F": lp.NEG, "G": lp.NEG})

INV = FS.inventory({"A": A, "B": B, "C": C, "D": D})


def run(word, *, out, cnd=None, inr, trm=None, direction="L"):
    rule = Rule.model_validate(
        {
            "Id": "r",
            "Inr": inr,
            "Trm": trm if trm is not None else [],
            "Dir": direction,
            "Out": out,
            "Cnd": cnd,
        }
    )
    cnd_ast = parse(rule.Cnd) if rule.Cnd is not None else None
    return apply_rule(rule, parse(rule.Out), word, FS, INV, cnd_ast)


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------


def test_absent_cnd_licenses_everything():
    assert run(w(A, C), inr=[["+F"]], out="&D") == w(D, C)


def test_true_cnd_licenses():
    result = run(w(A, C), inr=[["+F"]], out="&D", cnd="(in? INR [{+G}])")
    assert result == w(D, C)


def test_false_cnd_blocks():
    result = run(w(B, C), inr=[["+F"]], out="&D", cnd="(in? INR [{+G}])")
    assert result == w(B, C)  # B is -G, so not licensed


def test_cnd_can_read_the_trigger():
    """Licensing on TRM is the paper's Cnd; here it is just an expression."""
    result = run(
        w(A, D, C),
        inr=[["-F"], ["-F"]],
        trm=[["+F"]],
        out="&B",
        cnd="(in? TRM [{+G}])",
        direction="L",
    )
    assert result == w(A, B)  # A is +G, so <D, C> is licensed and collapses


def test_cnd_reading_the_trigger_can_block():
    """Same rule, but the only trigger to the left is -G, so nothing fires."""
    result = run(
        w(B, D, C),
        inr=[["-F"], ["-F"]],
        trm=[["+F"]],
        out="&B",
        cnd="(in? TRM [{+G}])",
        direction="L",
    )
    assert result == w(B, D, C)  # B is -G


def test_cnd_must_return_a_boolean():
    with pytest.raises(EvalError, match="did not evaluate to a boolean"):
        run(w(A), inr=[["+F"]], out="&D", cnd="INR")


def test_cnd_errors_are_prefixed_with_the_rule_id():
    with pytest.raises(EvalError, match="Rule 'r'"):
        run(w(A), inr=[["+F"]], out="&D", cnd="(in? &nope [{+F}])")


# ---------------------------------------------------------------------------
# The behaviour Cnd exists for: slide, don't consume
# ---------------------------------------------------------------------------

# Inr = [+F, +F] over <A, B, A>. Both windows (1,2) and (2,3) match Inr, and
# they overlap. The condition licenses only a window whose second segment is
# +G — true of (2,3) but not of (1,2).

_OVERLAP = dict(inr=[["+F"], ["+F"]], out="&D", direction="L")
_SECOND_IS_G = "(in? INR [{+F} {+F +G}])"


def test_unlicensed_window_slides_and_lets_the_next_one_fire():
    """With Cnd, the unlicensed window at (1,2) slides, so (2,3) fires."""
    result = run(w(A, B, A), cnd=_SECOND_IS_G, **_OVERLAP)
    assert result == w(A, D)


def test_same_condition_inside_out_consumes_the_window_instead():
    """Without Cnd the window at (1,2) fires, returns itself unchanged, and
    is consumed — so (2,3) never gets the chance to match."""
    out = f"(if {_SECOND_IS_G} &D INR)"
    result = run(w(A, B, A), inr=[["+F"], ["+F"]], out=out, direction="L")
    assert result == w(A, B, A)


def test_the_two_encodings_agree_when_windows_cannot_overlap():
    """At m=1 the distinction is invisible: firing and sliding both consume
    exactly one segment."""
    word = w(A, B, A)
    via_cnd = run(word, inr=[["+F"]], out="&D", cnd="(in? INR [{+G}])")
    via_out = run(
        word, inr=[["+F"]], out="(if (in? INR [{+G}]) &D INR)"
    )
    assert via_cnd == via_out == w(D, B, D)


def test_cnd_with_dir_right_resolves_from_the_right():
    """The slide is direction-aware, like every other part of the scan."""
    result = run(w(A, B, A), cnd=_SECOND_IS_G, inr=[["+F"], ["+F"]],
                 out="&D", direction="R")
    # Scanning right-to-left, the window at (2,3) is reached first and its
    # second segment (position 3) is A, which is +G — licensed, so it fires.
    assert result == w(A, D)
