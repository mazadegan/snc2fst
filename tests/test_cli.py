# tests/test_cli.py
from importlib.resources import files
from pathlib import Path
import shutil

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


def test_compile_no_epsilon_input_arcs_writes_eps_free_att(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    src = Path(STARTERS_PATH / "english_past_tense")
    target = tmp_path / "english_past_tense"
    shutil.copytree(src, target)

    config = str(target / "config.toml")
    result = runner.invoke(
        main,
        ["compile", config, "--att", "--no-epsilon-input-arcs"],
    )
    assert result.exit_code == 0, result.output

    att_files = sorted((target / "transducers").glob("*.att"))
    assert att_files, "Expected .att files from compile --att"

    for att_path in att_files:
        for line in att_path.read_text().splitlines():
            cols = line.split("\t")
            # Arc lines have at least 4 fields:
            # src, dst, ilabel, olabel, [weight]
            if len(cols) >= 4:
                assert cols[2] != "<eps>", (
                    f"Found epsilon-input arc in {att_path.name}: {line}"
                )


def test_compile_att_uses_numeric_zero_for_epsilon(tmp_path: Path) -> None:
    runner = CliRunner()
    src = Path(STARTERS_PATH / "english_past_tense")
    target = tmp_path / "english_past_tense"
    shutil.copytree(src, target)

    config = str(target / "config.toml")
    result = runner.invoke(main, ["compile", config, "--att"])
    assert result.exit_code == 0, result.output

    att_files = sorted((target / "transducers").glob("*.att"))
    assert att_files, "Expected .att files from compile --att"

    for att_path in att_files:
        text = att_path.read_text()
        assert "<eps>" not in text


def _copy_starter(tmp_path: Path, starter: str) -> Path:
    target = tmp_path / starter
    shutil.copytree(Path(str(STARTERS_PATH / starter)), target)
    return target


def test_validate_rejects_ill_formed_rule(tmp_path: Path) -> None:
    """An Inr-window and a Trm-window that can share a position is rejected.

    Dir=L with m=2 > n=1 puts offset 0 in D_Left, and (Inr[1], Trm[1]) is
    (+Syllabic, +Syllabic) — compatible, so the rule is ill-formed.
    """
    target = _copy_starter(tmp_path, "votic_vowel_harmony")
    config = target / "config.toml"
    config.write_text(
        config.read_text()
        + "\n[[rules]]\n"
        'Id = "BAD"\n'
        'Dir = "L"\n'
        'Inr = [["+Syllabic"], ["-Syllabic"]]\n'
        'Trm = [["+Syllabic"]]\n'
        'Out = "INR"\n'
    )
    result = CliRunner().invoke(main, ["validate", str(config)])
    assert result.exit_code != 0
    assert "BAD" in result.output
    assert "overlap at offset 0" in result.output


def test_validate_reports_unknown_feature_in_inr(tmp_path: Path) -> None:
    """Unknown features in Inr/Trm used to surface only at eval/compile."""
    target = _copy_starter(tmp_path, "votic_vowel_harmony")
    config = target / "config.toml"
    config.write_text(
        config.read_text()
        + "\n[[rules]]\n"
        'Id = "BADFEAT"\n'
        'Dir = "L"\n'
        'Inr = [["+NoSuchFeature"]]\n'
        "Trm = []\n"
        'Out = "INR"\n'
    )
    result = CliRunner().invoke(main, ["validate", str(config)])
    assert result.exit_code != 0
    assert "BADFEAT" in result.output
    assert "NoSuchFeature" in result.output
