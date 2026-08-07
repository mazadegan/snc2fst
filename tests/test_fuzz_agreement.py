"""Randomized agreement between the evaluator and the compiled FST.

``apply_rule`` and the FST are two independent implementations of the same
relation, and the rest of the suite pins only hand-picked cases. This sweeps
the compilable rule shapes systematically instead.

It is deterministic (fixed seed and a fixed enumeration order), so a failure
reproduces exactly. Marked ``slow``; run the whole thing with
``pytest -m slow`` or ``pytest tests/test_fuzz_agreement.py``.
"""

import itertools
import random
import warnings

import logical_phonology as lp
import pytest

from snc2fst import dsl
from snc2fst.compiler import compile_rule, compute_alphabets, transduce
from snc2fst.errors import CompileError, EvalError
from snc2fst.evaluator import apply_rule
from snc2fst.models import Rule
from snc2fst.wellformed import wellformedness_errors

pynini = pytest.importorskip("pynini", reason="pynini not installed")

# pyright: reportArgumentType=false
# mypy: ignore-errors

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
_NAMES = ["a", "m", "b", "n", "p"]

# Single-feature classes, plus the universal class.
_CLASSES = [
    [],
    ["+voc"],
    ["-voc"],
    ["+nas"],
    ["-nas"],
    ["+lab"],
    ["-lab"],
]

# Outputs spanning identity, substitution, deletion, insertion and reordering.
_OUTS_M1 = [
    "INR",
    "&p",
    "INR[1:0]",  # deletion
    "(INR[1] &a)",  # insertion
    "(unify INR[1] {+nas})",
    "(subtract INR[1] {+lab})",
]
_OUTS_M2 = [
    "INR",
    "INR[1:0]",
    "(INR[2] INR[1])",  # metathesis
    "(INR[1] &a INR[2])",
    "INR[1:1]",
]
_CNDS = [None, "(in? INR [{+nas}])", "(in? TRM [{+lab}])"]


def _words(rng, count, max_len=5):
    out = [[], ["a"], ["m", "m", "m"]]
    for _ in range(count):
        length = rng.randint(1, max_len)
        out.append([rng.choice(_NAMES) for _ in range(length)])
    return out


def _rules():
    """Every compilable shape this backend supports, in a fixed order."""
    # m = 1, n = 1
    for inr, trm, direction, out, cnd in itertools.product(
        _CLASSES, _CLASSES, ("L", "R"), _OUTS_M1, _CNDS
    ):
        yield Rule(
            Id="f", Inr=[inr], Trm=[trm], Dir=direction, Out=out, Cnd=cnd
        )
    # m >= 1, n = 0
    for inr, direction, out, cnd in itertools.product(
        _CLASSES, ("L", "R"), _OUTS_M1, _CNDS
    ):
        yield Rule(Id="f", Inr=[inr], Trm=[], Dir=direction, Out=out, Cnd=cnd)
    for inr1, inr2, direction, out in itertools.product(
        _CLASSES, _CLASSES, ("L", "R"), _OUTS_M2
    ):
        yield Rule(
            Id="f", Inr=[inr1, inr2], Trm=[], Dir=direction, Out=out
        )


def _reference(rule, inv, names):
    out_ast = dsl.parse(rule.Out)
    cnd_ast = dsl.parse(rule.Cnd) if rule.Cnd is not None else None
    word = _FS.word([inv[s] for s in names])
    result = apply_rule(rule, out_ast, word, _FS, inv, cnd_ast)
    return [inv.name_of(seg) for seg in result]


@pytest.mark.slow
def test_evaluator_and_fst_agree_over_random_rules_and_words():
    rng = random.Random(20260807)
    words = _words(rng, count=12)

    checked = 0
    disagreements: list[str] = []

    for rule in _rules():
        if wellformedness_errors(rule):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # Give the rule an inventory closed under its own output, so
                # novel segments are nameable on both sides.
                inv = compute_alphabets([rule, rule], _FS, _INV)[1]
                fst = compile_rule(rule, _FS, inv)
        except CompileError:
            continue

        for names in words:
            try:
                ref = _reference(rule, inv, names)
            except (EvalError, ValueError):
                continue
            try:
                got = transduce(fst, rule, names)
            except ValueError:
                disagreements.append(
                    f"{rule.Inr}/{rule.Trm}/{rule.Dir}/{rule.Out}"
                    f"/{rule.Cnd} on {names}: FST produced no output, "
                    f"evaluator gave {ref}"
                )
                continue
            checked += 1
            if got != ref:
                disagreements.append(
                    f"{rule.Inr}/{rule.Trm}/{rule.Dir}/{rule.Out}"
                    f"/{rule.Cnd} on {names}: FST={got} evaluator={ref}"
                )

    assert checked > 5000, f"fuzz coverage too thin: only {checked} cases"
    assert not disagreements, (
        f"{len(disagreements)} disagreement(s) out of {checked} cases; "
        f"first 10:\n" + "\n".join(disagreements[:10])
    )
