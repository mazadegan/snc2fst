from pathlib import Path

import click
import pynini  # type: ignore[import-untyped]

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
            f"[x] Unknown starter {starter!r}. Choose from: {', '.join(starter_names)}",  # noqa: E501
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
            f"'{target}' already exists. Overwrite? (files cannot be recovered)"  # noqa: E501
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
@click.option(
    "--fst",
    "use_fst",
    is_flag=True,
    default=False,
    help="Run test suite through compiled FSTs in the transducers/ directory.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["txt", "latex"]),
    default=None,
    help="Show a derivation table (txt = PrettyTable, latex = LaTeX tabular).",
)
def eval_cmd(
    config_file: Path,
    word: str | None,
    use_fst: bool,
    fmt: str | None,
) -> None:
    """Apply grammar rules to a word or run the full test suite.

    With --fst, runs through compiled FSTs in the transducers/ directory.
    With --format, shows a derivation table across all test cases (or a
    single word if provided).
    """
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

    # ------------------------------------------------------------------
    # FST setup (shared by both --fst and --format --fst paths)
    # ------------------------------------------------------------------
    fsts = None
    if use_fst:
        try:
            import pynini
        except ImportError:
            click.echo(
                "[x] The --fst flag requires pynini, which must be installed "
                "via conda:\n\n    conda install -c conda-forge pynini\n",
                err=True,
            )
            raise click.Abort()

        transducers_dir = config_file.parent / "transducers"
        expected = len(config.rules)

        if not transducers_dir.exists():
            click.echo(
                f"[x] No transducers/ directory found. "
                f"Compile the grammar first:\n\n"
                f"    snc compile {config_file}\n",
                err=True,
            )
            raise click.Abort()

        fst_files = sorted(transducers_dir.glob("*.fst"))
        if len(fst_files) != expected:
            click.echo(
                f"[x] Expected {expected} compiled FST(s) in "
                f"'{transducers_dir}' but found {len(fst_files)}. "
                f"Recompile the grammar:\n\n"
                f"    snc compile {config_file}\n",
                err=True,
            )
            raise click.Abort()

        fsts = [pynini.Fst.read(str(p)) for p in fst_files]

    # ------------------------------------------------------------------
    # Helpers: apply one step at a time, collecting intermediates
    # ------------------------------------------------------------------

    def _tokenize(input_word: str):
        tokenized = inv.tokenize(input_word)
        if isinstance(tokenized, list):
            raise click.ClickException(
                f"Ambiguous tokenization for {input_word!r} — "
                "use spaces to disambiguate."
            )
        return tokenized

    def _apply_chain_steps(input_word: str) -> list[str]:
        """Return [UR, after_R1, after_R2, ..., SR] as rendered strings."""
        if use_fst:
            from snc2fst.compiler import transduce

            tokenized = _tokenize(input_word)
            current_names = [inv.name_of(seg) for seg in tokenized]
            steps = ["".join(current_names)]
            assert fsts is not None
            for rule, fst in zip(config.rules, fsts):
                current_names = transduce(fst, rule, current_names)
                steps.append("".join(current_names))
        else:
            tokenized = _tokenize(input_word)
            current = tokenized
            steps = [inv.render(current)]
            for rule in config.rules:
                out_ast = parse(rule.Out)
                current = apply_rule(rule, out_ast, current, fs, inv)
                steps.append(inv.render(current))
        return steps

    # ------------------------------------------------------------------
    # --format mode: derivation table
    # ------------------------------------------------------------------
    if fmt is not None:
        # Collect inputs: single word or all test cases
        if word is not None:
            inputs = [word]
        else:
            tests = load_tests(config_file.parent / config.tests_path)
            inputs = [inp for inp, _ in tests]

        # Build derivation matrix: rows = stages, cols = inputs
        # stages[i] = [ur, after_r1, ..., sr]  for input i
        all_steps: list[list[str]] = []
        errors: list[str] = []
        for inp in inputs:
            try:
                all_steps.append(_apply_chain_steps(inp))
            except Exception as e:
                errors.append(f"{inp}: {e}")
                all_steps.append(["ERROR"] * (len(config.rules) + 1))

        if errors:
            for err in errors:
                click.echo(f"  [x] {err}", err=True)

        rule_ids = [rule.Id for rule in config.rules]

        if fmt == "txt":
            click.echo(_format_table_txt(inputs, all_steps, rule_ids))
        else:
            click.echo(_format_table_latex(inputs, all_steps, rule_ids))
        return

    # ------------------------------------------------------------------
    # --fst mode (no --format): standard pass/fail output
    # ------------------------------------------------------------------
    if use_fst:
        from snc2fst.compiler import transduce

        def apply_fst_chain(input_word: str) -> str:
            tokenized = _tokenize(input_word)
            current = [inv.name_of(seg) for seg in tokenized]
            assert fsts is not None
            for rule, fst in zip(config.rules, fsts):
                current = transduce(fst, rule, current)
            return "".join(current)

        tests = load_tests(config_file.parent / config.tests_path)
        passed = failed = 0
        for inp, expected_out in tests:
            try:
                result = apply_fst_chain(inp)
                ok = result == expected_out
                passed += ok
                failed += not ok
                status = "PASS" if ok else "FAIL"
                click.echo(
                    f"  [{status}] {inp} → {result}"
                    + ("" if ok else f"  (expected {expected_out})")
                )
            except Exception as e:
                click.echo(f"  [ERROR] {inp}: {e}")
                failed += 1
        click.echo(f"\n{passed}/{passed + failed} passed")
        return

    # ------------------------------------------------------------------
    # Standard evaluator mode
    # ------------------------------------------------------------------
    try:
        out_asts = {rule.Id: parse(rule.Out) for rule in config.rules}
    except Exception as e:
        click.echo(f"[x] Failed to parse Out expression: {e}", err=True)
        raise click.Abort()

    def apply_chain(input_word: str) -> str:
        w = _tokenize(input_word)
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

    tests = load_tests(config_file.parent / config.tests_path)
    passed = failed = 0
    for inp, expected_out in tests:
        try:
            result = apply_chain(inp)
            ok = result == expected_out
            passed += ok
            failed += not ok
            status = "PASS" if ok else "FAIL"
            click.echo(
                f"  [{status}] {inp} → {result}"
                + ("" if ok else f"  (expected {expected_out})")
            )
        except Exception as e:
            click.echo(f"  [ERROR] {inp}: {e}")
            failed += 1
    click.echo(f"\n{passed}/{passed + failed} passed")


