# tests/test_cli.py
from importlib.resources import files

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
