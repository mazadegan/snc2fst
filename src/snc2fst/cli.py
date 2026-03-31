import sys
import traceback
import click
import importlib.resources
import itertools
from pathlib import Path

import tomllib
import pynini
from pydantic import ValidationError
from snc2fst.models import GrammarConfig
from snc2fst.alphabet import TokenizeError, check_alphabet, load_alphabet, tokenize, word_to_str
from snc2fst.io import load_tests
from snc2fst import dsl
from snc2fst.evaluator import EvalError, apply_rule
from snc2fst.table import build_table, format_latex, format_txt
from snc2fst.compiler import CompileError, compile_rule, compute_alphabets, predict_arcs


def _load_config(config_file) -> GrammarConfig:
    with open(config_file, "rb") as f:
        raw_dict = tomllib.load(f)
    return GrammarConfig(**raw_dict)


def _resolve_language(raw: str) -> tuple[str, str | None]:
    """Resolve a language name or code to (code, display_name).

    If the input is unrecognized, returns (raw, None) so the caller can warn.
    """
    import langcodes
    stripped = raw.strip()

    # Try as a direct code first (1-3 alpha chars, typical for 639 codes).
    try:
        lang = langcodes.get(stripped)
        if lang.is_valid():
            return lang.to_alpha3(), lang.display_name()
    except Exception:
        pass

    # Try name search.
    try:
        found = langcodes.find(stripped)
        if found.is_valid():
            return found.to_alpha3(), found.display_name()
    except LookupError:
        pass

    return stripped, None


def _run_meta_wizard(config_path: Path) -> None:
    """Interactively collect metadata and patch [meta] in the written config."""
    import questionary

    click.echo("\nNew project setup — please provide some metadata.")
    click.echo("(Press Enter to skip optional fields.)\n")

    title = questionary.text("Grammar title:").ask()
    if title is None:
        raise click.Abort()

    lang_raw = questionary.text("Language name or ISO 639-3 code:").ask()
    if lang_raw is None:
        raise click.Abort()

    lang_code, lang_display = _resolve_language(lang_raw)
    if lang_display is None:
        click.echo(
            f"  [!] '{lang_raw}' is not a recognized ISO 639 code or language name. "
            "It will be stored as-is.",
            err=True,
        )
    else:
        click.echo(f"  → Resolved to: {lang_display} ({lang_code})")

    description = questionary.text("Description (optional):").ask() or ""
    if description is None:
        raise click.Abort()

    sources: list[str] = []
    click.echo("Sources/references (optional) — enter one per line, blank line to finish:")
    while True:
        entry = questionary.text("  Source:").ask()
        if entry is None:
            raise click.Abort()
        if not entry.strip():
            break
        sources.append(entry.strip())

    click.echo()

    # Patch the [meta] block in the written config file.
    text = config_path.read_text(encoding="utf-8")

    def _toml_escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    def _toml_str_list(items: list[str]) -> str:
        return "[" + ", ".join(f'"{_toml_escape(s)}"' for s in items) + "]"

    text = text.replace('title = ""', f'title = "{_toml_escape(title)}"', 1)
    text = text.replace('language = ""', f'language = "{_toml_escape(lang_code)}"', 1)
    text = text.replace('description = ""', f'description = "{_toml_escape(description)}"', 1)
    text = text.replace('sources = []', f'sources = {_toml_str_list(sources)}', 1)
    # Remove the comment line added by the template.
    text = text.replace("\n# [meta] is filled in by `snc init` — do not edit manually.", "", 1)

    config_path.write_text(text, encoding="utf-8")


@click.group()
def main():
    """SNC: Compile Search-and-Change grammars to OpenFST transducers."""
    pass