# ---------------------------------------------------------------------------
# Table formatters
# ---------------------------------------------------------------------------


def _format_table_txt(
    inputs: list[str],
    all_steps: list[list[str]],
    rule_ids: list[str],
) -> str:
    """
    Render a derivation table as plain text with borders only around UR/SR.
    """
    rows: list[list[str]] = []

    # UR row
    rows.append(["UR"] + [f"/{all_steps[i][0]}/" for i in range(len(inputs))])

    # One row per rule
    for r_idx, rule_id in enumerate(rule_ids):
        row = [rule_id]
        for i in range(len(inputs)):
            before = all_steps[i][r_idx]
            after = all_steps[i][r_idx + 1]
            row.append(f"[{after}]" if after != before else "---")
        rows.append(row)

    # SR row
    rows.append(["SR"] + [f"[{all_steps[i][-1]}]" for i in range(len(inputs))])

    # Compute column widths
    ncols = 1 + len(inputs)
    widths = [0] * ncols
    for row in rows:
        for j, cell in enumerate(row):
            widths[j] = max(widths[j], len(cell))

    def make_border() -> str:
        return "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def make_row(row: list[str]) -> str:
        cells = [f" {cell.center(widths[j])} " for j, cell in enumerate(row)]
        return "|" + "|".join(cells) + "|"

    border = make_border()
    lines: list[str] = []

    # Top + UR
    lines.append(border)
    lines.append(make_row(rows[0]))
    lines.append(border)

    # Rule rows
    for row in rows[1:-1]:
        lines.append(make_row(row))

    # SR + bottom
    lines.append(border)
    lines.append(make_row(rows[-1]))
    lines.append(border)

    return "\n".join(lines)


def _format_table_latex(
    inputs: list[str],
    all_steps: list[list[str]],
    rule_ids: list[str],
) -> str:
    """Render a derivation table as a LaTeX tabular environment."""
    col_spec = "r" + "c" * len(inputs)

    def _escape(s: str) -> str:
        """Minimal LaTeX escaping for phonological strings."""
        return s.replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")

    lines = [
        "\\begin{tabular}{" + col_spec + "}",
        "  \\hline",
    ]

    # UR row
    ur_cells = ["\\textsc{ur}"] + [
        f"/{_escape(all_steps[i][0])}/" for i in range(len(inputs))
    ]
    lines.append("  " + " & ".join(ur_cells) + " \\\\")
    lines.append("  \\hline")

    # Rule rows
    for r_idx, rule_id in enumerate(rule_ids):
        row_cells = [f"\\textsc{{{_escape(rule_id)}}}"]
        for i in range(len(inputs)):
            before = all_steps[i][r_idx]
            after = all_steps[i][r_idx + 1]
            if after != before:
                row_cells.append(f"[{_escape(after)}]")
            else:
                row_cells.append("---")
        lines.append("  " + " & ".join(row_cells) + " \\\\")

    lines.append("  \\hline")

    # SR row
    sr_cells = ["\\textsc{sr}"] + [
        f"[{_escape(all_steps[i][-1])}]" for i in range(len(inputs))
    ]
    lines.append("  " + " & ".join(sr_cells) + " \\\\")
    lines.append("  \\hline")
    lines.append("\\end{tabular}")

    return "\n".join(lines)


