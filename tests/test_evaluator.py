import logical_phonology as lp
import pytest

from snc2fst.dsl import parse
from snc2fst.errors import EvalError
from snc2fst.evaluator import apply_rule, evaluate
from snc2fst.models import Rule

FS = lp.FeatureSystem(frozenset(["F", "G"]))


def w(*segs: lp.Segment) -> lp.Word:
    return FS.word(list(segs))


A = FS.segment({"F": lp.POS, "G": lp.POS})
B = FS.segment({"F": lp.POS, "G": lp.NEG})
C = FS.segment({"F": lp.NEG, "G": lp.POS})
D = FS.segment({"F": lp.NEG, "G": lp.NEG})


INV = FS.inventory({"A": A, "B": B, "C": C, "D": D})


### Evaluate leaf nodes ###


def test_eval_inr() -> None:
    inr, trm = A + B, FS.word([C])
    assert evaluate(parse("INR"), inr, trm, FS, INV) == inr


def test_eval_trm() -> None:
    inr, trm = A + B, FS.word([C])
    assert evaluate(parse("TRM"), inr, trm, FS, INV) == trm


def test_eval_nth_inr() -> None:
    inr, trm = A + B, w(C)
    assert evaluate(parse("INR[2]"), inr, trm, FS, INV) == w(B)


def test_eval_nth_trm() -> None:
    inr, trm = A + B, w(C)
    assert evaluate(parse("TRM[1]"), inr, trm, FS, INV) == w(C)


def test_eval_slice() -> None:
    inr, trm = A + B, w(C)
    assert evaluate(parse("INR[1:2]"), inr, trm, FS, INV) == w(A, B)


def test_eval_symbol_literal() -> None:
    assert evaluate(parse("&A"), w(), w(), FS, INV) == w(A)


def test_eval_symbol_unknown():
    with pytest.raises(EvalError, match="Unknown segment symbol"):
        evaluate(parse("&Z"), w(), w(), FS, INV)


### Evaluate phonological operations


def test_eval_unify():
    # {G: "+"} ⊔ {+F}: -F not present → +F is added → {F: "+", G: "+"}
    result = evaluate(
        parse("(unify INR[1] {+F})"),
        w(FS.segment({"G": lp.POS})),
        w(),
        FS,
        INV,
    )
    assert result == w(FS.segment({"G": lp.POS, "F": lp.POS}))


def test_eval_unify_blocked():
    # B = {+F, -G}; unify with {+G} blocked because -G (opposite) IS present → stays B # noqa: E501
    result = evaluate(parse("(unify INR[1] {+G})"), w(B), w(), FS, INV)
    assert result == w(B)


def test_eval_subtract():
    # A = {+F, +G}; subtract {+F} → {+G}
    result = evaluate(parse("(subtract INR[1] {+F})"), w(A), w(), FS, INV)
    assert result == w(FS.segment({"G": lp.POS}))


def test_eval_project():
    # A = {+F, +G}; proj (G) → {+G}
    result = evaluate(parse("(proj INR[1] (G))"), w(A), w(), FS, INV)
    assert result == w(FS.segment({"G": lp.POS}))


### Evaluate predicates ###


def test_eval_in_class_true():
    assert evaluate(parse("(in? INR[1] [{+F}])"), w(A), w(), FS, INV) is True


def test_eval_in_class_false():
    assert evaluate(parse("(in? INR[1] [{-F}])"), w(A), w(), FS, INV) is False


def test_eval_in_class_sequence_true():
    result = evaluate(parse("(in? TRM [{+F}])"), w(), w(A), FS, INV)
    assert result is True


def test_eval_in_class_sequence_false():
    result = evaluate(parse("(in? TRM [{-F}])"), w(), w(A), FS, INV)
    assert result is False


def test_eval_in_class_length_mismatch():
    # Single segment tested against 2-position NC seq → False (not an error)
    result = evaluate(parse("(in? TRM [{+F} {-G}])"), w(), w(A), FS, INV)
    assert result is False


