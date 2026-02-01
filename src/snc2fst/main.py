from __future__ import annotations

import csv
import json
import shutil
import subprocess
import tempfile
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


def _load_alphabet(alphabet_path: Path) -> Alphabet:
    if alphabet_path.suffix.lower() not in {".csv", ".tsv", ".tab"}:
        raise typer.BadParameter(
            "Alphabet must be a CSV/TSV feature table."
        )
    payload = json.loads(_table_to_json(alphabet_path, delimiter=None))
    try:
        return Alphabet.model_validate(payload)
    except ValidationError as exc:
        raise typer.BadParameter(format_validation_error(exc)) from exc


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


def _validate_input_words(
    input_path: Path, alphabet_path: Path | None
) -> None:
    if alphabet_path is None:
        raise typer.BadParameter(
            "Input validation requires an alphabet file; pass --alphabet."
        )
    alphabet_data = _load_alphabet(alphabet_path)
    symbols = {row.symbol for row in alphabet_data.rows}
    payload = _load_json(input_path)
    if not isinstance(payload, list):
        raise typer.BadParameter(
            "Input JSON must be an array of words (arrays of symbols)."
        )
    for idx, word in enumerate(payload):
        if not isinstance(word, list):
            raise typer.BadParameter(
                f"Word at index {idx} is not an array of symbols."
            )
        for sym in word:
            if not isinstance(sym, str) or not sym.strip():
                raise typer.BadParameter(
                    f"Word {idx} contains a non-string symbol."
                )
            if sym not in symbols:
                raise typer.BadParameter(
                    f"Word {idx} has unknown symbol: {sym!r}"
                )


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
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Rules JSON or alphabet CSV/TSV file to validate.",
    ),
    kind: str | None = typer.Option(
        None,
        "--kind",
        "-k",
        help="Validation kind: rules, alphabet, or input (auto-detect if omitted).",
    ),
    alphabet: Path | None = typer.Option(
        None,
        "--alphabet",
        "-a",
        dir_okay=False,
        readable=True,
        help="Alphabet CSV/TSV file required for rules validation.",
    ),
    delimiter: str | None = typer.Option(
        None,
        "--delimiter",
        "-d",
        help="Override the delimiter for alphabet files (default: detect).",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress success output.",
    ),
) -> None:
    """Validate a rules JSON, alphabet CSV/TSV, or input words JSON."""
    kind_value = kind.lower() if kind else None
    if kind_value is None:
        if input_path.suffix.lower() == ".json":
            kind_value = "rules"
        else:
            kind_value = "alphabet"

    if kind_value == "rules":
        _validate_rules_file(input_path, alphabet)
    elif kind_value == "alphabet":
        _table_to_json(input_path, delimiter)
    elif kind_value == "input":
        _validate_input_words(input_path, alphabet)
    else:
        raise typer.BadParameter(
            "Invalid --kind. Use 'rules', 'alphabet', or 'input'."
        )

    if not quiet:
        typer.echo("OK")


@app.command("compile")
def compile_rule(
    rules_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Rules JSON file to compile.",
    ),
    output: Path = typer.Argument(
        ...,
        dir_okay=False,
        writable=True,
        help="AT&T output path (ignored when --no-att is set).",
    ),
    rule_id: str | None = typer.Option(
        None,
        "--rule-id",
        help="Rule id to compile (required if multiple rules).",
    ),
    alphabet: Path | None = typer.Option(
        None,
        "--alphabet",
        "-a",
        dir_okay=False,
        readable=True,
        help="Alphabet CSV/TSV file for rule validation.",
    ),
    symtab: Path | None = typer.Option(
        None,
        "--symtab",
        dir_okay=False,
        writable=True,
        help="Symbol table output path (defaults next to output).",
    ),
    fst: Path | None = typer.Option(
        None,
        "--fst",
        dir_okay=False,
        writable=True,
        help="Write a compiled OpenFst binary to this path.",
    ),
) -> None:
    """Compile a single rule into AT&T text format (always writes .att and .sym).

    The compiled machine is canonical LEFT; RIGHT direction is handled by
    reversing input/output at evaluation time.
    """
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

    if symtab is not None:
        symtab_path = symtab
    else:
        symtab_path = output.with_suffix(".sym")
    write_att(machine, str(output), symtab_path=str(symtab_path))
    if fst is not None:
        _compile_fst(output, fst)


