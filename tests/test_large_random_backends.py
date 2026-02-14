import random
import sys
import time
from itertools import product
from pathlib import Path

import pytest

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.feature_analysis import compute_v_features  # noqa: E402
from snc2fst.main import _evaluate_with_pynini, _evaluate_with_reference  # noqa: E402
from snc2fst.rules import Rule  # noqa: E402


def _random_rule(rng: random.Random, idx: int) -> Rule:
    feature_count = rng.randint(2, 5)
    features = [f"F{idx}x{i}" for i in range(feature_count)]
    inr = _random_feature_class(rng, features)
    trm = _random_feature_class(rng, features)
    cnd = _random_feature_class(rng, features)
    out = _random_out_expr(rng, features)
    return Rule(
        id=f"r{idx}",
        dir=rng.choice(["LEFT", "RIGHT"]),
        inr=inr,
        trm=trm,
        cnd=cnd,
        out=out,
    )


def _random_feature_class(
    rng: random.Random, features: list[str], max_size: int = 2
) -> list[tuple[str, str]]:
    size = rng.randint(0, min(max_size, len(features)))
    selected = rng.sample(features, size)
    return [(rng.choice(["+", "-"]), feature) for feature in selected]


def _random_out_expr(rng: random.Random, features: list[str]) -> str:
    f1 = rng.choice(features)
    f2 = rng.choice(features)
    feature_list = _format_feature_list(rng, features)
    templates = [
        lambda: f"(proj INR ({f1}))",
        lambda: f"(proj TRM ({f1}))",
        lambda: f"(proj INR ({feature_list}))",
        lambda: f"(proj TRM ({feature_list}))",
        lambda: f"(unify (proj INR ({f1})) (proj TRM ({f2})))",
        lambda: f"(subtract (proj TRM *) (proj TRM ({f1})))",
        lambda: f"(unify (bundle (+ {f1})) (proj INR ({f2})))",
        lambda: f"(subtract (proj INR *) (proj TRM ({f2})))",
        lambda: f"(bundle (+ {f1}))",
        lambda: f"(bundle (- {f1}))",
    ]
    return rng.choice(templates)()


def _format_feature_list(rng: random.Random, features: list[str]) -> str:
    size = rng.randint(1, min(2, len(features)))
    selected = rng.sample(features, size)
    return " ".join(selected)


def _make_symbol_maps(
    v_order: tuple[str, ...],
) -> tuple[dict[str, dict[str, str]], dict[tuple[str, ...], str], list[str]]:
    symbol_to_bundle: dict[str, dict[str, str]] = {}
    bundle_to_symbol: dict[tuple[str, ...], str] = {}
    symbols: list[str] = []
    for bundle in product((0, 1, 2), repeat=len(v_order)):
        symbol = "s" + "".join(str(value) for value in bundle)
        bundle_dict: dict[str, str] = {}
        bundle_key: list[str] = []
        for feature, value in zip(v_order, bundle):
            if value == 1:
                bundle_dict[feature] = "+"
            elif value == 2:
                bundle_dict[feature] = "-"
            else:
                bundle_dict[feature] = "0"
            bundle_key.append(bundle_dict[feature])
        symbol_to_bundle[symbol] = bundle_dict
        bundle_to_symbol[tuple(bundle_key)] = symbol
        symbols.append(symbol)
    return symbol_to_bundle, bundle_to_symbol, symbols


def _random_words(
    rng: random.Random, symbols: list[str], count: int, max_len: int
) -> list[list[str]]:
    words: list[list[str]] = []
    for _ in range(count):
        length = rng.randint(0, max_len)
        words.append([rng.choice(symbols) for _ in range(length)])
    return words


def _progress(total: int, label: str, enabled: bool) -> callable:
    if not enabled or total <= 0:
        return lambda _current: None

    start = time.monotonic()
    width = 30

    def _render(current: int) -> None:
        current = min(current, total)
        ratio = current / total
        filled = int(width * ratio)
        bar = "#" * filled + "-" * (width - filled)
        elapsed = time.monotonic() - start
        rate = current / elapsed if elapsed > 0 else 0.0
        sys.stderr.write(
            f"\r[{bar}] {label} {current}/{total} "
            f"({ratio:5.1%}) {rate:5.1f}/s"
        )
        if current == total:
            sys.stderr.write("\n")
        sys.stderr.flush()

    return _render


def _first_mismatch(
    expected: list[list[object]], actual: list[list[object]]
) -> tuple[int, list[object], list[object]] | None:
    for idx, (exp_word, act_word) in enumerate(zip(expected, actual)):
        if exp_word != act_word:
            return idx, exp_word, act_word
    if len(expected) != len(actual):
        return min(len(expected), len(actual)), [], []
    return None


def _format_rule(rule: Rule) -> str:
    return (
        f"id={rule.id} dir={rule.dir} inr={rule.inr} "
        f"trm={rule.trm} cnd={rule.cnd} out={rule.out}"
    )


def _format_word(
    word: list[object], symbol_to_bundle: dict[str, dict[str, str]]
) -> str:
    symbols: list[str] = []
    bundles: list[dict[str, str]] = []
    for item in word:
        if isinstance(item, str):
            symbols.append(item)
            bundles.append(symbol_to_bundle.get(item, {}))
        else:
            symbols.append(repr(item))
            bundles.append({})
    return f"symbols={symbols}\nbundles={bundles}"


@pytest.mark.stress
def test_random_pynini_backend_matches_reference_large(
    pytestconfig: pytest.Config,
) -> None:
    pytest.importorskip("pywrapfst")
    rng = random.Random(2)
    rule_count = pytestconfig.getoption("--stress-rules")
    word_count = pytestconfig.getoption("--stress-words")
    max_len = pytestconfig.getoption("--stress-max-len")
    progress = _progress(
        rule_count,
        "pynini rules",
        pytestconfig.getoption("--stress-progress"),
    )
    for idx in range(rule_count):
        rule = _random_rule(rng, idx + 2000)
        v_order = tuple(sorted(compute_v_features(rule)))
        symbol_to_bundle, bundle_to_symbol, symbols = _make_symbol_maps(v_order)
        words = _random_words(rng, symbols, word_count, max_len)
        ref_words = _evaluate_with_reference(
            rule=rule,
            words=words,
            feature_order=v_order,
            symbol_to_bundle=symbol_to_bundle,
            bundle_to_symbol=bundle_to_symbol,
            strict=True,
        )
        pynini_words = _evaluate_with_pynini(
            rule=rule,
            words=words,
            feature_order=v_order,
            symbol_to_bundle=symbol_to_bundle,
            bundle_to_symbol=bundle_to_symbol,
            strict=True,
        )
        mismatch = _first_mismatch(ref_words, pynini_words)
        if mismatch is not None:
            word_idx, expected, actual = mismatch
            input_word = words[word_idx] if word_idx < len(words) else []
            message = "\n".join(
                [
                    "Pynini output differs from reference.",
                    f"rule: {_format_rule(rule)}",
                    f"v_order: {list(v_order)}",
                    f"word_index: {word_idx}",
                    f"input: {_format_word(input_word, symbol_to_bundle)}",
                    f"expected: {expected}",
                    f"actual: {actual}",
                ]
            )
            pytest.fail(message)
        progress(idx + 1)
