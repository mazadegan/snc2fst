from __future__ import annotations

import csv
import json
from pathlib import Path

import typer
from pydantic import ValidationError

from ._version import __version__
from .alphabet import Alphabet, format_validation_error

app = typer.Typer(add_completion=False)


@app.callback()
def cli() -> None:
    """snc2fst command line interface."""
    pass


def _detect_delimiter(path: Path, sample: str, delimiter: str | None) -> str:
    if delimiter:
        return delimiter
    suffix = path.suffix.lower()
    if suffix in {".tsv", ".tab"}:
        return "\t"
    if suffix == ".csv":
        return ","
    return "\t" if "\t" in sample and "," not in sample else ","


def _normalize_value(value: str) -> str:
    cleaned = value.strip()
    if cleaned == "":
        return "0"
    if cleaned in {"+", "-", "0"}:
        return cleaned
    raise ValueError(f"Invalid feature value: {value!r} (expected '+', '-', '0', or blank)")


@app.command()
def version() -> None:
    """Print the snc2fst version."""
    typer.echo(__version__)


@app.command("import-table")
def import_table(
    table_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path | None = typer.Option(None, "--output", "-o", dir_okay=False),
    delimiter: str | None = typer.Option(None, "--delimiter", "-d"),
) -> None:
    """Convert a CSV/TSV feature matrix into JSON."""
    text = table_path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise typer.BadParameter("Input file is empty.")

    first_line = text.splitlines()[0]
    delim = _detect_delimiter(table_path, first_line, delimiter)

    reader = csv.reader(text.splitlines(), delimiter=delim)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise typer.BadParameter("Input file has no data rows.")

    header = [cell.strip() for cell in rows[0]]
    if len(header) < 2:
        raise typer.BadParameter("Header must contain an empty leading cell plus at least one symbol.")

    symbols = header[1:]
    if any(symbol == "" for symbol in symbols):
        raise typer.BadParameter("Header symbols cannot be empty.")

    features: list[str] = []
    values: list[list[str]] = []

    for row in rows[1:]:
        if len(row) < 2:
            continue
        feature_name = row[0].strip()
        if not feature_name:
            raise typer.BadParameter("Feature name cannot be empty.")
        row_values = row[1:]
        if len(row_values) != len(symbols):
            raise typer.BadParameter(
                f"Row for feature {feature_name!r} has {len(row_values)} values; expected {len(symbols)}."
            )

        normalized = [_normalize_value(value) for value in row_values]
        features.append(feature_name)
        values.append(normalized)

    try:
        alphabet = Alphabet.from_matrix(symbols, features, values)
    except (ValueError, ValidationError) as exc:
        message = str(exc)
        if isinstance(exc, ValidationError):
            message = format_validation_error(exc)
        raise typer.BadParameter(message) from exc

    output_json = json.dumps(alphabet.model_dump(by_alias=True), ensure_ascii=False, indent=2)

    if output:
        output.write_text(output_json + "\n", encoding="utf-8")
    else:
        typer.echo(output_json)


def main() -> None:
    app(prog_name="snc2fst")


if __name__ == "__main__":
    main()