### Evaluate implicit concat


def test_eval_concat_identity():
    # (INR) — returns the whole INR word unchanged
    assert evaluate(parse("(INR)"), A + B, w(), FS, INV) == A + B


def test_eval_concat_metathesis():
    # swap two segments
    result = evaluate(parse("(INR[2] INR[1])"), A + B, w(), FS, INV)
    assert result == B + A


def test_eval_concat_epenthesis():
    # insert a bare feature bundle between two segments
    result = evaluate(parse("(INR[1] {+F -G} INR[2])"), A + C, w(), FS, INV)
    assert result == A + B + C


def test_eval_concat_symbol_epenthesis():
    result = evaluate(parse("(INR[1] &D INR[2])"), A + C, w(), FS, INV)
    assert result == A + D + C


def test_eval_concat_single_operation():
    # (unify INR[1] {+F}) applied to [{G: "+"}] → [{+F, +G}]
    result = evaluate(
        parse("(unify INR[1] {+F})"),
        w(FS.segment({"G": lp.POS})),
        w(),
        FS,
        INV,
    )
    assert result == w(A)


### Evaluate conditional


def test_eval_if_then_branch():
    # TRM = [A] has +F → then branch: unify INR[1] (which is {F:"-"}) with {+G}
    # {F:"-"} has no -G, so +G can be added → {F:"-", G:"+"}
    result = evaluate(
        parse("(if (in? TRM [{+F}]) (unify INR[1] {+G}) INR)"),
        w(FS.segment({"F": lp.NEG})),
        w(A),
        FS,
        INV,
    )
    assert result == w(C)


def test_eval_if_else_branch():
    # TRM = [D] which has -F, so else branch taken: return INR unchanged
    result = evaluate(
        parse("(if (in? TRM [{+F}]) (unify INR[1] {+G}) INR)"),
        w(D),
        w(D),
        FS,
        INV,
    )
    assert result == w(D)


### Apply rule with DIR = R (trigger to the right)

# Rule: assimilate -F segment to +F when followed by a +F segment.
ASSIMILATION_R = Rule.model_validate(
    {
        "Id": "assim_R",
        "Inr": [["-F"]],
        "Trm": [["+F"]],
        "Dir": "R",
        "Out": "(unify (subtract INR[1] {-F}) {+F})",
    }
)
ASSIMILATION_R_AST = parse(ASSIMILATION_R.Out)


def test_apply_rule_single_match_right():
    # C = {-F, +G} before A = {+F, +G} → subtract -F → {+G}, unify +F → {+F, +G} # noqa: E501
    word = C + A
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, word, FS, INV)
    assert result == A + A


def test_apply_rule_no_trigger_right():
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, C + C, FS, INV)
    assert result == C + C


def test_apply_rule_no_target_right():
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, A + A, FS, INV)
    assert result == A + A


def test_apply_rule_multiple_matches_right():
    result = apply_rule(
        ASSIMILATION_R, ASSIMILATION_R_AST, C + A + C + A, FS, INV
    )
    assert result == A + A + A + A


def test_apply_rule_word_unchanged_when_no_match():
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, A + B + A, FS, INV)
    assert result == A + B + A


# apply_rule with DIR = L (trigger to the left)

ASSIMILATION_L = Rule.model_validate(
    {
        "Id": "assim_L",
        "Inr": [["-F"]],
        "Trm": [["+F"]],
        "Dir": "L",
        "Out": "(unify (subtract INR[1] {-F}) {+F})",
    }
)
ASSIMILATION_L_AST = parse(ASSIMILATION_L.Out)


def test_apply_rule_single_match_left():
    result = apply_rule(ASSIMILATION_L, ASSIMILATION_L_AST, A + C, FS, INV)
    assert result == A + A


def test_apply_rule_no_trigger_left():
    result = apply_rule(ASSIMILATION_L, ASSIMILATION_L_AST, C + C, FS, INV)
    assert result == C + C


