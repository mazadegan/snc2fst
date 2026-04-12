"""Integration tests for starter grammar projects.

For each starter in ``snc2fst/templates/starters/``, this test:
  1. Loads the config and alphabet.
  2. Computes per-rule inventories via ``compute_alphabets``.
  3. Compiles each rule to an FST.
  4. Runs every test case from ``tests.csv`` through both the reference
     evaluator and the compiled FST chain, asserting they agree.

Tests are parametrized by starter name so failures are clearly attributed.
"""

# mypy: ignore-errors

from importlib.resources import files
from pathlib import Path

import pytest

from snc2fst import dsl
from snc2fst.alphabet import load_alphabet
from snc2fst.compiler import compile_rule, compute_alphabets, transduce
from snc2fst.evaluator import apply_rule
from snc2fst.io import load_config, load_tests

pynini = pytest.importorskip("pynini", reason="pynini not installed")


# ---------------------------------------------------------------------------
# Collect starter directories
# ---------------------------------------------------------------------------

_STARTERS_PATH = Path(str(files("snc2fst") / "templates/starters"))

_STARTER_NAMES = [
    d.name for d in sorted(_STARTERS_PATH.iterdir()) if d.is_dir()
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_evaluator_chain(rules, out_asts, word, fs, inv):
    """
    Apply all rules via the reference evaluator, returning the output word.
    """
    current = word
    for rule, out_ast in zip(rules, out_asts):
        current = apply_rule(rule, out_ast, current, fs, inv)
    return current


def _run_fst_chain(rules, fsts, segment_names):
    """
    Apply all rules via compiled FSTs, returning output segment names.
    """
    current = segment_names
    for rule, fst in zip(rules, fsts):
        current = transduce(fst, rule, current)
    return current


# ---------------------------------------------------------------------------
# Parametrized starter test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("starter_name", _STARTER_NAMES)
def test_starter(starter_name: str) -> None:
    starter_dir = _STARTERS_PATH / starter_name
    config_path = starter_dir / "config.toml"

    config = load_config(config_path)
    fs, inv = load_alphabet(starter_dir / config.alphabet_path)
    tests = load_tests(starter_dir / config.tests_path)

    out_asts = [dsl.parse(rule.Out) for rule in config.rules]
    alphabets = compute_alphabets(config.rules, fs, inv)
    fsts = [
        compile_rule(rule, fs, rule_inv)
        for rule, rule_inv in zip(config.rules, alphabets)
    ]

    for inp_str, expected_str in tests:
        # Tokenize input
        inp_word = inv.tokenize(inp_str)
        assert not isinstance(inp_word, list), (
            f"Ambiguous tokenization for {inp_str!r} in starter {starter_name!r}"
        )

        # Reference evaluator output
        ref_word = _run_evaluator_chain(
            config.rules, out_asts, inp_word, fs, inv
        )
        ref_str = inv.render(ref_word)

        # FST chain output
        inp_names = [inv.name_of(seg) for seg in inp_word]
        out_names = _run_fst_chain(config.rules, fsts, inp_names)
        fst_str = "".join(out_names)

        assert fst_str == ref_str, (
            f"[{starter_name}] {inp_str!r}: FST={fst_str!r}, ref={ref_str!r}"
        )

        # Also check the evaluator agrees with the expected output from tests.csv
        assert ref_str == expected_str, (
            f"[{starter_name}] {inp_str!r}: "
            f"evaluator={ref_str!r}, expected={expected_str!r}"
        )
