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
from snc2fst.alphabet import TokenizeError, load_alphabet, tokenize, word_to_str
from snc2fst.io import load_tests
from snc2fst import dsl
from snc2fst.evaluator import EvalError, apply_rule
from snc2fst.table import build_table, format_latex, format_txt
from snc2fst.compiler import CompileError, compile_rule, compute_alphabets, predict_arcs


def _load_config(config_file) -> GrammarConfig:
    with open(config_file, "rb") as f:
        raw_dict = tomllib.load(f)
    return GrammarConfig(**raw_dict)


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

    for target_file, source in source_files:
        target_file.write_text(source.read_text())

    click.echo("Successfully initialized project files:")
    for target_file, _ in source_files:
        click.echo(f"  - {target_file.name}")


@main.command()
@click.argument("config_file", type=click.Path(exists=True, dir_okay=False))
def validate(config_file):
    """Validate the grammar configuration and all supporting files."""
    config_path = Path(config_file)
    base_dir = config_path.parent

    click.echo(f"Validating project at: {config_path}")

    try:
        config = _load_config(config_path)
        click.echo("  [✓] config.toml parsed successfully.")
    except ValidationError as e:
        click.echo("  [x] Configuration validation failed in config.toml:", err=True)
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
            click.echo(f"      - {loc_str}: {err['msg']} (Got: {bad_input})", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"  [x] Failed to read config.toml:\n{e}", err=True)
        raise click.Abort()

    try:
        alphabet = load_alphabet(base_dir / config.alphabet_path)
        click.echo(
            f"  [✓] {config.alphabet_path} loaded with {len(alphabet)} segments."
        )
    except FileNotFoundError:
        click.echo(
            f"  [x] Missing alphabet file: {base_dir / config.alphabet_path}", err=True
        )
        raise click.Abort()
    except Exception as e:
        click.echo(f"  [x] Failed to read alphabet file:\n{e}", err=True)
        raise click.Abort()

    valid_features = {f for seg in alphabet.values() for f in seg}

    rule_errors = []
    for rule in config.rules:
        for feature_spec in itertools.chain(rule.Inr, rule.Trm):
            for sign, feature_name in feature_spec:
                if feature_name not in valid_features:
                    rule_errors.append(
                        f"Rule '{rule.Id}' uses undefined feature '{feature_name}'."
                    )

    if rule_errors:
        click.echo("  [x] Feature validation failed:", err=True)
        for err in rule_errors:
            click.echo(f"      - {err}", err=True)
        raise click.Abort()
    click.echo("  [✓] All rule features match the alphabet matrix.")

    out_errors = []
    valid_segments = set(alphabet)
    for rule in config.rules:
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
        click.echo("  [x] Out expression validation failed:", err=True)
        for err in out_errors:
            click.echo(f"      - {err}", err=True)
        raise click.Abort()
    click.echo("  [✓] All Out expressions are syntactically valid.")

    try:
        tests = load_tests(base_dir / config.tests_path)
        click.echo(
            f"  [✓] {config.tests_path} loaded with {len(tests)} test cases."
        )
    except FileNotFoundError:
        click.echo(
            f"  [x] Missing tests file: {base_dir / config.tests_path}", err=True
        )
        raise click.Abort()
    except Exception as e:
        click.echo(f"  [x] Failed to read tests file:\n{e}", err=True)
        raise click.Abort()

    tok_errors = []
    for i, (inp, out) in enumerate(tests, 1):
        for word_str, label in [(inp, "input"), (out, "output")]:
            try:
                tokenize(word_str, alphabet)
            except TokenizeError as e:
                tok_errors.append(f"Test {i} {label} '{word_str}': {e}")

    if tok_errors:
        click.echo("  [x] Test word tokenization failed:", err=True)
        for err in tok_errors:
            click.echo(f"      - {err}", err=True)
        raise click.Abort()
    click.echo("  [✓] All test words tokenize unambiguously.")

    click.echo("All files valid.")


