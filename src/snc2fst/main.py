from __future__ import annotations

import csv
import json
from pathlib import Path

import typer
from pydantic import ValidationError

from ._version import __version__
from .alphabet import Alphabet, format_validation_error
from .out_dsl import OutDslError, evaluate_out_dsl
from .rules import RulesFile, Rule
from .tv_compiler import compile_tv, write_att

app = typer.Typer(add_completion=False)


@app.callback()
def cli() -> None:
    """snc2fst command line interface."""
    pass


def _detect_delimiter(path: Path, sample: str, delimiter: str | None) -> str:
    """Resolve the CSV/TSV delimiter from user input, extension, or sample text."""
    if delimiter:
        return delimiter
    suffix = path.suffix.lower()
    if suffix in {".tsv", ".tab"}:
        return "\t"
    if suffix == ".csv":
        return ","
    return "\t" if "\t" in sample and "," not in sample else ","


def _normalize_value(value: str) -> str:
    """Normalize a cell to '+', '-', or '0', treating blank as '0'."""
    cleaned = value.strip()
    if cleaned == "":
        return "0"
    if cleaned in {"+", "-", "0"}:
        return cleaned
    raise ValueError(
        f"Invalid feature value: {value!r} (expected '+', '-', '0', or blank)"
    )


@app.command()
def version() -> None:
    """Print the snc2fst version."""
    typer.echo(__version__)


def _table_to_json(
    table_path: Path,
    delimiter: str | None,
) -> str:
    """Parse a feature table and return JSON for the Alphabet model."""
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
        raise typer.BadParameter(
            "Header must contain an empty leading cell plus at least one symbol."
        )

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

    return json.dumps(
        alphabet.model_dump(by_alias=True), ensure_ascii=False, indent=2
    )


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"Invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc


def _load_alphabet_features(alphabet_path: Path) -> set[str]:
    if alphabet_path.suffix.lower() not in {".csv", ".tsv", ".tab"}:
        raise typer.BadParameter(
            "Alphabet must be a CSV/TSV feature table."
        )
    payload = json.loads(_table_to_json(alphabet_path, delimiter=None))
    try:
        alphabet = Alphabet.model_validate(payload)
    except ValidationError as exc:
        raise typer.BadParameter(format_validation_error(exc)) from exc
    return set(alphabet.feature_schema.features)


def _bundle_from_rule(rule: Rule, label: str) -> dict[str, str]:
    bundle: dict[str, str] = {}
    for polarity, feature in getattr(rule, label):
        bundle[feature] = polarity
    return bundle


def _validate_rule_features(
    rule: Rule, features: set[str], label: str
) -> None:
    for _, feature in getattr(rule, label):
        if feature not in features:
            raise typer.BadParameter(
                f"Rule {rule.id} {label} has unknown feature: {feature!r}"
            )


def _validate_rules_file(
    rules_path: Path, alphabet_path: Path | None
) -> None:
    payload = _load_json(rules_path)

    if alphabet_path is None:
        raise typer.BadParameter(
            "Rules validation requires an alphabet JSON file; pass --alphabet."
        )

    features = _load_alphabet_features(alphabet_path)

    try:
        rules = RulesFile.model_validate(payload).rules
    except ValidationError as exc:
        raise typer.BadParameter(format_validation_error(exc)) from exc
    for rule in rules:
        _validate_rule_features(rule, features, "inr")
        _validate_rule_features(rule, features, "trm")
        _validate_rule_features(rule, features, "cnd")
        try:
            evaluate_out_dsl(
                rule.out,
                inr=_bundle_from_rule(rule, "inr"),
                trm=_bundle_from_rule(rule, "trm"),
                features=features,
            )
        except OutDslError as exc:
            raise typer.BadParameter(
                f"Rule {rule.id} out is invalid: {exc}"
            ) from exc


def _select_rule(rules: list[Rule], rule_id: str | None) -> Rule:
    if rule_id is None:
        if len(rules) == 1:
            return rules[0]
        raise typer.BadParameter(
            "Rules file contains multiple rules; pass --rule-id."
        )
    for rule in rules:
        if rule.id == rule_id:
            return rule
    raise typer.BadParameter(f"Unknown rule id: {rule_id!r}")


@app.command("validate")
def validate(
    input_path: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True
    ),
    alphabet: Path | None = typer.Option(
        None, "--alphabet", "-a", dir_okay=False, readable=True
    ),
    delimiter: str | None = typer.Option(None, "--delimiter", "-d"),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress success output."
    ),
) -> None:
    """Validate a JSON rules file or a CSV/TSV alphabet file."""
    if input_path.suffix.lower() == ".json":
        _validate_rules_file(input_path, alphabet)
    else:
        _table_to_json(input_path, delimiter)

    if not quiet:
        typer.echo("OK")


@app.command("compile")
def compile_rule(
    rules_path: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True
    ),
    output: Path = typer.Argument(..., dir_okay=False, writable=True),
    rule_id: str | None = typer.Option(None, "--rule-id"),
    alphabet: Path | None = typer.Option(
        None, "--alphabet", "-a", dir_okay=False, readable=True
    ),
    symtab: Path | None = typer.Option(
        None, "--symtab", dir_okay=False, writable=True
    ),
) -> None:
    """Compile a single rule into AT&T text format."""
    payload = _load_json(rules_path)
    try:
        rules = RulesFile.model_validate(payload).rules
    except ValidationError as exc:
        raise typer.BadParameter(format_validation_error(exc)) from exc

    if alphabet is not None:
        features = _load_alphabet_features(alphabet)
        for rule in rules:
            _validate_rule_features(rule, features, "inr")
            _validate_rule_features(rule, features, "trm")
            _validate_rule_features(rule, features, "cnd")
            try:
                evaluate_out_dsl(
                    rule.out,
                    inr=_bundle_from_rule(rule, "inr"),
                    trm=_bundle_from_rule(rule, "trm"),
                    features=features,
                )
            except OutDslError as exc:
                raise typer.BadParameter(
                    f"Rule {rule.id} out is invalid: {exc}"
                ) from exc

    rule = _select_rule(rules, rule_id)
    machine = compile_tv(rule)
    symtab_path = symtab or output.with_suffix(".sym")
    write_att(machine, str(output), symtab_path=str(symtab_path))


def main() -> None:
    app(prog_name="snc2fst")


if __name__ == "__main__":
    main()