@app.command("eval")
def eval_rule(
    rules_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Rules JSON file to evaluate.",
    ),
    input_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Input JSON array of words (each word is an array of symbols).",
    ),
    output: Path = typer.Argument(
        ...,
        dir_okay=False,
        writable=True,
        help="Output JSON file for evaluated words.",
    ),
    rule_id: str | None = typer.Option(
        None,
        "--rule-id",
        help="Rule id to evaluate (required if multiple rules).",
    ),
    alphabet: Path | None = typer.Option(
        None,
        "--alphabet",
        "-a",
        dir_okay=False,
        readable=True,
        help="Alphabet CSV/TSV file used to map symbols to bundles.",
    ),
    include_input: bool = typer.Option(
        False,
        "--include-input",
        help="Include both input and output words in the result.",
    ),
    fst: Path | None = typer.Option(
        None,
        "--fst",
        dir_okay=False,
        readable=True,
        help="Use a compiled OpenFst binary to evaluate words.",
    ),
    fst_symtab: Path | None = typer.Option(
        None,
        "--fst-symtab",
        dir_okay=False,
        readable=True,
        help="Symbol table for --fst (defaults to <fst>.sym).",
    ),
    tv: bool = typer.Option(
        False,
        "--tv",
        help="Use the in-memory TvMachine backend to evaluate words.",
    ),
    compare: bool = typer.Option(
        False,
        "--compare",
        help="Compare FST output to the reference evaluator.",
    ),
    compare_all: bool = typer.Option(
        False,
        "--compare-all",
        help="Compare reference, TvMachine, and FST outputs.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail if an output bundle has no matching symbol in the alphabet.",
    ),
) -> None:
    """Evaluate a rule against an input word list.

    The compiled machine is canonical LEFT; RIGHT rules are evaluated by
    reversing input/output around the machine.
    """
    payload = _load_json(rules_path)
    try:
        rules = RulesFile.model_validate(payload).rules
    except ValidationError as exc:
        raise typer.BadParameter(format_validation_error(exc)) from exc

    if alphabet is None:
        raise typer.BadParameter(
            "Evaluation requires an alphabet; pass --alphabet."
        )
    alphabet_data = _load_alphabet(alphabet)
    features = set(alphabet_data.feature_schema.features)
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
    try:
        segments = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"Invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc
    if not isinstance(segments, list):
        raise typer.BadParameter(
            "Input JSON must be an array of words (arrays of symbols)."
        )

    symbol_to_bundle: dict[str, dict[str, str]] = {}
    bundle_to_symbol: dict[tuple[str, ...], str] = {}
    feature_order = tuple(alphabet_data.feature_schema.features)
    for row in alphabet_data.rows:
        symbol_to_bundle[row.symbol] = dict(row.features)
        bundle_key = tuple(row.features[feature] for feature in feature_order)
        if bundle_key in bundle_to_symbol:
            raise typer.BadParameter(
                f"Alphabet has multiple symbols for bundle: {bundle_key}"
            )
        bundle_to_symbol[bundle_key] = row.symbol

    output_words: list[list[object]] = []
    results_with_input: list[dict[str, list[object]]] = []

    if compare_all and not (tv and fst is not None):
        raise typer.BadParameter("--compare-all requires both --tv and --fst.")

    if fst is not None and tv:
        tv_words = _evaluate_with_tv(
            rule=rule,
            words=segments,
            feature_order=feature_order,
            symbol_to_bundle=symbol_to_bundle,
            bundle_to_symbol=bundle_to_symbol,
            strict=strict,
        )
        fst_words = _evaluate_with_fst(
            rule=rule,
            fst=fst,
            fst_symtab=fst_symtab,
            words=segments,
            feature_order=feature_order,
            symbol_to_bundle=symbol_to_bundle,
            bundle_to_symbol=bundle_to_symbol,
            strict=strict,
        )
        if compare_all:
            ref_words = _evaluate_with_reference(
                rule=rule,
                words=segments,
                feature_order=feature_order,
                symbol_to_bundle=symbol_to_bundle,
                bundle_to_symbol=bundle_to_symbol,
                strict=strict,
            )
            diffs = (
                _diff_word_lists(ref_words, tv_words)
                + _diff_word_lists(ref_words, fst_words)
                + _diff_word_lists(tv_words, fst_words)
            )
            if diffs:
                message = "Output mismatch:\n" + "\n".join(diffs)
                raise typer.BadParameter(message)
        output_words = tv_words
        if include_input:
            results_with_input = [
                {"input": word, "output": output_word}
                for word, output_word in zip(segments, output_words)
            ]
    elif fst is not None:
        output_words = _evaluate_with_fst(
            rule=rule,
            fst=fst,
            fst_symtab=fst_symtab,
            words=segments,
            feature_order=feature_order,
            symbol_to_bundle=symbol_to_bundle,
            bundle_to_symbol=bundle_to_symbol,
            strict=strict,
        )
        if compare:
            ref_words = _evaluate_with_reference(
                rule=rule,
                words=segments,
                feature_order=feature_order,
                symbol_to_bundle=symbol_to_bundle,
                bundle_to_symbol=bundle_to_symbol,
                strict=strict,
            )
            diffs = _diff_word_lists(ref_words, output_words)
            if diffs:
                message = "FST output differs from reference:\n" + "\n".join(
                    diffs
                )
                raise typer.BadParameter(message)
        if include_input:
            results_with_input = [
                {"input": word, "output": output_word}
                for word, output_word in zip(segments, output_words)
            ]
    elif tv:
        output_words = _evaluate_with_tv(
            rule=rule,
            words=segments,
            feature_order=feature_order,
            symbol_to_bundle=symbol_to_bundle,
            bundle_to_symbol=bundle_to_symbol,
            strict=strict,
        )
        if compare:
            ref_words = _evaluate_with_reference(
                rule=rule,
                words=segments,
                feature_order=feature_order,
                symbol_to_bundle=symbol_to_bundle,
                bundle_to_symbol=bundle_to_symbol,
                strict=strict,
            )
            diffs = _diff_word_lists(ref_words, output_words)
            if diffs:
                message = (
                    "TvMachine output differs from reference:\n"
                    + "\n".join(diffs)
                )
                raise typer.BadParameter(message)
        if include_input:
            results_with_input = [
                {"input": word, "output": output_word}
                for word, output_word in zip(segments, output_words)
            ]
    else:
        output_words = _evaluate_with_reference(
            rule=rule,
            words=segments,
            feature_order=feature_order,
            symbol_to_bundle=symbol_to_bundle,
            bundle_to_symbol=bundle_to_symbol,
            strict=strict,
        )
        if compare:
            raise typer.BadParameter("--compare requires --fst or --tv.")

    if include_input:
        rendered = _format_word_pairs(results_with_input)
    else:
        rendered = _format_word_list(output_words)
    output.write_text(rendered, encoding="utf-8")


