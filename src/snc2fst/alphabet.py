import csv
from pathlib import Path

import logical_phonology as lp

from snc2fst.errors import AlphabetError


def load_alphabet(
    path: Path, delimiter: str = ",", strict: bool = False
) -> tuple[lp.FeatureSystem, lp.Inventory]:
    """Load an alphabet CSV/TSV file and return a (FeatureSystem, Inventory)
    pair.

    The file must have features as rows and segments as columns. The first
    column contains feature names; the first row contains segment names with
    an empty leading cell. Cell values are '+', '-', or '0'/empty for
    underspecified.

    Args:
        path: Path to the alphabet file.
        delimiter: Column delimiter. Defaults to ',' for CSV; use '\\t' for
        TSV.
        strict: Ensures all rows in the input CSV/TSV file are of equal
        length. Default False.

    Raises:
        AlphabetError: If the file cannot be read, is malformed, or contains
            reserved feature names.
    """
    try:
        with open(path, newline="") as f:
            rows = list(csv.reader(f, delimiter=delimiter))
    except OSError as e:
        raise AlphabetError(f"Cannot read '{path}': {e}") from e

    if not rows:
        raise AlphabetError(f"'{path}' is empty.")
    if len(rows) < 2:
        raise AlphabetError(f"'{path}' has no feature rows.")
    if len(rows[0]) < 2:
        raise AlphabetError(f"'{path}' has no segment columns.")

    segments: list[str] = [s.strip() for s in rows[0][1:]]
    feature_set: list[str] = [row[0].strip() for row in rows[1:]]
    segment_dict: dict[str, dict[str, lp.FeatureValue]] = {
        seg: {} for seg in segments
    }

    try:
        fs = lp.FeatureSystem(frozenset(feature_set))
    except lp.errors.ReservedFeatureError as e:
        raise AlphabetError(
            f"'{path}' contains a reserved feature name: {e.conflicts}. "
            "'BOS' and 'EOS' are reserved."
        ) from e

    if strict:
        for row in rows[1:]:
            if len(row) - 1 != len(segments):
                feature = row[0].strip()
                raise AlphabetError(
                    f"Row '{feature}' has {len(row) - 1} values. "
                    f"Expected {len(segments)}."
                )

    for row in rows[1:]:
        feature = row[0].strip()
        for seg, val in zip(segments, row[1:]):
            val = val.strip()  # TODO: add test case to cover this!
            if val in ("+", "-"):
                segment_dict[seg][feature] = lp.FeatureValue.from_str(val)

    inv = fs.inventory({k: fs.segment(v) for k, v in segment_dict.items()})
    return fs, inv
