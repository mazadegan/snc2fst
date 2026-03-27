import click
import importlib.resources
import itertools
from pathlib import Path

import tomllib
from pydantic import ValidationError
from snc2fst.models import GrammarConfig
from snc2fst.alphabet import TokenizeError, load_alphabet, tokenize, word_to_str
from snc2fst.io import load_tests
from snc2fst import dsl
from snc2fst.evaluator import EvalError, apply_rule


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
def init(filename):
    """Initialize a new grammar configuration and supporting template files."""
    config_path = Path(filename)
    dir_path = config_path.parent

    alphabet_path = dir_path / "alphabet.csv"
    tests_path = dir_path / "tests.tsv"

    for target_file in [config_path, alphabet_path, tests_path]:
        if target_file.exists():
            click.echo(f"Error: '{target_file}' already exists.", err=True)
            raise click.Abort()

    templates_dir = importlib.resources.files("snc2fst").joinpath("templates")

    config_path.write_text(templates_dir.joinpath("default_config.toml").read_text())
    alphabet_path.write_text(templates_dir.joinpath("default_alphabet.csv").read_text())
    tests_path.write_text(templates_dir.joinpath("default_tests.tsv").read_text())

    click.echo("Successfully initialized project files:")
    click.echo(f"  - {config_path.name}")
    click.echo(f"  - {alphabet_path.name}")
    click.echo(f"  - {tests_path.name}")


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
    click.echo("  [✓] All Out expressions are valid.")

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
def eval_cmd(config_file):
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

    passed = failed = errors = 0
    for i, (inp_str, exp_str) in enumerate(tests, 1):
        try:
            inp_tokens = tokenize(inp_str, alphabet)
            exp_tokens = tokenize(exp_str, alphabet)
        except TokenizeError as e:
            click.echo(f"  [{i}] ERROR  {inp_str}: {e}")
            errors += 1
            continue

        word = [dict(alphabet[t]) for t in inp_tokens]
        try:
            for rule in config.rules:
                word = apply_rule(rule, out_asts[rule.Id], word, alphabet)
        except EvalError as e:
            click.echo(f"  [{i}] ERROR  {inp_str}: {e}")
            errors += 1
            continue

        out_tokens = tokenize(word_to_str(word, alphabet), alphabet)
        ok = out_tokens == exp_tokens
        if ok:
            passed += 1
            click.echo(f"  [{i}] PASS  {inp_str} → {word_to_str(word, alphabet)}")
        else:
            failed += 1
            click.echo(
                f"  [{i}] FAIL  {inp_str} → {word_to_str(word, alphabet)}"
                f"  (expected {exp_str})"
            )

    total = len(tests)
    click.echo(f"\n{passed}/{total} passed, {failed} failed, {errors} errors.")


if __name__ == "__main__":
    main()
