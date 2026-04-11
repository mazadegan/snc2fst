import pytest

from snc2fst import dsl_ast as ast
from snc2fst.dsl import collect_errors, parse
from snc2fst.errors import ParseError, TokenizationError

#############################################################################
############################ Syntactic Errors ###############################
#############################################################################

### Leaves ###


def test_inr():
    assert parse("INR") == ast.Inr()


def test_trm():
    assert parse("TRM") == ast.Trm()


def test_bare_integer_raises() -> None:
    with pytest.raises(ParseError):
        parse("1")


def test_symbol_ascii():
    assert parse("&A") == ast.Symbol("A")


def test_symbol_ipa():
    assert parse("&ŋ") == ast.Symbol("ŋ")
    assert parse("&ʔ") == ast.Symbol("ʔ")


### Indexed access on INR/TRM i.e. INR[], TRM[] ###


def test_inr_index():
    assert parse("INR[1]") == ast.Slice(1, 1, ast.Inr())


def test_trm_index():
    assert parse("TRM[2]") == ast.Slice(2, 2, ast.Trm())


def test_inr_slice():
    assert parse("INR[1:3]") == ast.Slice(1, 3, ast.Inr())


def test_trm_slice():
    assert parse("TRM[2:4]") == ast.Slice(2, 4, ast.Trm())


def test_inr_bare_not_indexed():
    assert parse("INR") == ast.Inr()


def test_trm_bare_not_indexed():
    assert parse("TRM") == ast.Trm()


### Feature Bundles ###


def test_feature_bundle_single():
    assert parse("{+F}") == ast.FeatureSpec((ast.ValuedFeature("F", "+"),))


def test_feature_bundle_multiple():
    assert parse("{+F -G}") == ast.FeatureSpec(
        (ast.ValuedFeature("F", "+"), ast.ValuedFeature("G", "-"))
    )


def test_feature_bundle_with_commas_raises() -> None:
    with pytest.raises(ParseError):
        parse("{+F, -G}")


def test_feature_bundle_empty():
    assert parse("{}") == ast.FeatureSpec(())


### Natural class sequences [{+F} {-G}] ###


def test_nc_sequence_single():
    assert parse("[{+F -G}]") == ast.NcSequence(
        (
            ast.FeatureSpec(
                (ast.ValuedFeature("F", "+"), ast.ValuedFeature("G", "-"))
            ),
        )
    )


def test_nc_sequence_multiple():
    assert parse("[{+F} {-G}]") == ast.NcSequence(
        (
            ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),
            ast.FeatureSpec((ast.ValuedFeature("G", "-"),)),
        )
    )


def test_nc_sequence_with_commas_raises() -> None:
    with pytest.raises(ParseError):
        parse("[{+F}, {-G}]")


def test_nc_sequence_empty_bundle():
    assert parse("[{}]") == ast.NcSequence((ast.FeatureSpec(()),))


### Operations ###


def test_unify_with_bundle():
    assert parse("(unify INR[1] {+F})") == ast.Unify(
        ast.Slice(1, 1, ast.Inr()),
        ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),
    )


def test_subtract():
    assert parse("(subtract INR[1] {-G})") == ast.Subtract(
        ast.Slice(1, 1, ast.Inr()),
        ast.FeatureSpec((ast.ValuedFeature("G", "-"),)),
    )


def test_proj_single():
    assert parse("(proj INR[1] (F))") == ast.Project(
        ast.Slice(1, 1, ast.Inr()),
        ast.FeatureNames(("F",)),
    )


def test_proj_multiple():
    assert parse("(proj TRM[1] (F G))") == ast.Project(
        ast.Slice(1, 1, ast.Trm()),
        ast.FeatureNames(("F", "G")),
    )


def test_in_class():
    assert parse("(in? TRM[1] [{+F}])") == ast.InClass(
        ast.Slice(1, 1, ast.Trm()),
        ast.NcSequence((ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),)),
    )


def test_in_class_sequence():
    assert parse("(in? TRM [{+F}])") == ast.InClass(
        ast.Trm(),
        ast.NcSequence((ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),)),
    )


def test_in_class_multi_position():
    assert parse("(in? TRM [{+F} {-G}])") == ast.InClass(
        ast.Trm(),
        ast.NcSequence(
            (
                ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),
                ast.FeatureSpec((ast.ValuedFeature("G", "-"),)),
            )
        ),
    )


