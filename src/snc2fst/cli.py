from pathlib import Path

import click

STARTERS = [
    "english_past_tense",
    "english_plural",
    "iloko_plural",
    "turkish_k_deletion",
    "votic_vowel_harmony",
]


@click.group()
def main() -> None:
    """
    snc2fst: Compile Search-and-Change grammars to finite state transducers.
    """
    pass


@main.command(name="init")
@click.argument("directory", default=".", type=click.Path(path_type=Path))
@click.option(
    "--starter",
    default=None,
    help="Starter template name (or 'blank'). Skips interactive prompt.",
)
@click.option(
    "--title", default=None, help="Project title. Skips interactive prompt."
)
@click.option(
    "--language",
    default=None,
    help="Language code (ISO 639-3 preferred). Skips interactive prompt.",
)
def init_cmd(
    directory: Path,
    starter: str | None,
    title: str | None,
    language: str | None,
) -> None:
    """Create a new grammar project from a starter template."""
    import shutil
    from importlib.resources import files

    import questionary

    templates_path = files("snc2fst") / "templates"
    starters_path = templates_path / "starters"

    starter_names = ["blank"] + STARTERS

    if starter is None:
        starter = questionary.select(
            "Choose a starter template:",
            choices=starter_names,
        ).ask()
        if starter is None:
            raise click.Abort()

    if starter not in starter_names:
        click.echo(
            f"[x] Unknown starter {starter!r}. Choose from: {', '.join(starter_names)}",
            err=True,
        )
        raise click.Abort()

    if title is None:
        title = questionary.text("Project title:").ask()
        if title is None:
            raise click.Abort()

    if language is None:
        language = questionary.text("Language (ISO 639-3 preferred):").ask()
        if language is None:
            raise click.Abort()

    # resolve target directory
    target = (
        directory
        if directory != Path(".")
        else Path(title.lower().replace(" ", "_"))
    )
    if target.exists():
        overwrite = questionary.confirm(
            f"'{target}' already exists. Overwrite? (files cannot be recovered)"
        ).ask()
        if not overwrite:
            raise click.Abort()
        shutil.rmtree(target)

    target.mkdir(parents=True)

    if starter == "blank":
        source = templates_path
        for f in ["alphabet.csv", "default_config.toml", "tests.csv"]:
            shutil.copy(
                str(source / f),
                str(
                    target
                    / (f if f != "default_config.toml" else "config.toml")
                ),
            )
    else:
        source = starters_path / starter
        shutil.copytree(str(source), str(target), dirs_exist_ok=True)

    config_path = target / "config.toml"
    content = config_path.read_text()
    content = content.replace('title = ""', f'title = "{title}"')
    content = content.replace('language = ""', f'language = "{language}"')
    config_path.write_text(content)

    click.echo(f"\n[✓] Project created at '{target}'.")
    click.echo(f"    Edit {target}/config.toml to add rules.")
    click.echo(
        f"    Edit {target}/alphabet.csv to define your feature system."
    )


@main.command(name="validate")
@click.argument(
    "config_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
def validate_cmd(config_file: Path) -> None:
    """Validate a grammar config and all supporting files."""
    from snc2fst.alphabet import load_alphabet
    from snc2fst.dsl import collect_errors, parse
    from snc2fst.errors import ParseError, TokenizationError
    from snc2fst.io import load_config, load_tests

    errors: list[str] = []
    base_dir = config_file.parent
    click.echo(f"Validating: {config_file}")

    # config
    try:
        config = load_config(config_file)
        click.echo("  [✓] config.toml")
    except Exception as e:
        click.echo(f"  [x] config.toml: {e}", err=True)
        raise click.Abort()

    # alphabet
    try:
        fs, inv = load_alphabet(base_dir / config.alphabet_path)
        click.echo(f"  [✓] {config.alphabet_path} ({len(inv)} segments)")
    except Exception as e:
        click.echo(f"  [x] {config.alphabet_path}: {e}", err=True)
        raise click.Abort()

    # Out expressions
    valid_features = fs.valid_features
    valid_segments = set(inv.user_names)
    for rule in config.rules:
        try:
            out_ast = parse(rule.Out)
            rule_errors = collect_errors(
                out_ast,
                rule_id=rule.Id,
                inr_len=len(rule.Inr),
                trm_len=len(rule.Trm),
                valid_segments=valid_segments,
                valid_features=set(valid_features),
            )
            errors.extend(rule_errors)
        except (ParseError, TokenizationError) as e:
            errors.append(f"Rule '{rule.Id}': {e}")

    if not errors:
        click.echo("  [✓] All Out expressions valid")

    # tests file
    try:
        tests = load_tests(base_dir / config.tests_path)
        click.echo(f"  [✓] {config.tests_path} ({len(tests)} tests)")
        for inp, _ in tests:
            try:
                inv.tokenize(inp)
            except Exception as e:
                errors.append(f"Test input {inp!r}: {e}")
    except Exception as e:
        errors.append(f"Tests file: {e}")

    if errors:
        for err in errors:
            click.echo(f"  [x] {err}", err=True)
        raise click.Abort()

    click.echo("All files valid.")


@main.command(name="eval")
@click.argument(
    "config_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.argument("word", required=False, default=None)
def eval_cmd(config_file: Path, word: str | None) -> None:
    """Apply grammar rules to a word or run the full test suite."""

    from snc2fst.alphabet import load_alphabet
    from snc2fst.dsl import parse
    from snc2fst.evaluator import apply_rule
    from snc2fst.io import load_config, load_tests

    try:
        config = load_config(config_file)
    except Exception as e:
        click.echo(f"[x] Failed to load config: {e}", err=True)
        raise click.Abort()

    try:
        fs, inv = load_alphabet(config_file.parent / config.alphabet_path)
    except Exception as e:
        click.echo(f"[x] Failed to load alphabet: {e}", err=True)
        raise click.Abort()

    try:
        out_asts = {rule.Id: parse(rule.Out) for rule in config.rules}
    except Exception as e:
        click.echo(f"[x] Failed to parse Out expression: {e}", err=True)
        raise click.Abort()

    def apply_chain(input_word: str) -> str:
        tokenized = inv.tokenize(input_word)
        if isinstance(tokenized, list):
            raise click.ClickException(
                f"Ambiguous tokenization for {input_word!r} — use spaces to disambiguate."
            )
        w = tokenized
        for rule in config.rules:
            w = apply_rule(rule, out_asts[rule.Id], w, fs, inv)
        return inv.render(w)

    if word is not None:
        try:
            result = apply_chain(word)
            click.echo(f"{word} → {result}")
        except Exception as e:
            click.echo(f"[x] {e}", err=True)
            raise click.Abort()
        return

    # test suite mode
    tests = load_tests(config_file.parent / config.tests_path)
    passed = failed = 0
    for inp, expected in tests:
        try:
            result = apply_chain(inp)
            ok = result == expected
            passed += ok
            failed += not ok
            status = "PASS" if ok else "FAIL"
            click.echo(
                f"  [{status}] {inp} → {result}"
                + ("" if ok else f"  (expected {expected})")
            )
        except Exception as e:
            click.echo(f"  [ERROR] {inp}: {e}")
            failed += 1
    click.echo(f"\n{passed}/{passed + failed} passed")
