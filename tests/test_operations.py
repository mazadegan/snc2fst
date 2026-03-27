"""Tests for operations.py.

Test cases are taken directly from the paper's formal definitions and
bullet-point examples. The two-feature toy language (F, G) is used throughout.
"""

from snc2fst.operations import subtract, unify, project, in_class, models


# ---------------------------------------------------------------------------
# subtract: A \ B = {cF | cF ∈ A ∧ cF ∉ B}
# ---------------------------------------------------------------------------

def test_subtract_successful():
    # {+F, -G} \ {+F} = {-G}
    assert subtract({"F": "+", "G": "-"}, [("+", "F")]) == {"G": "-"}

def test_subtract_vacuous_disjoint():
    # {+F} \ {-G} = {+F}  (disjoint sets — nothing to remove)
    assert subtract({"F": "+"}, [("-", "G")]) == {"F": "+"}

def test_subtract_vacuous_empty():
    # {+F} \ {} = {+F}
    assert subtract({"F": "+"}, []) == {"F": "+"}

def test_subtract_sign_sensitive():
    # {+F} \ {-F} = {+F}  (wrong sign — -F is not in A)
    assert subtract({"F": "+"}, [("-", "F")]) == {"F": "+"}

def test_subtract_removes_all():
    # {+F, -G} \ {+F, -G} = {}
    assert subtract({"F": "+", "G": "-"}, [("+", "F"), ("-", "G")]) == {}

def test_subtract_empty_seg():
    assert subtract({}, [("+", "F")]) == {}


# ---------------------------------------------------------------------------
# unify: A ⊔ B = A ∪ {cF | cF ∈ B ∧ ¬cF ∉ A}
# ---------------------------------------------------------------------------

def test_unify_successful():
    # {-G} ⊔ {+F} = {+F, -G}
    assert unify({"G": "-"}, [("+", "F")]) == {"F": "+", "G": "-"}

def test_unify_vacuous_conflict():
    # {-F, -G} ⊔ {+F} = {-F, -G}  (A already has -F — opposite of +F)
    assert unify({"F": "-", "G": "-"}, [("+", "F")]) == {"F": "-", "G": "-"}

def test_unify_vacuous_idempotent():
    # {-G} ⊔ {-G} = {-G}  (A already has -G)
    assert unify({"G": "-"}, [("-", "G")]) == {"G": "-"}

def test_unify_empty_seg():
    # {} ⊔ {+F} = {+F}
    assert unify({}, [("+", "F")]) == {"F": "+"}

def test_unify_empty_features():
    # {+F} ⊔ {} = {+F}
    assert unify({"F": "+"}, []) == {"F": "+"}

def test_unify_multiple_features():
    # {} ⊔ {+F, -G} = {+F, -G}
    assert unify({}, [("+", "F"), ("-", "G")]) == {"F": "+", "G": "-"}


# ---------------------------------------------------------------------------
# project: π_F(s) = s ∩ ({-,+} × F)
# ---------------------------------------------------------------------------

def test_project_full():
    # π_{F,G}({+F, -G}) = {+F, -G}
    assert project({"F": "+", "G": "-"}, ["F", "G"]) == {"F": "+", "G": "-"}

def test_project_single_feature():
    # π_{G}({+F, -G}) = {-G}
    assert project({"F": "+", "G": "-"}, ["G"]) == {"G": "-"}

def test_project_empty_names():
    # π_{}({+F, -G}) = {}
    assert project({"F": "+", "G": "-"}, []) == {}

def test_project_feature_not_in_seg():
    # projecting onto a feature the segment doesn't have returns {}
    assert project({"F": "+"}, ["G"]) == {}

def test_project_empty_seg():
    assert project({}, ["F"]) == {}


# ---------------------------------------------------------------------------
# in_class: seg ∈ N(spec) ↔ spec ⊆ seg
# ---------------------------------------------------------------------------

def test_in_class_true_single():
    assert in_class({"F": "+", "G": "-"}, [("+", "F")]) is True

def test_in_class_true_multiple():
    assert in_class({"F": "+", "G": "-"}, [("+", "F"), ("-", "G")]) is True

def test_in_class_false_wrong_sign():
    assert in_class({"F": "+", "G": "-"}, [("-", "F")]) is False

def test_in_class_false_missing_feature():
    # Spec requires -G but seg has no value for G
    assert in_class({"F": "+"}, [("+", "F"), ("-", "G")]) is False

def test_in_class_universal_class():
    # Empty spec = universal natural class N(∅) — every segment is a member
    assert in_class({"F": "+", "G": "-"}, []) is True
    assert in_class({}, []) is True

def test_in_class_underspecified_seg():
    # Underspecified segment is in class as long as spec features are present
    assert in_class({"F": "+"}, [("+", "F")]) is True


# ---------------------------------------------------------------------------
# models: w ⊨ S ↔ |w| = |S| ∧ ∀i, w_i ∈ S_i
# ---------------------------------------------------------------------------

def test_models_true_single():
    word = [{"F": "+", "G": "-"}]
    spec_seq = [[("+", "F")]]
    assert models(word, spec_seq) is True

def test_models_true_multiple():
    word = [{"F": "+", "G": "-"}, {"F": "-", "G": "+"}]
    spec_seq = [[("+", "F")], [("-", "F")]]
    assert models(word, spec_seq) is True

def test_models_false_wrong_feature():
    word = [{"F": "+", "G": "-"}]
    spec_seq = [[("+", "G")]]  # G is -, not +
    assert models(word, spec_seq) is False

def test_models_false_length_mismatch():
    word = [{"F": "+", "G": "-"}]
    spec_seq = [[("+", "F")], [("-", "G")]]
    assert models(word, spec_seq) is False

def test_models_empty_word_and_spec():
    # The only word that models the empty sequence is the empty word
    assert models([], []) is True

def test_models_empty_spec_seq_mismatch():
    assert models([{"F": "+"}], []) is False

def test_models_universal_class():
    # Every segment models the universal natural class N(∅)
    word = [{"F": "+", "G": "-"}, {"F": "-"}]
    spec_seq = [[], []]
    assert models(word, spec_seq) is True
