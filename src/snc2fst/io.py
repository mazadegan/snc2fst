import csv
from pathlib import Path


def load_tests(filepath: Path) -> list[tuple[str, str]]:
    """Load input/output string pairs from a TSV or CSV file."""
    delimiter = "\t" if filepath.suffix.lower() == ".tsv" else ","
    tests = []
    with filepath.open("r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=delimiter)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 2:
                tests.append((row[0].strip(), row[1].strip()))
    return tests
