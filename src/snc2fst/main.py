from __future__ import annotations

import csv
import io
import json
import tomllib
from pathlib import Path

import typer
from pydantic import ValidationError

from ._version import __version__
from .alphabet import Alphabet, format_validation_error
from .out_dsl import OutDslError, evaluate_out_dsl
from .rules import RulesFile, Rule
from .compile_pynini_fst import (
    compile_pynini_fst,
    evaluate_with_pynini,
    to_optimal,
    write_att_pynini,
)


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


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"Invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc


def _load_toml(path: Path) -> object:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise typer.BadParameter(
            f"Invalid TOML: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc


def _load_rules_payload(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = _load_json(path)
    elif suffix == ".toml":
        payload = _load_toml(path)
    else:
        raise typer.BadParameter(
            "Rules file must be a .json or .toml file."
        )
    if not isinstance(payload, dict):
        raise typer.BadParameter(
            "Rules file must be an object/table with a 'rules' array."
        )
    return payload


def _load_rules_file(path: Path) -> RulesFile:
    payload = _load_rules_payload(path)
    try:
        return RulesFile.model_validate(payload)
    except ValidationError as exc:
        raise typer.BadParameter(format_validation_error(exc)) from exc


def _load_input_payload(path: Path) -> list[object]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = _load_json(path)
        if not isinstance(payload, list):
            raise typer.BadParameter(
                "Input JSON must be an array of words (arrays of symbols)."
            )
        return payload
    if suffix == ".toml":
        payload = _load_toml(path)
        if not isinstance(payload, dict):
            raise typer.BadParameter(
                "Input TOML must be a table containing an 'inputs' array."
            )
        inputs = payload.get("inputs")
        if not isinstance(inputs, list):
            raise typer.BadParameter(
                "Input TOML must define 'inputs' as an array of words."
            )
        return inputs
    raise typer.BadParameter(
        "Input file must be a .json or .toml file."
    )


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


def _validate_rules_against_alphabet(
    rules_file: RulesFile, alphabet_features: set[str]
) -> None:
    for rule in rules_file.rules:
        _validate_rule_features(rule, alphabet_features, "inr")
        _validate_rule_features(rule, alphabet_features, "trm")
        _validate_rule_features(rule, alphabet_features, "cnd")
        try:
            evaluate_out_dsl(
                rule.out,
                inr=_bundle_from_rule(rule, "inr"),
                trm=_bundle_from_rule(rule, "trm"),
                features=alphabet_features,
            )
        except OutDslError as exc:
            raise typer.BadParameter(
                f"Rule {rule.id} out is invalid: {exc}"
            ) from exc


def _validate_rules_file(
    rules_path: Path, alphabet_path: Path | None
) -> RulesFile:
    if alphabet_path is None:
        raise typer.BadParameter(
            "Rules validation requires an alphabet CSV/TSV file. "
            f"Try: snc2fst validate rules {rules_path} alphabet.csv"
        )

    features = _load_alphabet_features(alphabet_path)
    rules_file = _load_rules_file(rules_path)
    _validate_rules_against_alphabet(rules_file, features)
    return rules_file


def _validate_input_words(
    input_path: Path, alphabet_path: Path | None
) -> None:
    if alphabet_path is None:
        raise typer.BadParameter(
            "Input validation requires an alphabet file. "
            f"Try: snc2fst validate input {input_path} alphabet.csv"
        )
    alphabet_data = _load_alphabet(alphabet_path)
    symbols = {row.symbol for row in alphabet_data.rows}
    payload = _load_input_payload(input_path)
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


validate_app = typer.Typer(
    help="Validate rules, alphabet, or input words."
)
app.add_typer(validate_app, name="validate")


@validate_app.command("rules")
def validate_rules(
    rules: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Rules JSON/TOML file to validate.",
    ),
    alphabet: Path = typer.Argument(
        ...,
        dir_okay=False,
        readable=True,
        help="Alphabet CSV/TSV file for rule validation.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress success output.",
    ),
    dump_vp: bool = typer.Option(
        False,
        "--dump-vp",
        help="Print V and P feature sets for rules.",
    ),
    fst_stats: bool = typer.Option(
        False,
        "--fst-stats",
        help="Print estimated states/arcs for the compiled FST.",
    ),
) -> None:
    """Validate a rules JSON/TOML file."""
    rules_file = _validate_rules_file(rules, alphabet)
    rules_list = rules_file.rules
    if dump_vp or fst_stats:
        from .feature_analysis import compute_p_features, compute_v_features

        alphabet_features = _load_alphabet_features(alphabet)
        for rule in rules_list:
            v_features = sorted(
                compute_v_features(
                    rule, alphabet_features=alphabet_features
                )
            )
            p_features = sorted(
                compute_p_features(
                    rule, alphabet_features=alphabet_features
                )
            )
            if dump_vp:
                typer.echo(f"{rule.id} V: {', '.join(v_features)}")
                typer.echo(f"{rule.id} P: {', '.join(p_features)}")
            if fst_stats:
                v_size = len(v_features)
                p_size = len(p_features)
                state_count = 1 + (3 ** p_size)
                arc_count = state_count * (3 ** v_size)
                typer.echo(
                    f"{rule.id} states: {state_count} arcs: {arc_count}"
                )
    if not quiet:
        typer.echo("OK")


@validate_app.command("alphabet")
def validate_alphabet(
    alphabet: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Alphabet CSV/TSV file to validate.",
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
    """Validate an alphabet CSV/TSV file."""
    _table_to_json(alphabet, delimiter)
    if not quiet:
        typer.echo("OK")


@validate_app.command("input")
def validate_input(
    input_words: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Input JSON/TOML words file (each word is an array of symbols).",
    ),
    alphabet: Path = typer.Argument(
        ...,
        dir_okay=False,
        readable=True,
        help="Alphabet CSV/TSV file for input validation.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress success output.",
    ),
) -> None:
    """Validate an input word list."""
    _validate_input_words(input_words, alphabet)
    if not quiet:
        typer.echo("OK")


@app.command("compile")
def compile_rule(
    rules: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Rules JSON/TOML file to compile.",
    ),
    alphabet: Path = typer.Argument(
        ...,
        dir_okay=False,
        readable=True,
        help="Alphabet CSV/TSV file for rule validation.",
    ),
    output: Path = typer.Argument(
        ...,
        dir_okay=True,
        writable=True,
        help="AT&T output path (file for single rule, directory for multiple).",
    ),
    rule_id: str | None = typer.Option(
        None,
        "--rule-id",
        help="Rule id to compile (required if multiple rules).",
    ),
    symtab: Path | None = typer.Option(
        None,
        "--symtab",
        dir_okay=False,
        writable=True,
        help="Symbol table output path (defaults next to output).",
    ),
    fst: bool = typer.Option(
        False,
        "--fst",
        help=(
            "Write a compiled FST binary using Pynini "
            "(uses output path/dir)."
        ),
    ),
    max_arcs: int = typer.Option(
        5_000_000,
        "--max-arcs",
        min=1,
        help="Maximum allowed arcs before aborting compilation.",
    ),
    progress: bool = typer.Option(
        False,
        "--progress",
        "-p",
        help="Show a progress bar during compilation.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show extra optimization details.",
    ),
    normalize: bool = typer.Option(
        False,
        "--normalize",
        "-n",
        help="Normalize the compiled FST (determinize -> minimize).",
    ),
    no_epsilon: bool = typer.Option(
        False,
        "--no-epsilon",
        help="Fail if the normalized FST contains any epsilon transitions.",
    ),
) -> None:
    """Compile a single rule into AT&T text format (always writes .att and .sym).

    The compiled machine is canonical LEFT; RIGHT direction is handled by
    reversing input/output at evaluation time.
    This command requires Pynini/pywrapfst.
    """
    rules_path = rules
    rules_file = _load_rules_file(rules_path)
    rules_list = rules_file.rules

    from .feature_analysis import compute_p_features, compute_v_features

    features = _load_alphabet_features(alphabet)
    _validate_rules_against_alphabet(rules_file, features)

    if rule_id is not None:
        selected_rules = [_select_rule(rules_list, rule_id)]
    else:
        selected_rules = list(rules_list)

    if len(selected_rules) > 1:
        if output.suffix:
            raise typer.BadParameter(
                "When compiling multiple rules, output must be a directory."
            )
        output_dir = output
        output_dir.mkdir(parents=True, exist_ok=True)
        if symtab is not None:
            raise typer.BadParameter(
                "--symtab is only valid when compiling a single rule."
            )
    else:
        output_dir = None
        if output.exists() and output.is_dir():
            raise typer.BadParameter(
                "When compiling a single rule, output must be a file path."
            )

    total_rules = len(selected_rules)
    for idx, rule in enumerate(selected_rules, start=1):
        prefix = (
            f"[{idx}/{total_rules}] {rule.id}"
            if total_rules > 1
            else f"{rule.id}"
        )
        _enforce_arc_limit(rule, max_arcs, alphabet_features=features)
        v_features = compute_v_features(rule, alphabet_features=features)
        p_features = compute_p_features(rule, alphabet_features=features)
        machine = compile_pynini_fst(
            rule,
            show_progress=progress,
            v_features=v_features,
            p_features=p_features,
        )
        before_counts = None
        if normalize:
            before_counts = _count_fst_states_arcs(machine.fst)
            machine = to_optimal(machine)
            after_counts = _count_fst_states_arcs(machine.fst)
            if before_counts == after_counts:
                if verbose:
                    typer.echo(
                        "normalize: no reduction in states/arcs after determinize/minimize"
                    )
        if no_epsilon and _has_epsilon_arcs(machine.fst):
            raise typer.BadParameter(
                "FST contains epsilon transitions; "
                "remove epsilons or omit --no-epsilon."
            )
        no_eps_label = "no-eps" if no_epsilon else None
        if progress:
            typer.echo("writing output...")

        if output_dir is None:
            att_path = output
        else:
            att_path = output_dir / f"{rule.id}.att"
        if normalize:
            att_path = att_path.with_suffix(".norm.att")
        if symtab is not None and output_dir is None:
            symtab_path = symtab
        else:
            symtab_path = att_path.with_suffix(".sym")
        write_att_pynini(machine, att_path, symtab_path=symtab_path)
        if fst:
            if output_dir is None:
                fst_out = att_path.with_suffix(".fst")
                machine.fst.write(str(fst_out))
            else:
                fst_out = output_dir / f"{rule.id}.fst"
                machine.fst.write(str(fst_out))
        state_count, arc_count = _count_fst_states_arcs(machine.fst)
        parts = [
            prefix,
            f"states={state_count} arcs={arc_count}",
            f"att={att_path} sym={symtab_path}",
        ]
        if fst:
            parts.append(f"fst={fst_out}")
        if no_eps_label:
            parts.append(no_eps_label)
        typer.echo(" | ".join(parts))


