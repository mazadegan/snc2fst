"""Tests for compiler.py.

Uses a four-segment toy language with three features (voc, nas, lab):

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
"""

import pytest
import pynini

from snc2fst.compiler import CompileError, compile_rule
from snc2fst.evaluator import apply_rule
from snc2fst import dsl
from snc2fst.models import Rule

# ---------------------------------------------------------------------------
# Toy alphabet
# ---------------------------------------------------------------------------

ALPHABET = {
    "a": {"voc": "+", "nas": "-", "lab": "-"},
    "m": {"voc": "-", "nas": "+", "lab": "+"},
    "b": {"voc": "-", "nas": "-", "lab": "+"},
    "n": {"voc": "-", "nas": "+", "lab": "-"},
    "p": {"voc": "-", "nas": "-", "lab": "-"},
}

# ---------------------------------------------------------------------------
# Transduction helpers
# ---------------------------------------------------------------------------

def _transduce(fst: pynini.Fst, seg_names: list[str]) -> list[str]:
    """Run the FST on a list of segment names; return output as list of names."""
    sym = fst.input_symbols()
    output_sym = fst.output_symbols()
    one = pynini.Weight.one("tropical")

    # Build linear acceptor
    lin = pynini.Fst()
    s = lin.add_state()
    lin.set_start(s)
    for name in seg_names:
        t = lin.add_state()
        lin.add_arc(s, pynini.Arc(sym.find(name), sym.find(name), one, t))
        s = t
    lin.set_final(s, one)

    composed = pynini.compose(lin, fst)
    if composed.start() == -1:
        raise ValueError(f"FST produced no output for input {seg_names!r}")

    # Greedy traversal: always prefer arcs that consume real input (ilabel != 0)
    # over epsilon arcs (ilabel == 0, i.e. flush arcs). Epsilon arcs are only
    # taken when no real arc is available, which is exactly end-of-input.
    result = []
    state = composed.start()
    seen: set[int] = set()
    while state != -1 and state not in seen:
        seen.add(state)
        arcs = list(composed.arcs(state))
        if not arcs:
            break
        real = [a for a in arcs if a.ilabel != 0]
        arc = real[0] if real else arcs[0]
        if arc.olabel != 0:
            result.append(output_sym.find(arc.olabel))
        state = arc.nextstate
    return result


def _segs(word_str: str) -> list[str]:
    """Tokenize a space-separated segment string."""
    return word_str.split()


_REV = {frozenset(seg.items()): name for name, seg in ALPHABET.items()}


def _eval_ref(rule: Rule, inp: list[str]) -> list[str]:
    """Run the reference evaluator; return output as list of segment names."""
    out_ast = dsl.parse(rule.Out)
    in_word = [dict(ALPHABET[s]) for s in inp]
    out_word = apply_rule(rule, out_ast, in_word, ALPHABET)
    return [_REV[frozenset(seg.items())] for seg in out_word]


def _assert_agrees(rule: Rule, inputs: list[list[str]]) -> None:
    """Compile rule to FST and check it agrees with the reference evaluator.

    For Dir=R rules, compile_rule returns the left-to-right FST T_L that
    encodes reversed semantics.  We feed reversed input and reverse the output
    to recover the correct surface form.
    """
    fst = compile_rule(rule, ALPHABET)
    dir_r = rule.Dir == "R"
    for inp in inputs:
        ref = _eval_ref(rule, inp)
        if dir_r:
            got = list(reversed(_transduce(fst, list(reversed(inp)))))
        else:
            got = _transduce(fst, inp)
        assert got == ref, (
            f"Mismatch on input {inp!r}: FST={got!r}, ref={ref!r}"
        )


# ---------------------------------------------------------------------------
# n=1, m=1, Dir=L  — nasalization before nasal
#
# Rule: [+voc] → [+nas] / __ [+nas]
# Inr=[+voc], Trm=[+nas], Dir=L, Out=(unify (nth 1 INR) [+nas])
# ---------------------------------------------------------------------------