def test_apply_rule_at_start_no_trigger_left():
    result = apply_rule(ASSIMILATION_L, ASSIMILATION_L_AST, C + A, FS, INV)
    assert result == C + A


### apply_rule, multi-segment INR ###

ASSIMILATION_2SEG = Rule.model_validate(
    {
        "Id": "assim_2seg",
        "Inr": [["-F"], ["-F"]],
        "Trm": [["+F"]],
        "Dir": "L",
        "Out": """
        ((unify (subtract INR[1] {-F}) {+F}) 
            (unify (subtract INR[2] {-F}) {+F}))
        """,
    }
)
ASSIMILATION_2SEG_AST = parse(ASSIMILATION_2SEG.Out)


def test_apply_rule_two_segment_inr():
    result = apply_rule(
        ASSIMILATION_2SEG, ASSIMILATION_2SEG_AST, A + C + D, FS, INV
    )
    assert result == A + A + B


def test_apply_rule_two_segment_inr_no_match():
    result = apply_rule(
        ASSIMILATION_2SEG, ASSIMILATION_2SEG_AST, A + C + A, FS, INV
    )
    assert result == A + C + A


### apply_rule, conditional output ###

CONDITIONAL = Rule.model_validate(
    {
        "Id": "cond",
        "Inr": [["-F"]],
        "Trm": [["+F"]],
        "Dir": "R",
        "Out": """
        (if (in? TRM[1] [{+G}]) 
            (unify (subtract INR[1] {-G}) {+G}) 
            INR)
        """,  # TRM[1] is a length-1 seq
    }
)
CONDITIONAL_AST = parse(CONDITIONAL.Out)


def test_apply_rule_conditional_then():
    result = apply_rule(CONDITIONAL, CONDITIONAL_AST, D + A, FS, INV)
    assert result == C + A


def test_apply_rule_conditional_else():
    result = apply_rule(CONDITIONAL, CONDITIONAL_AST, D + B, FS, INV)
    assert result == D + B


### apply_rule,  BOS/EOS boundary pseudo-segments ###

WORD_INITIAL_TARGET = Rule.model_validate(
    {
        "Id": "word_initial",
        "Inr": [["+BOS"], ["-F"]],
        "Trm": [],
        "Dir": "L",
        "Out": "(INR[1] (unify (subtract INR[2] {-F}) {+F}))",
    }
)
WORD_INITIAL_TARGET_AST = parse(WORD_INITIAL_TARGET.Out)

WORD_INITIAL_TRIGGER = Rule.model_validate(
    {
        "Id": "word_initial_trm",
        "Inr": [["-F"]],
        "Trm": [["+BOS"]],
        "Dir": "L",
        "Out": "(unify (subtract INR[1] {-F}) {+F})",
    }
)
WORD_INITIAL_TRIGGER_AST = parse(WORD_INITIAL_TRIGGER.Out)

WORD_FINAL_DELETION = Rule.model_validate(
    {
        "Id": "word_final_del",
        "Inr": [["-F"], ["+EOS"]],
        "Trm": [],
        "Dir": "L",
        "Out": "INR[2]",
    }
)
WORD_FINAL_DELETION_AST = parse(WORD_FINAL_DELETION.Out)

EPENTHESIS_WORD_FINAL = Rule.model_validate(
    {
        "Id": "epen_final",
        "Inr": [[], ["+EOS"]],
        "Trm": [],
        "Dir": "L",
        "Out": "(INR[1] &A INR[2])",
    }
)
EPENTHESIS_WORD_FINAL_AST = parse(EPENTHESIS_WORD_FINAL.Out)


def test_apply_rule_bos_in_inr_matches_word_initial():
    result = apply_rule(
        WORD_INITIAL_TARGET, WORD_INITIAL_TARGET_AST, w(C), FS, INV
    )
    assert result == w(A)


def test_apply_rule_bos_in_inr_no_match_non_initial():
    result = apply_rule(
        WORD_INITIAL_TARGET, WORD_INITIAL_TARGET_AST, A + C, FS, INV
    )
    assert result == A + C


