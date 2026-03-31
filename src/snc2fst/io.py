import csv
from pathlib import Path


def load_tests(filepath: Path) -> list[tuple[str, str]]:
    """Load input/output string pairs from a TSV or CSV file."""
    delimiter = "\t" if filepath.suffix.lower() == ".tsv" else ","
    tests = []
    with filepath.open("r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=delimiter)
        next(reader, None)  # skip header
        for lineno, row in enumerate(reader, start=2):  # 1-based, header is line 1
            if not any(cell.strip() for cell in row):
                continue  # blank line
            if len(row) < 2 or len(row) > 3:
                raise ValueError(
                    f"{filepath}:{lineno}: expected 2 or 3 columns, got {len(row)}"
                )
            tests.append((row[0].strip(), row[1].strip()))
    return tests
