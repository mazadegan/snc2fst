import csv
import tomllib
from pathlib import Path

from snc2fst.models import GrammarConfig


def load_tests(filepath: Path) -> list[tuple[str, str]]:
    """Load input/output string pairs from a CSV or TSV test file.

    The file must have a header row followed by data rows with at least
    two columns — input string and expected output string. A third column
    is allowed and silently ignored. Blank lines are skipped.

    The delimiter is inferred from the file extension: '.tsv' uses tab,
    everything else uses comma.

    Args:
        filepath: Path to the CSV or TSV test file.

    Returns:
        A list of (input, expected_output) string pairs.

    Raises:
        ValueError: If any non-blank row has fewer than 2 or more than 3
            columns, with the offending line number in the message.
    """
    delimiter = "\t" if filepath.suffix.lower() == ".tsv" else ","
    tests: list[tuple[str, str]] = []
    with filepath.open("r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=delimiter)
        next(reader, None)  # skip header
        for lineno, row in enumerate(
            reader, start=2
        ):  # 1-based, header is line 1
            if not any(cell.strip() for cell in row):
                continue  # blank line
            if len(row) < 2 or len(row) > 3:
                raise ValueError(
                    f"{filepath}:{lineno}: expected 2 or 3 columns, got {len(row)}"  # noqa: E501
                )
            tests.append((row[0].strip(), row[1].strip()))
    return tests


def load_config(config_file: Path) -> GrammarConfig:
    """Load and validate a grammar configuration from a TOML file.

    Args:
        config_file: Path to the config.toml file.

    Returns:
        A validated GrammarConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
        pydantic.ValidationError: If the config structure is invalid.
    """
    with open(config_file, "rb") as f:
        raw_dict = tomllib.load(f)
    return GrammarConfig(**raw_dict)
