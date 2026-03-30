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
    assert _expr_txt(parse("(nth 1 INR)")) == "ι₁"

def test_txt_nth_trm():
    assert _expr_txt(parse("(nth 2 TRM)")) == "τ₂"

def test_txt_symbol():
    assert _expr_txt(parse("'ə")) == "ə"

def test_txt_feature_spec():
    assert _expr_txt(parse("[+Back -High]")) == "{+Back, -High}"

def test_txt_feature_spec_empty():
    assert _expr_txt(parse("[]")) == "{}"

def test_txt_feature_names():
    assert _expr_txt(parse("[Back Voice]")) == "{Back, Voice}"

def test_latex_inr():
    assert _expr_latex(parse("INR")) == "\\iota"

def test_latex_trm():
    assert _expr_latex(parse("TRM")) == "\\tau"

def test_latex_nth_inr():
    assert _expr_latex(parse("(nth 1 INR)")) == "\\iota_{1}"

def test_latex_nth_trm():
    assert _expr_latex(parse("(nth 2 TRM)")) == "\\tau_{2}"

def test_latex_symbol():
    assert _expr_latex(parse("'ə")) == "\\text{ə}"

def test_latex_feature_spec():
    assert _expr_latex(parse("[+Back -High]")) == "\\{+\\textsc{Back}, -\\textsc{High}\\}"

def test_latex_feature_spec_empty():
    assert _expr_latex(parse("[]")) == "\\{\\}"

def test_latex_feature_names():
    assert _expr_latex(parse("[Back Voice]")) == "\\{\\textsc{Back}, \\textsc{Voice}\\}"


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def test_txt_unify_literal():
    assert _expr_txt(parse("(unify (nth 1 INR) [+Back])")) == "(ι₁ ⊔ {+Back})"

def test_txt_unify_expr():
    assert _expr_txt(parse("(unify (nth 1 INR) (project (nth 1 TRM) [Back]))")) == \
        "(ι₁ ⊔ (τ₁ ↾ {Back}))"

def test_txt_subtract():
    assert _expr_txt(parse("(subtract (nth 1 INR) [+Dorsal])")) == "(ι₁ ∖ {+Dorsal})"

def test_txt_project():
    assert _expr_txt(parse("(project (nth 1 TRM) [Back])")) == "(τ₁ ↾ {Back})"

def test_txt_concat():
    assert _expr_txt(parse("(concat (nth 1 INR) (nth 2 INR))")) == "ι₁ · ι₂"

def test_txt_in_class():
    assert _expr_txt(parse("(in? (nth 1 TRM) [-Back])")) == "τ₁ ∈ 𝒩({-Back})"

def test_txt_models():
    assert _expr_txt(parse("(models? INR [[+Back]])")) == "ι ⊨ ⟨{+Back}⟩"

def test_latex_unify_literal():
    assert _expr_latex(parse("(unify (nth 1 INR) [+Back])")) == \
        "(\\iota_{1} \\sqcup \\{+\\textsc{Back}\\})"

def test_latex_subtract():
    assert _expr_latex(parse("(subtract (nth 1 INR) [+Dorsal])")) == \
        "(\\iota_{1} \\setminus \\{+\\textsc{Dorsal}\\})"

def test_latex_project():
    assert _expr_latex(parse("(project (nth 1 TRM) [Back])")) == \
        "(\\tau_{1} \\upharpoonright \\{\\textsc{Back}\\})"

def test_latex_concat():
    assert _expr_latex(parse("(concat (nth 1 INR) (nth 2 INR))")) == \
        "\\iota_{1} \\cdot \\iota_{2}"

def test_latex_in_class():
    assert _expr_latex(parse("(in? (nth 1 TRM) [-Back])")) == \
        "\\tau_{1} \\in \\mathcal{N}(\\{-\\textsc{Back}\\})"


# ---------------------------------------------------------------------------
# Conditionals
# ---------------------------------------------------------------------------

def test_txt_if():
    result = _expr_txt(parse("(if (in? (nth 1 TRM) [-Back]) (nth 1 INR) INR)"))
    assert "if τ₁ ∈ 𝒩({-Back}):" in result
    assert "ι₁" in result
    assert "else:" in result
    assert result.splitlines()[-1].strip() == "ι"

def test_txt_if_nested():
    expr = "(if (in? (nth 1 TRM) [-Back]) (if (in? (nth 1 INR) [+High]) (nth 1 INR) INR) INR)"
    result = _expr_txt(parse(expr))
    lines = result.splitlines()
    assert lines[0].startswith("if ")
    assert any("if " in l for l in lines[1:])

def test_latex_if_top_level():
    result = _expr_latex(parse("(if (in? (nth 1 TRM) [-Back]) (nth 1 INR) INR)"), depth=0)
    assert "\\begin{cases}" in result
    assert "\\text{if }" in result
    assert "\\text{otherwise}" in result
    assert "\\end{cases}" in result

def test_latex_if_nested():
    result = _expr_latex(parse("(if (in? (nth 1 TRM) [-Back]) (nth 1 INR) INR)"), depth=1)
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
