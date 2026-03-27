import click
import importlib.resources
from pathlib import Path

import tomllib
from snc2fst.models import GrammarConfig

@click.group()
def main():
    """SNC: Compile Search-and-Change grammars to OpenFST transducers."""
    pass

@main.command()
@click.option(
    '--filename', 
    '-f', 
    default='config.toml', 
    help='Name of the main configuration file to generate.'
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
    alphabet_template = templates_dir.joinpath("default_alphabet.csv").read_text()
    tests_template = templates_dir.joinpath("default_tests.tsv").read_text()
        
    config_path.write_text(config_template)
    alphabet_path.write_text(alphabet_template)
    tests_path.write_text(tests_template)
    
    click.echo("Successfully initialized project files:")
    click.echo(f"  - {config_path.name}")
    click.echo(f"  - {alphabet_path.name}")
    click.echo(f"  - {tests_path.name}")

@main.command()
@click.argument('config_file', type=click.Path(exists=True, dir_okay=False))
@click.option(
    '--output', 
    '-o', 
    default='out.fst', 
    type=click.Path(),
    help='Output path for the compiled OpenFST transducer.'
)
def compile(config_file, output):
    """Compile a grammar configuration to an FST."""
    with open(config_file, "rb") as f:
        raw_dict = tomllib.load(f)

    config = GrammarConfig(**raw_dict)

    print(f"Loading alphabet from: {config.alphabet_path}")
    print(f"First rule direction: {config.rules[0].Dir}")

if __name__ == '__main__':
    main()