@main.command()
@click.option(
    "--filename",
    "-f",
    default="config.toml",
    help="Name of the main configuration file to generate.",
)
@click.option(
    "--from",
    "from_starter",
    default=None,
    help="Initialize from a named starter project.",
)
@click.option(
    "--pick",
    "pick_starter",
    is_flag=True,
    default=False,
    help="Interactively choose a starter project.",
)
def init(filename, from_starter, pick_starter):
    """Initialize a new grammar configuration and supporting template files."""
    config_path = Path(filename)
    dir_path = config_path.parent

    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    templates_dir = importlib.resources.files("snc2fst").joinpath("templates")

    if from_starter is not None and pick_starter:
        click.echo("Error: --from and --pick are mutually exclusive.", err=True)
        raise click.Abort()

    if pick_starter:
        available = sorted(p.name for p in starters_dir.iterdir() if p.is_dir())
        if not sys.stdin.isatty():
            click.echo(
                "Error: --pick requires an interactive terminal. Use --from NAME instead.",
                err=True,
            )
            click.echo(f"Available starters: {', '.join(available)}", err=True)
            raise click.Abort()
        import questionary
        from_starter = questionary.select(
            "Choose a starter:", choices=available
        ).ask()
        if from_starter is None:
            raise click.Abort()

    if from_starter is not None:
        available = sorted(p.name for p in starters_dir.iterdir() if p.is_dir())
        if from_starter not in available:
            click.echo(
                f"Error: unknown starter '{from_starter}'. Available: {', '.join(available)}",
                err=True,
            )
            raise click.Abort()

        source_dir = starters_dir.joinpath(from_starter)
        source_files = [
            (config_path, source_dir.joinpath("config.toml")),
            (dir_path / "alphabet.csv", source_dir.joinpath("alphabet.csv")),
            (dir_path / "tests.tsv", source_dir.joinpath("tests.tsv")),
        ]
    else:
        source_files = [
            (config_path, templates_dir.joinpath("default_config.toml")),
            (dir_path / "alphabet.csv", templates_dir.joinpath("default_alphabet.csv")),
            (dir_path / "tests.tsv", templates_dir.joinpath("default_tests.tsv")),
        ]

    for target_file, _ in source_files:
        if target_file.exists():
            click.echo(f"Error: '{target_file}' already exists.", err=True)
            raise click.Abort()

    # Read all content into memory before writing anything so that a read
    # failure leaves no files on disk.
    contents = [(target, source.read_text()) for target, source in source_files]

    written: list[Path] = []
    try:
        for target_file, text in contents:
            target_file.write_text(text)
            written.append(target_file)
    except Exception as e:
        for f in written:
            f.unlink(missing_ok=True)
        click.echo(f"Error: failed to write '{target_file}': {e}", err=True)
        raise click.Abort()

    # For new projects (no starter), run the metadata wizard and patch [meta].
    if from_starter is None:
        _run_meta_wizard(config_path)

    click.echo("Successfully initialized project files:")
    for target_file, _ in source_files:
        click.echo(f"  - {target_file.name}")


from dataclasses import dataclass, field as dc_field


@dataclass
class _ValidationResult:
    config: object = None
    alphabet: dict = dc_field(default_factory=dict)
    tests: list = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)
    ok: bool = True


