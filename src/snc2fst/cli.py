import click
import importlib.resources
import itertools
from pathlib import Path

import tomllib
from pydantic import ValidationError
from snc2fst.models import GrammarConfig
from snc2fst.io import Alphabet, load_tests


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

    config_template = templates_dir.joinpath("default_config.toml").read_text()
    alphabet_template = templates_dir.joinpath(
        "default_alphabet.csv"
    ).read_text()
    tests_template = templates_dir.joinpath("default_tests.tsv").read_text()

    config_path.write_text(config_template)
    alphabet_path.write_text(alphabet_template)
    tests_path.write_text(tests_template)

    click.echo("Successfully initialized project files:")
    click.echo(f"  - {config_path.name}")
    click.echo(f"  - {alphabet_path.name}")
    click.echo(f"  - {tests_path.name}")


@main.command()
@click.argument("config_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    "-o",
    default="out.fst",
    type=click.Path(),
    help="Output path for the compiled OpenFST transducer.",
)
def compile(config_file, output):
    """Compile a grammar configuration to an FST."""
    config = _load_config(config_file)
    click.echo(f"Loading alphabet from: {config.alphabet_path}")
    click.echo(f"First rule direction: {config.rules[0].Dir}")


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

    alphabet_path = base_dir / config.alphabet_path
    try:
        alphabet = Alphabet.from_file(alphabet_path)
        click.echo(
            f"  [✓] {config.alphabet_path} loaded with {len(alphabet.segments)} segments."
        )
    except FileNotFoundError:
        click.echo(f"  [x] Missing alphabet file: {alphabet_path}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"  [x] Failed to read alphabet file:\n{e}", err=True)
        raise click.Abort()

    valid_features = {f for feats in alphabet.matrix.values() for f in feats}

    rule_errors = []
    for rule in config.rules:
        for natural_class in itertools.chain(rule.Inr, rule.Trm):
            for sign, feature_name in natural_class:
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

    tests_path = base_dir / config.tests_path
    try:
        tests = load_tests(tests_path)
        click.echo(
            f"  [✓] {config.tests_path} loaded with {len(tests)} test cases."
        )
    except FileNotFoundError:
        click.echo(f"  [x] Missing tests file: {tests_path}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"  [x] Failed to read tests file:\n{e}", err=True)
        raise click.Abort()

    click.echo("All files valid.")


if __name__ == "__main__":
    main()
