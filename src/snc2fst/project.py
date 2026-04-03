"""Shared project logic used by both the TUI and web interfaces."""

import importlib.resources
import json
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Recent projects
# ---------------------------------------------------------------------------

_RECENT_PATH = Path.home() / ".config" / "snc2fst" / "recent.json"
_MAX_RECENT = 5


def load_recent() -> list[dict]:
    """Return list of recent projects [{title, path}, ...]."""
    if not _RECENT_PATH.exists():
        return []
    try:
        entries = json.loads(_RECENT_PATH.read_text())
        # Prune entries whose paths no longer exist.
        valid = [e for e in entries if Path(e["path"]).exists()]
        if len(valid) != len(entries):
            _save_recent(valid)
        return valid
    except Exception:
        return []


def _save_recent(entries: list[dict]) -> None:
    _RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RECENT_PATH.write_text(json.dumps(entries, indent=2))


def add_recent(title: str, config_path: Path) -> None:
    """Add a project to the recent list, deduplicating by path."""
    entries = load_recent()
    entry = {"title": title, "path": str(config_path.resolve())}
    entries = [e for e in entries if e["path"] != entry["path"]]
    entries.insert(0, entry)
    _save_recent(entries[:_MAX_RECENT])


# ---------------------------------------------------------------------------
# Project creation helpers
# ---------------------------------------------------------------------------

def resolve_language(raw: str) -> tuple[str, str | None]:
    """Resolve a language name or code to (iso_code, display_name).

    Returns (raw, None) if unrecognized.
    """
    import langcodes
    stripped = raw.strip()
    try:
        lang = langcodes.get(stripped)
        if lang.is_valid():
            return lang.to_alpha3(), lang.display_name()
    except Exception:
        pass
    try:
        found = langcodes.find(stripped)
        if found.is_valid():
            return found.to_alpha3(), found.display_name()
    except LookupError:
        pass
    return stripped, None


def list_starters() -> list[str]:
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    return sorted(p.name for p in starters_dir.iterdir() if p.is_dir())


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _toml_str_list(items: list[str]) -> str:
    return "[" + ", ".join(f'"{_toml_escape(s)}"' for s in items) + "]"


def create_project(
    directory: Path,
    title: str,
    language: str,
    description: str,
    sources: list[str],
    starter: str | None,
) -> Path:
    """Create project files and return the path to config.toml."""
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    templates_dir = importlib.resources.files("snc2fst").joinpath("templates")
    config_path = directory / "config.toml"

    if starter:
        source_dir = starters_dir.joinpath(starter)
        import tomllib
        raw_config = tomllib.loads(source_dir.joinpath("config.toml").read_text())
        tests_filename = raw_config.get("tests_path", "tests.csv")
        alphabet_filename = raw_config.get("alphabet_path", "alphabet.csv")
        source_files = [
            (config_path, source_dir.joinpath("config.toml")),
            (directory / alphabet_filename, source_dir.joinpath(alphabet_filename)),
            (directory / tests_filename, source_dir.joinpath(tests_filename)),
        ]
    else:
        source_files = [
            (config_path, templates_dir.joinpath("default_config.toml")),
            (directory / "alphabet.csv", templates_dir.joinpath("default_alphabet.csv")),
            (directory / "tests.csv", templates_dir.joinpath("default_tests.csv")),
        ]

    directory.mkdir(parents=True, exist_ok=True)
    contents = [(target, source.read_text()) for target, source in source_files]
    written: list[Path] = []
    try:
        for target_file, text in contents:
            target_file.write_text(text)
            written.append(target_file)
    except Exception as e:
        for f in written:
            f.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to write project files: {e}") from e

    if not starter:
        text = config_path.read_text(encoding="utf-8")
        text = text.replace('title = ""', f'title = "{_toml_escape(title)}"', 1)
        text = text.replace('language = ""', f'language = "{_toml_escape(language)}"', 1)
        text = text.replace('description = ""', f'description = "{_toml_escape(description)}"', 1)
        text = text.replace('sources = []', f'sources = {_toml_str_list(sources)}', 1)
        text = text.replace("\n# [meta] is filled in by `snc init` — do not edit manually.", "", 1)
        config_path.write_text(text, encoding="utf-8")

    return config_path


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------

@dataclass
class EvalRow:
    index: int
    input: str
    output: str
    expected: str
    status: str  # "pass", "fail", "error"
    message: str = ""


