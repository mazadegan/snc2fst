"""Tests for dsl.collect_errors — semantic validation of Out expressions.

Fixtures use the two-feature toy language from the paper (features F and G).
"""

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
    assert errors("(concat (nth 2 INR) (nth 1 INR))") == []

def test_unify():
    assert errors("(concat (unify (nth 1 INR) [+F]))") == []

def test_subtract():
    assert errors("(concat (subtract (nth 1 INR) [-G]))") == []

def test_project():
    assert errors("(concat (project (nth 1 INR) [F G]))") == []

def test_epenthesis():
    assert errors("(concat (nth 1 INR) [+F -G] (nth 2 INR))") == []

def test_conditional_via_models():
    assert errors(
        "(if (models? TRM [[+F]]) (concat (unify (nth 1 INR) [+F])) INR)"
    ) == []

def test_conditional_via_in_class():
    assert errors(
        "(if (in? (nth 1 TRM) [+F]) (concat (unify (nth 1 INR) [+G])) INR)"
    ) == []

def test_valid_symbol():
    assert errors("(concat 'A)") == []

def test_inr_index_at_boundary():
    assert errors("(concat (nth 2 INR))", inr_len=2) == []

def test_trm_index_at_boundary():
    assert errors("(concat (nth 1 TRM))", trm_len=1) == []


# ---------------------------------------------------------------------------
# Index out of bounds
# ---------------------------------------------------------------------------

def test_inr_index_out_of_bounds():
    errs = errors("(concat (nth 3 INR))", inr_len=2)
    assert len(errs) == 1
    assert "nth 3 INR" in errs[0]
    assert "length 2" in errs[0]

def test_trm_index_out_of_bounds():
    errs = errors("(concat (nth 2 TRM))", trm_len=1)
    assert len(errs) == 1
    assert "nth 2 TRM" in errs[0]
    assert "length 1" in errs[0]

def test_index_zero():
    errs = errors("(concat (nth 0 INR))")
    assert len(errs) == 1
    assert ">= 1" in errs[0]


# ---------------------------------------------------------------------------
# Undefined segment symbol
# ---------------------------------------------------------------------------

def test_undefined_symbol():
    errs = errors("(concat 'Z)")
    assert len(errs) == 1
    assert "Z" in errs[0]

def test_defined_symbol_no_error():
    assert errors("(concat 'A)") == []


# ---------------------------------------------------------------------------
# Undefined feature names
# ---------------------------------------------------------------------------

def test_unify_undefined_feature():
    errs = errors("(concat (unify (nth 1 INR) [+H]))")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_subtract_undefined_feature():
    errs = errors("(concat (subtract (nth 1 INR) [+H]))")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_project_undefined_feature():
    errs = errors("(concat (project (nth 1 INR) [H]))")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_in_class_undefined_feature():
    errs = errors("(if (in? (nth 1 TRM) [+H]) INR INR)")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_models_undefined_feature():
    errs = errors("(if (models? TRM [[+H]]) INR INR)")
    assert len(errs) == 1
    assert "H" in errs[0]

def test_epenthesis_undefined_feature():
    errs = errors("(concat (nth 1 INR) [+H] (nth 2 INR))")
    assert len(errs) == 1
    assert "H" in errs[0]


# ---------------------------------------------------------------------------
# Multiple errors
# ---------------------------------------------------------------------------

def test_multiple_errors_index_and_feature():
    # nth 3 out of bounds (inr_len=2) AND undefined feature H
    errs = errors("(concat (unify (nth 3 INR) [+H]))", inr_len=2)
    assert len(errs) == 2

def test_multiple_undefined_features():
    errs = errors("(concat (unify (nth 1 INR) [+H]) (subtract (nth 2 INR) [-X]))")
    assert len(errs) == 2
    feature_names = {e for err in errs for e in ["H", "X"] if e in err}
    assert feature_names == {"H", "X"}
