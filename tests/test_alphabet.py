"""Tests for alphabet.py — load, check, tokenize, and boundary helpers."""

import pytest
from pathlib import Path
import tempfile
import textwrap

from snc2fst.alphabet import (
    BOS_SEGMENT,
    EOS_SEGMENT,
    RESERVED_FEATURES,
    bracket_word,
    load_alphabet,
    strip_boundaries,
    word_to_str,
)


# ---------------------------------------------------------------------------
# Toy alphabet shared across tests
# ---------------------------------------------------------------------------

ALPHABET = {
    "a": {"Syllabic": "+", "Voice": "+"},
    "b": {"Syllabic": "-", "Voice": "+"},
    "p": {"Syllabic": "-", "Voice": "-"},
}


def _write_csv(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    f.write(textwrap.dedent(content))
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# Reserved feature names rejected by load_alphabet
# ---------------------------------------------------------------------------


def test_load_alphabet_rejects_bos_feature():
    path = _write_csv("""\
        ,a,b
        BOS,+,-
        Voice,+,+
    """)
    with pytest.raises(ValueError, match="Reserved feature name"):
        load_alphabet(path)


def test_load_alphabet_rejects_eos_feature():
    path = _write_csv("""\
        ,a,b
        EOS,+,-
        Voice,+,+
    """)
    with pytest.raises(ValueError, match="Reserved feature name"):
        load_alphabet(path)


def test_load_alphabet_rejects_bos_segment():
    path = _write_csv("""\
        ,a,BOS
        Voice,+,+
    """)
    with pytest.raises(ValueError, match="Reserved segment name"):
        load_alphabet(path)


def test_load_alphabet_rejects_eos_segment():
    path = _write_csv("""\
        ,a,EOS
        Voice,+,+
    """)
    with pytest.raises(ValueError, match="Reserved segment name"):
        load_alphabet(path)


# ---------------------------------------------------------------------------
# bracket_word / strip_boundaries
# ---------------------------------------------------------------------------


def test_bracket_word_prepends_bos():
    word = [ALPHABET["a"], ALPHABET["b"]]
    bracketed = bracket_word(word)
    assert bracketed[0] == BOS_SEGMENT


def test_bracket_word_appends_eos():
    word = [ALPHABET["a"], ALPHABET["b"]]
    bracketed = bracket_word(word)
    assert bracketed[-1] == EOS_SEGMENT


def test_bracket_word_preserves_content():
    word = [ALPHABET["a"], ALPHABET["b"]]
    bracketed = bracket_word(word)
    assert bracketed[1:-1] == word


def test_bracket_word_empty():
    bracketed = bracket_word([])
    assert bracketed == [BOS_SEGMENT, EOS_SEGMENT]


def test_strip_boundaries_removes_bos_eos():
    word = [ALPHABET["a"], ALPHABET["b"]]
    assert strip_boundaries(bracket_word(word)) == word


def test_strip_boundaries_empty():
    assert strip_boundaries([BOS_SEGMENT, EOS_SEGMENT]) == []


def test_strip_boundaries_no_boundaries():
    word = [ALPHABET["a"], ALPHABET["b"]]
    assert strip_boundaries(word) == word


# ---------------------------------------------------------------------------
# word_to_str renders boundaries as BOS/EOS
# ---------------------------------------------------------------------------


def test_word_to_str_renders_bos():
    assert word_to_str([BOS_SEGMENT], ALPHABET) == "BOS"


def test_word_to_str_renders_eos():
    assert word_to_str([EOS_SEGMENT], ALPHABET) == "EOS"


def test_word_to_str_renders_bracketed_word():
    word = [ALPHABET["a"], ALPHABET["b"]]
    assert word_to_str(bracket_word(word), ALPHABET) == "BOSabEOS"
