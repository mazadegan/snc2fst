"""Tests for evaluator.py.

Uses a two-feature toy language (F, G) throughout:
  A = {+F, +G},  B = {+F, -G},  C = {-F, +G},  D = {-F, -G}
"""

import pytest
from snc2fst import dsl
from snc2fst.evaluator import EvalError, apply_rule, evaluate
from snc2fst.models import Rule

# ---------------------------------------------------------------------------
# Toy alphabet
# ---------------------------------------------------------------------------

A = {"F": "+", "G": "+"}
B = {"F": "+", "G": "-"}
C = {"F": "-", "G": "+"}
D = {"F": "-", "G": "-"}

ALPHABET = {"A": A, "B": B, "C": C, "D": D}


def parse(expr: str):
    return dsl.parse(expr)


# ---------------------------------------------------------------------------
# evaluate — leaf nodes
# ---------------------------------------------------------------------------


def test_eval_inr():
    assert evaluate(parse("INR"), [A, B], [C], ALPHABET) == [A, B]


def test_eval_trm():
    assert evaluate(parse("TRM"), [A], [C, D], ALPHABET) == [C, D]


def test_eval_nth_inr():
    assert evaluate(parse("(nth 1 INR)"), [A, B], [], ALPHABET) == A


def test_eval_nth_trm():
    assert evaluate(parse("(nth 1 TRM)"), [], [C], ALPHABET) == C


def test_eval_nth_second():
    assert evaluate(parse("(nth 2 INR)"), [A, B], [], ALPHABET) == B


def test_eval_symbol():
    assert evaluate(parse("'A"), [], [], ALPHABET) == A


def test_eval_symbol_unknown():
    with pytest.raises(EvalError, match="Unknown segment symbol"):
        evaluate(parse("'Z"), [], [], ALPHABET)


# ---------------------------------------------------------------------------
# evaluate — phonological operations
# ---------------------------------------------------------------------------


def test_eval_unify():
    # {G: "+"} ⊔ {+F}: -F not present → +F is added → {F: "+", G: "+"}
    result = evaluate(parse("(unify (nth 1 INR) [+F])"), [{"G": "+"}], [], ALPHABET)
    assert result == {"F": "+", "G": "+"}


def test_eval_unify_blocked():
    # B = {+F, -G}; unify with [+G] blocked because -G (opposite) IS present → stays B
    result = evaluate(parse("(unify (nth 1 INR) [+G])"), [B], [], ALPHABET)
    assert result == B


def test_eval_subtract():
    # A = {+F, +G}; subtract [+F] → {+G}
    result = evaluate(parse("(subtract (nth 1 INR) [+F])"), [A], [], ALPHABET)
    assert result == {"G": "+"}


def test_eval_project():
    # A = {+F, +G}; project [G] → {+G}
    result = evaluate(parse("(project (nth 1 INR) [G])"), [A], [], ALPHABET)
    assert result == {"G": "+"}


# ---------------------------------------------------------------------------
# evaluate — predicates
# ---------------------------------------------------------------------------


def test_eval_in_class_true():
    assert evaluate(parse("(in? (nth 1 INR) [+F])"), [A], [], ALPHABET) is True


def test_eval_in_class_false():
    assert evaluate(parse("(in? (nth 1 INR) [-F])"), [A], [], ALPHABET) is False


def test_eval_models_true():
    result = evaluate(parse("(models? TRM [[+F]])"), [], [A], ALPHABET)
    assert result is True


def test_eval_models_false():
    result = evaluate(parse("(models? TRM [[-F]])"), [], [A], ALPHABET)
    assert result is False


# ---------------------------------------------------------------------------
# evaluate — Concat (word-level output)
# ---------------------------------------------------------------------------


def test_eval_concat_identity():
    # (concat INR) — returns the whole INR word unchanged
    assert evaluate(parse("(concat INR)"), [A, B], [], ALPHABET) == [A, B]


def test_eval_concat_metathesis():
    # swap two segments
    result = evaluate(parse("(concat (nth 2 INR) (nth 1 INR))"), [A, B], [], ALPHABET)
    assert result == [B, A]


