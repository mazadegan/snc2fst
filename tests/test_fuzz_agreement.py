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
# Outputs by INR-window length. The TRM-reading ones matter most: `proj`
# exercises the collapsing path of the terminator quotient, while a bare TRM
# collapses nothing, so both sides of that optimization get covered.
_OUTS_M1 = [
    "INR",
    "&p",
    "INR[1:0]",  # deletion
    "(INR[1] &a)",  # insertion
    "(unify INR[1] {+nas})",
    "(subtract INR[1] {+lab})",
]
_OUTS_M1_TRM = [
    "(unify INR[1] (proj TRM[1] (nas)))",  # lossy read: quotient collapses
    "(TRM[1] INR[1])",
    "(INR[1] TRM)",  # verbatim read: quotient collapses nothing
]
_OUTS_M2 = [
    "INR",
    "INR[1:0]",
    "(INR[2] INR[1])",  # metathesis
    "(INR[1] &a INR[2])",
    "INR[1:1]",
]
_OUTS_M2_TRM = [
    "(INR[2] TRM[1] INR[1])",
    "(unify INR[1] (proj TRM[1] (lab)))",
]
_OUTS_M3 = ["INR", "INR[1:2]", "(INR[3] INR[2] INR[1])"]
_CNDS = [None, "(in? INR [{+nas}])", "(in? TRM [{+lab}])"]

# (m, n) shapes to sweep. n costs more than m in state count, so the sweep is
# deliberately lopsided.
_SHAPES = [(1, 1), (2, 1), (1, 2), (2, 2), (3, 1), (1, 3), (3, 2), (2, 3)]

# Per (shape, Dir), how many well-formed rules to keep. Non-overlap rejects
# most generated rules, but at m=1 with Dir=R it rejects none (D_Right is
# empty), so those shapes would otherwise dominate the run.
_RULES_PER_SHAPE = 22


def _words(rng, count, max_len=6):
    out = [[], ["a"], ["m", "m", "m"], ["a", "b", "a", "b", "a"]]
    for _ in range(count):
        length = rng.randint(1, max_len)
        out.append([rng.choice(_NAMES) for _ in range(length)])
    return out


def _outs_for(m: int, n: int) -> list[str]:
    if m == 1:
        base = list(_OUTS_M1)
        return base + (_OUTS_M1_TRM if n else [])
    if m == 2:
        base = list(_OUTS_M2)
        return base + (_OUTS_M2_TRM if n else [])
    return list(_OUTS_M3)


def _rules(rng):
    """Well-formed rules across every supported shape, in a fixed order."""
    # n = 0: the unconditional-rewrite builder.
    for m in (1, 2, 3):
        for inr in itertools.product(_CLASSES, repeat=m):
            for direction in ("L", "R"):
                for out in _outs_for(m, 0):
                    cnds = _CNDS if m == 1 else [None]
                    for cnd in cnds:
                        rule = Rule(
                            Id="f",
                            Inr=list(inr),
                            Trm=[],
                            Dir=direction,
                            Out=out,
                            Cnd=cnd,
                        )
                        if not wellformedness_errors(rule):
                            yield rule

    # n >= 1: the general builder. Subsample the (Inr, Trm) pairs per shape so
    # no single shape dominates, then cross with every output.
    for m, n in _SHAPES:
        for direction in ("L", "R"):
            pairs = [
                (list(inr), list(trm))
                for inr in itertools.product(_CLASSES, repeat=m)
                for trm in itertools.product(_CLASSES, repeat=n)
                if not wellformedness_errors(
                    Rule(
                        Id="f",
                        Inr=list(inr),
                        Trm=list(trm),
                        Dir=direction,
                        Out="INR",
                    )
                )
            ]
            rng.shuffle(pairs)
            for inr, trm in pairs[:_RULES_PER_SHAPE]:
                for out in _outs_for(m, n):
                    for cnd in _CNDS:
                        yield Rule(
                            Id="f",
                            Inr=inr,
                            Trm=trm,
                            Dir=direction,
                            Out=out,
                            Cnd=cnd,
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
    words = _words(rng, count=11)

    checked = 0
    disagreements: list[str] = []

    for rule in _rules(rng):
        if wellformedness_errors(rule):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                inv = compute_alphabets([rule], _FS, _INV)[0]
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

    assert checked > 40000, f"fuzz coverage too thin: only {checked} cases"
    assert not disagreements, (
        f"{len(disagreements)} disagreement(s) out of {checked} cases; "
        f"first 10:\n" + "\n".join(disagreements[:10])
    )
