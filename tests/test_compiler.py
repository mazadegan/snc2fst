"""Tests for compiler.py.

Uses a five-segment toy language with three features (voc, nas, lab):

  Segment  voc  nas  lab
  -------  ---  ---  ---
  a        +    -    -     (oral vowel)
  m        -    +    +     (nasal labial)
  b        -    -    +     (oral labial)
  n        -    +    -     (nasal non-labial)
  p        -    -    -     (oral non-labial)

Natural classes used in tests:
  [+voc]        = {a}
  [-voc]        = {m, b, n, p}
  [+nas]        = {m, n}
  [-nas]        = {a, b, p}
  [+lab]        = {m, b}
  [-lab]        = {n, p, a}
  [+nas +lab]   = {m}
  [-nas -lab]   = {p}
  [*nas]        = {m, n, a, b, p}  (union of [+nas] and [-nas] = all segments)
"""

# Rule validators convert list[list[str]] → list[list[tuple[str, str]]] at
# runtime; Pyright cannot see through Pydantic's field_validator transforms.
# Mypy also has similar issues.
# pyright: reportArgumentType=false
# mypy: ignore-errors

import warnings

import logical_phonology as lp
import pytest

from snc2fst import dsl
from snc2fst.compiler import (
    CompileError,
    compile_rule,
    compute_alphabets,
    transduce,
)
from snc2fst.evaluator import apply_rule
from snc2fst.models import Rule

pynini = pytest.importorskip("pynini", reason="pynini not installed")

# ---------------------------------------------------------------------------
# Toy feature system and inventory
# ---------------------------------------------------------------------------

_FS = lp.FeatureSystem(frozenset(["voc", "nas", "lab"]))