@main.command(name="eval")
@click.argument("config_file", type=click.Path(exists=True, dir_okay=False))
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
def eval_cmd(config_file, fmt, output):
    """Apply grammar rules to all test cases and report results."""
    config_path = Path(config_file)
    base_dir = config_path.parent

    try:
        config = _load_config(config_path)
    except Exception as e:
        click.echo(f"[x] Failed to load config: {e}", err=True)
        raise click.Abort()

    try:
        alphabet = load_alphabet(base_dir / config.alphabet_path)
    except FileNotFoundError:
        click.echo(
            f"[x] Missing alphabet file: {base_dir / config.alphabet_path}", err=True
        )
        raise click.Abort()

    try:
        tests = load_tests(base_dir / config.tests_path)
    except FileNotFoundError:
        click.echo(
            f"[x] Missing tests file: {base_dir / config.tests_path}", err=True
        )
        raise click.Abort()

    try:
        out_asts = {rule.Id: dsl.parse(rule.Out) for rule in config.rules}
    except dsl.ParseError as e:
        click.echo(f"[x] Failed to parse Out expression: {e}", err=True)
        raise click.Abort()

    # Run every test case, collecting per-rule intermediate states.
    rule_ids = [rule.Id for rule in config.rules]
    passed = failed = errors = 0
    good_inputs: list[str] = []
    good_states: list[list] = []   # per-test list of word states (one per rule boundary)
    good_expected: list[list[str]] = []

    for i, (inp_str, exp_str) in enumerate(tests, 1):
        try:
            inp_tokens = tokenize(inp_str, alphabet)
            exp_tokens = tokenize(exp_str, alphabet)
        except TokenizeError as e:
            click.echo(f"  [{i}] ERROR  {inp_str}: {e}", err=True)
            errors += 1
            continue

        word = [dict(alphabet[t]) for t in inp_tokens]
        states = [list(word)]
        try:
            for rule in config.rules:
                word = apply_rule(rule, out_asts[rule.Id], word, alphabet)
                states.append(list(word))
        except EvalError as e:
            click.echo(f"  [{i}] ERROR  {inp_str}: {e}", err=True)
            errors += 1
            continue

        out_tokens = tokenize(word_to_str(word, alphabet), alphabet)
        ok = out_tokens == exp_tokens
        passed += ok
        failed += not ok

        good_inputs.append(inp_str)
        good_states.append(states)
        good_expected.append(exp_tokens)

        if fmt is None:
            result = word_to_str(word, alphabet)
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
    "--output", "-o",
    default=None,
    help="Base output path (no extension). Defaults to <config_dir>/grammar.",
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
def compile_cmd(config_file, output, fmt, max_arcs, no_optimize, verbose):
    """Compile all grammar rules to a single composed FST transducer."""
    config_path = Path(config_file)
    base_dir = config_path.parent
    out_base = Path(output) if output else base_dir / "grammar"

    def die(msg: str, exc: BaseException | None = None) -> None:
        click.echo(f"[x] {msg}", err=True)
        if verbose and exc is not None:
            click.echo(traceback.format_exc(), err=True)
        raise click.Abort()

    # Load config
    try:
        config = _load_config(config_path)
    except Exception as e:
        die(f"Failed to load config: {e}", e)

    # Load alphabet
    try:
        base_alphabet = load_alphabet(base_dir / config.alphabet_path)
    except FileNotFoundError as e:
        die(f"Missing alphabet file: {base_dir / config.alphabet_path}", e)
    except Exception as e:
        die(f"Failed to read alphabet: {e}", e)

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

    # Write one FST per rule
    for rule, fst in zip(config.rules, fsts):
        sym = fst.input_symbols()
        stem = f"{out_base}_{rule.Id}"
        sym_path = Path(stem).with_suffix(".syms")
        try:
            _write_syms(sym, sym_path)
        except Exception as e:
            die(f"Rule '{rule.Id}': failed to write symbol table: {e}", e)

        try:
            total_arcs = sum(1 for s in fst.states() for _ in fst.arcs(s))
            if fmt == "fst":
                fst_path = Path(stem).with_suffix(".fst")
                fst.write(str(fst_path))
                click.echo(f"  {rule.Id}: {fst.num_states():,} states, {total_arcs:,} arcs → {fst_path.name}")
            else:
                att_path = Path(stem).with_suffix(".att")
                _write_att(fst, att_path)
                click.echo(f"  {rule.Id}: {fst.num_states():,} states, {total_arcs:,} arcs → {att_path.name}")
        except Exception as e:
            die(f"Rule '{rule.Id}': failed to write FST: {e}", e)


if __name__ == "__main__":
    main()
