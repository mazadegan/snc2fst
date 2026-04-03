"""CLI integration tests for `snc validate`."""

import importlib.resources
import textwrap
import pytest
from pathlib import Path
from click.testing import CliRunner

from snc2fst.cli import main


@pytest.fixture(scope="module")
def starter_dir(tmp_path_factory):
    """Copy the english_plural starter into a temp directory."""
    tmp = tmp_path_factory.mktemp("english_plural")
    src = importlib.resources.files("snc2fst").joinpath(
        "templates/starters/english_plural"
    )
    for item in src.iterdir():
        dest = tmp / item.name
        dest.write_bytes(item.read_bytes())
    return tmp


@pytest.fixture(scope="module")
def config_path(starter_dir):
    return str(starter_dir / "config.toml")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_validate_passes_on_valid_config(config_path):
    runner = CliRunner()
    result = runner.invoke(main, ["validate", config_path])
    assert result.exit_code == 0
    assert "All files valid" in result.output


def test_validate_prints_checkmarks(config_path):
    runner = CliRunner()
    result = runner.invoke(main, ["validate", config_path])
    assert "[✓]" in result.output


# ---------------------------------------------------------------------------
# Missing files
# ---------------------------------------------------------------------------


def test_validate_missing_alphabet(tmp_path):
    src = importlib.resources.files("snc2fst").joinpath(
        "templates/starters/english_plural"
    )
    for item in src.iterdir():
        (tmp_path / item.name).write_bytes(item.read_bytes())
    (tmp_path / "alphabet.csv").unlink()
    runner = CliRunner()
    result = runner.invoke(main, ["validate", str(tmp_path / "config.toml")])
    assert result.exit_code != 0
    assert "alphabet" in result.output.lower() or "alphabet" in (result.output + "").lower()


def test_validate_missing_tests_file(tmp_path):
    src = importlib.resources.files("snc2fst").joinpath(
        "templates/starters/english_plural"
    )
    for item in src.iterdir():
        (tmp_path / item.name).write_bytes(item.read_bytes())
    (tmp_path / "tests.csv").unlink()
    runner = CliRunner()
    result = runner.invoke(main, ["validate", str(tmp_path / "config.toml")])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Malformed config
# ---------------------------------------------------------------------------


def test_validate_undefined_feature(tmp_path):
    src = importlib.resources.files("snc2fst").joinpath(
        "templates/starters/english_plural"
    )
    for item in src.iterdir():
        (tmp_path / item.name).write_bytes(item.read_bytes())

    config = (tmp_path / "config.toml").read_text()
    # Inject a rule referencing a feature that doesn't exist in the alphabet
    config += textwrap.dedent("""
        [[rules]]
        Id = "BadRule"
        Inr = [["+NOSUCHFEATURE"]]
        Trm = []
        Out = "INR[1]"
        Dir = "L"
    """)
    (tmp_path / "config.toml").write_text(config)

    runner = CliRunner()
    result = runner.invoke(main, ["validate", str(tmp_path / "config.toml")])
    assert result.exit_code != 0
    assert "NOSUCHFEATURE" in result.output or "NOSUCHFEATURE" in (result.output + "")


def test_validate_invalid_toml(tmp_path):
    bad_config = tmp_path / "config.toml"
    bad_config.write_text("this is not [ valid toml }{")
    runner = CliRunner()
    result = runner.invoke(main, ["validate", str(bad_config)])
    assert result.exit_code != 0


def test_validate_missing_meta_section(tmp_path):
    src = importlib.resources.files("snc2fst").joinpath(
        "templates/starters/english_plural"
    )
    for item in src.iterdir():
        (tmp_path / item.name).write_bytes(item.read_bytes())

    lines = (tmp_path / "config.toml").read_text().splitlines()
    # Strip [meta] block lines
    filtered = [l for l in lines if not l.startswith("[meta]") and not any(
        l.startswith(k) for k in ("title", "language", "description", "sources")
    )]
    (tmp_path / "config.toml").write_text("\n".join(filtered))

    runner = CliRunner()
    result = runner.invoke(main, ["validate", str(tmp_path / "config.toml")])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def test_validate_warnings_do_not_cause_failure(config_path):
    # english_plural has underspecified segments (S) — warnings expected but not fatal
    runner = CliRunner()
    result = runner.invoke(main, ["validate", config_path])
    assert result.exit_code == 0
    assert "All files valid" in result.output