NASAL_L = Rule(
    Id="nasal_L",
    Inr=[["+voc"]],
    Trm=[["+nas"]],
    Dir="L",
    Out="(unify (nth 1 INR) [+nas])",
)


def test_nasal_l_no_trigger():
    # No nasal in input — vowel unchanged
    _assert_agrees(NASAL_L, [_segs("a b a")])


def test_nasal_l_single():
    # a before m: a → nasalized-a (a+nas = a with +nas, but a has -nas, so unify adds +nas)
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
    # Nasal first, then vowel — vowel has no nasal to its left
    _assert_agrees(NASAL_L, [_segs("m a")])


def test_nasal_l_only_trigger():
    _assert_agrees(NASAL_L, [_segs("m n")])


# ---------------------------------------------------------------------------
# n=1, m=1, Dir=R  — nasalization after nasal (trigger to the right)
#
# Rule: [+voc] → [+nas] / [+nas] __
# Inr=[+voc], Trm=[+nas], Dir=R, Out=(unify (nth 1 INR) [+nas])
# ---------------------------------------------------------------------------

NASAL_R = Rule(
    Id="nasal_R",
    Inr=[["+voc"]],
    Trm=[["+nas"]],
    Dir="R",
    Out="(unify (nth 1 INR) [+nas])",
)


def test_nasal_r_single():
    _assert_agrees(NASAL_R, [_segs("m a")])


def test_nasal_r_no_trigger():
    _assert_agrees(NASAL_R, [_segs("b a p")])


def test_nasal_r_trigger_after():
    # Nasal follows — vowel unchanged (trigger is to the left, not right)
    _assert_agrees(NASAL_R, [_segs("a m")])


def test_nasal_r_multiple():
    _assert_agrees(NASAL_R, [_segs("n a m a"), _segs("m a a n")])


# ---------------------------------------------------------------------------
# n=1, m=1 — target is also a potential trigger (harmony spread)
#
# Rule: [-voc] → [+lab] / __ [+lab]
# A non-labial consonant becomes labial when immediately before a labial.
# Inr=[-voc], Trm=[+lab], Dir=L, Out=(unify (nth 1 INR) [+lab])
# ---------------------------------------------------------------------------

LAB_HARMONY = Rule(
    Id="lab_harmony",
    Inr=[["-voc"]],
    Trm=[["+lab"]],
    Dir="L",
    Out="(unify (nth 1 INR) [+lab])",
)


def test_lab_harmony_single():
    # p before b: p → b (p gains +lab)
    _assert_agrees(LAB_HARMONY, [_segs("p b")])


def test_lab_harmony_trigger_is_also_target():
    # b is both Inr and Trm; reading b while already in trigger state → self-retrigger
    _assert_agrees(LAB_HARMONY, [_segs("n b b")])


def test_lab_harmony_chain():
    _assert_agrees(LAB_HARMONY, [_segs("n p b"), _segs("p n b")])


def test_lab_harmony_no_trigger():
    _assert_agrees(LAB_HARMONY, [_segs("n p n")])


# ---------------------------------------------------------------------------
# n=1, m=0  — unconditional nasalization of labials
#
# Rule: [+lab] → [+nas] / (unconditionally)
# Inr=[+lab], Trm=[], Dir=L, Out=(unify (nth 1 INR) [+nas])
# ---------------------------------------------------------------------------

NASALIZE_LAB = Rule(
    Id="nas_lab",
    Inr=[["+lab"]],
    Trm=[],
    Dir="L",
    Out="(unify (nth 1 INR) [+nas])",
)


def test_nasalize_lab_single():
    # b → m  (b gains +nas, becoming m)
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
# n=2, m=0, Dir=L — metathesis: swap adjacent labials
#
# Rule: [+lab][-voc] [−lab][-voc] → swap
# Inr=[[+lab][-voc], [-lab][-voc]], Trm=[], Dir=L
# Out=(concat (nth 2 INR) (nth 1 INR))
# ---------------------------------------------------------------------------