def test_apply_rule_bos_trigger_all_minus_f_assimilated():
    result = apply_rule(
        WORD_INITIAL_TRIGGER, WORD_INITIAL_TRIGGER_AST, C + D, FS, INV
    )
    assert result == A + B


def test_apply_rule_eos_in_inr_deletion():
    result = apply_rule(
        WORD_FINAL_DELETION, WORD_FINAL_DELETION_AST, C + D, FS, INV
    )
    assert result == w(C)


def test_apply_rule_eos_in_inr_deletion_only_final():
    result = apply_rule(
        WORD_FINAL_DELETION, WORD_FINAL_DELETION_AST, D + A, FS, INV
    )
    assert result == D + A


def test_apply_rule_epenthesis_before_eos():
    result = apply_rule(
        EPENTHESIS_WORD_FINAL, EPENTHESIS_WORD_FINAL_AST, w(B), FS, INV
    )
    assert result == B + A


def test_apply_rule_boundaries_stripped_from_output():
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, C + A, FS, INV)
    assert FS.BOS not in result
    assert FS.EOS not in result


def test_apply_rule_boundary_position_error():
    bad_rule = Rule.model_validate(
        {
            "Id": "bad",
            "Inr": [["+BOS"], []],
            "Trm": [],
            "Dir": "L",
            "Out": "(INR[2] INR[1])",
        }
    )
    bad_ast = parse(bad_rule.Out)
    with pytest.raises(EvalError, match="BOS boundary ended up at position"):
        apply_rule(bad_rule, bad_ast, w(A), FS, INV)


def test_eval_first_inr() -> None:
    inr, trm = A + B, w(C)
    assert evaluate(parse("INR[1]"), inr, trm, FS, INV) == w(A)


def test_eval_trm_slice() -> None:
    inr, trm = w(A), B + C
    assert evaluate(parse("TRM[1:2]"), inr, trm, FS, INV) == B + C


def test_eval_nested_operations() -> None:
    # (unify (subtract INR[1] {-F}) {+F}) on C = {-F, +G}
    # subtract -F → {+G}, unify +F → {+F, +G} = A
    result = evaluate(
        parse("(unify (subtract INR[1] {-F}) {+F})"),
        w(C),
        w(),
        FS,
        INV,
    )
    assert result == w(A)


def test_eval_nested_conditional() -> None:
    # outer if: TRM has +F → inner if: INR has +G → unify +F else INR
    # use segment with only +G (no F specified) so unify +F can fire
    seg = FS.segment({"G": lp.POS})
    result = evaluate(
        parse(
            """
            (if (in? TRM [{+F}]) 
                (if (in? INR[1] [{+G}]) 
                    (unify INR[1] {+F}) 
                    INR) 
                INR)
            """
        ),
        w(seg),
        w(A),  # A has +F
        FS,
        INV,
    )
    assert result == w(A)


def test_eval_nested_conditional_inner_else() -> None:
    # outer if fires (TRM has +F), inner else fires (INR has -G)
    result = evaluate(
        parse(
            """
            (if (in? TRM [{+F}]) 
                (if (in? INR[1] [{+G}]) 
                (unify INR[1] {+F}) 
                INR) 
            INR)
            """
        ),
        w(D),  # D has -G
        w(A),  # A has +F
        FS,
        INV,
    )
    assert result == w(D)


def test_eval_nested_conditional_outer_else() -> None:
    # TRM has -F → outer else branch, return INR unchanged
    result = evaluate(
        parse(
            """
            (if (in? TRM [{+F}]) 
                (if (in? INR[1] [{+G}]) 
                    (unify INR[1] {+F}) 
                    INR) 
                INR)
            """
        ),
        w(C),
        w(C),  # C has -F
        FS,
        INV,
    )
    assert result == w(C)


def test_apply_rule_empty_word() -> None:
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, w(), FS, INV)
    assert result == w()