@app.command("generate")
def generate_samples(
    output_dir: Path = typer.Argument(
        ...,
        dir_okay=True,
        writable=True,
        help="Directory to write sample alphabet, rules, and input files.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing sample files.",
    ),
) -> None:
    """Generate sample alphabet.csv, rules.json, and input.json files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    alphabet_path = output_dir / "alphabet.csv"
    rules_path = output_dir / "rules.json"
    input_path = output_dir / "input.json"

    if not force:
        existing = [
            path.name
            for path in (alphabet_path, rules_path, input_path)
            if path.exists()
        ]
        if existing:
            raise typer.BadParameter(
                "Sample files already exist: " + ", ".join(existing)
            )

    alphabet_path.write_text(
        ",a,b,c,d\n"
        "Voice,+,-,0,-\n"
        "Consonantal,0,+,-,0\n",
        encoding="utf-8",
    )
    rules_payload = {
        "rules": [
            {
                "id": "spread_voice_right",
                "dir": "RIGHT",
                "inr": [["+","Voice"]],
                "trm": [["+","Consonantal"]],
                "cnd": [],
                "out": "(proj TRM (Voice))",
            }
        ]
    }
    rules_path.write_text(
        "{\n"
        '  "rules": [\n'
        "    {\n"
        '      "id": "spread_voice_right",\n'
        '      "dir": "RIGHT",\n'
        '      "inr": [["+","Voice"]],\n'
        '      "trm": [["+","Consonantal"]],\n'
        '      "cnd": [],\n'
        '      "out": "(proj TRM (Voice))"\n'
        "    }\n"
        "  ]\n"
        "}\n",
        encoding="utf-8",
    )
    input_path.write_text(
        '[\n  ["a","b","c","a"]\n]\n',
        encoding="utf-8",
    )


def _compile_fst(att_path: Path, fst_path: Path) -> None:
    if shutil.which("fstcompile") is None:
        raise typer.BadParameter(
            "fstcompile not found on PATH. Install OpenFst or omit --fst."
        )
    with fst_path.open("wb") as out_handle:
        try:
            subprocess.run(
                ["fstcompile", str(att_path)],
                check=True,
                stdout=out_handle,
            )
        except subprocess.CalledProcessError as exc:
            raise typer.BadParameter(
                f"fstcompile failed with exit code {exc.returncode}."
            ) from exc


def _format_word_list(words: list[list[object]]) -> str:
    lines = ["["]
    for idx, word in enumerate(words):
        rendered_items: list[str] = []
        for item in word:
            if isinstance(item, str):
                rendered_items.append(json.dumps(item, ensure_ascii=False))
            else:
                rendered_items.append(
                    json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                )
        suffix = "," if idx < len(words) - 1 else ""
        lines.append(f'  [{",".join(rendered_items)}]{suffix}')
    lines.append("]")
    return "\n".join(lines) + "\n"


def _format_word_pairs(
    pairs: list[dict[str, list[object]]],
) -> str:
    lines = ["["]
    for idx, item in enumerate(pairs):
        input_word = item.get("input", [])
        output_word = item.get("output", [])
        input_rendered = _format_word_inline(input_word)
        output_rendered = _format_word_inline(output_word)
        suffix = "," if idx < len(pairs) - 1 else ""
        lines.append(
            f'  {{"input": {input_rendered}, "output": {output_rendered}}}{suffix}'
        )
    lines.append("]")
    return "\n".join(lines) + "\n"


def _format_word_inline(word: list[object]) -> str:
    rendered_items: list[str] = []
    for item in word:
        if isinstance(item, str):
            rendered_items.append(json.dumps(item, ensure_ascii=False))
        else:
            rendered_items.append(
                json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            )
    return f'[{",".join(rendered_items)}]'


def _diff_word_lists(
    expected: list[list[object]],
    actual: list[list[object]],
    *,
    max_diffs: int = 10,
) -> list[str]:
    diffs: list[str] = []
    word_count = min(len(expected), len(actual))
    for idx in range(word_count):
        if expected[idx] == actual[idx]:
            continue
        diffs.append(
            f"word {idx}: expected={_format_word_inline(expected[idx])} actual={_format_word_inline(actual[idx])}"
        )
        if len(diffs) >= max_diffs:
            break
    if len(expected) != len(actual) and len(diffs) < max_diffs:
        diffs.append(
            f"word count mismatch: expected={len(expected)} actual={len(actual)}"
        )
    return diffs


def _evaluate_with_reference(
    *,
    rule: Rule,
    words: list[object],
    feature_order: tuple[str, ...],
    symbol_to_bundle: dict[str, dict[str, str]],
    bundle_to_symbol: dict[tuple[str, ...], str],
    strict: bool,
) -> list[list[object]]:
    from .evaluator import evaluate_rule_on_bundles

    output_words: list[list[object]] = []
    for idx, word in enumerate(words):
        if not isinstance(word, list):
            raise typer.BadParameter(
                f"Word at index {idx} is not an array of symbols."
            )
        bundles: list[dict[str, str]] = []
        for sym in word:
            if not isinstance(sym, str) or not sym.strip():
                raise typer.BadParameter(
                    f"Word {idx} contains a non-string symbol."
                )
            if sym not in symbol_to_bundle:
                raise typer.BadParameter(
                    f"Word {idx} has unknown symbol: {sym!r}"
                )
            bundles.append(symbol_to_bundle[sym])
        evaluated = evaluate_rule_on_bundles(rule, bundles)
        output_syms: list[object] = []
        for bundle in evaluated:
            bundle_key = tuple(
                bundle.get(feature, "0") for feature in feature_order
            )
            if bundle_key not in bundle_to_symbol:
                if strict:
                    raise typer.BadParameter(
                        f"Output bundle has no symbol: {bundle_key}"
                    )
                output_syms.append(bundle)
            else:
                output_syms.append(bundle_to_symbol[bundle_key])
        output_words.append(output_syms)
    return output_words


def _evaluate_with_tv(
    *,
    rule: Rule,
    words: list[object],
    feature_order: tuple[str, ...],
    symbol_to_bundle: dict[str, dict[str, str]],
    bundle_to_symbol: dict[tuple[str, ...], str],
    strict: bool,
) -> list[list[object]]:
    from .tv_compiler import compile_tv, run_tv_machine

    machine = compile_tv(rule)
    v_order = machine.v_order
    if set(v_order) != set(feature_order):
        raise typer.BadParameter(
            "Alphabet features do not match TvMachine features: "
            f"alphabet={sorted(feature_order)}; tv={sorted(v_order)}"
        )
    output_words: list[list[object]] = []
    for idx, word in enumerate(words):
        if not isinstance(word, list):
            raise typer.BadParameter(
                f"Word at index {idx} is not an array of symbols."
            )
        word_symbols = word[::-1] if rule.dir == "RIGHT" else word
        bundles: list[dict[str, str]] = []
        for sym in word_symbols:
            if not isinstance(sym, str) or not sym.strip():
                raise typer.BadParameter(
                    f"Word {idx} contains a non-string symbol."
                )
            if sym not in symbol_to_bundle:
                raise typer.BadParameter(
                    f"Word {idx} has unknown symbol: {sym!r}"
                )
            bundles.append(symbol_to_bundle[sym])

        inputs = [
            _bundle_to_tv_tuple(bundle, v_order) for bundle in bundles
        ]
        outputs = run_tv_machine(machine, inputs)
        output_syms: list[object] = []
        for bundle_tuple in outputs:
            bundle = _tv_tuple_to_bundle(bundle_tuple, v_order)
            bundle_key = tuple(
                bundle.get(feature, "0") for feature in feature_order
            )
            if bundle_key not in bundle_to_symbol:
                if strict:
                    raise typer.BadParameter(
                        f"Output bundle has no symbol: {bundle_key}"
                    )
                output_syms.append(bundle)
            else:
                output_syms.append(bundle_to_symbol[bundle_key])
        if rule.dir == "RIGHT":
            output_syms = list(reversed(output_syms))
        output_words.append(output_syms)
    return output_words


def _bundle_to_tv_tuple(
    bundle: dict[str, str], v_order: tuple[str, ...]
) -> tuple[int, ...]:
    values: list[int] = []
    for feature in v_order:
        value = bundle.get(feature, "0")
        if value == "+":
            values.append(1)
        elif value == "-":
            values.append(2)
        else:
            values.append(0)
    return tuple(values)


def _tv_tuple_to_bundle(
    bundle: tuple[int, ...], v_order: tuple[str, ...]
) -> dict[str, str]:
    result: dict[str, str] = {}
    for feature, value in zip(v_order, bundle):
        if value == 1:
            result[feature] = "+"
        elif value == 2:
            result[feature] = "-"
    return result


def _evaluate_with_fst(
    *,
    rule: Rule,
    fst: Path,
    fst_symtab: Path | None,
    words: list[object],
    feature_order: tuple[str, ...],
    symbol_to_bundle: dict[str, dict[str, str]],
    bundle_to_symbol: dict[tuple[str, ...], str],
    strict: bool,
) -> list[list[object]]:
    _ensure_openfst_tools(
        ["fstcompile", "fstcompose", "fstshortestpath", "fstprint"]
    )
    symtab_path = fst_symtab or fst.with_suffix(".sym")
    if not symtab_path.exists():
        raise typer.BadParameter(
            f"Symbol table not found: {symtab_path}"
        )

    symtab = _load_symtab(symtab_path)
    v_order = _infer_feature_order(symtab.symbols)
    if set(v_order) != set(feature_order):
        raise typer.BadParameter(
            "Alphabet features do not match FST symtab features: "
            f"alphabet={sorted(feature_order)}; fst={sorted(v_order)}"
        )
    label_map = _build_label_map(symtab, v_order)

    output_words: list[list[object]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        for idx, word in enumerate(words):
            if not isinstance(word, list):
                raise typer.BadParameter(
                    f"Word at index {idx} is not an array of symbols."
                )
            word_symbols = word[::-1] if rule.dir == "RIGHT" else word
            input_symbols: list[str] = []
            for sym in word_symbols:
                if not isinstance(sym, str) or not sym.strip():
                    raise typer.BadParameter(
                        f"Word {idx} contains a non-string symbol."
                    )
                if sym not in symbol_to_bundle:
                    raise typer.BadParameter(
                        f"Word {idx} has unknown symbol: {sym!r}"
                    )
                bundle = symbol_to_bundle[sym]
                label = _bundle_to_label(
                    bundle, v_order, label_map
                )
                input_symbols.append(str(label))

            input_att = temp_root / f"input_{idx}.att"
            input_fst = temp_root / f"input_{idx}.fst"
            composed_fst = temp_root / f"composed_{idx}.fst"
            output_fst = temp_root / f"output_{idx}.fst"
            input_att.write_text(
                _render_input_att(input_symbols), encoding="utf-8"
            )

            _run_command(
                [
                    "fstcompile",
                    str(input_att),
                    str(input_fst),
                ],
            )
            _run_command(
                ["fstcompose", str(input_fst), str(fst), str(composed_fst)],
            )
            _run_command(
                ["fstshortestpath", str(composed_fst), str(output_fst)],
            )
            printed = _run_command(
                [
                    "fstprint",
                    str(output_fst),
                ],
                capture_stdout=True,
            )
            output_symbols = _parse_fstprint_output(printed)
            output_syms = _symbols_to_alphabet(
                output_symbols,
                v_order,
                feature_order,
                bundle_to_symbol,
                strict,
            )
            if rule.dir == "RIGHT":
                output_syms = list(reversed(output_syms))
            output_words.append(output_syms)

    return output_words


def _symbols_to_alphabet(
    symbols: list[str],
    v_order: tuple[str, ...],
    feature_order: tuple[str, ...],
    bundle_to_symbol: dict[tuple[str, ...], str],
    strict: bool,
) -> list[object]:
    output: list[object] = []
    for sym in symbols:
        if sym.isdigit():
            bundle = _decode_label_to_bundle(int(sym), v_order)
        else:
            bundle = _symbol_string_to_bundle(sym, v_order)
        bundle_key = tuple(bundle.get(feature, "0") for feature in feature_order)
        if bundle_key not in bundle_to_symbol:
            if strict:
                raise typer.BadParameter(
                    f"Output bundle has no symbol: {bundle_key}"
                )
            output.append(bundle)
        else:
            output.append(bundle_to_symbol[bundle_key])
    return output


def _build_label_map(
    symtab: _Symtab, v_order: tuple[str, ...]
) -> dict[tuple[str, ...], int]:
    mapping: dict[tuple[str, ...], int] = {}
    for symbol, label in symtab.symbols.items():
        if symbol == "<eps>":
            continue
        bundle = _symbol_string_to_bundle(symbol, v_order)
        bundle_key = tuple(
            bundle.get(feature, "0") for feature in v_order
        )
        mapping[bundle_key] = label
    return mapping


def _bundle_to_label(
    bundle: dict[str, str],
    v_order: tuple[str, ...],
    label_map: dict[tuple[str, ...], int],
) -> int:
    key = tuple(bundle.get(feature, "0") for feature in v_order)
    if key not in label_map:
        raise typer.BadParameter(
            f"Input bundle has no label: {key}"
        )
    return label_map[key]


def _decode_label_to_bundle(
    label: int, v_order: tuple[str, ...]
) -> dict[str, str]:
    if label <= 0:
        raise typer.BadParameter(
            f"Invalid label: {label}"
        )
    value = label - 1
    bundle: dict[str, str] = {}
    for feature in v_order:
        digit = value % 3
        if digit == 1:
            bundle[feature] = "+"
        elif digit == 2:
            bundle[feature] = "-"
        value //= 3
    return bundle


def _render_input_att(symbols: list[str]) -> str:
    if not symbols:
        return "0 0\n"
    lines: list[str] = []
    for idx, sym in enumerate(symbols):
        lines.append(f"{idx} {idx + 1} {sym} {sym} 0")
    lines.append(f"{len(symbols)} 0")
    return "\n".join(lines) + "\n"


def _parse_fstprint_output(text: str) -> list[str]:
    arcs: list[tuple[int, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        src = int(parts[0])
        olabel = parts[3]
        if olabel == "<eps>":
            continue
        arcs.append((src, olabel))
    arcs.sort(key=lambda item: item[0])
    return [olabel for _, olabel in arcs]


class _Symtab:
    def __init__(self, symbols: dict[str, int]):
        self.symbols = symbols


def _load_symtab(path: Path) -> _Symtab:
    symbols: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2:
            raise typer.BadParameter(
                f"Invalid symtab line: {line!r}"
            )
        symbol, label = parts
        symbols[symbol] = int(label)
    return _Symtab(symbols)


def _infer_feature_order(symbols: dict[str, int]) -> tuple[str, ...]:
    for symbol in symbols:
        if symbol == "<eps>":
            continue
        return tuple(_parse_symbol_part(part)[0] for part in symbol.split("_"))
    raise typer.BadParameter("Symtab contains no symbols.")


def _bundle_to_symbol_string(
    bundle: dict[str, str],
    v_order: tuple[str, ...],
    symtab: _Symtab,
) -> str:
    parts: list[str] = []
    for feature in v_order:
        value = bundle.get(feature, "0")
        if value not in {"+", "-", "0"}:
            raise typer.BadParameter(
                f"Invalid bundle value for {feature!r}: {value!r}"
            )
        parts.append(f"{feature}{value}")
    symbol = "_".join(parts)
    if symbol not in symtab.symbols:
        raise typer.BadParameter(
            f"Symbol not in symtab: {symbol!r}"
        )
    return symbol


def _symbol_string_to_bundle(
    symbol: str, v_order: tuple[str, ...]
) -> dict[str, str]:
    parts = symbol.split("_")
    if len(parts) != len(v_order):
        raise typer.BadParameter(
            f"Symbol does not match feature order: {symbol!r}"
        )
    bundle: dict[str, str] = {}
    for part, feature in zip(parts, v_order):
        name, value = _parse_symbol_part(part)
        if name != feature:
            raise typer.BadParameter(
                f"Symbol feature mismatch: {symbol!r}"
            )
        if value != "0":
            bundle[feature] = value
    return bundle


def _parse_symbol_part(part: str) -> tuple[str, str]:
    if not part:
        raise typer.BadParameter("Empty symbol part.")
    value = part[-1]
    name = part[:-1]
    if value not in {"+", "-", "0"} or not name:
        raise typer.BadParameter(
            f"Invalid symbol part: {part!r}"
        )
    return name, value


def _ensure_openfst_tools(tools: list[str]) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise typer.BadParameter(
            "OpenFst tools not found on PATH: " + ", ".join(missing)
        )


def _run_command(
    args: list[str],
    *,
    stdout_path: Path | None = None,
    capture_stdout: bool = False,
) -> str:
    if stdout_path is not None and capture_stdout:
        raise typer.BadParameter("Invalid command configuration.")
    if stdout_path is not None:
        try:
            result = subprocess.run(
                args,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (
                exc.stderr.decode().strip()
                if exc.stderr
                else ""
            )
            stdout = (
                exc.stdout.decode().strip()
                if exc.stdout
                else ""
            )
            message = stderr or stdout
            raise typer.BadParameter(
                _format_command_error(args[0], exc.returncode, message)
            ) from exc
        if result.stderr:
            stderr = result.stderr.decode().strip()
            if stderr:
                raise typer.BadParameter(
                    _format_command_error(args[0], 0, stderr)
                )
        stdout_path.write_bytes(result.stdout)
        return ""
    if capture_stdout:
        try:
            result = subprocess.run(
                args, check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else ""
            raise typer.BadParameter(
                _format_command_error(args[0], exc.returncode, stderr)
            ) from exc
        return result.stdout
    try:
        subprocess.run(args, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = (
            exc.stderr.decode().strip() if exc.stderr else ""
        )
        stdout = (
            exc.stdout.decode().strip() if exc.stdout else ""
        )
        message = stderr or stdout
        raise typer.BadParameter(
            _format_command_error(args[0], exc.returncode, message)
        ) from exc
    return ""


def _format_command_error(cmd: str, code: int, stderr: str) -> str:
    if stderr:
        return f"Command failed ({cmd}): {stderr}"
    return f"Command failed with exit code {code}: {cmd}"


def main() -> None:
    app(prog_name="snc2fst")


if __name__ == "__main__":
    main()