def test_eval_concat_epenthesis():
    # insert a bare feature spec between two segments
    result = evaluate(
        parse("(concat (nth 1 INR) [+F -G] (nth 2 INR))"), [A, C], [], ALPHABET
    )
    assert result == [A, {"F": "+", "G": "-"}, C]


def test_eval_concat_symbol_epenthesis():
    result = evaluate(
        parse("(concat (nth 1 INR) 'D (nth 2 INR))"), [A, C], [], ALPHABET
    )
    assert result == [A, D, C]


def test_eval_concat_single_operation():
    # (concat (unify (nth 1 INR) [+F])) applied to [{G: "+"}] → [{+F, +G}]
    result = evaluate(parse("(concat (unify (nth 1 INR) [+F]))"), [{"G": "+"}], [], ALPHABET)
    assert result == [{"F": "+", "G": "+"}]


# ---------------------------------------------------------------------------
# evaluate — conditional
# ---------------------------------------------------------------------------


def test_eval_if_then_branch():
    # TRM = [A] has +F → then branch: unify INR[1] (which is {F:"-"}) with [+G]
    # {F:"-"} has no -G, so +G can be added → {F:"-", G:"+"}
    result = evaluate(
        parse("(if (models? TRM [[+F]]) (concat (unify (nth 1 INR) [+G])) INR)"),
        [{"F": "-"}],
        [A],
        ALPHABET,
    )
    assert result == [{"F": "-", "G": "+"}]


def test_eval_if_else_branch():
    # TRM = [D] which has -F, so else branch taken: return INR unchanged
    result = evaluate(
        parse("(if (models? TRM [[+F]]) (concat (unify (nth 1 INR) [+G])) INR)"),
        [D],
        [D],
        ALPHABET,
    )
    assert result == [D]


# ---------------------------------------------------------------------------
# apply_rule — Dir="R" (trigger to the right)
# ---------------------------------------------------------------------------

# Rule: assimilate -F segment to +F when followed by a +F segment.
#   Assimilation that overrides an existing value uses subtract+unify:
#   subtract the old value first, then unify with the new one.
#   INR = [[-F]], TRM = [[+F]], Dir = R
#   Out: "(concat (unify (subtract (nth 1 INR) [-F]) [+F]))"
ASSIMILATION_R = Rule(
    Id="assim_R",
    Inr=[["-F"]],
    Trm=[["+F"]],
    Dir="R",
    Out="(concat (unify (subtract (nth 1 INR) [-F]) [+F]))",
)
ASSIMILATION_R_AST = parse(ASSIMILATION_R.Out)


def test_apply_rule_single_match_right():
    # C = {-F, +G} before A = {+F, +G} → subtract -F → {+G}, unify +F → {+F, +G}
    word = [C, A]
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, word, ALPHABET)
    assert result == [{"F": "+", "G": "+"}, A]


def test_apply_rule_no_trigger_right():
    # C before C — no +F trigger on right — no change
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, [C, C], ALPHABET)
    assert result == [C, C]


def test_apply_rule_no_target_right():
    # A before A — A has +F, not -F — no target match — no change
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, [A, A], ALPHABET)
    assert result == [A, A]


def test_apply_rule_multiple_matches_right():
    # [C, A, C, A]: positions 0 and 2 are targets with +F trigger to the right
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, [C, A, C, A], ALPHABET)
    assert result == [{"F": "+", "G": "+"}, A, {"F": "+", "G": "+"}, A]


def test_apply_rule_word_unchanged_when_no_match():
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, [A, B, A], ALPHABET)
    assert result == [A, B, A]


# ---------------------------------------------------------------------------
# apply_rule — Dir="L" (trigger to the left)
# ---------------------------------------------------------------------------

# Rule: assimilate -F segment to +F when preceded by a +F segment
ASSIMILATION_L = Rule(
    Id="assim_L",
    Inr=[["-F"]],
    Trm=[["+F"]],
    Dir="L",
    Out="(concat (unify (subtract (nth 1 INR) [-F]) [+F]))",
)
ASSIMILATION_L_AST = parse(ASSIMILATION_L.Out)


def test_apply_rule_single_match_left():
    # A = {+F, +G} precedes C = {-F, +G} → subtract -F → {+G}, unify +F → {+F, +G}
    word = [A, C]
    result = apply_rule(ASSIMILATION_L, ASSIMILATION_L_AST, word, ALPHABET)
    assert result == [A, {"F": "+", "G": "+"}]