@app.command("eval")
def eval_rule(
    rules: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Rules JSON/TOML file to evaluate.",
    ),
    alphabet: Path = typer.Argument(
        ...,
        dir_okay=False,
        readable=True,
        help="Alphabet CSV/TSV file used to map symbols to bundles.",
    ),
    input_words: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Input JSON/TOML words file (each word is an array of symbols).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        dir_okay=False,
        writable=True,
        help="Output file for evaluated words (defaults to rules id).",
    ),
    rule_id: str | None = typer.Option(
        None,
        "--rule-id",
        help="Rule id to evaluate (required if multiple rules).",
    ),
    include_input: bool = typer.Option(
        False,
        "--include-input",
        help="Include per-rule input and output in the result table.",
    ),
    pynini: bool = typer.Option(
        False,
        "--pynini",
        help="Use Pynini/pywrapfst to evaluate words.",
    ),
    compare: bool = typer.Option(
        False,
        "--compare",
        help="Compare Pynini output to the reference evaluator.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail if an output bundle has no matching symbol in the alphabet.",
    ),
    dump_vp: bool = typer.Option(
        False,
        "--dump-vp",
        help="Print V and P feature sets for debugging.",
    ),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format (json, txt, csv, tsv).",
        show_choices=True,
        case_sensitive=False,
    ),
) -> None:
    """Evaluate rules against an input word list.

    The compiled machine is canonical LEFT; RIGHT rules are evaluated by
    reversing input/output around the machine.
    """
    rules_path = rules
    rules_file = _load_rules_file(rules_path)
    rules_list = rules_file.rules

    alphabet_data = _load_alphabet(alphabet)
    feature_order = tuple(alphabet_data.feature_schema.features)
    features = set(feature_order)
    _validate_rules_against_alphabet(rules_file, features)

    from .feature_analysis import compute_p_features, compute_v_features

    if rule_id is not None:
        selected_rules = [_select_rule(rules_list, rule_id)]
    else:
        selected_rules = list(rules_list)
    segments = _load_input_payload(input_words)

    symbol_to_bundle: dict[str, dict[str, str]] = {}
    bundle_to_symbol: dict[tuple[str, ...], str] = {}
    for row in alphabet_data.rows:
        symbol_to_bundle[row.symbol] = dict(row.features)
        bundle_key = tuple(row.features[feature] for feature in feature_order)
        if bundle_key in bundle_to_symbol:
            raise typer.BadParameter(
                f"Alphabet has multiple symbols for bundle: {bundle_key}"
            )
        bundle_to_symbol[bundle_key] = row.symbol

    if compare:
        pynini = True

    current_words = segments
    table_rows: list[dict[str, object]] = []
    alphabet_features = set(feature_order)

    for rule in selected_rules:
        v_features = compute_v_features(
            rule, alphabet_features=alphabet_features
        )
        p_features = compute_p_features(
            rule, alphabet_features=alphabet_features
        )
        v_order = (
            feature_order
            if v_features == alphabet_features
            else tuple(sorted(v_features))
        )
        if dump_vp:
            v_features_sorted = sorted(v_features)
            p_features_sorted = sorted(p_features)
            typer.echo(f"{rule.id} V: {', '.join(v_features_sorted)}")
            typer.echo(f"{rule.id} P: {', '.join(p_features_sorted)}")

        if pynini:
            output_words = _evaluate_with_pynini(
                rule=rule,
                words=current_words,
                feature_order=feature_order,
                symbol_to_bundle=symbol_to_bundle,
                bundle_to_symbol=bundle_to_symbol,
                strict=strict,
                v_features=v_features,
                p_features=p_features,
            )
            if compare:
                ref_words = _evaluate_with_reference(
                    rule=rule,
                    words=current_words,
                    feature_order=feature_order,
                    symbol_to_bundle=symbol_to_bundle,
                    bundle_to_symbol=bundle_to_symbol,
                    strict=strict,
                    v_order=v_order,
                )
                diffs = _diff_word_lists(ref_words, output_words)
                if diffs:
                    message = (
                        "Pynini output differs from reference:\n"
                        + "\n".join(diffs)
                    )
                    raise typer.BadParameter(message)
        else:
            output_words = _evaluate_with_reference(
                rule=rule,
                words=current_words,
                feature_order=feature_order,
                symbol_to_bundle=symbol_to_bundle,
                bundle_to_symbol=bundle_to_symbol,
                strict=strict,
                v_order=v_order,
            )

        if include_input:
            table_rows.append(
                {
                    "rule_id": rule.id,
                    "input": current_words,
                    "output": output_words,
                }
            )
        else:
            table_rows.append(
                {"rule_id": rule.id, "outputs": output_words}
            )

        current_words = output_words

    table = {
        "id": rules_file.id,
        "inputs": segments,
        "rows": table_rows,
    }
    output_format = output_format.lower()
    valid_formats = {"json", "txt", "csv", "tsv"}
    if output_format not in valid_formats:
        raise typer.BadParameter(
            "--format must be one of: " + ", ".join(sorted(valid_formats))
        )
    if output is None:
        suffix = output_format if output_format != "json" else "json"
        output = rules_path.with_name(f"{rules_file.id}.out.{suffix}")

    if output_format == "json":
        rendered = json.dumps(table, ensure_ascii=False, indent=2) + "\n"
        output.write_text(rendered, encoding="utf-8")
    else:
        headers = ["UR"] + [_format_word_compact(word) for word in segments]
        rows: list[list[str]] = []
        last_outputs: list[list[object]] = segments
        for row_idx, row in enumerate(table_rows):
            outputs = row.get("outputs")
            if outputs is None:
                outputs = row.get("output", [])
            last_outputs = outputs
            prev_outputs: list[list[object]]
            if row_idx == 0:
                prev_outputs = segments
            else:
                prev_row = table_rows[row_idx - 1]
                prev_outputs = prev_row.get("outputs")
                if prev_outputs is None:
                    prev_outputs = prev_row.get("output", [])
            rendered_outputs: list[str] = []
            for idx, word in enumerate(outputs):
                if idx < len(prev_outputs) and word == prev_outputs[idx]:
                    rendered_outputs.append("---")
                else:
                    rendered_outputs.append(_format_word_compact(word))
            rows.append([str(row.get("rule_id", ""))] + rendered_outputs)
        final_rendered = [_format_word_compact(word) for word in last_outputs]
        rows.append(["SR"] + final_rendered)

        if output_format == "txt":
            rendered = _render_ascii_table(headers, rows)
            output.write_text(rendered, encoding="utf-8")
        else:
            delimiter = "," if output_format == "csv" else "\t"
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter=delimiter)
            writer.writerow(headers)
            writer.writerows(rows)
            output.write_text(buffer.getvalue(), encoding="utf-8")
    typer.echo("OK")