@main.command(name="compile")
@click.argument(
    "config_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--att",
    is_flag=True,
    default=False,
    help="Also write .att text files alongside the .fst binaries.",
)
@click.option(
    "--max-arcs",
    default=1_000_000,
    show_default=True,
    type=int,
    help="Abort compilation of a rule if its FST exceeds this many arcs.",
)
def compile_cmd(config_file: Path, att: bool, max_arcs: int) -> None:
    """Compile grammar rules to OpenFST transducers.

    Writes one .fst file per rule into a 'transducers/' directory at the
    project root (next to config.toml). With --att, also writes a .att text
    file for each rule.

    Rules are named by their position and Id, e.g. '01_vowel-harmony.fst'.
    """
    import warnings

    from snc2fst.alphabet import load_alphabet
    from snc2fst.compiler import compile_rule, compute_alphabets
    from snc2fst.errors import CompileError
    from snc2fst.io import load_config

    try:
        config = load_config(config_file)
    except Exception as e:
        click.echo(f"[x] Failed to load config: {e}", err=True)
        raise click.Abort()

    base_dir = config_file.parent

    try:
        fs, inv = load_alphabet(base_dir / config.alphabet_path)
    except Exception as e:
        click.echo(f"[x] Failed to load alphabet: {e}", err=True)
        raise click.Abort()

    out_dir = base_dir / "transducers"
    out_dir.mkdir(exist_ok=True)

    click.echo(f"Compiling {len(config.rules)} rule(s) → {out_dir}/")

    # Compute per-rule inventories (propagates output alphabet between rules).
    # We capture warnings here so we can echo them via click rather than
    # letting them go to stderr in an unpredictable format.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            alphabets = compute_alphabets(config.rules, fs, inv)
        except Exception as e:
            click.echo(f"[x] Alphabet propagation failed: {e}", err=True)
            raise click.Abort()

    for w in caught:
        click.echo(f"  [!] {w.message}", err=True)

    # Compile each rule
    for idx, (rule, rule_inv) in enumerate(
        zip(config.rules, alphabets), start=1
    ):
        stem = f"{idx:02d}_{rule.Id}"
        fst_path = out_dir / f"{stem}.fst"
        att_path = out_dir / f"{stem}.att"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                fst = compile_rule(rule, fs, rule_inv, max_arcs=max_arcs)
            except CompileError as e:
                click.echo(f"  [x] Rule '{rule.Id}': {e}", err=True)
                raise click.Abort()
            except Exception as e:
                click.echo(
                    f"  [x] Rule '{rule.Id}': unexpected error: {e}", err=True
                )
                raise click.Abort()

        for w in caught:
            click.echo(f"  [!] {w.message}", err=True)

        # Write binary .fst
        fst.write(str(fst_path))

        # Optionally write .att text format
        if att:
            _write_att(fst, att_path)

        arc_count = sum(fst.num_arcs(s) for s in fst.states())
        state_count = fst.num_states()
        click.echo(
            f"  [✓] {stem}.fst  "
            f"({state_count} states, {arc_count} arcs)"
            + (f"  → {stem}.att" if att else "")
        )

    click.echo(
        f"\n[✓] Done. {len(config.rules)} transducer(s) written to '{out_dir}'."  # noqa: E501
    )


def _write_att(fst: pynini.Fst, path: Path) -> None:
    """Write an FST in AT&T text format.

    Format per line:
      src_state  dst_state  input_label  output_label  [weight]
    Final states:
      state_id  [weight]

    Label 0 is rendered as <eps>.
    """
    import pynini

    sym_in = fst.input_symbols()
    sym_out = fst.output_symbols()

    def label_str(sym_table: pynini.SymbolTable, label: int) -> str:  # type: ignore[name-defined]
        if label == 0:
            return "<eps>"
        name = sym_table.find(label)
        return name if name else str(label)

    lines: list[str] = []
    # Emit arcs — start state first for convention, then rest
    start = fst.start()
    state_order = [start] + [s for s in fst.states() if s != start]

    for state in state_order:
        for arc in fst.arcs(state):
            il = label_str(sym_in, arc.ilabel)
            ol = label_str(sym_out, arc.olabel)
            weight = float(arc.weight)
            if weight == 0.0:
                lines.append(f"{state}\t{arc.nextstate}\t{il}\t{ol}")
            else:
                lines.append(f"{state}\t{arc.nextstate}\t{il}\t{ol}\t{weight}")

    # Emit final states
    for state in state_order:
        w = fst.final(state)
        if w != pynini.Weight.zero("tropical"):  # type: ignore[attr-defined]
            fw = float(w)
            if fw == 0.0:
                lines.append(str(state))
            else:
                lines.append(f"{state}\t{fw}")

    path.write_text("\n".join(lines) + "\n")
