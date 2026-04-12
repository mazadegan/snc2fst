# tests/test_cli.py
from importlib.resources import files
from pathlib import Path

import pytest
from click.testing import CliRunner

from snc2fst.cli import main

STARTERS_PATH = files("snc2fst") / "templates" / "starters"

STARTERS = [
    "english_past_tense",
    "english_plural",
    "iloko_plural",
    "turkish_k_deletion",
    "votic_vowel_harmony",
]


def test_init_blank(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "my_project"
    result = runner.invoke(
        main,
        [
            "init",
            str(target),
            "--starter",
            "blank",
            "--title",
            "Test Grammar",
            "--language",
            "tst",
        ],
    )
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("starter", STARTERS)
def test_init_starter(starter: str, tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "my_project"
    result = runner.invoke(
        main,
        [
            "init",
            str(target),
            "--starter",
            starter,
            "--title",
            "Test",
            "--language",
            "tst",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (target / "config.toml").exists()
    assert (target / "alphabet.csv").exists()
    assert (target / "tests.csv").exists()


@pytest.mark.parametrize("starter", STARTERS)
def test_validate_starter(starter: str) -> None:
    runner = CliRunner()
    config = str(STARTERS_PATH / starter / "config.toml")
    result = runner.invoke(main, ["validate", config])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("starter", STARTERS)
def test_eval_starter(starter: str) -> None:
    runner = CliRunner()
    config = str(STARTERS_PATH / starter / "config.toml")
    result = runner.invoke(main, ["eval", config])
    assert result.exit_code == 0, result.output
    assert "passed" in result.output
    assert "0/" not in result.output


@pytest.mark.parametrize("starter", STARTERS)
def test_export_txt_starter(starter: str) -> None:
    runner = CliRunner()
    config = str(STARTERS_PATH / starter / "config.toml")
    result = runner.invoke(main, ["export", config, "--format", "txt"])
    assert result.exit_code == 0, result.output
    assert "=== Alphabet ===" in result.output


@pytest.mark.parametrize("starter", STARTERS)
def test_export_latex_starter(starter: str) -> None:
    runner = CliRunner()
    config = str(STARTERS_PATH / starter / "config.toml")
    result = runner.invoke(main, ["export", config, "--format", "latex"])
    assert result.exit_code == 0, result.output
    assert "\\begin{tabular}" in result.output
