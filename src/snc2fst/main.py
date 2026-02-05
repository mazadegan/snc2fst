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
from .compile_pynini_fst import (
    compile_pynini_fst,
    evaluate_with_pynini,
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
) -> list[Rule]:
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
    return rules


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
    """Validate a rules JSON, alphabet CSV/TSV, or input words JSON."""
    kind_value = kind.lower() if kind else None
    if kind_value is None:
        if input_path.suffix.lower() == ".json":
            try:
                payload = _load_json(input_path)
            except typer.BadParameter:
                payload = None
            if isinstance(payload, dict) and "rules" in payload:
                kind_value = "rules"
            elif isinstance(payload, list):
                kind_value = "input"
            else:
                raise typer.BadParameter(
                    "Unable to infer JSON kind; use --kind."
                )
        else:
            kind_value = "alphabet"

    if kind_value == "rules":
        rules = _validate_rules_file(input_path, alphabet)
        if dump_vp or fst_stats:
            from .feature_analysis import compute_p_features, compute_v_features
            if alphabet is None:
                raise typer.BadParameter(
                    "--dump-vp/--fst-stats requires --alphabet."
                )
            alphabet_features = _load_alphabet_features(alphabet)

            for rule in rules:
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
    elif kind_value == "alphabet":
        if dump_vp or fst_stats:
            raise typer.BadParameter(
                "--dump-vp/--fst-stats is only valid for rules validation."
            )
        _table_to_json(input_path, delimiter)
    elif kind_value == "input":
        if dump_vp or fst_stats:
            raise typer.BadParameter(
                "--dump-vp/--fst-stats is only valid for rules validation."
            )
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
    pynini_fst: Path | None = typer.Option(
        None,
        "--pynini",
        dir_okay=False,
        writable=True,
        help="Write a compiled FST binary using Pynini.",
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
        help="Show a progress bar during compilation.",
    ),
) -> None:
    """Compile a single rule into AT&T text format (always writes .att and .sym).

    The compiled machine is canonical LEFT; RIGHT direction is handled by
    reversing input/output at evaluation time.
    This command requires Pynini/pywrapfst.
    """
    payload = _load_json(rules_path)
    try:
        rules = RulesFile.model_validate(payload).rules
    except ValidationError as exc:
        raise typer.BadParameter(format_validation_error(exc)) from exc

    from .feature_analysis import compute_p_features, compute_v_features

    features: set[str] | None = None
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
    _enforce_arc_limit(rule, max_arcs, alphabet_features=features)
    v_features = (
        compute_v_features(rule, alphabet_features=features)
        if features is not None
        else None
    )
    p_features = (
        compute_p_features(rule, alphabet_features=features)
        if features is not None
        else None
    )
    machine = compile_pynini_fst(
        rule,
        show_progress=progress,
        v_features=v_features,
        p_features=p_features,
    )
    if progress:
        typer.echo("writing output...")

    if symtab is not None:
        symtab_path = symtab
    else:
        symtab_path = output.with_suffix(".sym")
    write_att_pynini(machine, output, symtab_path=symtab_path)
    if pynini_fst is not None:
        machine.fst.write(str(pynini_fst))
    arc_count = 0
    for state in machine.fst.states():
        arc_count += sum(1 for _ in machine.fst.arcs(state))
    state_count = machine.fst.num_states()
    symtab_display = symtab_path
    typer.echo(
        f"done. states={state_count} arcs={arc_count}"
    )
    typer.echo(f"att: {output}")
    typer.echo(f"symtab: {symtab_display}")
    if pynini_fst is not None:
        typer.echo(f"fst: {pynini_fst}")


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
    feature_order = tuple(alphabet_data.feature_schema.features)
    features = set(feature_order)
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
    from .feature_analysis import compute_p_features, compute_v_features

    alphabet_features = set(feature_order)
    v_features = compute_v_features(rule, alphabet_features=alphabet_features)
    p_features = compute_p_features(rule, alphabet_features=alphabet_features)
    v_order = (
        feature_order
        if v_features == alphabet_features
        else tuple(sorted(v_features))
    )
    if dump_vp:
        v_features_sorted = sorted(v_features)
        p_features_sorted = sorted(p_features)
        typer.echo(f"V: {', '.join(v_features_sorted)}")
        typer.echo(f"P: {', '.join(p_features_sorted)}")
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

    if pynini:
        output_words = _evaluate_with_pynini(
            rule=rule,
            words=segments,
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
                words=segments,
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
            v_order=v_order,
        )
        if include_input:
            results_with_input = [
                {"input": word, "output": output_word}
                for word, output_word in zip(segments, output_words)
            ]
        if compare:
            raise typer.BadParameter("--compare requires --pynini.")

    if include_input:
        rendered = _format_word_pairs(results_with_input)
    else:
        rendered = _format_word_list(output_words)
    output.write_text(rendered, encoding="utf-8")


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
    """Generate sample alphabet.csv, rules.json, and input.json files.

    The sample alphabet has 3 features and 27 symbols, the rules file has
    two rules, and the input file includes multiple example sentences.
    """
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
        "{\n"
        '  "rules": [\n'
        "    {\n"
        '      "id": "spread_f1_right",\n'
        '      "dir": "RIGHT",\n'
        '      "inr": [["+","F1"]],\n'
        '      "trm": [["+", "F2"]],\n'
        '      "cnd": [],\n'
        '      "out": "(proj TRM (F1))"\n'
        "    },\n"
        "    {\n"
        '      "id": "set_f3_left",\n'
        '      "dir": "LEFT",\n'
        '      "inr": [],\n'
        '      "trm": [],\n'
        '      "cnd": [],\n'
        '      "out": "(lit + F3)"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )
    rules_path.write_text(rules_text, encoding="utf-8")
    input_text = (
        "[\n"
        '  ["0", "A", "B", "C", "D"],\n'
        '  ["J", "K", "L"],\n'
        '  ["T", "U", "V", "W", "X", "Y", "Z"]\n'
        "]\n"
    )
    input_path.write_text(input_text, encoding="utf-8")


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