@app.command("init")
def init_samples(
    output_dir: Path = typer.Argument(
        Path("."),
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
    """Generate sample alphabet.csv, rules.toml, and input.toml files.

    The sample alphabet has 3 features and 27 symbols, the rules file has
    one rule, and the input file includes multiple example sentences.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    alphabet_path = output_dir / "alphabet.csv"
    rules_path = output_dir / "rules.toml"
    input_path = output_dir / "input.toml"

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

    features = ["F1", "F2", "F3"]
    digits = [0, 1, 2]
    symbols = ["0"] + [chr(code) for code in range(ord("A"), ord("Z") + 1)]
    value_map = {0: "0", 1: "+", 2: "-"}
    header = "," + ",".join(symbols)
    rows = [header]
    for idx, feature in enumerate(features):
        values = []
        for sym_index in range(len(symbols)):
            digit = (sym_index // (3 ** idx)) % 3
            values.append(value_map[digit])
        rows.append(f"{feature}," + ",".join(values))
    alphabet_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    rules_text = (
        'id = "sample_rules"\n'
        "\n"
        "[[rules]]\n"
        'id = "spread_f1_right"\n'
        'dir = "RIGHT"\n'
        'inr = [["+", "F1"]]\n'
        'trm = [["+", "F2"]]\n'
        "cnd = []\n"
        'out = "(proj TRM (F1))"\n'
    )
    rules_path.write_text(rules_text, encoding="utf-8")
    input_words = [
        ["0", "A", "B", "C", "D"],
        ["J", "K", "L"],
        ["T", "U", "V", "W", "X", "Y", "Z"],
    ]
    input_text = "inputs = " + _format_word_list(input_words).rstrip() + "\n"
    input_path.write_text(input_text, encoding="utf-8")
    base = Path.cwd().resolve()
    def _relpath(path: Path) -> Path:
        resolved = path.resolve()
        try:
            return resolved.relative_to(base)
        except ValueError:
            return resolved
    typer.echo("OK")
    typer.echo(f"alphabet: {_relpath(alphabet_path)}")
    typer.echo(f"rules: {_relpath(rules_path)}")
    typer.echo(f"input: {_relpath(input_path)}")


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


def _format_word_compact(word: list[object]) -> str:
    return "".join(str(item) for item in word)


def _render_ascii_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def render_row(cells: list[str]) -> str:
        padded = [cell.ljust(widths[idx]) for idx, cell in enumerate(cells)]
        return "| " + " | ".join(padded) + " |"

    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    lines = [separator, render_row(headers), separator]
    for row in rows:
        lines.append(render_row(row))
        lines.append(separator)
    return "\n".join(lines) + "\n"


def _enforce_arc_limit(
    rule: Rule, max_arcs: int, *, alphabet_features: set[str] | None = None
) -> None:
    from .feature_analysis import compute_p_features, compute_v_features

    v_size = len(
        compute_v_features(rule, alphabet_features=alphabet_features)
    )
    p_size = len(
        compute_p_features(rule, alphabet_features=alphabet_features)
    )
    arc_count = (1 + (3 ** p_size)) * (3 ** v_size)
    if arc_count > max_arcs:
        raise typer.BadParameter(
            "Estimated arcs exceed --max-arcs: "
            f"{arc_count} > {max_arcs} (|V|={v_size}, |P|={p_size})"
        )


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


def _count_fst_states_arcs(fst_obj: object) -> tuple[int, int]:
    arc_count = 0
    state_count = 0
    for state in fst_obj.states():
        state_count += 1
        arc_count += sum(1 for _ in fst_obj.arcs(state))
    return state_count, arc_count


def _has_epsilon_arcs(fst_obj: object) -> bool:
    for state in fst_obj.states():
        for arc in fst_obj.arcs(state):
            if arc.ilabel == 0 or arc.olabel == 0:
                return True
    return False


def _evaluate_with_reference(
    *,
    rule: Rule,
    words: list[object],
    feature_order: tuple[str, ...],
    symbol_to_bundle: dict[str, dict[str, str]],
    bundle_to_symbol: dict[tuple[str, ...], str],
    strict: bool,
    v_order: tuple[str, ...] | None = None,
) -> list[list[object]]:
    from .evaluator import (
        evaluate_rule_on_bundles,
        evaluate_rule_on_bundles_with_order,
    )

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
        if v_order is None:
            evaluated = evaluate_rule_on_bundles(rule, bundles)
        else:
            evaluated = evaluate_rule_on_bundles_with_order(
                rule, bundles, v_order
            )
            v_set = set(v_order)
            reconstructed: list[dict[str, str]] = []
            for input_bundle, out_bundle in zip(bundles, evaluated):
                recon = {
                    feature: value
                    for feature, value in input_bundle.items()
                    if feature not in v_set
                }
                recon.update(out_bundle)
                reconstructed.append(recon)
            evaluated = reconstructed
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


def _evaluate_with_pynini(
    *,
    rule: Rule,
    words: list[object],
    feature_order: tuple[str, ...],
    symbol_to_bundle: dict[str, dict[str, str]],
    bundle_to_symbol: dict[tuple[str, ...], str],
    strict: bool,
    v_features: set[str] | None = None,
    p_features: set[str] | None = None,
) -> list[list[object]]:
    return evaluate_with_pynini(
        rule=rule,
        words=words,
        feature_order=feature_order,
        symbol_to_bundle=symbol_to_bundle,
        bundle_to_symbol=bundle_to_symbol,
        strict=strict,
        v_features=v_features,
        p_features=p_features,
    )


def main() -> None:
    app(prog_name="snc2fst")


if __name__ == "__main__":
    main()
