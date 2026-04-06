import csv
from pathlib import Path

from snc2fst.types import Segment, Word


RESERVED_FEATURES = frozenset({"BOS", "EOS"})

BOS_SEGMENT: Segment = {"BOS": "+"}
EOS_SEGMENT: Segment = {"EOS": "+"}


class TokenizeError(Exception):
    pass


def load_segment_order(path: Path) -> list[str]:
    """Return segment names from the alphabet header row, in file order."""
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise ValueError(f"Alphabet file '{path}' is empty.")

    return [segment.strip() for segment in rows[0][1:] if segment.strip()]


def load_alphabet(path: Path) -> dict[str, Segment]:
    """Parse an alphabet CSV into {segment_name: {feature: valence}}."""
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise ValueError(f"Alphabet file '{path}' is empty.")

    segments = [s.strip() for s in rows[0][1:] if s.strip()]
    alphabet: dict[str, Segment] = {seg: {} for seg in segments}

    seen_features: list[str] = []
    duplicate_features: list[str] = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        feature = row[0].strip()
        if feature in seen_features:
            duplicate_features.append(feature)
        else:
            seen_features.append(feature)
        for seg, val in zip(segments, row[1:]):
            alphabet[seg][feature] = val.strip()

    if duplicate_features:
        dupes = ", ".join(f"'{f}'" for f in duplicate_features)
        raise ValueError(f"Duplicate feature row(s) in alphabet: {dupes}.")

    reserved_used = RESERVED_FEATURES & set(seen_features)
    if reserved_used:
        names = ", ".join(f"'{f}'" for f in sorted(reserved_used))
        raise ValueError(
            f"Reserved feature name(s) used in alphabet: {names}. "
            "'BOS' and 'EOS' are reserved for word boundary pseudo-segments."
        )

    reserved_segs = RESERVED_FEATURES & set(segments)
    if reserved_segs:
        names = ", ".join(f"'{s}'" for s in sorted(reserved_segs))
        raise ValueError(
            f"Reserved segment name(s) used in alphabet: {names}. "
            "'BOS' and 'EOS' are reserved for word boundary pseudo-segments."
        )

    return alphabet


def check_alphabet(alphabet: dict[str, Segment]) -> tuple[list[str], list[str]]:
    """Check for duplicate features and indistinguishable segments.

    Returns (errors, warnings) where:
      errors   — pairs of segments with identical full feature bundles
      warnings — segments that are underspecified relative to one or more others
                 (their specified features are a proper subset of another's)
    """
    errors: list[str] = []
    warnings: list[str] = []
    names = list(alphabet.keys())

    # Check for identical bundles (error)
    seen: dict[frozenset, str] = {}
    for name in names:
        key = frozenset(alphabet[name].items())
        if key in seen:
            errors.append(
                f"Segments '{seen[key]}' and '{name}' are identical — "
                "they have exactly the same feature bundle."
            )
        else:
            seen[key] = name

    # Check for underspecification subset relationship (warning)
    def specified(seg: Segment) -> frozenset:
        return frozenset((f, v) for f, v in seg.items() if v in ("+", "-"))

    for i, a in enumerate(names):
        spec_a = specified(alphabet[a])
        supers = []
        for b in names:
            if b == a:
                continue
            spec_b = specified(alphabet[b])
            if spec_a < spec_b:  # proper subset: a is underspecified relative to b
                supers.append(b)
        if supers:
            warnings.append(
                f"Segment '{a}' is underspecified relative to: "
                + ", ".join(f"'{s}'" for s in supers)
                + "."
            )

    return errors, warnings


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


def bracket_word(word: Word) -> Word:
    """Wrap a word with BOS/EOS boundary pseudo-segments."""
    return [dict(BOS_SEGMENT)] + list(word) + [dict(EOS_SEGMENT)]


def strip_boundaries(word: Word) -> Word:
    """Remove all BOS/EOS pseudo-segments from a word."""
    return [s for s in word if s != BOS_SEGMENT and s != EOS_SEGMENT]


def _segment_matches_symbol(seg: Segment, symbol_seg: Segment) -> bool:
    """Return True when seg matches symbol_seg, treating 0 as unspecified."""
    for feature in set(seg) | set(symbol_seg):
        seg_value = seg.get(feature, "0")
        symbol_value = symbol_seg.get(feature, "0")
        if seg_value != symbol_value:
            return False
    return True


def word_to_str(word: Word, alphabet: dict[str, Segment]) -> str:
    """Convert a Word back to a concatenated string of segment names.

    Segments that do not exactly match any alphabet entry are rendered as
    their feature bundle, e.g. [+F1 -F2], so output is always readable.
    """
    parts = []
    for seg in word:
        if seg == BOS_SEGMENT:
            parts.append("BOS")
        elif seg == EOS_SEGMENT:
            parts.append("EOS")
        else:
            rendered = None
            for name, symbol_seg in alphabet.items():
                if _segment_matches_symbol(seg, symbol_seg):
                    rendered = name
                    break
            if rendered is None:
                bundle = " ".join(f"{v}{f}" for f, v in sorted(seg.items()))
                parts.append(f"[{bundle}]")
            else:
                parts.append(rendered)
    return "".join(parts)
