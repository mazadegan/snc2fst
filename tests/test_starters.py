"""Smoke tests for all starter projects.

For each starter under templates/starters/, this verifies:
  1. config.toml parses into a valid GrammarConfig
  2. alphabet.csv loads without error
  3. tests.tsv loads without error
  4. Every test case passes when the rules are applied via apply_rule
  5. Every test case passes when rules are compiled to FSTs (skipped if pynini
     is not installed)
"""

import importlib.resources
import tomllib
import pytest

from snc2fst.models import GrammarConfig
from snc2fst.alphabet import load_alphabet, tokenize, word_to_str
from snc2fst.io import load_tests
from snc2fst.evaluator import apply_rule
from snc2fst import dsl


def _starter_names() -> list[str]:
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    return sorted(p.name for p in starters_dir.iterdir() if p.is_dir())


@pytest.mark.parametrize("name", _starter_names())
def test_starter_config_loads(name):
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    raw = tomllib.loads(starters_dir.joinpath(name, "config.toml").read_text())
    GrammarConfig(**raw)


@pytest.mark.parametrize("name", _starter_names())
def test_starter_alphabet_loads(name):
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    alphabet_resource = starters_dir.joinpath(name, "alphabet.csv")
    with importlib.resources.as_file(alphabet_resource) as path:
        alphabet = load_alphabet(path)
    assert len(alphabet) > 0


@pytest.mark.parametrize("name", _starter_names())
def test_starter_test_cases_pass(name):
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    d = starters_dir.joinpath(name)

    raw = tomllib.loads(d.joinpath("config.toml").read_text())
    config = GrammarConfig(**raw)

    with importlib.resources.as_file(d.joinpath("alphabet.csv")) as path:
        alphabet = load_alphabet(path)

    with importlib.resources.as_file(d.joinpath("tests.tsv")) as path:
        tests = load_tests(path)

    out_asts = {rule.Id: dsl.parse(rule.Out) for rule in config.rules}

    failures = []
    for inp_str, expected_str in tests:
        tokens = tokenize(inp_str, alphabet)
        word = [dict(alphabet[t]) for t in tokens]
        for rule in config.rules:
            word = apply_rule(rule, out_asts[rule.Id], word, alphabet)
        result_str = word_to_str(word, alphabet)
        if result_str != expected_str:
            failures.append(f"{inp_str} → {result_str!r} (expected {expected_str!r})")

    assert not failures, "Test case failures:\n" + "\n".join(failures)


def _transduce(fst, seg_names: list[str], pynini) -> list[str]:
    """Run an FST on a list of segment names and return the output segment names."""
    sym = fst.input_symbols()
    output_sym = fst.output_symbols()
    one = pynini.Weight.one("tropical")

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


@pytest.mark.parametrize("name", _starter_names())
def test_starter_fst_agrees(name):
    pynini = pytest.importorskip("pynini")
    from snc2fst.compiler import compile_rule

    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    d = starters_dir.joinpath(name)

    raw = tomllib.loads(d.joinpath("config.toml").read_text())
    config = GrammarConfig(**raw)

    with importlib.resources.as_file(d.joinpath("alphabet.csv")) as path:
        alphabet = load_alphabet(path)

    with importlib.resources.as_file(d.joinpath("tests.tsv")) as path:
        tests = load_tests(path)

    failures = []
    for inp_str, expected_str in tests:
        seg_names = tokenize(inp_str, alphabet)

        for rule in config.rules:
            fst = compile_rule(rule, alphabet)
            if rule.Dir == "R":
                seg_names = list(reversed(_transduce(fst, list(reversed(seg_names)), pynini)))
            else:
                seg_names = _transduce(fst, seg_names, pynini)

        result_str = "".join(seg_names)
        if result_str != expected_str:
            failures.append(f"{inp_str} → {result_str!r} (expected {expected_str!r})")

    assert not failures, "FST test case failures:\n" + "\n".join(failures)