def run_eval(config_path: Path, use_fst: bool = False) -> tuple[list[EvalRow], int, int, int]:
    """Run the test suite and return (rows, passed, failed, errors)."""
    from snc2fst.cli import _run_validate
    from snc2fst.alphabet import tokenize, word_to_str
    from snc2fst.evaluator import apply_rule, EvalError
    from snc2fst import dsl

    v = _run_validate(config_path)
    if not v.ok:
        return [], 0, 0, 0

    config = v.config
    alphabet = v.alphabet
    tests = v.tests
    rows: list[EvalRow] = []
    passed = failed = errors = 0

    if use_fst:
        import pynini
        from snc2fst.compiler import transduce
        fst_dir = config_path.parent / "transducers"
        fsts: dict = {}
        for rule in config.rules:
            fst_path = fst_dir / f"{rule.Id}.fst"
            syms_path = fst_dir / f"{rule.Id}.syms"
            if not fst_path.exists():
                return [EvalRow(1, "", "", "", "error",
                    f"FST not found for rule '{rule.Id}'. Run Compile first.")], 0, 0, 1
            fst = pynini.Fst.read(str(fst_path))
            sym = pynini.SymbolTable.read_text(str(syms_path))
            fst.set_input_symbols(sym)
            fst.set_output_symbols(sym)
            fsts[rule.Id] = fst

        for i, (inp_str, exp_str) in enumerate(tests, 1):
            try:
                inp_tokens = tokenize(inp_str, alphabet)
                exp_tokens = tokenize(exp_str, alphabet)
                current = ["⋊"] + list(inp_tokens) + ["⋉"]
                for rule in config.rules:
                    current = transduce(fsts[rule.Id], rule, current)
                out_str = "".join(s for s in current if s not in ("⋊", "⋉"))
            except Exception as e:
                rows.append(EvalRow(i, inp_str, "", exp_str, "error", str(e)))
                errors += 1
                continue
            ok = tokenize(out_str, alphabet) == exp_tokens
            status = "pass" if ok else "fail"
            passed += ok
            failed += not ok
            rows.append(EvalRow(i, inp_str, out_str, exp_str, status))
        return rows, passed, failed, errors

    try:
        out_asts = {rule.Id: dsl.parse(rule.Out) for rule in config.rules}
    except dsl.ParseError:
        return [], 0, 0, 0

    for i, (inp_str, exp_str) in enumerate(tests, 1):
        try:
            inp_tokens = tokenize(inp_str, alphabet)
            exp_tokens = tokenize(exp_str, alphabet)
        except Exception as e:
            rows.append(EvalRow(i, inp_str, "", exp_str, "error", str(e)))
            errors += 1
            continue
        try:
            w = [dict(alphabet[t]) for t in inp_tokens]
            for rule in config.rules:
                w = apply_rule(rule, out_asts[rule.Id], w, alphabet)
            out_str = word_to_str(w, alphabet)
        except EvalError as e:
            rows.append(EvalRow(i, inp_str, "", exp_str, "error", str(e)))
            errors += 1
            continue

        ok = tokenize(out_str, alphabet) == exp_tokens
        status = "pass" if ok else "fail"
        passed += ok
        failed += not ok
        rows.append(EvalRow(i, inp_str, out_str, exp_str, status))

    return rows, passed, failed, errors


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

@dataclass
class CompileRow:
    rule_id: str
    states: int
    arcs: int
    filename: str


def run_compile(
    config_path: Path,
    fmt: str = "fst",
    max_arcs: int = 1_000_000,
    no_optimize: bool = False,
) -> tuple[list[CompileRow], Path | None, str]:
    """Compile all rules. Returns (rows, out_path, error_message)."""
    import pynini
    from snc2fst.cli import _run_validate
    from snc2fst.compiler import compile_rule, compute_alphabets, CompileError

    v = _run_validate(config_path)
    if not v.ok:
        return [], None, "Validation failed — fix errors before compiling."

    config = v.config
    base_alphabet = v.alphabet
    out_path = config_path.parent / "transducers"

    if not config.meta.compilable:
        return [], None, "compilable = false in [meta]. FST compilation is not enabled."

    try:
        alphabets = compute_alphabets(config.rules, base_alphabet)
    except Exception as e:
        return [], None, f"Failed to compute rule alphabets: {e}"

    from snc2fst.cli import _DEFAULT_MAX_ARCS
    from snc2fst.compiler import predict_arcs
    from snc2fst import dsl

    fsts: list[tuple] = []
    for rule, alphabet in zip(config.rules, alphabets):
        try:
            out_ast = dsl.parse(rule.Out)
            arc_count = predict_arcs(rule, alphabet, out_ast)
        except Exception as e:
            return [], None, f"Rule '{rule.Id}': failed to predict arc count: {e}"
        if arc_count > max_arcs:
            return [], None, (
                f"Rule '{rule.Id}' would produce {arc_count:,} arcs "
                f"(limit {max_arcs:,})."
            )
        try:
            fst = compile_rule(rule, alphabet)
            if not no_optimize:
                pynini.optimize(fst)
            fsts.append((rule, fst))
        except CompileError as e:
            return [], None, f"Rule '{rule.Id}': {e}"
        except Exception as e:
            return [], None, f"Rule '{rule.Id}': unexpected error: {e}"

    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return [], None, f"Failed to create output directory: {e}"

    rows: list[CompileRow] = []
    for rule, fst in fsts:
        sym = fst.input_symbols()
        syms_path = out_path / f"{rule.Id}.syms"
        total_arcs = sum(1 for s in fst.states() for _ in fst.arcs(s))
        try:
            if fmt == "att":
                from snc2fst.cli import _write_att
                out_file = out_path / f"{rule.Id}.att"
                _write_att(fst, out_file)
            else:
                out_file = out_path / f"{rule.Id}.fst"
                fst.write(str(out_file))
            sym.write_text(str(syms_path))
            rows.append(CompileRow(rule.Id, fst.num_states(), total_arcs, out_file.name))
        except Exception as e:
            return rows, out_path, f"Rule '{rule.Id}': failed to write: {e}"

    return rows, out_path, ""