def _run_validate(config_path: Path, verbose: bool = False) -> _ValidationResult:
    """Run all validation checks, printing results if verbose.

    Returns a _ValidationResult. If ok=False, at least one hard error was found
    and the result's config/alphabet/tests may be incomplete.
    """
    result = _ValidationResult()
    base_dir = config_path.parent

    def info(msg):
        if verbose:
            click.echo(msg)

    def error(msg):
        click.echo(msg, err=True)

    # --- config.toml ---
    try:
        result.config = _load_config(config_path)
        info("  [✓] config.toml parsed successfully.")
    except ValidationError as e:
        error("  [x] Configuration validation failed in config.toml:")
        for err in e.errors():
            parts = []
            for loc in err["loc"]:
                if isinstance(loc, int):
                    parts.append(f"[{loc}]")
                elif parts:
                    parts.append(f".{loc}")
                else:
                    parts.append(str(loc))
            loc_str = "".join(parts)
            bad_input = repr(err.get("input", "Unknown"))
            error(f"      - {loc_str}: {err['msg']} (Got: {bad_input})")
        result.ok = False
        return result
    except Exception as e:
        error(f"  [x] Failed to read config.toml:\n{e}")
        result.ok = False
        return result

    # --- alphabet ---
    try:
        result.alphabet = load_alphabet(base_dir / result.config.alphabet_path)
        info(f"  [✓] {result.config.alphabet_path} loaded with {len(result.alphabet)} segments.")
    except FileNotFoundError:
        error(f"  [x] Missing alphabet file: {base_dir / result.config.alphabet_path}")
        result.ok = False
        return result
    except Exception as e:
        error(f"  [x] Failed to read alphabet file:\n{e}")
        result.ok = False
        return result

    alph_errors, alph_warnings = check_alphabet(result.alphabet)
    result.warnings.extend(alph_warnings)
    for w in alph_warnings:
        info(f"  [!] {w}")
    if alph_errors:
        error("  [x] Alphabet segment errors:")
        for e in alph_errors:
            error(f"      - {e}")
        result.ok = False
        return result
    if not alph_warnings:
        info("  [✓] All segments are distinguishable.")

    from snc2fst.alphabet import RESERVED_FEATURES
    valid_features = {f for seg in result.alphabet.values() for f in seg} | RESERVED_FEATURES

    # --- rule features ---
    rule_errors = []
    for rule in result.config.rules:
        for feature_spec in itertools.chain(rule.Inr, rule.Trm):
            for sign, feature_name in feature_spec:
                if feature_name not in valid_features:
                    rule_errors.append(
                        f"Rule '{rule.Id}' uses undefined feature '{feature_name}'."
                    )
    if rule_errors:
        error("  [x] Feature validation failed:")
        for e in rule_errors:
            error(f"      - {e}")
        result.ok = False
        return result
    info("  [✓] All rule features match the alphabet matrix.")

    # --- Out expressions ---
    out_errors = []
    valid_segments = set(result.alphabet)
    for rule in result.config.rules:
        try:
            out_ast = dsl.parse(rule.Out)
        except dsl.ParseError as e:
            out_errors.append(f"Rule '{rule.Id}': invalid Out expression — {e}")
            continue
        out_errors.extend(
            dsl.collect_errors(
                out_ast,
                rule_id=rule.Id,
                inr_len=len(rule.Inr),
                trm_len=len(rule.Trm),
                valid_segments=valid_segments,
                valid_features=valid_features,
            )
        )
    if out_errors:
        error("  [x] Out expression validation failed:")
        for e in out_errors:
            error(f"      - {e}")
        result.ok = False
        return result
    info("  [✓] All Out expressions are syntactically valid.")

    # --- tests file ---
    try:
        result.tests = load_tests(base_dir / result.config.tests_path)
        info(f"  [✓] {result.config.tests_path} loaded with {len(result.tests)} test cases.")
    except FileNotFoundError:
        error(f"  [x] Missing tests file: {base_dir / result.config.tests_path}")
        result.ok = False
        return result
    except Exception as e:
        error(f"  [x] Failed to read tests file:\n{e}")
        result.ok = False
        return result

    tok_errors = []
    for i, (inp, out) in enumerate(result.tests, 1):
        for word_str, label in [(inp, "input"), (out, "output")]:
            try:
                tokenize(word_str, result.alphabet)
            except TokenizeError as e:
                tok_errors.append(f"Test {i} {label} '{word_str}': {e}")
    if tok_errors:
        error("  [x] Test word tokenization failed:")
        for e in tok_errors:
            error(f"      - {e}")
        result.ok = False
        return result
    info("  [✓] All test words tokenize unambiguously.")

    return result


@main.command()
@click.argument("config_file", type=click.Path(exists=True, dir_okay=False))
def validate(config_file):
    """Validate the grammar configuration and all supporting files."""
    config_path = Path(config_file)
    click.echo(f"Validating project at: {config_path}")
    result = _run_validate(config_path, verbose=True)
    if result.ok:
        click.echo("All files valid.")


