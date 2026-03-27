import csv
from pathlib import Path

from snc2fst.types import Segment, Word


class TokenizeError(Exception):
    pass


def load_alphabet(path: Path) -> dict[str, Segment]:
    """Parse an alphabet CSV into {segment_name: {feature: valence}}."""
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise ValueError(f"Alphabet file '{path}' is empty.")

    segments = [s.strip() for s in rows[0][1:] if s.strip()]
    alphabet: dict[str, Segment] = {seg: {} for seg in segments}

    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        feature = row[0].strip()
        for seg, val in zip(segments, row[1:]):
            alphabet[seg][feature] = val.strip()

    return alphabet


def _all_parses(s: str, names: frozenset[str]) -> list[list[str]]:
    """Return every way to split s into a sequence of names."""
    if not s:
        return [[]]
    return [
        [name] + rest
        for name in names
        if s.startswith(name)
        for rest in _all_parses(s[len(name):], names)
    ]


def tokenize(word_str: str, alphabet: dict[str, Segment]) -> list[str]:
    """Split a word string into a list of segment names.

    If the string contains spaces it is treated as already delimited — each
    token is looked up directly.  Otherwise all valid segmentations are
    enumerated; exactly one must exist.
    """
    if " " in word_str:
        tokens = word_str.split()
        unknown = [t for t in tokens if t not in alphabet]
        if unknown:
            raise TokenizeError(
                f"Unknown segment(s): {', '.join(repr(t) for t in unknown)}"
            )
        return tokens

    parses = _all_parses(word_str, frozenset(alphabet))

    if len(parses) == 1:
        return parses[0]

    if not parses:
        raise TokenizeError(
            f"Cannot tokenize '{word_str}': "
            "no combination of alphabet segments covers it"
        )

    options = "  |  ".join(" ".join(p) for p in parses)
    raise TokenizeError(
        f"Ambiguous tokenization of '{word_str}': {options} "
        "— use spaces to disambiguate"
    )


def word_to_str(word: Word, alphabet: dict[str, Segment]) -> str:
    """Convert a Word back to a concatenated string of segment names.

    Segments that do not exactly match any alphabet entry are rendered as
    their feature bundle, e.g. [+F1 -F2], so output is always readable.
    """
    rev: dict[frozenset, str] = {
        frozenset(seg.items()): name for name, seg in alphabet.items()
    }
    parts = []
    for seg in word:
        key = frozenset(seg.items())
        if key in rev:
            parts.append(rev[key])
        else:
            bundle = " ".join(f"{v}{f}" for f, v in sorted(seg.items()))
            parts.append(f"[{bundle}]")
    return "".join(parts)