def test_apply_rule_no_trigger_left():
    # C before C — no +F trigger on left — no change
    result = apply_rule(ASSIMILATION_L, ASSIMILATION_L_AST, [C, C], ALPHABET)
    assert result == [C, C]


def test_apply_rule_at_start_no_trigger_left():
    # C at position 0 has no left context — no change
    result = apply_rule(ASSIMILATION_L, ASSIMILATION_L_AST, [C, A], ALPHABET)
    assert result == [C, A]


# ---------------------------------------------------------------------------
# apply_rule — multi-segment INR
# ---------------------------------------------------------------------------

# Rule: assimilate 2-segment window [-F, -F] to +F when preceded by a +F segment
ASSIMILATION_2SEG = Rule(
    Id="assim_2seg",
    Inr=[["-F"], ["-F"]],
    Trm=[["+F"]],
    Dir="L",
    Out="(concat (unify (subtract (nth 1 INR) [-F]) [+F]) (unify (subtract (nth 2 INR) [-F]) [+F]))",
)
ASSIMILATION_2SEG_AST = parse(ASSIMILATION_2SEG.Out)


def test_apply_rule_two_segment_inr():
    # A, C, D → A triggers, [C,D] are targets → [{+F,+G}, {+F,-G}]
    word = [A, C, D]
    result = apply_rule(ASSIMILATION_2SEG, ASSIMILATION_2SEG_AST, word, ALPHABET)
    assert result == [A, {"F": "+", "G": "+"}, {"F": "+", "G": "-"}]


def test_apply_rule_two_segment_inr_no_match():
    # only one -F segment — window [C, A] doesn't model [[-F],[-F]]
    result = apply_rule(ASSIMILATION_2SEG, ASSIMILATION_2SEG_AST, [A, C, A], ALPHABET)
    assert result == [A, C, A]


# ---------------------------------------------------------------------------
# apply_rule — conditional output
# ---------------------------------------------------------------------------

# Rule: if TRM has +G, add +G to target (only works when target lacks -G);
#       otherwise return INR unchanged.
# Use D = {-F, -G} as target — lacks -G, so unify +G succeeds.
CONDITIONAL = Rule(
    Id="cond",
    Inr=[["-F"]],
    Trm=[["+F"]],
    Dir="R",
    Out="(if (in? (nth 1 TRM) [+G]) (concat (unify (subtract (nth 1 INR) [-G]) [+G])) (concat INR))",
)
CONDITIONAL_AST = parse(CONDITIONAL.Out)


def test_apply_rule_conditional_then():
    # D = {-F, -G} before A = {+F, +G}: trigger has +G → unify D with +G → {-F, +G} = C
    result = apply_rule(CONDITIONAL, CONDITIONAL_AST, [D, A], ALPHABET)
    assert result == [{"F": "-", "G": "+"}, A]


def test_apply_rule_conditional_else():
    # D before B (+F, -G): trigger lacks +G → else branch → INR unchanged
    result = apply_rule(CONDITIONAL, CONDITIONAL_AST, [D, B], ALPHABET)
    assert result == [D, B]


# ---------------------------------------------------------------------------
# apply_rule — BOS/EOS boundary pseudo-segments
# ---------------------------------------------------------------------------

from snc2fst.alphabet import BOS_SEGMENT, EOS_SEGMENT

# Rule: assimilate the word-initial segment if it is -F.
#   INR = [[+BOS], [-F]], Trm = [], Dir = L (unconditional; BOS in target window)
WORD_INITIAL_TARGET = Rule(
    Id="word_initial",
    Inr=[["+BOS"], ["-F"]],
    Trm=[],
    Dir="L",
    Out="(concat (nth 1 INR) (unify (subtract (nth 2 INR) [-F]) [+F]))",
)
WORD_INITIAL_TARGET_AST = parse(WORD_INITIAL_TARGET.Out)

# Rule: assimilate -F segment to +F when the nearest left trigger is BOS
#   (i.e. there is no non-BOS segment between it and the start of the word).
#   INR = [[-F]], Trm = [[+BOS]], Dir = L
WORD_INITIAL_TRIGGER = Rule(
    Id="word_initial_trm",
    Inr=[["-F"]],
    Trm=[["+BOS"]],
    Dir="L",
    Out="(concat (unify (subtract (nth 1 INR) [-F]) [+F]))",
)
WORD_INITIAL_TRIGGER_AST = parse(WORD_INITIAL_TRIGGER.Out)