def test_if():
    assert parse("(if (in? TRM [{+F}]) INR INR)") == ast.If(
        cond=ast.InClass(
            ast.Trm(),
            ast.NcSequence((ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),)),
        ),
        then=ast.Inr(),
        else_=ast.Inr(),
    )


### Implicit concat ###


def test_implicit_concat_single():
    assert parse("(INR[1])") == ast.Concat((ast.Slice(1, 1, ast.Inr()),))


def test_implicit_concat_metathesis():
    assert parse("(INR[2] INR[1])") == ast.Concat(
        (
            ast.Slice(2, 2, ast.Inr()),
            ast.Slice(1, 1, ast.Inr()),
        )
    )


def test_implicit_concat_epenthesis():
    assert parse("(INR[1] &ə INR[2])") == ast.Concat(
        (
            ast.Slice(1, 1, ast.Inr()),
            ast.Symbol("ə"),
            ast.Slice(2, 2, ast.Inr()),
        )
    )


def test_implicit_concat_with_bundle():
    assert parse("(INR[1] {+F -G} INR[2])") == ast.Concat(
        (
            ast.Slice(1, 1, ast.Inr()),
            ast.FeatureSpec(
                (ast.ValuedFeature("F", "+"), ast.ValuedFeature("G", "-"))
            ),
            ast.Slice(2, 2, ast.Inr()),
        )
    )


def test_conditional_assimilation():
    result = parse("(if (in? TRM [{+F}]) (unify INR[1] {+F}) INR)")
    assert isinstance(result, ast.If)
    assert isinstance(result.cond, ast.InClass)
    assert isinstance(result.then, ast.Unify)
    assert isinstance(result.else_, ast.Inr)


### Whitespace and comments ###


def test_leading_trailing_whitespace():
    assert parse("  INR  ") == ast.Inr()


def test_internal_whitespace():
    assert parse("( unify  INR[1]  {+F} )") == ast.Unify(
        ast.Slice(1, 1, ast.Inr()),
        ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),
    )


def test_line_comment_ignored():
    assert parse("; this is a comment\nINR") == ast.Inr()


def test_inline_comment_ignored():
    assert parse("INR[1] ; extract first segment") == ast.Slice(
        1, 1, ast.Inr()
    )


### Parse errors ###


def test_error_unknown_token_in_concat():
    with pytest.raises(ParseError, match="Unexpected token"):
        parse("(foo INR)")


def test_error_proj_too_few_args():
    with pytest.raises(ParseError, match="feature name list"):
        parse("(proj INR[1])")


def test_error_if_too_few_args():
    with pytest.raises(ParseError, match="requires 3"):
        parse("(if INR INR)")


def test_error_unify_wrong_type():
    with pytest.raises(ParseError, match="feature bundle"):
        parse("(unify INR[1] [{+F}])")  # NcSequence instead of FeatureSpec


def test_error_in_class_sequence_wrong_type():
    with pytest.raises(ParseError, match="natural class sequence"):
        parse("(in? TRM {+F})")  # FeatureSpec instead of NcSequence


def test_error_proj_wrong_type():
    with pytest.raises(ParseError, match="feature name list"):
        parse("(proj INR[1] {+F})")  # FeatureSpec instead of FeatureNames


def test_error_in_class_wrong_type():
    with pytest.raises(ParseError, match="natural class"):
        parse("(in? TRM[1] {+F})")  # FeatureSpec instead of NcSequence


def test_error_bracket_non_bundle():
    with pytest.raises(ParseError, match="'{'"):
        parse("[+F]")  # bare feature spec not allowed inside []


def test_error_unclosed_paren():
    with pytest.raises(ParseError, match="Unclosed"):
        parse("(unify INR[1] {+F}")


def test_error_unclosed_bracket():
    with pytest.raises(ParseError, match="Unclosed"):
        parse("[{+F}")


def test_error_unclosed_bundle():
    with pytest.raises(ParseError, match="Unclosed"):
        parse("{+F")


def test_error_unexpected_character():
    with pytest.raises(TokenizationError):
        parse("'INR")


def test_error_trailing_token():
    with pytest.raises(ParseError, match="Unexpected token after"):
        parse("INR TRM")


def test_error_empty_implicit_concat():
    with pytest.raises(ParseError, match="at least 1"):
        parse("()")


def test_error_symbol_missing_name():
    with pytest.raises(ParseError, match="segment name"):
        parse("&")


### Special Cases ###


def test_in_class_with_inr_sequence() -> None:
    assert parse("(in? INR [{+F}])") == ast.InClass(
        ast.Inr(),
        ast.NcSequence((ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),)),
    )


