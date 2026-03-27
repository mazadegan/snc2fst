import pytest
from snc2fst import ast
from snc2fst.dsl import parse, ParseError


# ---------------------------------------------------------------------------
# Leaves
# ---------------------------------------------------------------------------

def test_inr():
    assert parse("INR") == ast.Inr()

def test_trm():
    assert parse("TRM") == ast.Trm()

def test_integer():
    assert parse("1") == ast.Integer(1)
    assert parse("42") == ast.Integer(42)

def test_symbol_ascii():
    assert parse("'A") == ast.Symbol("A")

def test_symbol_ipa():
    assert parse("'ŋ") == ast.Symbol("ŋ")
    assert parse("'ʔ") == ast.Symbol("ʔ")


# ---------------------------------------------------------------------------
# Brackets
# ---------------------------------------------------------------------------

def test_feature_spec_single():
    assert parse("[+F]") == ast.FeatureSpec([ast.ValuedFeature("+", "F")])

def test_feature_spec_multiple():
    assert parse("[+F -G]") == ast.FeatureSpec([
        ast.ValuedFeature("+", "F"),
        ast.ValuedFeature("-", "G"),
    ])

def test_feature_spec_empty():
    assert parse("[]") == ast.FeatureSpec([])

def test_feature_names_single():
    assert parse("[F]") == ast.FeatureNames(["F"])

def test_feature_names_multiple():
    assert parse("[F G]") == ast.FeatureNames(["F", "G"])

def test_nc_sequence_single():
    assert parse("[[+F -G]]") == ast.NcSequence([
        ast.FeatureSpec([ast.ValuedFeature("+", "F"), ast.ValuedFeature("-", "G")]),
    ])

def test_nc_sequence_multiple():
    assert parse("[[+F] [-G]]") == ast.NcSequence([
        ast.FeatureSpec([ast.ValuedFeature("+", "F")]),
        ast.FeatureSpec([ast.ValuedFeature("-", "G")]),
    ])


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def test_nth_inr():
    assert parse("(nth 1 INR)") == ast.Nth(ast.Integer(1), ast.Inr())

def test_nth_trm():
    assert parse("(nth 2 TRM)") == ast.Nth(ast.Integer(2), ast.Trm())

def test_unify():
    assert parse("(unify (nth 1 INR) [+F])") == ast.Unify(
        ast.Nth(ast.Integer(1), ast.Inr()),
        ast.FeatureSpec([ast.ValuedFeature("+", "F")]),
    )

def test_subtract():
    assert parse("(subtract (nth 1 INR) [-G])") == ast.Subtract(
        ast.Nth(ast.Integer(1), ast.Inr()),
        ast.FeatureSpec([ast.ValuedFeature("-", "G")]),
    )

def test_project():
    assert parse("(project (nth 1 INR) [F G])") == ast.Project(
        ast.Nth(ast.Integer(1), ast.Inr()),
        ast.FeatureNames(["F", "G"]),
    )

def test_in_class():
    assert parse("(in? (nth 1 TRM) [+F])") == ast.InClass(
        ast.Nth(ast.Integer(1), ast.Trm()),
        ast.FeatureSpec([ast.ValuedFeature("+", "F")]),
    )

def test_models():
    assert parse("(models? TRM [[+F]])") == ast.Models(
        ast.Trm(),
        ast.NcSequence([ast.FeatureSpec([ast.ValuedFeature("+", "F")])]),
    )

def test_if():
    assert parse("(if (models? TRM [[+F]]) INR INR)") == ast.If(
        cond=ast.Models(
            ast.Trm(),
            ast.NcSequence([ast.FeatureSpec([ast.ValuedFeature("+", "F")])]),
        ),
        then=ast.Inr(),
        else_=ast.Inr(),
    )

def test_concat_single():
    assert parse("(concat (nth 1 INR))") == ast.Concat([
        ast.Nth(ast.Integer(1), ast.Inr()),
    ])

def test_concat_metathesis():
    assert parse("(concat (nth 2 INR) (nth 1 INR))") == ast.Concat([
        ast.Nth(ast.Integer(2), ast.Inr()),
        ast.Nth(ast.Integer(1), ast.Inr()),
    ])

def test_concat_epenthesis():
    assert parse("(concat (nth 1 INR) [+F -G] (nth 2 INR))") == ast.Concat([
        ast.Nth(ast.Integer(1), ast.Inr()),
        ast.FeatureSpec([ast.ValuedFeature("+", "F"), ast.ValuedFeature("-", "G")]),
        ast.Nth(ast.Integer(2), ast.Inr()),
    ])

def test_conditional_assimilation():
    result = parse(
        "(if (models? TRM [[+F]]) (concat (unify (nth 1 INR) [+F])) INR)"
    )
    assert isinstance(result, ast.If)
    assert isinstance(result.cond, ast.Models)
    assert isinstance(result.then, ast.Concat)
    assert isinstance(result.else_, ast.Inr)


# ---------------------------------------------------------------------------
# Whitespace and comments
# ---------------------------------------------------------------------------

def test_leading_trailing_whitespace():
    assert parse("  INR  ") == ast.Inr()

def test_internal_whitespace():
    assert parse("( nth   1   INR )") == ast.Nth(ast.Integer(1), ast.Inr())

def test_line_comment_ignored():
    assert parse("; this is a comment\nINR") == ast.Inr()

def test_inline_comment_ignored():
    assert parse("(nth 1 INR) ; extract first segment") == ast.Nth(
        ast.Integer(1), ast.Inr()
    )


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------

def test_error_unknown_operator():
    with pytest.raises(ParseError, match="Unknown operator"):
        parse("(foo INR)")

def test_error_nth_too_few_args():
    with pytest.raises(ParseError, match="requires 2"):
        parse("(nth 1)")

def test_error_if_too_few_args():
    with pytest.raises(ParseError, match="requires 3"):
        parse("(if INR INR)")

def test_error_unify_wrong_type():
    with pytest.raises(ParseError, match="feature spec"):
        parse("(unify (nth 1 INR) [F G])")  # FeatureNames instead of FeatureSpec

def test_error_models_wrong_type():
    with pytest.raises(ParseError, match="NC sequence"):
        parse("(models? TRM [+F])")  # FeatureSpec instead of NcSequence

def test_error_project_wrong_type():
    with pytest.raises(ParseError, match="feature name list"):
        parse("(project (nth 1 INR) [+F])")  # FeatureSpec instead of FeatureNames

def test_error_mixed_bracket():
    with pytest.raises(ParseError, match="Mixed bracket"):
        parse("[+F G]")

def test_error_nested_non_feature_spec():
    with pytest.raises(ParseError, match="valued features"):
        parse("[[F G]]")  # FeatureNames not allowed as inner bracket

def test_error_unclosed_paren():
    with pytest.raises(ParseError, match="Unclosed"):
        parse("(nth 1 INR")

def test_error_unclosed_bracket():
    with pytest.raises(ParseError, match="Unclosed"):
        parse("[+F -G")

def test_error_unexpected_character():
    with pytest.raises(ParseError, match="Unexpected character"):
        parse("@INR")

def test_error_trailing_token():
    with pytest.raises(ParseError, match="Unexpected token after"):
        parse("INR TRM")

def test_error_concat_empty():
    with pytest.raises(ParseError, match="at least 1"):
        parse("(concat)")