_INV = _FS.inventory(
    {
        "a": _FS.segment({"voc": lp.POS, "nas": lp.NEG, "lab": lp.NEG}),
        "m": _FS.segment({"voc": lp.NEG, "nas": lp.POS, "lab": lp.POS}),
        "b": _FS.segment({"voc": lp.NEG, "nas": lp.NEG, "lab": lp.POS}),
        "n": _FS.segment({"voc": lp.NEG, "nas": lp.POS, "lab": lp.NEG}),
        "p": _FS.segment({"voc": lp.NEG, "nas": lp.NEG, "lab": lp.NEG}),
    }
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _segs(word_str: str) -> list[str]:
    """Tokenize a space-separated segment string."""
    return word_str.split()


def _eval_ref(rule: Rule, inp: list[str]) -> list[str]:
    """
    Run the reference evaluator; return output as a list of segment names.
    """
    out_ast = dsl.parse(rule.Out)
    cnd_ast = dsl.parse(rule.Cnd) if rule.Cnd is not None else None
    in_word = _FS.word([_INV[s] for s in inp])
    out_word = apply_rule(rule, out_ast, in_word, _FS, _INV, cnd_ast)
    return [_INV.name_of(seg) for seg in out_word]


def _assert_agrees(rule: Rule, inputs: list[list[str]]) -> None:
    """
    Compile rule to FST and check it agrees with the reference evaluator.
    """
    fst = compile_rule(rule, _FS, _INV)
    for inp in inputs:
        ref = _eval_ref(rule, inp)
        got = transduce(fst, rule, inp)
        assert got == ref, (
            f"Mismatch on input {inp!r}: FST={got!r}, ref={ref!r}"
        )


def _assert_agrees_no_eps(
    rule: Rule,
    inputs: list[list[str]],
) -> None:
    """Compile rule in no-epsilon-input mode and compare with evaluator."""
    fst = compile_rule(rule, _FS, _INV, no_epsilon_input_arcs=True)
    for inp in inputs:
        ref = _eval_ref(rule, inp)
        got = transduce(fst, rule, inp)
        assert got == ref, (
            f"Mismatch on input {inp!r}: FST={got!r}, ref={ref!r}"
        )


def _count_eps_input_arcs(fst) -> int:
    count = 0
    for state in fst.states():
        for arc in fst.arcs(state):
            if arc.ilabel == 0:
                count += 1
    return count


def _assert_agrees_bounded(rule: Rule, inputs: list[list[str]]) -> None:
    """
    Like _assert_agrees but brackets input with ⋉/⋊ for boundary-aware rules.
    """
    fst = compile_rule(rule, _FS, _INV)
    for inp in inputs:
        ref = _eval_ref(rule, inp)
        bracketed = ["⋉"] + inp + ["⋊"]
        raw = transduce(fst, rule, bracketed)
        got = [s for s in raw if s not in ("⋉", "⋊")]
        assert got == ref, (
            f"Mismatch on input {inp!r}: FST={got!r}, ref={ref!r}"
        )


# ---------------------------------------------------------------------------
# m=1, n=1, Dir=L  — nasalization before nasal
#
# Rule: [+voc] → [+nas] / __ [+nas]
# ---------------------------------------------------------------------------

NASAL_L = Rule(
    Id="nasal_L",
    Inr=[["+voc"]],
    Trm=[["+nas"]],
    Dir="L",
    Out="(unify INR[1] {+nas})",
)


def test_nasal_l_no_trigger():
    _assert_agrees(NASAL_L, [_segs("a b a")])


def test_nasal_l_single():
    _assert_agrees(NASAL_L, [_segs("a m")])


def test_nasal_l_multiple():
    _assert_agrees(NASAL_L, [_segs("a m a n"), _segs("a a m")])


def test_nasal_l_no_vowel():
    _assert_agrees(NASAL_L, [_segs("b m n p")])


def test_nasal_l_empty():
    _assert_agrees(NASAL_L, [[]])


def test_nasal_l_match_at_start():
    _assert_agrees(NASAL_L, [_segs("a n b")])


def test_nasal_l_trigger_at_start():
    _assert_agrees(NASAL_L, [_segs("m a")])


def test_nasal_l_only_trigger():
    _assert_agrees(NASAL_L, [_segs("m n")])


# ---------------------------------------------------------------------------
# m=1, n=1, Dir=R  — nasalization after nasal (trigger to the right)
#
# Rule: [+voc] → [+nas] / [+nas] __
# ---------------------------------------------------------------------------

NASAL_R = Rule(
    Id="nasal_R",
    Inr=[["+voc"]],
    Trm=[["+nas"]],
    Dir="R",
    Out="(unify INR[1] {+nas})",
)


def test_nasal_r_single():
    _assert_agrees(NASAL_R, [_segs("m a")])


def test_nasal_r_no_trigger():
    _assert_agrees(NASAL_R, [_segs("b a p")])


def test_nasal_r_trigger_after():
    _assert_agrees(NASAL_R, [_segs("a m")])


def test_nasal_r_multiple():
    _assert_agrees(NASAL_R, [_segs("n a m a"), _segs("m a a n")])


# ---------------------------------------------------------------------------
# m=1, n=1 — target is also a potential trigger (harmony spread)
#
# Rule: [-voc] → [+lab] / __ [+lab]
# ---------------------------------------------------------------------------

LAB_HARMONY = Rule(
    Id="lab_harmony",
    Inr=[["-voc"]],
    Trm=[["+lab"]],
    Dir="L",
    Out="(unify INR[1] {+lab})",
)


def test_lab_harmony_single():
    _assert_agrees(LAB_HARMONY, [_segs("p b")])


def test_lab_harmony_trigger_is_also_target():
    _assert_agrees(LAB_HARMONY, [_segs("n b b")])


def test_lab_harmony_chain():
    _assert_agrees(LAB_HARMONY, [_segs("n p b"), _segs("p n b")])


def test_lab_harmony_no_trigger():
    _assert_agrees(LAB_HARMONY, [_segs("n p n")])


# ---------------------------------------------------------------------------
# n=1, m=0  — unconditional nasalization of labials
#
# Rule: [+lab] → [+nas] (unconditionally)
# ---------------------------------------------------------------------------

NASALIZE_LAB = Rule(
    Id="nas_lab",
    Inr=[["+lab"]],
    Trm=[],
    Dir="L",
    Out="(unify INR[1] {+nas})",
)


def test_nasalize_lab_single():
    _assert_agrees(NASALIZE_LAB, [_segs("b")])


def test_nasalize_lab_multiple():
    _assert_agrees(NASALIZE_LAB, [_segs("b m b")])


def test_nasalize_lab_none():
    _assert_agrees(NASALIZE_LAB, [_segs("a n p")])


def test_nasalize_lab_empty():
    _assert_agrees(NASALIZE_LAB, [[]])


def test_nasalize_lab_edges():
    _assert_agrees(NASALIZE_LAB, [_segs("b a b"), _segs("b n"), _segs("n b")])


# ---------------------------------------------------------------------------
# n=2, m=0, Dir=L — metathesis: swap adjacent labial + non-labial consonants
#
# Rule: [+lab -voc][-lab -voc] → swap
# ---------------------------------------------------------------------------

METATHESIS_L = Rule(
    Id="meta_L",
    Inr=[["+lab", "-voc"], ["-lab", "-voc"]],
    Trm=[],
    Dir="L",
    Out="(INR[2] INR[1])",
)


def test_metathesis_l_single():
    _assert_agrees(METATHESIS_L, [_segs("b n")])


def test_metathesis_l_no_match():
    _assert_agrees(METATHESIS_L, [_segs("n b")])


def test_metathesis_l_with_context():
    _assert_agrees(METATHESIS_L, [_segs("a b n a")])


def test_metathesis_l_greedy():
    _assert_agrees(METATHESIS_L, [_segs("b n n")])


def test_metathesis_l_non_overlapping():
    _assert_agrees(METATHESIS_L, [_segs("b n b n")])


# ---------------------------------------------------------------------------
# n=2, m=0, Dir=R — same metathesis, right-to-left scan
# ---------------------------------------------------------------------------

METATHESIS_R = Rule(
    Id="meta_R",
    Inr=[["+lab", "-voc"], ["-lab", "-voc"]],
    Trm=[],
    Dir="R",
    Out="(INR[2] INR[1])",
)


def test_metathesis_r_single():
    _assert_agrees(METATHESIS_R, [_segs("b n")])


def test_metathesis_r_scan_direction():
    _assert_agrees(METATHESIS_R, [_segs("b n n")])


def test_metathesis_r_agrees_with_l_when_unambiguous():
    _assert_agrees(METATHESIS_R, [_segs("a b n a")])


# ---------------------------------------------------------------------------
# n=2, m=0  — epenthesis: insert 'p' between two consecutive nasals
#
# Rule: [+nas][+nas] → [+nas] p [+nas]
# ---------------------------------------------------------------------------

EPENTHESIS = Rule(
    Id="epen",
    Inr=[["+nas"], ["+nas"]],
    Trm=[],
    Dir="L",
    Out="(INR[1] &p INR[2])",
)


def test_epenthesis_single():
    _assert_agrees(EPENTHESIS, [_segs("m n")])


def test_epenthesis_no_match():
    _assert_agrees(EPENTHESIS, [_segs("m b n")])


def test_epenthesis_multiple():
    _assert_agrees(EPENTHESIS, [_segs("m n n m")])


def test_epenthesis_with_context():
    _assert_agrees(EPENTHESIS, [_segs("a m n a")])


def test_epenthesis_greedy():
    _assert_agrees(EPENTHESIS, [_segs("m m m")])


def test_epenthesis_no_eps_input_mode_matches_evaluator():
    _assert_agrees_no_eps(
        EPENTHESIS,
        [_segs("m n"), _segs("m b n"), _segs("m n n m"), _segs("m m m")],
    )


def test_epenthesis_no_eps_input_mode_has_no_eps_input_arcs():
    fst = compile_rule(EPENTHESIS, _FS, _INV, no_epsilon_input_arcs=True)
    assert _count_eps_input_arcs(fst) == 0


def test_epenthesis_no_eps_input_mode_uses_readable_seq_labels():
    fst = compile_rule(EPENTHESIS, _FS, _INV, no_epsilon_input_arcs=True)
    sym = fst.output_symbols()
    labels = [sym.find(i) for i in range(sym.num_symbols())]
    map_labels = [lbl for lbl in labels if lbl.startswith("__SEQMAP__:")]
    assert map_labels
    mapped_lhs: set[str] = set()
    for lbl in map_labels:
        payload = lbl[len("__SEQMAP__:") :]
        lhs, _sep, _rhs = payload.partition("=")
        mapped_lhs.add(lhs)

    seq_labels_used: set[str] = set()
    for state in fst.states():
        for arc in fst.arcs(state):
            if arc.olabel == 0:
                continue
            name = sym.find(arc.olabel)
            if name in mapped_lhs:
                seq_labels_used.add(name)

    assert seq_labels_used
    assert all("__SEQ__" not in lbl for lbl in seq_labels_used)
    assert all(ch not in lbl for lbl in seq_labels_used for ch in ":[]|")


# ---------------------------------------------------------------------------
# NaturalClassUnion via * wildcard
#
# Rule: [*nas -voc] → [+lab]  (make all consonants labial, regardless of
# nasality)
#
# [*nas -voc] matches any consonant (union of [+nas -voc] and [-nas -voc]),
# i.e. {m, b, n, p}.  The rule should labialize all consonants unconditionally.
# ---------------------------------------------------------------------------

LABIALIZE_CONS = Rule(
    Id="lab_cons",
    Inr=[["*nas", "-voc"]],
    Trm=[],
    Dir="L",
    Out="(unify INR[1] {+lab})",
)


def test_union_labialize_nasal_consonant():
    # m and n are [+nas -voc]; both should become [+lab]
    _assert_agrees(LABIALIZE_CONS, [_segs("n"), _segs("m")])


def test_union_labialize_oral_consonant():
    # b and p are [-nas -voc]; both should become [+lab]
    _assert_agrees(LABIALIZE_CONS, [_segs("b"), _segs("p")])


def test_union_labialize_mixed():
    _assert_agrees(LABIALIZE_CONS, [_segs("n p b m"), _segs("a n a p a")])


def test_union_vowel_unchanged():
    # 'a' is [+voc] so it does not match [*nas -voc] and should pass through
    _assert_agrees(LABIALIZE_CONS, [_segs("a"), _segs("a a a")])


def test_union_empty():
    _assert_agrees(LABIALIZE_CONS, [[]])


# NaturalClassUnion in Trm: trigger on any consonant (nasal or oral labial)
#
# Rule: [+voc] → [+nas] / __ [*nas +lab]
# Trigger is any [+lab] consonant (m or b), regardless of nasality.
# Equivalent to: nasalize vowel before any labial consonant.

NASAL_BEFORE_ANY_LAB = Rule(
    Id="nas_before_lab",
    Inr=[["+voc"]],
    Trm=[["*nas", "+lab"]],
    Dir="L",
    Out="(unify INR[1] {+nas})",
)


def test_union_trm_nasal_trigger():
    # 'a' before 'm' (nasal labial) — should nasalize
    _assert_agrees(NASAL_BEFORE_ANY_LAB, [_segs("a m")])


def test_union_trm_oral_trigger():
    # 'a' before 'b' (oral labial) — should also nasalize
    _assert_agrees(NASAL_BEFORE_ANY_LAB, [_segs("a b")])


def test_union_trm_no_trigger():
    # 'a' before 'n' or 'p' (non-labial) — should not nasalize
    _assert_agrees(NASAL_BEFORE_ANY_LAB, [_segs("a n"), _segs("a p")])


def test_union_trm_multiple():
    _assert_agrees(
        NASAL_BEFORE_ANY_LAB,
        [_segs("a b a m"), _segs("a n a b"), _segs("a m a n")],
    )


# ---------------------------------------------------------------------------
# Multi-rule sequential application
# ---------------------------------------------------------------------------


def _apply_chain(rules: list[Rule], inp: list[str]) -> list[str]:
    """Apply a sequence of rules via their FSTs, one at a time."""
    alphabets = compute_alphabets(rules, _FS, _INV)
    current = inp
    for rule, inv in zip(rules, alphabets):
        fst = compile_rule(rule, _FS, inv)
        current = transduce(fst, rule, current)
    return current


def _ref_chain(rules: list[Rule], inp: list[str]) -> list[str]:
    """Apply a sequence of rules via the reference evaluator."""
    current = _FS.word([_INV[s] for s in inp])
    for rule in rules:
        out_ast = dsl.parse(rule.Out)
        current = apply_rule(rule, out_ast, current, _FS, _INV)
    return [_INV.name_of(seg) for seg in current]


def _assert_chain(rules: list[Rule], inputs: list[list[str]]) -> None:
    for inp in inputs:
        ref = _ref_chain(rules, inp)
        got = _apply_chain(rules, inp)
        assert got == ref, (
            f"Chain mismatch on {inp!r}: FST={got!r}, ref={ref!r}"
        )


_CHAIN_LL = [
    Rule(
        Id="r1",
        Inr=[["+voc"]],
        Trm=[["+nas"]],
        Dir="L",
        Out="(unify INR[1] {+nas})",
    ),
    Rule(
        Id="r2",
        Inr=[["+nas"]],
        Trm=[],
        Dir="L",
        Out="(unify INR[1] {+lab})",
    ),
]


def test_chain_ll_basic():
    _assert_chain(_CHAIN_LL, [_segs("a m"), _segs("a n"), _segs("b a m")])


def test_chain_ll_no_trigger():
    _assert_chain(_CHAIN_LL, [_segs("a b p"), _segs("p a b")])


def test_chain_ll_feed():
    _assert_chain(_CHAIN_LL, [_segs("a n b"), _segs("b a n")])


_CHAIN_RR = [
    Rule(
        Id="r1",
        Inr=[["+voc"]],
        Trm=[["+nas"]],
        Dir="R",
        Out="(unify INR[1] {+nas})",
    ),
    Rule(
        Id="r2",
        Inr=[["+nas"]],
        Trm=[],
        Dir="R",
        Out="(unify INR[1] {+lab})",
    ),
]


def test_chain_rr_basic():
    _assert_chain(_CHAIN_RR, [_segs("m a"), _segs("n a b"), _segs("m a n")])


def test_chain_rr_no_trigger():
    _assert_chain(_CHAIN_RR, [_segs("a b p"), []])


_CHAIN_LR = [
    Rule(
        Id="r1",
        Inr=[["+voc"]],
        Trm=[["+nas"]],
        Dir="L",
        Out="(unify INR[1] {+nas})",
    ),
    Rule(
        Id="r2",
        Inr=[["+lab", "-voc"], ["-lab", "-voc"]],
        Trm=[],
        Dir="R",
        Out="(INR[2] INR[1])",
    ),
]


def test_chain_lr_no_interaction():
    _assert_chain(_CHAIN_LR, [_segs("a m b n"), _segs("b n p")])


def test_chain_lr_sequential():
    _assert_chain(_CHAIN_LR, [_segs("b n a m"), _segs("a m b n p")])


_CHAIN_RL = [
    Rule(
        Id="r1",
        Inr=[["+lab", "-voc"], ["-lab", "-voc"]],
        Trm=[],
        Dir="R",
        Out="(INR[2] INR[1])",
    ),
    Rule(
        Id="r2",
        Inr=[["+voc"]],
        Trm=[["+nas"]],
        Dir="L",
        Out="(unify INR[1] {+nas})",
    ),
]


def test_chain_rl_no_interaction():
    _assert_chain(_CHAIN_RL, [_segs("b n a p"), _segs("a m p")])


def test_chain_rl_sequential():
    _assert_chain(_CHAIN_RL, [_segs("b n a m"), _segs("a b n m")])


# ---------------------------------------------------------------------------
# CompileError for unsupported (n, m) pairs
# ---------------------------------------------------------------------------


def test_compile_error_m0():
    rule = Rule(Id="r", Inr=[], Trm=[], Dir="L", Out="INR")
    with pytest.raises(CompileError):
        compile_rule(rule, _FS, _INV)


def test_compile_error_m2_n1():
    rule = Rule(
        Id="r", Inr=[["+voc"], ["+voc"]], Trm=[["+nas"]], Dir="L", Out="INR"
    )
    with pytest.raises(CompileError):
        compile_rule(rule, _FS, _INV)


def test_compile_error_m1_n2():
    rule = Rule(
        Id="r",
        Inr=[["+voc"]],
        Trm=[["+nas"], ["+nas"]],
        Dir="L",
        Out="INR",
    )
    with pytest.raises(CompileError):
        compile_rule(rule, _FS, _INV)


# ---------------------------------------------------------------------------
# Boundary rules — BOS/EOS in Inr or Trm
# ---------------------------------------------------------------------------

NASALIZE_INITIAL = Rule(
    Id="nas_initial",
    Inr=[["+BOS"], ["+voc"]],
    Trm=[],
    Dir="L",
    Out="(INR[1] (unify INR[2] {+nas}))",
)

DELETE_FINAL_VOC = Rule(
    Id="del_final_voc",
    Inr=[["+voc"], ["+EOS"]],
    Trm=[],
    Dir="L",
    Out="INR[2]",
)

NASALIZE_BOS_TRIGGER = Rule(
    Id="nas_bos_trm",
    Inr=[["+voc"]],
    Trm=[["+BOS"]],
    Dir="L",
    Out="(unify INR[1] {+nas})",
)

NASALIZE_EOS_TRIGGER = Rule(
    Id="nas_eos_trm",
    Inr=[["+voc"]],
    Trm=[["+EOS"]],
    Dir="R",
    Out="(unify INR[1] {+nas})",
)


def test_boundary_nasalize_initial_only():
    _assert_agrees_bounded(
        NASALIZE_INITIAL,
        [
            _segs("a b"),
            _segs("b a"),
            _segs("a b a"),
            _segs("b m p"),
            [],
        ],
    )


def test_boundary_delete_final_vowel():
    _assert_agrees_bounded(
        DELETE_FINAL_VOC,
        [
            _segs("b a"),
            _segs("a b"),
            _segs("a b a"),
            _segs("a"),
            _segs("b m"),
            [],
        ],
    )


def test_boundary_bos_trigger_nasalizes_all_vowels():
    _assert_agrees_bounded(
        NASALIZE_BOS_TRIGGER,
        [
            _segs("a b a"),
            _segs("b a m"),
            _segs("b m p"),
            [],
        ],
    )


def test_boundary_eos_trigger_nasalizes_all_vowels():
    _assert_agrees_bounded(
        NASALIZE_EOS_TRIGGER,
        [
            _segs("a b a"),
            _segs("m a b"),
            _segs("b m p"),
            [],
        ],
    )


def test_compiled_fst_symbol_tables_are_named(tmp_path) -> None:
    fst = compile_rule(NASAL_L, _FS, _INV)
    path = tmp_path / "assim_prev.fst"
    fst.write(str(path))

    reloaded = pynini.Fst.read(str(path))
    assert reloaded.input_symbols().name() == "snc2fst_symbols"
    assert reloaded.output_symbols().name() == "snc2fst_symbols"


# ---------------------------------------------------------------------------
# Regressions: cases where the evaluator used to disagree with the FST
# ---------------------------------------------------------------------------


def test_overlap_resolves_from_the_dir_end():
    """Dir=R must fire the *right-most* of two overlapping INR windows.

    On 'm m m a' the windows at positions 1-2 and 2-3 overlap. Scanning
    against Dir=R reaches 2-3 first, so it fires and the buffer reset
    suppresses 1-2. The evaluator previously scanned left-to-right regardless
    of Dir and produced 'm m b m a', disagreeing with the FST.
    """
    rule = Rule(
        Id="ov",
        Inr=[["+nas"], ["+nas"]],
        Trm=[],
        Dir="R",
        Out="(INR[1:2] &b)",
    )
    assert _eval_ref(rule, _segs("m m m a")) == _segs("m m m b a")
    _assert_agrees(rule, [_segs("m m m a"), _segs("m m m m"), _segs("m m")])


def test_trigger_search_reads_the_input_not_the_rewritten_prefix():
    """Theta is computed from the input word, not from partial output.

    On 'b m b b' only the second segment is a +lab nasal trigger, so only the
    third segment should be nasalized. The evaluator previously searched the
    partially rewritten word, so the newly nasalized third segment acted as a
    trigger for the fourth, producing 'b m m m'.
    """
    rule = Rule(
        Id="fd",
        Inr=[["-nas", "-voc"]],
        Trm=[["+lab"]],
        Dir="L",
        Out="(unify (subtract INR[1] {-nas}) (proj TRM[1] (nas)))",
    )
    assert _eval_ref(rule, _segs("b m b b")) == _segs("b m m b")
    _assert_agrees(rule, [_segs("b m b b"), _segs("b m b m b")])


# ---------------------------------------------------------------------------
# Cnd licensing expression
# ---------------------------------------------------------------------------


def test_cnd_agrees_between_evaluator_and_fst_m1_n1():
    rule = Rule(
        Id="cnd11",
        Inr=[["-nas"]],
        Trm=[["+nas"]],
        Dir="L",
        Out="&p",
        Cnd="(in? TRM [{+lab}])",
    )
    _assert_agrees(
        rule,
        [_segs("b m b"), _segs("b n b"), _segs("a m b a"), _segs("b")],
    )


def test_cnd_agrees_between_evaluator_and_fst_m2_n0():
    """The window that fails Cnd slides, so an overlapping one can fire."""
    rule = Rule(
        Id="cnd20",
        Inr=[["+nas"], ["+nas"]],
        Trm=[],
        Dir="L",
        Out="(&b &b)",
        Cnd="(in? INR [{+nas} {+nas +lab}])",
    )
    _assert_agrees(
        rule,
        [_segs("n n m"), _segs("m m"), _segs("n n n"), _segs("n m n m")],
    )


def test_cnd_blocking_keeps_segments_out_of_the_alphabet():
    """Out is never evaluated on a pair Cnd rejects, so segments reachable
    only that way must not be added to the inventory."""
    rule = Rule(
        Id="cndalpha",
        Inr=[["+voc"]],
        Trm=[["+nas"]],
        Dir="L",
        Out="(unify (subtract INR[1] {-nas}) {+nas})",
        Cnd="(in? TRM [{+voc}])",  # no segment is both +nas and +voc
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compute_alphabets([rule], _FS, _INV)
    assert not caught, [str(x.message) for x in caught]


def test_dir_right_multisegment_output_chunk_is_not_reversed():
    """A Dir=R rule inserting material must not reverse the chunk.

    transduce reverses the whole output string for Dir=R, which would also
    reverse each emitted chunk internally. _compile_m_n0 compensated for this;
    _compile_m1_n1 did not, so '(INR[1] &a)' on 'm m m' produced
    'a m a m a m' instead of 'm a m a m a'.
    """
    rule = Rule(
        Id="chunk",
        Inr=[["-voc"]],
        Trm=[[]],
        Dir="R",
        Out="(INR[1] &a)",
    )
    assert _eval_ref(rule, _segs("m m m")) == _segs("m a m a m a")
    _assert_agrees(rule, [_segs("m m m"), _segs("b"), _segs("a b a")])
    _assert_agrees_no_eps(rule, [_segs("m m m"), _segs("a b a")])