def test_nested_operations() -> None:
    assert parse("(unify (subtract INR[1] {-F}) {+F})") == ast.Unify(
        ast.Subtract(
            ast.Slice(1, 1, ast.Inr()),
            ast.FeatureSpec((ast.ValuedFeature("F", "-"),)),
        ),
        ast.FeatureSpec((ast.ValuedFeature("F", "+"),)),
    )


def test_multiline_if() -> None:
    result = parse(
        "(if (in? TRM [{-Back}])\n    (unify INR[1] {-Back})\n    INR)"
    )
    assert isinstance(result, ast.If)
    assert isinstance(result.cond, ast.InClass)
    assert isinstance(result.then, ast.Unify)
    assert isinstance(result.else_, ast.Inr)


def test_slice_in_concat() -> None:
    assert parse("(INR[1:4] INR[2:4])") == ast.Concat(
        (
            ast.Slice(1, 4, ast.Inr()),
            ast.Slice(2, 4, ast.Inr()),
        )
    )


def test_bare_trm_in_in_class() -> None:
    assert parse("(in? TRM [{}])") == ast.InClass(
        ast.Trm(),
        ast.NcSequence((ast.FeatureSpec(()),)),
    )


#############################################################################
############################ Semantic Errors ################################
#############################################################################


RULE_ID = "R_0"
VALID_FEATURES = {"F", "G"}
VALID_SEGMENTS = {"A", "B", "C", "D", "E", "F", "G", "H", "I"}


def errors(expr: str, inr_len: int = 2, trm_len: int = 1):
    node = parse(expr)
    return collect_errors(
        node,
        rule_id=RULE_ID,
        inr_len=inr_len,
        trm_len=trm_len,
        valid_segments=VALID_SEGMENTS,
        valid_features=VALID_FEATURES,
    )


### Valid expressions — no errors expected ###


def test_metathesis():
    assert errors("(INR[2] INR[1])") == []


def test_unify():
    assert errors("(unify INR[1] {+F})") == []


def test_subtract_error():
    assert errors("(subtract INR[1] {-G})") == []


def test_proj():
    assert errors("(proj INR[1] (F G))") == []


def test_epenthesis():
    assert errors("(INR[1] {+F -G} INR[2])") == []


def test_conditional_via_in_class_sequence():
    assert errors("(if (in? TRM [{+F}]) (unify INR[1] {+F}) INR)") == []


def test_conditional_via_in_class():
    assert errors("(if (in? TRM[1] [{+F}]) (unify INR[1] {+G}) INR)") == []


def test_valid_symbol():
    assert errors("(INR[1] &A INR[2])") == []


def test_inr_index_at_boundary():
    assert errors("(INR[2])", inr_len=2) == []


def test_trm_index_at_boundary():
    assert errors("(proj TRM[1] (F))", trm_len=1) == []


### Index out of bounds ###


def test_inr_index_out_of_bounds():
    errs = errors("(INR[3])", inr_len=2)
    assert len(errs) == 1
    assert "INR[3" in errs[0]
    assert "length 2" in errs[0]


def test_trm_index_out_of_bounds():
    errs = errors("(proj TRM[2] (F))", trm_len=1)
    assert len(errs) == 1
    assert "TRM[2" in errs[0]
    assert "length 1" in errs[0]


def test_index_zero():
    errs = errors("(INR[0])")
    assert len(errs) == 1
    assert ">= 1" in errs[0]


### Undefined segment symbol ###


def test_undefined_symbol():
    errs = errors("(INR[1] &Z INR[2])")
    assert len(errs) == 1
    assert "Z" in errs[0]


def test_defined_symbol_no_error():
    assert errors("(INR[1] &A)") == []


### Undefined feature names ###


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
    errs = errors("(if (in? TRM [{+H}]) INR INR)")
    assert len(errs) == 1
    assert "H" in errs[0]


def test_epenthesis_undefined_feature():
    errs = errors("(INR[1] {+H} INR[2])")
    assert len(errs) == 1
    assert "H" in errs[0]


### Multiple errors ###


def test_multiple_errors_index_and_feature():
    errs = errors("(unify INR[3] {+H})", inr_len=2)
    assert len(errs) == 2


def test_multiple_undefined_features():
    errs = errors("((unify INR[1] {+H}) (subtract INR[2] {-X}))")
    assert len(errs) == 2
    feature_names = {e for err in errs for e in ["H", "X"] if e in err}
    assert feature_names == {"H", "X"}
