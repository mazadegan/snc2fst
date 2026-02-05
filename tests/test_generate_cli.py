import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Allow tests to run without installing the package.
SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from snc2fst.main import app


def test_init_creates_sample_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "samples"
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(output_dir)])
    assert result.exit_code == 0, result.output

    alphabet_path = output_dir / "alphabet.csv"
    rules_path = output_dir / "rules.json"
    input_path = output_dir / "input.json"
    assert alphabet_path.exists()
    assert rules_path.exists()
    assert input_path.exists()

    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    assert "rules" in rules
    assert len(rules["rules"]) == 2
    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    assert isinstance(input_payload, list)
    assert len(input_payload) >= 3

    alphabet_lines = alphabet_path.read_text(encoding="utf-8").splitlines()
    header = alphabet_lines[0].split(",")
    symbols = header[1:]
    assert len(symbols) == 27
    assert len(alphabet_lines) == 1 + 3


def test_init_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output

    assert (tmp_path / "alphabet.csv").exists()
    assert (tmp_path / "rules.json").exists()
    assert (tmp_path / "input.json").exists()
