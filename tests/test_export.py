"""Tests for export.py — DSL-to-text and DSL-to-LaTeX renderers."""

import pytest
from snc2fst import ast, dsl
from snc2fst.export import _expr_txt, _expr_latex


def parse(s):
    return dsl.parse(s)


# ---------------------------------------------------------------------------
# Leaves
# ---------------------------------------------------------------------------

def test_txt_inr():
    assert _expr_txt(parse("INR")) == "ι"

def test_txt_trm():
    assert _expr_txt(parse("TRM")) == "τ"

def test_txt_nth_inr():
    assert _expr_txt(parse("INR[1]")) == "ι₁"

def test_txt_nth_trm():
    assert _expr_txt(parse("TRM[2]")) == "τ₂"

def test_txt_symbol():
    assert _expr_txt(parse("&ə")) == "ə"

def test_txt_feature_spec():
    assert _expr_txt(parse("{+Back -High}")) == "{+Back, -High}"

def test_txt_feature_spec_empty():
    assert _expr_txt(parse("{}")) == "{}"

def test_latex_inr():
    assert _expr_latex(parse("INR")) == "\\iota"

def test_latex_trm():
    assert _expr_latex(parse("TRM")) == "\\tau"

def test_latex_nth_inr():
    assert _expr_latex(parse("INR[1]")) == "\\iota_{1}"

def test_latex_nth_trm():
    assert _expr_latex(parse("TRM[2]")) == "\\tau_{2}"

def test_latex_symbol():
    assert _expr_latex(parse("&ə")) == "\\text{ə}"

def test_latex_feature_spec():
    assert _expr_latex(parse("{+Back -High}")) == "\\{+\\textsc{Back}, -\\textsc{High}\\}"

def test_latex_feature_spec_empty():
    assert _expr_latex(parse("{}")) == "\\{\\}"


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def test_txt_unify_literal():
    assert _expr_txt(parse("(unify INR[1] {+Back})")) == "(ι₁ ⊔ {+Back})"

def test_txt_unify_expr():
    assert _expr_txt(parse("(unify INR[1] (proj TRM[1] (Back)))")) == \
        "(ι₁ ⊔ (τ₁ ↾ {Back}))"

def test_txt_subtract():
    assert _expr_txt(parse("(subtract INR[1] {+Dorsal})")) == "(ι₁ ∖ {+Dorsal})"

def test_txt_proj():
    assert _expr_txt(parse("(proj TRM[1] (Back))")) == "(τ₁ ↾ {Back})"

def test_txt_concat():
    assert _expr_txt(parse("(INR[1] INR[2])")) == "ι₁ · ι₂"

def test_txt_in_class():
    assert _expr_txt(parse("(in? TRM[1] [{-Back}])")) == "τ₁ ∈ 𝒩({-Back})"

def test_txt_models():
    assert _expr_txt(parse("(models? INR [{+Back}])")) == "ι ⊨ ⟨{+Back}⟩"

def test_latex_unify_literal():
    assert _expr_latex(parse("(unify INR[1] {+Back})")) == \
        "(\\iota_{1} \\sqcup \\{+\\textsc{Back}\\})"

def test_latex_subtract():
    assert _expr_latex(parse("(subtract INR[1] {+Dorsal})")) == \
        "(\\iota_{1} \\setminus \\{+\\textsc{Dorsal}\\})"

def test_latex_proj():
    assert _expr_latex(parse("(proj TRM[1] (Back))")) == \
        "(\\tau_{1} \\upharpoonright \\{\\textsc{Back}\\})"

def test_latex_concat():
    assert _expr_latex(parse("(INR[1] INR[2])")) == \
        "\\iota_{1} \\cdot \\iota_{2}"

def test_latex_in_class():
    assert _expr_latex(parse("(in? TRM[1] [{-Back}])")) == \
        "\\tau_{1} \\in \\mathcal{N}(\\{-\\textsc{Back}\\})"


# ---------------------------------------------------------------------------
# Conditionals
# ---------------------------------------------------------------------------

def test_txt_if():
    result = _expr_txt(parse("(if (in? TRM[1] [{-Back}]) INR[1] INR)"))
    assert "if τ₁ ∈ 𝒩({-Back}):" in result
    assert "ι₁" in result
    assert "else:" in result
    assert result.splitlines()[-1].strip() == "ι"

def test_txt_if_nested():
    expr = "(if (in? TRM[1] [{-Back}]) (if (in? INR[1] [{+High}]) INR[1] INR) INR)"
    result = _expr_txt(parse(expr))
    lines = result.splitlines()
    assert lines[0].startswith("if ")
    assert any("if " in l for l in lines[1:])

def test_latex_if_top_level():
    result = _expr_latex(parse("(if (in? TRM[1] [{-Back}]) INR[1] INR)"), depth=0)
    assert "\\begin{cases}" in result
    assert "\\text{if }" in result
    assert "\\text{otherwise}" in result
    assert "\\end{cases}" in result

def test_latex_if_nested():
    result = _expr_latex(parse("(if (in? TRM[1] [{-Back}]) INR[1] INR)"), depth=1)
    assert "\\mathbin{?}" in result
    assert "\\mathbin{:}" in result
    assert "\\begin{cases}" not in result


# ---------------------------------------------------------------------------
# Subscript helper
# ---------------------------------------------------------------------------

def test_subscript_multi_digit():
    from snc2fst.export import _subscript
    assert _subscript(12) == "₁₂"

def test_subscript_zero():
    from snc2fst.export import _subscript
    assert _subscript(0) == "₀"