# Rule: word-final deletion — target is [-F] immediately before EOS.
#   INR = [[-F], [+EOS]], Trm = [], Dir = L (unconditional)
WORD_FINAL_DELETION = Rule(
    Id="word_final_del",
    Inr=[["-F"], ["+EOS"]],
    Trm=[],
    Dir="L",
    Out="(nth 2 INR)",
)
WORD_FINAL_DELETION_AST = parse(WORD_FINAL_DELETION.Out)

# Rule: epenthesis before EOS — insert 'A' between last segment and EOS.
#   INR = [[], [+EOS]], Trm = [], Dir = L (unconditional)
EPENTHESIS_WORD_FINAL = Rule(
    Id="epen_final",
    Inr=[[], ["+EOS"]],
    Trm=[],
    Dir="L",
    Out="(concat (nth 1 INR) 'A (nth 2 INR))",
)
EPENTHESIS_WORD_FINAL_AST = parse(EPENTHESIS_WORD_FINAL.Out)


def test_apply_rule_bos_in_inr_matches_word_initial():
    # BOS + C at the start: C is -F, window [BOS, C] matches → assimilate C
    result = apply_rule(WORD_INITIAL_TARGET, WORD_INITIAL_TARGET_AST, [C], ALPHABET)
    assert result == [{"F": "+", "G": "+"}]


def test_apply_rule_bos_in_inr_no_match_non_initial():
    # [A, C]: C is at position 1, so window [BOS, C] does not occur → unchanged
    result = apply_rule(WORD_INITIAL_TARGET, WORD_INITIAL_TARGET_AST, [A, C], ALPHABET)
    assert result == [A, C]


def test_apply_rule_bos_trigger_all_minus_f_assimilated():
    # [C, D]: both are -F; BOS is always to the left of any segment → both assimilate
    result = apply_rule(WORD_INITIAL_TRIGGER, WORD_INITIAL_TRIGGER_AST, [C, D], ALPHABET)
    assert result == [{"F": "+", "G": "+"}, {"F": "+", "G": "-"}]


def test_apply_rule_eos_in_inr_deletion():
    # [C, D]: D is -F immediately before EOS → D is deleted
    result = apply_rule(WORD_FINAL_DELETION, WORD_FINAL_DELETION_AST, [C, D], ALPHABET)
    assert result == [C]


def test_apply_rule_eos_in_inr_deletion_only_final():
    # [D, A]: A is +F so not a target; D is not word-final → nothing deleted
    result = apply_rule(WORD_FINAL_DELETION, WORD_FINAL_DELETION_AST, [D, A], ALPHABET)
    assert result == [D, A]


def test_apply_rule_epenthesis_before_eos():
    # [B]: insert A before EOS → [B, A]
    result = apply_rule(EPENTHESIS_WORD_FINAL, EPENTHESIS_WORD_FINAL_AST, [B], ALPHABET)
    assert result == [B, A]


def test_apply_rule_boundaries_stripped_from_output():
    # BOS/EOS should never appear in the returned word
    result = apply_rule(ASSIMILATION_R, ASSIMILATION_R_AST, [C, A], ALPHABET)
    assert BOS_SEGMENT not in result
    assert EOS_SEGMENT not in result


def test_apply_rule_boundary_position_error():
    # A rule that swaps BOS and the following segment puts BOS at position 1 — illegal.
    # INR = [[+BOS], []], Trm = [], Out = (concat (nth 2 INR) (nth 1 INR))
    # Bracketed [BOS, A, EOS]: window at 0 is [BOS, A] → output [A, BOS] → BOS not at 0.
    bad_rule = Rule(
        Id="bad",
        Inr=[["+BOS"], []],
        Trm=[],
        Dir="L",
        Out="(concat (nth 2 INR) (nth 1 INR))",
    )
    bad_ast = parse(bad_rule.Out)
    with pytest.raises(EvalError, match="BOS boundary ended up at position"):
        apply_rule(bad_rule, bad_ast, [A], ALPHABET)
