"""CLI integration tests for `snc tool nc`."""

from click.testing import CliRunner

from snc2fst.cli import main


def _write_project(tmp_path, alphabet_text: str) -> None:
    (tmp_path / "config.toml").write_text(
        """
alphabet_path = "alphabet.csv"
tests_path = "tests.csv"

[meta]
title = "Test"
language = "eng"
description = ""
sources = []
compilable = false

[[rules]]
Id = "R_0"
Inr = [["+F1"]]
Trm = []
Out = "INR[1]"
Dir = "L"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "alphabet.csv").write_text(alphabet_text, encoding="utf-8")
    (tmp_path / "tests.csv").write_text("Input,Output\na,a\n", encoding="utf-8")


def test_tool_nc_segments_reports_shared_bundle(tmp_path):
    _write_project(
        tmp_path,
        ",a,e,o,i,u,p\n"
        "F1,+,+,+,+,+,-\n"
        "high,-,-,-,+,+,-\n"
        "back,-,+,+,-,+,-\n",
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["tool", "nc", "--config", str(tmp_path / "config.toml"), "--segments", "a,e,o"],
    )
    assert result.exit_code == 0
    assert "Shared bundle" in result.output
    assert "{+F1 -high}" in result.output
    assert "Natural class: a, e, o" in result.output


def test_tool_nc_segments_warns_on_extra_matches(tmp_path):
    _write_project(
        tmp_path,
        ",a,e,o,i\n"
        "F1,+,+,+,+\n"
        "high,-,-,-\n",
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["tool", "nc", "--config", str(tmp_path / "config.toml"), "--segments", "a,e"],
    )
    assert result.exit_code == 0
    assert "Shared bundle" in result.output
    assert "Natural class: a, e, o" in result.output
    assert "Warning: this natural class also contains o." in result.output


def test_tool_nc_bundle_lists_matching_segments(tmp_path):
    _write_project(
        tmp_path,
        ",a,e,o,i,u,p\n"
        "F1,+,+,+,+,+,-\n"
        "high,-,-,-,+,+,-\n"
        "back,-,+,+,-,+,-\n",
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["tool", "nc", "--config", str(tmp_path / "config.toml"), "--bundle", "+F1,-high"],
    )
    assert result.exit_code == 0
    assert "Bundle: {+F1 -high}" in result.output
    assert "Matches: a, e, o" in result.output
