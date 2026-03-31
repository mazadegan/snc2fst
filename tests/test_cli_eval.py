"""CLI integration tests for `snc eval` with a single WORD argument.

Uses the english_plural starter as a real grammar fixture, copied into
a temporary directory so tests are isolated from the package source.
"""

import importlib.resources
import shutil
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
# Evaluator path — snc eval CONFIG WORD
# ---------------------------------------------------------------------------


def test_eval_single_word_voiceless(config_path):
    # kætS → kæts (voiceless stop → voiceless suffix)
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "kætS"])
    assert result.exit_code == 0
    assert "kætS → kæts" in result.output


def test_eval_single_word_voiced(config_path):
    # leɪdiS → leɪdiz (voiced context → voiced suffix)
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "leɪdiS"])
    assert result.exit_code == 0
    assert "leɪdiS → leɪdiz" in result.output


def test_eval_single_word_epenthesis(config_path):
    # kɪsS → kɪsəz (strident → schwa epenthesis + voiced suffix)
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "kɪsS"])
    assert result.exit_code == 0
    assert "kɪsS → kɪsəz" in result.output


def test_eval_single_word_unknown_segment(config_path):
    # A string that can't be tokenized should exit non-zero
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "XXXXXX"])
    assert result.exit_code != 0


def test_eval_single_word_no_warnings_flag(config_path):
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "kætS", "--no-warn"])
    assert result.exit_code == 0
    assert "[!]" not in result.output


def test_eval_single_word_output_contains_arrow(config_path):
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "kætS"])
    assert "→" in result.output


def test_eval_single_word_no_summary_line(config_path):
    # Single-word mode should not print a pass/fail summary
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "kætS"])
    assert "passed" not in result.output
    assert "failed" not in result.output


# ---------------------------------------------------------------------------
# Evaluator path — test suite (no WORD) still works
# ---------------------------------------------------------------------------


def test_eval_test_suite_still_works(config_path):
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path])
    assert result.exit_code == 0
    assert "passed" in result.output


# ---------------------------------------------------------------------------
# FST path — snc eval CONFIG WORD --fst
# ---------------------------------------------------------------------------


pynini = pytest.importorskip("pynini", reason="pynini not installed")


@pytest.fixture(scope="module")
def compiled_dir(starter_dir, config_path):
    """Compile the starter grammar into transducers/ once for the module."""
    runner = CliRunner()
    result = runner.invoke(main, ["compile", config_path])
    assert result.exit_code == 0, result.output
    return starter_dir / "transducers"


def test_eval_fst_single_word(config_path, compiled_dir):
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "kætS", "--fst"])
    assert result.exit_code == 0
    assert "→" in result.output


def test_eval_fst_single_word_agrees_with_evaluator(config_path, compiled_dir):
    runner = CliRunner()
    ref = runner.invoke(main, ["eval", config_path, "kætS"])
    fst = runner.invoke(main, ["eval", config_path, "kætS", "--fst"])
    assert ref.exit_code == 0
    assert fst.exit_code == 0
    # Both should contain the same output word after the arrow
    ref_out = ref.output.strip().split("→")[-1].strip()
    fst_out = fst.output.strip().split("→")[-1].strip()
    assert ref_out == fst_out


def test_eval_fst_test_suite(config_path, compiled_dir):
    runner = CliRunner()
    result = runner.invoke(main, ["eval", config_path, "--fst"])
    assert result.exit_code == 0
    assert "passed" in result.output


def test_eval_fst_missing_transducers(starter_dir):
    """--fst should error clearly if transducers/ doesn't exist."""
    tmp = Path(str(starter_dir) + "_no_fst")
    if not tmp.exists():
        shutil.copytree(starter_dir, tmp)
        shutil.rmtree(tmp / "transducers", ignore_errors=True)
    runner = CliRunner()
    result = runner.invoke(main, ["eval", str(tmp / "config.toml"), "kats", "--fst"])
    assert result.exit_code != 0
    assert "snc compile" in result.output


def test_eval_fst_format_flag_rejected(config_path, compiled_dir):
    """--fst and --format together should error."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["eval", config_path, "--fst", "--format", "txt"]
    )
    assert result.exit_code != 0
    assert "--format" in result.output