METATHESIS_L = Rule(
    Id="meta_L",
    Inr=[["+lab", "-voc"], ["-lab", "-voc"]],
    Trm=[],
    Dir="L",
    Out="(concat (nth 2 INR) (nth 1 INR))",
)


def test_metathesis_l_single():
    # b n → n b
    _assert_agrees(METATHESIS_L, [_segs("b n")])


def test_metathesis_l_no_match():
    # n b doesn't match [+lab][-lab] (n is -lab)
    _assert_agrees(METATHESIS_L, [_segs("n b")])


def test_metathesis_l_with_context():
    _assert_agrees(METATHESIS_L, [_segs("a b n a")])


def test_metathesis_l_greedy():
    # bnn: b+n match first, leaving n; no second match
    _assert_agrees(METATHESIS_L, [_segs("b n n")])


def test_metathesis_l_non_overlapping():
    # b n b n — two non-overlapping matches
    _assert_agrees(METATHESIS_L, [_segs("b n b n")])


# ---------------------------------------------------------------------------
# n=2, m=0, Dir=R — same metathesis, right-to-left scan
# ---------------------------------------------------------------------------

METATHESIS_R = Rule(
    Id="meta_R",
    Inr=[["+lab", "-voc"], ["-lab", "-voc"]],
    Trm=[],
    Dir="R",
    Out="(concat (nth 2 INR) (nth 1 INR))",
)


def test_metathesis_r_single():
    _assert_agrees(METATHESIS_R, [_segs("b n")])


def test_metathesis_r_scan_direction():
    # b n n: Dir=R scans right-to-left, matches the rightmost b+n first
    _assert_agrees(METATHESIS_R, [_segs("b n n")])


def test_metathesis_r_agrees_with_l_when_unambiguous():
    # Single match — both directions agree
    _assert_agrees(METATHESIS_R, [_segs("a b n a")])


# ---------------------------------------------------------------------------
# n=2, m=0  — epenthesis: insert 'p' between two consecutive nasals
#
# Rule: [+nas][+nas] → [+nas] p [+nas]
# Inr=[[+nas],[+nas]], Trm=[], Dir=L
# Out=(concat (nth 1 INR) 'p (nth 2 INR))
# ---------------------------------------------------------------------------

EPENTHESIS = Rule(
    Id="epen",
    Inr=[["+nas"], ["+nas"]],
    Trm=[],
    Dir="L",
    Out="(concat (nth 1 INR) 'p (nth 2 INR))",
)


def test_epenthesis_single():
    # m n → m p n
    _assert_agrees(EPENTHESIS, [_segs("m n")])


def test_epenthesis_no_match():
    _assert_agrees(EPENTHESIS, [_segs("m b n")])


def test_epenthesis_multiple():
    _assert_agrees(EPENTHESIS, [_segs("m n n m")])


def test_epenthesis_with_context():
    _assert_agrees(EPENTHESIS, [_segs("a m n a")])


def test_epenthesis_greedy():
    # m m m: greedy L matches m+m first → m p m, remaining m is unbuffered
    _assert_agrees(EPENTHESIS, [_segs("m m m")])


# ---------------------------------------------------------------------------
# CompileError for unsupported (n, m) pairs
# ---------------------------------------------------------------------------

def test_compile_error_n0():
    rule = Rule(Id="r", Inr=[], Trm=[], Dir="L", Out="INR")
    with pytest.raises(CompileError):
        compile_rule(rule, ALPHABET)


def test_compile_error_n2_m1():
    rule = Rule(Id="r", Inr=[["+voc"], ["+voc"]], Trm=[["+nas"]], Dir="L", Out="INR")
    with pytest.raises(CompileError):
        compile_rule(rule, ALPHABET)


def test_compile_error_n1_m2():
    rule = Rule(
        Id="r", Inr=[["+voc"]], Trm=[["+nas"], ["+nas"]], Dir="L", Out="INR"
    )
    with pytest.raises(CompileError):
        compile_rule(rule, ALPHABET)