@main.command(name="eval")
@click.argument("config_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("word", required=False, default=None)
@click.option(
    "--format", "fmt",
    type=click.Choice(["txt", "latex"]),
    default=None,
    help="Render results as a table in the given format instead of per-test lines.",
)
@click.option(
    "--output", "-o",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write output to a file instead of stdout.",
)
@click.option(
    "--no-warn", "no_warn",
    is_flag=True,
    default=False,
    help="Suppress alphabet warnings.",
)
@click.option(
    "--fst",
    "use_fst",
    is_flag=True,
    default=False,
    help="Transduce via compiled FSTs in the transducers/ directory instead of the evaluator.",
)
def eval_cmd(config_file, word, fmt, output, no_warn, use_fst):
    """Apply grammar rules to test cases and report results.

    If WORD is given, evaluate that single word instead of the test suite.
    Use --fst to transduce via compiled FSTs in the transducers/ directory.
    """
    config_path = Path(config_file)
    input_word = word  # rename to avoid collision with loop variable

    if use_fst and fmt is not None:
        click.echo("[x] --format is not supported with --fst.", err=True)
        raise click.Abort()

    v = _run_validate(config_path, verbose=False)
    if not v.ok:
        click.echo(
            f"[x] Validation failed. Run 'snc validate {config_file}' for details.",
            err=True,
        )
        raise click.Abort()

    if v.warnings and not no_warn:
        click.echo("Warnings:")
        for w in v.warnings:
            click.echo(f"  [!] {w}")
        click.echo()

    config = v.config
    alphabet = v.alphabet

    # ------------------------------------------------------------------
    # FST path
    # ------------------------------------------------------------------
    if use_fst:
        try:
            import pynini
        except ImportError:
            click.echo("[x] pynini is not installed. Cannot use --fst.", err=True)
            raise click.Abort()

        from snc2fst.compiler import compile_rule, compute_alphabets, transduce

        fst_dir = config_path.parent / "transducers"
        missing = [
            rule.Id for rule in config.rules
            if not (fst_dir / f"{rule.Id}.fst").exists()
        ]
        if missing:
            ids = ", ".join(missing)
            click.echo(
                f"[x] Compiled FSTs not found for: {ids}. "
                f"Run 'snc compile {config_file}' first.",
                err=True,
            )
            raise click.Abort()

        fsts: dict[str, pynini.Fst] = {}
        for rule in config.rules:
            fst_path = fst_dir / f"{rule.Id}.fst"
            syms_path = fst_dir / f"{rule.Id}.syms"
            fst = pynini.Fst.read(str(fst_path))
            sym = pynini.SymbolTable.read_text(str(syms_path))
            fst.set_input_symbols(sym)
            fst.set_output_symbols(sym)
            fsts[rule.Id] = fst

        def _apply_fst_chain(inp_str: str) -> str:
            try:
                tokens = tokenize(inp_str, alphabet)
            except TokenizeError as e:
                raise EvalError(str(e))
            current = ["⋊"] + list(tokens) + ["⋉"]
            for rule in config.rules:
                current = transduce(fsts[rule.Id], rule, current)
            stripped = [s for s in current if s not in ("⋊", "⋉")]
            return "".join(stripped)

        if input_word is not None:
            try:
                result = _apply_fst_chain(input_word)
                click.echo(f"{input_word} → {result}")
            except (EvalError, ValueError) as e:
                click.echo(f"[x] {e}", err=True)
                raise click.Abort()
            return

        tests = v.tests
        click.echo("Results:")
        passed = failed = errors = 0
        for i, (inp_str, exp_str) in enumerate(tests, 1):
            try:
                result = _apply_fst_chain(inp_str)
            except (EvalError, ValueError) as e:
                click.echo(f"  [{i}] ERROR  {inp_str}: {e}", err=True)
                errors += 1
                continue
            try:
                exp_tokens = tokenize(exp_str, alphabet)
            except TokenizeError as e:
                click.echo(f"  [{i}] ERROR  {inp_str}: {e}", err=True)
                errors += 1
                continue
            ok = result == "".join(exp_tokens)
            passed += ok
            failed += not ok
            if ok:
                click.echo(f"  [{i}] PASS  {inp_str} → {result}")
            else:
                click.echo(f"  [{i}] FAIL  {inp_str} → {result}  (expected {exp_str})")
        total = len(tests)
        click.echo(f"\n{passed}/{total} passed, {failed} failed, {errors} errors.")
        return

    # ------------------------------------------------------------------
    # Evaluator path
    # ------------------------------------------------------------------
    try:
        out_asts = {rule.Id: dsl.parse(rule.Out) for rule in config.rules}
    except dsl.ParseError as e:
        click.echo(f"[x] Failed to parse Out expression: {e}", err=True)
        raise click.Abort()

    def _apply_eval_chain(inp_str: str) -> "tuple[list, list[list]]":
        inp_tokens = tokenize(inp_str, alphabet)
        w = [dict(alphabet[t]) for t in inp_tokens]
        states = [list(w)]
        for rule in config.rules:
            w = apply_rule(rule, out_asts[rule.Id], w, alphabet)
            states.append(list(w))
        return w, states

    if input_word is not None:
        try:
            w, _ = _apply_eval_chain(input_word)
            click.echo(f"{input_word} → {word_to_str(w, alphabet)}")
        except TokenizeError as e:
            click.echo(f"[x] {e}", err=True)
            raise click.Abort()
        except EvalError as e:
            click.echo(f"[x] {e}", err=True)
            raise click.Abort()
        return

    tests = v.tests
    click.echo("Results:")
    rule_ids = [rule.Id for rule in config.rules]
    passed = failed = errors = 0
    good_inputs: list[str] = []
    good_states: list[list] = []
    good_expected: list[list[str]] = []

    for i, (inp_str, exp_str) in enumerate(tests, 1):
        try:
            inp_tokens = tokenize(inp_str, alphabet)
            exp_tokens = tokenize(exp_str, alphabet)
        except TokenizeError as e:
            click.echo(f"  [{i}] ERROR  {inp_str}: {e}", err=True)
            errors += 1
            continue

        try:
            w, states = _apply_eval_chain(inp_str)
        except EvalError as e:
            click.echo(f"  [{i}] ERROR  {inp_str}: {e}", err=True)
            errors += 1
            continue

        out_tokens = tokenize(word_to_str(w, alphabet), alphabet)
        ok = out_tokens == exp_tokens
        passed += ok
        failed += not ok

        good_inputs.append(inp_str)
        good_states.append(states)
        good_expected.append(exp_tokens)

        if fmt is None:
            result = word_to_str(w, alphabet)
            if ok:
                click.echo(f"  [{i}] PASS  {inp_str} → {result}")
            else:
                click.echo(f"  [{i}] FAIL  {inp_str} → {result}  (expected {exp_str})")

    total = len(tests)

    if fmt is not None:
        table = build_table(good_inputs, rule_ids, good_states, alphabet)
        rendered = format_latex(table) if fmt == "latex" else format_txt(table)
        if output:
            Path(output).write_text(rendered + "\n", encoding="utf-8")
            click.echo(f"Table written to {output}")
        else:
            click.echo(rendered)

    if fmt is None or errors:
        click.echo(f"\n{passed}/{total} passed, {failed} failed, {errors} errors.")


_DEFAULT_MAX_ARCS = 1_000_000


def _write_syms(sym: pynini.SymbolTable, path: Path) -> None:
    sym.write_text(str(path))


def _write_att(fst: pynini.Fst, path: Path) -> None:
    isym = fst.input_symbols()
    osym = fst.output_symbols()
    lines = []
    for state in fst.states():
        for arc in fst.arcs(state):
            isym_str = isym.find(arc.ilabel) if arc.ilabel != 0 else "<eps>"
            osym_str = osym.find(arc.olabel) if arc.olabel != 0 else "<eps>"
            lines.append(f"{state}\t{arc.nextstate}\t{isym_str}\t{osym_str}\t{arc.weight}")
        final_w = fst.final(state)
        if final_w != pynini.Weight.zero("tropical"):
            lines.append(f"{state}\t{final_w}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@main.command(name="compile")
@click.argument("config_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--dir", "-d", "out_dir",
    default=None,
    help="Output directory for compiled FSTs. Defaults to <config_dir>/transducers/.",
)
@click.option(
    "--format", "fmt",
    type=click.Choice(["fst", "att"]),
    default="fst",
    show_default=True,
    help="Output format. 'fst' writes an OpenFST binary + .syms; "
         "'att' writes an AT&T text file + .syms.",
)
@click.option(
    "--max-arcs",
    default=_DEFAULT_MAX_ARCS,
    show_default=True,
    type=int,
    help="Abort if any single rule FST exceeds this many arcs before optimization.",
)
@click.option(
    "--no-optimize",
    is_flag=True,
    default=False,
    help="Skip rmepsilon / determinize / minimize after compilation.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Print full tracebacks on error.",
)
def compile_cmd(config_file, out_dir, fmt, max_arcs, no_optimize, verbose):
    """Compile all grammar rules to FST transducers, written to a directory."""
    config_path = Path(config_file)
    out_path = Path(out_dir) if out_dir else config_path.parent / "transducers"

    def die(msg: str, exc: BaseException | None = None) -> None:
        click.echo(f"[x] {msg}", err=True)
        if verbose and exc is not None:
            click.echo(traceback.format_exc(), err=True)
        raise click.Abort()

    v = _run_validate(config_path, verbose=False)
    if not v.ok:
        die(f"Validation failed. Run 'snc validate {config_file}' for details.")

    for w in v.warnings:
        click.echo(f"[!] {w}")

    config = v.config
    base_alphabet = v.alphabet

    if not config.rules:
        die("No rules defined in config.")

    # Propagate alphabets through the rule chain
    try:
        alphabets = compute_alphabets(config.rules, base_alphabet)
    except Exception as e:
        die(f"Failed to compute rule alphabets: {e}", e)

    # Check compilability and predict arc counts before allocating any FSTs
    for rule, alphabet in zip(config.rules, alphabets):
        try:
            out_ast = dsl.parse(rule.Out)
            arc_count = predict_arcs(rule, alphabet, out_ast)
        except CompileError as e:
            die(f"Rule '{rule.Id}': {e}", e)
        except Exception as e:
            die(f"Rule '{rule.Id}': failed to predict arc count: {e}", e)

        if arc_count > max_arcs:
            die(
                f"Rule '{rule.Id}' would produce {arc_count:,} arcs "
                f"(limit {max_arcs:,}). Use --max-arcs to raise the limit."
            )
        click.echo(f"  {rule.Id}: {arc_count:,} arcs")

    # Compile each rule with its effective input alphabet
    fsts: list[pynini.Fst] = []
    for rule, alphabet in zip(config.rules, alphabets):
        click.echo(f"  Compiling {rule.Id} ...")
        try:
            fst = compile_rule(rule, alphabet)
        except CompileError as e:
            die(f"Rule '{rule.Id}': {e}", e)
        except Exception as e:
            die(f"Rule '{rule.Id}': unexpected error during compilation: {e}", e)

        if not no_optimize:
            try:
                pynini.optimize(fst)
            except Exception as e:
                die(f"Rule '{rule.Id}': optimization failed: {e}", e)

        fsts.append(fst)

    # Create output directory
    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        die(f"Failed to create output directory '{out_path}': {e}", e)

    click.echo(f"Writing to {out_path}/")

    # Write one FST per rule
    for rule, fst in zip(config.rules, fsts):
        sym = fst.input_symbols()
        sym_path = out_path / f"{rule.Id}.syms"
        try:
            _write_syms(sym, sym_path)
        except Exception as e:
            die(f"Rule '{rule.Id}': failed to write symbol table: {e}", e)

        try:
            total_arcs = sum(1 for s in fst.states() for _ in fst.arcs(s))
            if fmt == "fst":
                fst_path = out_path / f"{rule.Id}.fst"
                fst.write(str(fst_path))
                click.echo(f"  {rule.Id}: {fst.num_states():,} states, {total_arcs:,} arcs → {fst_path.name}")
            else:
                att_path = out_path / f"{rule.Id}.att"
                _write_att(fst, att_path)
                click.echo(f"  {rule.Id}: {fst.num_states():,} states, {total_arcs:,} arcs → {att_path.name}")
        except Exception as e:
            die(f"Rule '{rule.Id}': failed to write FST: {e}", e)


@main.command("export")
@click.argument("config_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--format", "-f",
    "fmt",
    type=click.Choice(["txt", "latex"]),
    default="txt",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output", "-o",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write output to this file instead of stdout.",
)
def export_cmd(config_file, fmt, output):
    """Export the grammar and alphabet to txt or LaTeX format."""
    from snc2fst.export import export_txt, export_latex

    config_path = Path(config_file)
    v = _run_validate(config_path, verbose=False)
    if not v.ok:
        click.echo(
            f"[x] Validation failed. Run 'snc validate {config_file}' for details.",
            err=True,
        )
        raise click.Abort()

    for w in v.warnings:
        click.echo(f"[!] {w}")

    rendered = export_latex(v.config, v.alphabet) if fmt == "latex" else export_txt(v.config, v.alphabet)

    if output:
        Path(output).write_text(rendered, encoding="utf-8")
        click.echo(f"Exported to {output}")
    else:
        click.echo(rendered)


if __name__ == "__main__":
    main()
