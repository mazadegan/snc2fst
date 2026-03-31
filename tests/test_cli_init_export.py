"""CLI integration tests for `snc init` and `snc export`."""

import importlib.resources
import pytest
from pathlib import Path
from click.testing import CliRunner

from snc2fst.cli import main


# ---------------------------------------------------------------------------
# snc init --from <starter>
# ---------------------------------------------------------------------------


def test_init_from_starter_creates_files(tmp_path):
    runner = CliRunner()
    config = tmp_path / "config.toml"
    result = runner.invoke(main, ["init", "--filename", str(config), "--from", "english_plural"])
    assert result.exit_code == 0
    assert config.exists()
    assert (tmp_path / "alphabet.csv").exists()
    assert (tmp_path / "tests.tsv").exists()


def test_init_from_starter_prints_file_list(tmp_path):
    runner = CliRunner()
    config = tmp_path / "config.toml"
    result = runner.invoke(main, ["init", "--filename", str(config), "--from", "english_plural"])
    assert "config.toml" in result.output
    assert "alphabet.csv" in result.output
    assert "tests.tsv" in result.output


def test_init_from_unknown_starter_errors(tmp_path):
    runner = CliRunner()
    config = tmp_path / "config.toml"
    result = runner.invoke(main, ["init", "--filename", str(config), "--from", "nonexistent_starter"])
    assert result.exit_code != 0
    assert "nonexistent_starter" in result.output or "nonexistent_starter" in (result.output + "")


def test_init_from_all_starters(tmp_path):
    """Every bundled starter should init cleanly."""
    starters_dir = importlib.resources.files("snc2fst").joinpath("templates/starters")
    available = sorted(p.name for p in starters_dir.iterdir() if p.is_dir())
    runner = CliRunner()
    for name in available:
        dest = tmp_path / name
        dest.mkdir()
        config = dest / "config.toml"
        result = runner.invoke(main, ["init", "--filename", str(config), "--from", name])
        assert result.exit_code == 0, f"init --from {name} failed: {result.output}"


# ---------------------------------------------------------------------------
# snc init collision guard
# ---------------------------------------------------------------------------


def test_init_fails_if_config_exists(tmp_path):
    runner = CliRunner()
    config = tmp_path / "config.toml"
    # First init succeeds
    runner.invoke(main, ["init", "--filename", str(config), "--from", "english_plural"])
    # Second init must fail
    result = runner.invoke(main, ["init", "--filename", str(config), "--from", "english_plural"])
    assert result.exit_code != 0
    assert "already exists" in result.output or "already exists" in (result.output + "")


# ---------------------------------------------------------------------------
# snc init --from / --pick mutual exclusion
# ---------------------------------------------------------------------------


def test_init_from_and_pick_are_mutually_exclusive(tmp_path):
    runner = CliRunner()
    config = tmp_path / "config.toml"
    result = runner.invoke(
        main, ["init", "--filename", str(config), "--from", "english_plural", "--pick"]
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output or "mutually exclusive" in (result.output + "")


# ---------------------------------------------------------------------------
# snc export
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def starter_dir(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("english_plural_export")
    src = importlib.resources.files("snc2fst").joinpath(
        "templates/starters/english_plural"
    )
    for item in src.iterdir():
        (tmp / item.name).write_bytes(item.read_bytes())
    return tmp


@pytest.fixture(scope="module")
def config_path(starter_dir):
    return str(starter_dir / "config.toml")


def test_export_txt_to_stdout(config_path):
    runner = CliRunner()
    result = runner.invoke(main, ["export", config_path])
    assert result.exit_code == 0
    assert len(result.output.strip()) > 0


def test_export_txt_contains_rule_ids(config_path):
    import tomllib
    config = tomllib.loads(Path(config_path).read_text())
    rule_ids = [r["Id"] for r in config["rules"]]
    runner = CliRunner()
    result = runner.invoke(main, ["export", config_path])
    for rid in rule_ids:
        assert rid in result.output


def test_export_latex_format(config_path):
    runner = CliRunner()
    result = runner.invoke(main, ["export", config_path, "--format", "latex"])
    assert result.exit_code == 0
    # LaTeX output should contain some LaTeX markup
    assert "\\" in result.output


def test_export_to_file(config_path, tmp_path):
    out = tmp_path / "grammar.txt"
    runner = CliRunner()
    result = runner.invoke(main, ["export", config_path, "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert len(out.read_text().strip()) > 0


def test_export_blocked_by_invalid_config(tmp_path):
    bad_config = tmp_path / "config.toml"
    bad_config.write_text("not valid toml }{")
    runner = CliRunner()
    result = runner.invoke(main, ["export", str(bad_config)])
    assert result.exit_code != 0
