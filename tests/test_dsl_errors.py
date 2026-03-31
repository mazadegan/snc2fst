"""Tests for dsl.collect_errors — semantic validation of Out expressions."""

from snc2fst import dsl

RULE_ID = "R_0"
VALID_FEATURES = {"F", "G"}
VALID_SEGMENTS = {"A", "B", "C", "D", "E", "F", "G", "H", "I"}


def errors(expr, inr_len=2, trm_len=1):
    node = dsl.parse(expr)
    return dsl.collect_errors(
        node,
        rule_id=RULE_ID,
        inr_len=inr_len,
        trm_len=trm_len,
        valid_segments=VALID_SEGMENTS,
        valid_features=VALID_FEATURES,
    )


# ---------------------------------------------------------------------------
# Valid expressions — no errors expected
# ---------------------------------------------------------------------------

def test_metathesis():
    assert errors("(INR[2] INR[1])") == []

def test_unify():
    assert errors("(unify INR[1] {+F})") == []

def test_subtract():
    assert errors("(subtract INR[1] {-G})") == []

def test_proj():
    assert errors("(proj INR[1] (F G))") == []

def test_epenthesis():
    assert errors("(INR[1] {+F -G} INR[2])") == []

def test_conditional_via_models():
    assert errors(
        "(if (models? TRM [{+F}]) (unify INR[1] {+F}) INR)"
    ) == []

def test_conditional_via_in_class():
    assert errors(
        "(if (in? TRM[1] [{+F}]) (unify INR[1] {+G}) INR)"
    ) == []

def test_valid_symbol():
    assert errors("(INR[1] &A INR[2])") == []

def test_inr_index_at_boundary():
    assert errors("(INR[2])", inr_len=2) == []

def test_trm_index_at_boundary():
    assert errors("(proj TRM[1] (F))", trm_len=1) == []


# ---------------------------------------------------------------------------
# Index out of bounds
# ---------------------------------------------------------------------------

def test_inr_index_out_of_bounds():
    errs = errors("(INR[3])", inr_len=2)
    assert len(errs) == 1
    assert "INR[3]" in errs[0]
    assert "length 2" in errs[0]

def test_trm_index_out_of_bounds():
    errs = errors("(proj TRM[2] (F))", trm_len=1)
    assert len(errs) == 1
    assert "TRM[2]" in errs[0]
    assert "length 1" in errs[0]

def test_index_zero():
    errs = errors("(INR[0])")
    assert len(errs) == 1
    assert ">= 1" in errs[0]


# ---------------------------------------------------------------------------
# Undefined segment symbol
# ---------------------------------------------------------------------------

def test_undefined_symbol():
    errs = errors("(INR[1] &Z INR[2])")
    assert len(errs) == 1
    assert "Z" in errs[0]

def test_defined_symbol_no_error():
    assert errors("(INR[1] &A)") == []


# ---------------------------------------------------------------------------
# Undefined feature names
# ---------------------------------------------------------------------------

def test_unify_undefined_feature():
    errs = errors("(unify INR[1] {+H})")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_subtract_undefined_feature():
    errs = errors("(subtract INR[1] {+H})")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_proj_undefined_feature():
    errs = errors("(proj INR[1] (H))")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_in_class_undefined_feature():
    errs = errors("(if (in? TRM[1] [{+H}]) INR INR)")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_models_undefined_feature():
    errs = errors("(if (models? TRM [{+H}]) INR INR)")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_epenthesis_undefined_feature():
    errs = errors("(INR[1] {+H} INR[2])")
    assert len(errs) == 1
    assert "H" in errs[0]


# ---------------------------------------------------------------------------
# Multiple errors
# ---------------------------------------------------------------------------

def test_multiple_errors_index_and_feature():
    errs = errors("(unify INR[3] {+H})", inr_len=2)
    assert len(errs) == 2

def test_multiple_undefined_features():
    errs = errors("((unify INR[1] {+H}) (subtract INR[2] {-X}))")
    assert len(errs) == 2
    feature_names = {e for err in errs for e in ["H", "X"] if e in err}
    assert feature_names == {"H", "X"}
