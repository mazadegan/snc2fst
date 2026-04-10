from pathlib import Path

import logical_phonology as lp
import pytest

from snc2fst.alphabet import load_alphabet
from snc2fst.errors import AlphabetError

FIXTURES = Path(__file__).parent / "fixtures"
SEGMENT_NAMES = [
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    "∅",
]


@pytest.fixture
def inv() -> lp.Inventory:
    _, inv = load_alphabet(FIXTURES / "simple.csv")
    return inv


def test_loads_csv() -> None:
    fs, inv = load_alphabet(FIXTURES / "simple.csv")
    assert fs.valid_features == frozenset(["F1", "F2", "F3"])
    assert len(inv) == 3**3 + 2


def test_loads_tsv() -> None:
    fs, inv = load_alphabet(FIXTURES / "simple.tsv", delimiter="\t")
    assert fs.valid_features == frozenset(["F1", "F2", "F3"])
    assert len(inv) == 3**3 + 2


def test_strict_mode_raises_on_unequal_rows() -> None:
    with pytest.raises(AlphabetError) as exc_info:
        load_alphabet(FIXTURES / "unequal_rows.csv", strict=True)
    assert "values" in str(exc_info.value).lower()


def test_non_strict_mode_accepts_unequal_rows() -> None:
    # should not raise — unequal rows are silently handled
    _, inv = load_alphabet(FIXTURES / "unequal_rows.csv", strict=False)
    assert "A" in inv


@pytest.mark.parametrize("segment_name", SEGMENT_NAMES)
def test_all_segments_in_inv(segment_name: str, inv: lp.Inventory) -> None:
    assert segment_name in inv


def test_empty_input() -> None:
    with pytest.raises(AlphabetError) as exc_info:
        load_alphabet(FIXTURES / "empty.csv")
    assert "empty" in str(exc_info.value).lower()


def test_reserved_feature() -> None:
    with pytest.raises(AlphabetError) as exc_info:
        load_alphabet(FIXTURES / "reserved_feature.csv")
    assert "reserved feature" in str(exc_info.value).lower()


def test_no_segments() -> None:
    with pytest.raises(AlphabetError) as exc_info:
        load_alphabet(FIXTURES / "no_segments.csv")
    assert "no segment columns" in str(exc_info.value).lower()


def test_no_features() -> None:
    with pytest.raises(AlphabetError) as exc_info:
        load_alphabet(FIXTURES / "no_features.csv")
    assert "no feature rows" in str(exc_info.value).lower()


def test_missing_file() -> None:
    with pytest.raises(AlphabetError):
        load_alphabet(FIXTURES / "nonexistent.csv")


def test_empty_segment_has_no_features(inv: lp.Inventory) -> None:
    assert len(inv["∅"].features) == 0
